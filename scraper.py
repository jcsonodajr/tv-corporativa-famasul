    for element in soup.find_all(True):
        label = text_of(element)
        if not label or len(label) > 320:
            continue
        match = DATE_RANGE.match(label)
        if not match:
            continue
        start, end, title = match.groups()
        title = clean(title).strip(" -–—:")
        # Descarta contêineres maiores cujo texto também começa pela data do curso;
        # o título válido deve ser o texto do botão/link, não o cartão inteiro.
        if re.search(r"\b(CONFIRMADO|ABERTO|INSCRIÇÕES ABERTAS|CARGA HORÁRIA|LOCALIZAÇÃO|PARCEIRO|TELEFONE|E-MAIL)\b", title, re.I):
            continue
        if len(title) < 4 or title.lower() in {"mais informações", "leia mais"}:
            continue
        # Escolhe o menor ancestral que contenha os metadados do curso.
        card = element
        for ancestor in element.parents:
            blob = text_of(ancestor)
            if len(blob) > 3500:
                break
            if "Carga horária:" in blob and ("Localização:" in blob or "Local:" in blob):
                card = ancestor
                break
        blob = text_of(card)
        hours = re.search(r"Carga\s+horária\s*:\s*(\d+)", blob, re.I)
        local = re.search(r"Localização\s*:\s*(.+?)(?=\s+(?:Parceiro|Telefone|E-mail)\s*:|\s+MAIS INFORMAÇÕES\b|$)", blob, re.I)
        status = re.search(r"\b(CONFIRMADO|ABERTO|INSCRIÇÕES ABERTAS)\b", blob, re.I)
        more_link = ""
        for a in card.select("a[href]"):
            if "mais informações" in text_of(a).lower():
                more_link = urljoin(url, a.get("href", ""))
                break
        key = (slugify(title), start, end)
        if key in seen:
            continue
        seen.add(key)
        courses.append({
            "titulo": title[:180],
            "periodo": f"{start} até {end}",
            "data_inicio": start,
            "data_fim": end,
            "carga_horaria": int(hours.group(1)) if hours else None,
            "local": clean(local.group(1)) if local else "",
            "status": status.group(1).upper() if status else "",
            "municipio_slug": slug,
            "link": more_link or url,
            "fonte": url,
        })
    logging.info("SENAR %s: %d cursos identificados", slug, len(courses))
    return courses


def main() -> None:
    previous = {}
    if OUTPUT.exists():
        try:
            previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
        except Exception:
            logging.warning("JSON anterior inválido; será reconstruído.")
    now = datetime.now(timezone.utc).isoformat()
    old_famasul = previous.get("famasul", {"banners": [], "noticias": []})
    old_quotes = previous.get("cotacoes", {"soja": [], "milho": [], "boi": [], "vaca": []})
    payload = {
        "schema_version": 1,
        "gerado_em": now,
        "fontes": {"famasul": FAMASUL, "noticias": NEWS_URL, "cotacoes": COTACOES, "senar": "https://senarms.org.br/municipios"},
        "municipios": {},
        "famasul": old_famasul,
        "cotacoes": old_quotes,
        "avisos": [],
    }
    try:
        collected = scrape_famasul()
        if collected.get("banners") or collected.get("noticias"):
            # Se uma das duas partes vier vazia, preserva o último conjunto válido daquela parte.
            payload["famasul"] = {
                "banners": collected.get("banners") or old_famasul.get("banners", []),
                "noticias": collected.get("noticias") or old_famasul.get("noticias", []),
            }
        logging.info("FAMASUL: %d banners, %d notícias", len(payload["famasul"].get("banners", [])), len(payload["famasul"].get("noticias", [])))
    except Exception:
        logging.exception("Falha ao coletar FAMASUL")
        payload["avisos"].append("FAMASUL indisponível; preservados dados anteriores.")
    try:
        fresh_quotes = scrape_cotacoes()
        for key in ("soja", "milho", "boi", "vaca"):
            if fresh_quotes.get(key):
                payload["cotacoes"][key] = fresh_quotes[key]
            else:
                payload["cotacoes"][key] = old_quotes.get(key, [])
                payload["avisos"].append(f"Cotação de {key} não identificada; preservados dados anteriores.")
    except Exception:
        logging.exception("Falha ao coletar cotações")
        payload["avisos"].append("Cotações indisponíveis; preservados dados anteriores.")
    old_municipios = previous.get("municipios", {})
    for name in MUNICIPIOS:
        slug = slugify(name)
        old = old_municipios.get(slug, {})
        try:
            fresh_courses = scrape_cursos(slug)
            # Uma coleta vazia não apaga a programação anterior: o portal pode mudar o HTML.
            courses = fresh_courses if fresh_courses else old.get("cursos", [])
            if not fresh_courses:
                payload["avisos"].append(f"Nenhum curso identificado para {name}; preservada a lista anterior.")
            payload["municipios"][slug] = {
                "nome": name,
                "slug": slug,
                "cursos": courses,
                "praca_graos": PRACAS.get(slug, "Mato Grosso do Sul"),
                "regiao_pecuaria": REGIOES.get(slug, "Mato Grosso do Sul"),
                "atualizado_em": now if fresh_courses else old.get("atualizado_em"),
            }
        except Exception as exc:
            logging.warning("Falha SENAR %s: %s", name, exc)
            payload["municipios"][slug] = old or {
                "nome": name, "slug": slug, "cursos": [],
                "praca_graos": PRACAS.get(slug, "Mato Grosso do Sul"),
                "regiao_pecuaria": REGIOES.get(slug, "Mato Grosso do Sul"), "atualizado_em": None,
            }
            payload["avisos"].append(f"Falha ao atualizar cursos de {name}; preservada a lista anterior.")
    tmp = OUTPUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUTPUT)
    logging.info("Arquivo atualizado: %s", OUTPUT)
    logging.info("Resumo: noticias=%d, soja=%d, milho=%d, boi=%d, vaca=%d", len(payload["famasul"].get("noticias", [])), *(len(payload["cotacoes"].get(k, [])) for k in ("soja", "milho", "boi", "vaca")))
    logging.info("Avisos gerados: %d", len(payload["avisos"]))
