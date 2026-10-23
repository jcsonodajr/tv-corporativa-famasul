#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coletor da TV Corporativa FAMASUL / SENAR-MS.

- Cotações: identifica cada tabela pelo marcador imediatamente anterior (@Boi, @Vaca,
  Saca - Milho, Saca - Soja), evitando classificar todas como soja.
- Notícias: coleta a listagem e consulta os metadados da página individual para
  recuperar imagem e resumo.
- Cursos: identifica os títulos dos eventos pelo texto de data + nome e extrai
  metadados do cartão correspondente.
- Se uma fonte falhar ou retornar vazia inesperadamente, preserva os dados anteriores.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "dados_tv.json"
FAMASUL = "https://portal.sistemafamasul.com.br/"
NEWS_URL = urljoin(FAMASUL, "noticias")
COTACOES = urljoin(FAMASUL, "cotacoes-online")
SENAR = "https://senarms.org.br/cursos"
TIMEOUT = 20
MAX_NEWS = 8
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
session = requests.Session()
session.headers.update(HEADERS)

MUNICIPIOS = [
    "Água Clara", "Alcinópolis", "Amambai", "Anastácio", "Anaurilândia", "Angélica", "Antônio João",
    "Aparecida do Taboado", "Aquidauana", "Aral Moreira", "Bandeirantes", "Bataguassu", "Batayporã",
    "Bela Vista", "Bodoquena", "Bonito", "Brasilândia", "Caarapó", "Camapuã", "Campo Grande",
    "Caracol", "Cassilândia", "Chapadão do Sul", "Corguinho", "Coronel Sapucaia", "Corumbá",
    "Costa Rica", "Coxim", "Deodápolis", "Dois Irmãos do Buriti", "Douradina", "Dourados",
    "Eldorado", "Fátima do Sul", "Figueirão", "Glória de Dourados", "Guia Lopes da Laguna",
    "Iguatemi", "Inocência", "Itaporã", "Itaquiraí", "Ivinhema", "Japorã", "Jaraguari", "Jardim",
    "Jateí", "Juti", "Ladário", "Laguna Carapã", "Maracaju", "Miranda", "Mundo Novo", "Naviraí",
    "Nioaque", "Nova Alvorada do Sul", "Nova Andradina", "Novo Horizonte do Sul", "Paraíso das Águas",
    "Paranaíba", "Paranhos", "Pedro Gomes", "Ponta Porã", "Porto Murtinho", "Ribas do Rio Pardo",
    "Rio Brilhante", "Rio Negro", "Rio Verde de Mato Grosso", "Rochedo", "Santa Rita do Pardo",
    "São Gabriel do Oeste", "Selvíria", "Sete Quedas", "Sidrolândia", "Sonora", "Tacuru",
    "Taquarussu", "Terenos", "Três Lagoas", "Vicentina"
]

PRACAS = {
    "dourados": "Dourados", "douradina": "Dourados", "itapora": "Dourados", "caarapo": "Dourados",
    "fatima-do-sul": "Dourados", "gloria-de-dourados": "Dourados", "deodapolis": "Dourados",
    "rio-brilhante": "Dourados", "maracaju": "Maracaju", "sidrolandia": "Sidrolândia",
    "campo-grande": "Campo Grande", "chapadao-do-sul": "Chapadão do Sul",
    "sao-gabriel-do-oeste": "São Gabriel do Oeste", "sonora": "Sonora", "ponta-pora": "Ponta Porã"
}
REGIOES = {
    "dourados": "Região Sul", "douradina": "Região Sul", "itapora": "Região Sul", "caarapo": "Região Sul",
    "fatima-do-sul": "Região Sul", "gloria-de-dourados": "Região Sul", "maracaju": "Região Sul",
    "ponta-pora": "Região Sul", "amambai": "Região Sul", "navirai": "Região Sul", "iguatemi": "Região Sul",
    "campo-grande": "Região Centro", "sidrolandia": "Região Centro", "terenos": "Região Centro",
    "corumba": "Região Oeste", "ladario": "Região Oeste", "porto-murtinho": "Região Oeste",
    "miranda": "Região Oeste", "bonito": "Região Oeste", "aquidauana": "Região Oeste",
    "coxim": "Região Norte", "sonora": "Região Norte", "sao-gabriel-do-oeste": "Região Norte",
    "chapadao-do-sul": "Região Norte", "costa-rica": "Região Norte"
}

DATE_RANGE = re.compile(
    r"^\s*(\d{1,2}/\d{1,2}(?:/\d{4})?)\s*(?:até|a|[-–—])\s*"
    r"(\d{1,2}/\d{1,2}(?:/\d{4})?)\s*[-–—:]\s*(.+?)\s*$", re.I
)
DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def clean(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def text_of(node) -> str:
    return clean(node.get_text(" ", strip=True)) if node else ""


def fetch_soup(url: str) -> BeautifulSoup:
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return BeautifulSoup(response.text, "html.parser")


def abs_img(img_or_url, base_url: str) -> str:
    if not img_or_url:
        return ""
    if isinstance(img_or_url, str):
        src = img_or_url.strip()
    else:
        src = (img_or_url.get("data-src") or img_or_url.get("data-lazy-src") or
               img_or_url.get("data-original") or img_or_url.get("src") or "")
        if (not src or src.startswith("data:image")) and img_or_url.get("srcset"):
            src = img_or_url.get("srcset", "").split(",")[0].strip().split(" ")[0]
    if src.startswith("//"):
        src = "https:" + src
    if src.startswith("data:"):
        return ""
    return urljoin(base_url, src) if src else ""


def scrape_banners(soup: BeautifulSoup) -> list[dict]:
    banners, seen = [], set()
    for img in soup.select(".view-banner-principal img, .views-field-field-arquivo img, .field--name-field-banner img"):
        src = abs_img(img, FAMASUL)
        if not src or src in seen:
            continue
        seen.add(src)
        parent = img.find_parent("a")
        banners.append({
            "imagem": src,
            "titulo": clean(img.get("alt", "")),
            "link": urljoin(FAMASUL, parent.get("href", "")) if parent else FAMASUL,
        })
    return banners


def scrape_news() -> list[dict]:
    listing = fetch_soup(NEWS_URL)
    links, seen = [], set()
    for a in listing.select('a[href*="/noticias/"]'):
        href = urljoin(NEWS_URL, a.get("href", ""))
        title = text_of(a)
        if not title or title.lower() in {"leia mais", "mais informações"}:
            continue
        if href.rstrip("/") == NEWS_URL.rstrip("/") or href in seen:
            continue
        # Prefere o link que contém o título completo, não o botão LEIA MAIS.
        if len(title) < 18:
            continue
        seen.add(href)
        links.append((title, href))
    news = []
    for listing_title, link in links[:MAX_NEWS]:
        item = {"titulo": listing_title, "link": link, "imagem": "", "resumo": "", "fonte": "Sistema FAMASUL"}
        # Primeiro tenta a imagem do cartão na listagem (incluindo lazy-loading).
        try:
            anchor = listing.select_one(f'a[href="{link}"]')
            if anchor:
                card = anchor
                for ancestor in anchor.parents:
                    if ancestor.name in {"article", "li"} or (ancestor.name == "div" and ancestor.select_one("img")):
                        card = ancestor
                        break
                for img in card.select("img"):
                    src = abs_img(img, NEWS_URL)
                    if src and not any(x in src.lower() for x in ["logo", "icon", "avatar", "placeholder"]):
                        item["imagem"] = src
                        break
        except Exception:
            pass
        try:
            detail = fetch_soup(link)
            h1 = detail.select_one("main h1, article h1, h1.page-title, h1")
            if h1 and text_of(h1):
                item["titulo"] = text_of(h1)
            for selector in [
                'meta[property="og:image"]', 'meta[name="twitter:image"]',
                'meta[property="og:image:url"]'
            ]:
                meta = detail.select_one(selector)
                if meta and meta.get("content"):
                    item["imagem"] = abs_img(meta.get("content"), link)
                    break
            if not item["imagem"]:
                for selector in ["article img", "main .field--name-field-imagem img", "main .field-name-field-foto img",
                                 "main .node__content img", "main img", ".field--name-body img"]:
                    for img in detail.select(selector):
                        src = abs_img(img, link)
                        low = src.lower()
                        if src and not any(x in low for x in ["logo", "icon", "avatar", "banner", "placeholder"]):
                            item["imagem"] = src
                            break
                    if item["imagem"]:
                        break
            for selector in ['meta[property="og:description"]', 'meta[name="description"]', 'meta[name="twitter:description"]']:
                meta = detail.select_one(selector)
                if meta and meta.get("content"):
                    item["resumo"] = clean(meta.get("content"))[:420]
                    break
            if not item["resumo"]:
                for selector in ["article .field--name-body p", "article .field-name-body p", "main article p", "main p"]:
                    p = detail.select_one(selector)
                    if p and len(text_of(p)) > 60:
                        item["resumo"] = text_of(p)[:420]
                        break
        except Exception as exc:
            logging.warning("Não foi possível abrir notícia %s: %s", link, exc)
        news.append(item)
    return news


def scrape_famasul() -> dict:
    home = fetch_soup(FAMASUL)
    banners = scrape_banners(home)
    news = scrape_news()
    return {"banners": banners, "noticias": news}


def parse_brl(value: str):
    value = clean(value).replace("R$", "").replace(" ", "")
    if not value:
        return None
    # No portal os preços aparecem em formato 363.97. Também aceita 1.234,56.
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def marker_for_table(table) -> str | None:
    """Procura o marcador de cotação mais próximo antes da tabela no HTML."""
    marker_patterns = [
        (re.compile(r"^\s*@?boi(?:\s|$)", re.I), "boi"),
        (re.compile(r"^\s*@?vaca(?:\s|$)", re.I), "vaca"),
        (re.compile(r"^\s*saca\s*[-–—:]?\s*milho\s*$", re.I), "milho"),
        (re.compile(r"^\s*saca\s*[-–—:]?\s*soja\s*$", re.I), "soja"),
    ]
    for string_node in table.find_all_previous(string=True, limit=350):
        value = clean(string_node)
        for pattern, key in marker_patterns:
            if pattern.search(value):
                return key
    # Fallback contextual local: nunca usa o texto da página inteira para classificar a tabela.
    parent = table.parent
    local = text_of(parent)[:500].lower() if parent else ""
    for term, key in [("boi", "boi"), ("vaca", "vaca"), ("milho", "milho"), ("soja", "soja")]:
        if term in local:
            return key
    return None


def scrape_cotacoes() -> dict:
    soup = fetch_soup(COTACOES)
    data = {"soja": [], "milho": [], "boi": [], "vaca": []}
    for table in soup.select("table"):
        key = marker_for_table(table)
        if key not in data:
            continue
        for row in table.select("tr"):
            cells = [text_of(c) for c in row.select("th,td")]
            if len(cells) < 3:
                continue
            date = next((c for c in cells if DATE_RE.search(c)), "")
            if not date:
                continue
            # A coluna de preço da tabela é a primeira célula numérica de valor; ignora Funrural.
            price = None
            for cell in cells:
                if "R$" in cell or re.fullmatch(r"\d{2,3}(?:\.\d{2}|,\d{2})", cell.strip()):
                    candidate = parse_brl(cell)
                    if candidate is not None:
                        price = candidate
                        break
            if price is None:
                continue
            place = ""
            for cell in cells:
                if cell == date or DATE_RE.search(cell) or "R$" in cell or parse_brl(cell) is not None:
                    continue
                if clean(cell).lower() in {"data", "praça", "praca", "valor", "com funrural"}:
                    continue
                if clean(cell):
                    place = clean(cell)
                    break
            if place:
                data[key].append({"data": date, "praca": place, "valor": price})
    for key, rows in data.items():
        dedup = {}
        for item in rows:
            dedup[(item["data"], slugify(item["praca"]))] = item
        data[key] = list(dedup.values())
        logging.info("Cotações %s: %d registros", key, len(data[key]))
    return data


_COURSES_CACHE: list[dict] | None = None


def scrape_cursos(slug: str) -> list[dict]:
    """Coleta a listagem pública de próximos cursos e filtra pelo município.

    O portal /municipios não apresenta os cursos no HTML inicial em várias
    situações; /cursos publica os cartões com título, período e metadados.
    A listagem é baixada uma única vez por execução.
    """
    global _COURSES_CACHE
    if _COURSES_CACHE is None:
        url = SENAR
        soup = fetch_soup(url)
        all_courses: list[dict] = []
        seen: set[tuple[str, str, str, str]] = set()
        municipality_by_slug = {slugify(name): name for name in MUNICIPIOS}

        for element in soup.find_all(True):
            label = text_of(element)
            if not label or len(label) > 320:
                continue
            match = DATE_RANGE.match(label)
            if not match:
                continue
            start, end, full_title = match.groups()
            full_title = clean(full_title).strip(" -–—:")
            if re.search(r"\b(CONFIRMADO|ABERTO|INSCRIÇÕES ABERTAS|CARGA HORÁRIA|LOCALIZAÇÃO|PARCEIRO|TELEFONE|E-MAIL)\b", full_title, re.I):
                continue
            if len(full_title) < 4 or full_title.lower() in {"mais informações", "leia mais"}:
                continue

            # O nome do município normalmente aparece no final do título do curso.
            matched_slug = None
            course_title = full_title
            for candidate_slug, city in sorted(municipality_by_slug.items(), key=lambda item: len(item[1]), reverse=True):
                if full_title.casefold().endswith(" - " + city.casefold()):
                    matched_slug = candidate_slug
                    course_title = full_title[:-(len(city) + 3)].strip(" -–—:")
                    break
            if not matched_slug:
                continue

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
            key = (matched_slug, slugify(course_title), start, end)
            if key in seen:
                continue
            seen.add(key)
            all_courses.append({
                "titulo": course_title[:180],
                "periodo": f"{start} até {end}",
                "data_inicio": start,
                "data_fim": end,
                "carga_horaria": int(hours.group(1)) if hours else None,
                "local": clean(local.group(1)) if local else "",
                "status": status.group(1).upper() if status else "",
                "municipio_slug": matched_slug,
                "link": more_link or url,
                "fonte": url,
            })
        _COURSES_CACHE = all_courses
        logging.info("SENAR: %d cursos identificados na listagem pública", len(all_courses))

    result = [course for course in _COURSES_CACHE if course["municipio_slug"] == slug]
    logging.info("SENAR %s: %d cursos identificados", slug, len(result))
    return result


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


if __name__ == "__main__":
    main()
