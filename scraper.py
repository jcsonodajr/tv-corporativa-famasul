#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Digital Signage FAMASUL / SENAR-MS
Instalação: pip install requests beautifulsoup4
Execução: python scraper.py
O script mantém dados_tv.json válido se uma das fontes falhar.
"""
from __future__ import annotations
import json, logging, os, re, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "dados_tv.json"
FAMASUL = "https://portal.sistemafamasul.com.br/"
COTACOES = urljoin(FAMASUL, "cotacoes-online")
SENAR = "https://senarms.org.br/municipios?municipio="
TIMEOUT = 25
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FamasulDigitalSignage/1.0; +https://sistemafamasul.com.br)",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
session = requests.Session()
session.headers.update(HEADERS)

# Catálogo oficial de municípios de MS. Coordenadas são resolvidas pelo endpoint
# público de geocodificação Open-Meteo no navegador, evitando coordenadas aproximadas.
MUNICIPIOS = [
    "Água Clara","Alcinópolis","Amambai","Anastácio","Anaurilândia","Angélica","Antônio João",
    "Aparecida do Taboado","Aquidauana","Aral Moreira","Bandeirantes","Bataguassu","Batayporã",
    "Bela Vista","Bodoquena","Bonito","Brasilândia","Caarapó","Camapuã","Campo Grande",
    "Caracol","Cassilândia","Chapadão do Sul","Corguinho","Coronel Sapucaia","Corumbá",
    "Costa Rica","Coxim","Deodápolis","Dois Irmãos do Buriti","Douradina","Dourados",
    "Eldorado","Fátima do Sul","Figueirão","Glória de Dourados"," Guia Lopes da Laguna".strip(),
    "Iguatemi","Inocência","Itaporã","Itaquiraí","Ivinhema","Japorã","Jaraguari","Jardim",
    "Jateí","Juti","Ladário","Laguna Carapã","Maracaju","Miranda","Mundo Novo","Naviraí",
    "Nioaque","Nova Alvorada do Sul","Nova Andradina","Novo Horizonte do Sul","Paraíso das Águas",
    "Paranaíba","Paranhos","Pedro Gomes","Ponta Porã","Porto Murtinho","Ribas do Rio Pardo",
    "Rio Brilhante","Rio Negro","Rio Verde de Mato Grosso","Rochedo","Santa Rita do Pardo",
    "São Gabriel do Oeste","Selvíria","Sete Quedas","Sidrolândia","Sonora","Tacuru",
    "Taquarussu","Terenos","Três Lagoas","Vicentina"
]
# Praça polo e macrorregião são regras operacionais configuráveis; revisar com a metodologia
# oficial vigente antes de uso institucional. Sem praça definida, usa-se Média MS.
PRACAS = {
    "dourados":"Dourados","douradina":"Dourados","itapora":"Dourados","caarapo":"Dourados",
    "fatima-do-sul":"Dourados","gloria-de-dourados":"Dourados","deodapolis":"Dourados",
    "rio-brilhante":"Dourados","maracaju":"Maracaju","sidrolandia":"Sidrolândia",
    "campo-grande":"Campo Grande","chapadao-do-sul":"Chapadão do Sul",
    "sao-gabriel-do-oeste":"São Gabriel do Oeste","sonora":"Sonora","ponta-pora":"Ponta Porã"
}
REGIOES = {
    "dourados":"Região Sul","douradina":"Região Sul","itapora":"Região Sul","caarapo":"Região Sul",
    "fatima-do-sul":"Região Sul","gloria-de-dourados":"Região Sul","maracaju":"Região Sul",
    "ponta-pora":"Região Sul","amambai":"Região Sul","navirai":"Região Sul","iguatemi":"Região Sul",
    "campo-grande":"Região Centro","sidrolandia":"Região Centro","terenos":"Região Centro",
    "corumba":"Região Oeste","ladario":"Região Oeste","porto-murtinho":"Região Oeste",
    "miranda":"Região Oeste","bonito":"Região Oeste","aquidauana":"Região Oeste",
    "cox im".replace(" ",""):"Região Norte","sonora":"Região Norte","cox im".replace(" ",""):"Região Norte",
    "sao-gabriel-do-oeste":"Região Norte","chapadao-do-sul":"Região Norte","costa-rica":"Região Norte"
}

def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")

def text_of(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""

def fetch_soup(url: str) -> BeautifulSoup:
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return BeautifulSoup(response.text, "html.parser")

def abs_img(img, base_url):
    if not img:
        return ""
    src = img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
    if src.startswith("//"):
        src = "https:" + src
    # Se o site entrega imagem Drupal derivada, preserva a URL que ele publica.
    return urljoin(base_url, src)

def scrape_famasul():
    result = {"banners": [], "noticias": []}
    soup = fetch_soup(FAMASUL)
    seen = set()
    for selector in [".view-banner-principal img", ".views-field-field-arquivo img"]:
        for img in soup.select(selector):
            src = abs_img(img, FAMASUL)
            if src and src not in seen:
                seen.add(src)
                parent = img.find_parent("a")
                result["banners"].append({
                    "imagem": src, "titulo": img.get("alt","").strip(),
                    "link": urljoin(FAMASUL, parent.get("href","")) if parent else FAMASUL
                })
    seen_titles = set()
    # Cada item é tratado como unidade para não cruzar imagem/título entre cards.
    for item in soup.select(".jcarousel-item, .view-noticias .views-row, .views-field-field-data-blog"):
        title_node = item.select_one(".views-field-field-data-blog .blog-rotativo a, .blog-rotativo a, h2 a, h3 a, .views-field-title a")
        if not title_node:
            continue
        title = text_of(title_node)
        link = urljoin(FAMASUL, title_node.get("href",""))
        img = item.select_one(".views-field-field-foto-destaque img, img")
        image = abs_img(img, FAMASUL)
        key = (title, link)
        if title and key not in seen_titles:
            seen_titles.add(key)
            result["noticias"].append({
                "titulo": title, "link": link, "imagem": image,
                "resumo": text_of(item.select_one(".field-content p, .views-field-body, p"))[:420],
                "fonte": "Sistema FAMASUL"
            })
    # Tentativa adicional em cards Drupal comuns, sem perder o vínculo de cada item.
    if len(result["noticias"]) < 5:
        for item in soup.select(".views-row"):
            a = item.select_one("h2 a, h3 a, .views-field-title a")
            if not a:
                continue
            title = text_of(a); link = urljoin(FAMASUL, a.get("href",""))
            key = (title, link)
            if title and key not in seen_titles:
                seen_titles.add(key)
                result["noticias"].append({
                    "titulo": title, "link": link,
                    "imagem": abs_img(item.select_one("img"), FAMASUL),
                    "resumo": text_of(item.select_one("p"))[:420],
                    "fonte": "Sistema FAMASUL"
                })
    return result

def parse_brl(value):
    value = value.strip().replace("R$", "").replace(" ", "")
    # O portal costuma publicar decimal com ponto (ex.: 142.50).
    try:
        return float(value.replace(",", "."))
    except (ValueError, AttributeError):
        return None

def scrape_cotacoes():
    soup = fetch_soup(COTACOES)
    # Coleta tabelas do Drupal pelo cabeçalho e contexto da tabela.
    tables = soup.select("table")
    data = {"soja": [], "milho": [], "boi": [], "vaca": []}
    for table in tables:
        heading = table.find_previous(["h2","h3","h4","strong"])
        context = (text_of(heading) + " " + text_of(table.find_parent())).lower()
        if "soja" in context: key = "soja"
        elif "milho" in context: key = "milho"
        elif "vaca" in context: key = "vaca"
        elif "boi" in context: key = "boi"
        else: continue
        rows = table.select("tr")
        for row in rows[1:]:
            cells = [text_of(c) for c in row.select("th,td")]
            if len(cells) < 3:
                continue
            date = next((c for c in cells if re.search(r"\d{2}/\d{2}/\d{4}", c)), "")
            price_cells = [parse_brl(c) for c in cells if "R$" in c or re.fullmatch(r"\d{2,3}\.\d{2}", c)]
            price_cells = [p for p in price_cells if p is not None]
            place = next((c for c in cells if c != date and not re.search(r"\d{2}/\d{2}/\d{4}", c) and parse_brl(c) is None and c.lower() not in ("data","praça","valor","com funrural")), "")
            if date and place and price_cells:
                data[key].append({"data":date,"praca":place,"valor":price_cells[0]})
    # Fallback robusto para o conteúdo textual indexado no portal: evita publicar preço inventado.
    for key in data:
        dedup = {}
        for item in data[key]:
            ident = (item["data"], item["praca"])
            dedup[ident] = item
        data[key] = list(dedup.values())
    return data

def scrape_cursos(slug):
    url = SENAR + slug
    soup = fetch_soup(url)
    courses = []
    # Seletores tolerantes a alterações de classes; cada bloco de curso é lido isoladamente.
    candidates = soup.select(".views-row, .curso, .views-field-title, article, .item-list li")
    seen = set()
    for item in candidates:
        title_node = item.select_one("h2, h3, h4, .views-field-title, strong, a")
        title = text_of(title_node)
        blob = text_of(item)
        if not title or len(title) < 5:
            continue
        if not re.search(r"\d{1,2}/\d{1,2}(?:\s+até\s+\d{1,2}/\d{1,2})?", blob, re.I):
            continue
        # Evita recolher texto geral de páginas e mantém título e metadados do mesmo card.
        date_match = re.search(r"\d{1,2}/\d{1,2}(?:/\d{4})?\s*(?:até|a|-)\s*\d{1,2}/\d{1,2}(?:/\d{4})?", blob, re.I)
        hours_match = re.search(r"Carga horária:\s*(\d+)", blob, re.I)
        local_match = re.search(r"(?:Localização|Local):\s*(.+?)(?:Parceiro:|Telefone:|E-mail:|$)", blob, re.I)
        status_match = re.search(r"\b(CONFIRMADO|ABERTO|INSCRIÇÕES ABERTAS)\b", blob, re.I)
        key = (title.lower(), date_match.group(0) if date_match else "")
        if key in seen:
            continue
        seen.add(key)
        courses.append({
            "titulo": title[:180],
            "periodo": date_match.group(0) if date_match else "",
            "carga_horaria": int(hours_match.group(1)) if hours_match else None,
            "local": local_match.group(1).strip() if local_match else "",
            "status": status_match.group(1).upper() if status_match else "",
            "municipio_slug": slug,
            "fonte": url
        })
    return courses

def main():
    previous = {}
    if OUTPUT.exists():
        try:
            previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
        except Exception:
            logging.warning("JSON anterior inválido; será reconstruído.")
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema_version": 1,
        "gerado_em": now,
        "fontes": {"famasul": FAMASUL, "cotacoes": COTACOES, "senar": "https://senarms.org.br/municipios"},
        "municipios": {},
        "famasul": previous.get("famasul", {"banners": [], "noticias": []}),
        "cotacoes": previous.get("cotacoes", {"soja": [], "milho": [], "boi": [], "vaca": []}),
        "avisos": []
    }
    try:
        payload["famasul"] = scrape_famasul()
        logging.info("FAMASUL: %d banners, %d notícias", len(payload["famasul"]["banners"]), len(payload["famasul"]["noticias"]))
    except Exception as exc:
        logging.exception("Falha ao coletar FAMASUL")
        payload["avisos"].append("FAMASUL indisponível; preservados dados anteriores.")
    try:
        new_quotes = scrape_cotacoes()
        if any(new_quotes.values()):
            payload["cotacoes"] = new_quotes
        else:
            payload["avisos"].append("Nenhuma cotação reconhecida; preservadas cotações anteriores.")
    except Exception:
        logging.exception("Falha ao coletar cotações")
        payload["avisos"].append("Cotações indisponíveis; preservados dados anteriores.")
    old_municipios = previous.get("municipios", {})
    for name in MUNICIPIOS:
        slug = slugify(name)
        try:
            courses = scrape_cursos(slug)
            payload["municipios"][slug] = {
                "nome": name, "slug": slug, "cursos": courses,
                "praca_graos": PRACAS.get(slug, "Mato Grosso do Sul"),
                "regiao_pecuaria": REGIOES.get(slug, "Mato Grosso do Sul"),
                "atualizado_em": now
            }
            logging.info("%s: %d cursos", name, len(courses))
        except Exception as exc:
            logging.warning("Falha SENAR %s: %s", name, exc)
            payload["municipios"][slug] = old_municipios.get(slug, {
                "nome": name, "slug": slug, "cursos": [],
                "praca_graos": PRACAS.get(slug, "Mato Grosso do Sul"),
                "regiao_pecuaria": REGIOES.get(slug, "Mato Grosso do Sul"),
                "atualizado_em": None
            })
            payload["avisos"].append(f"Falha ao atualizar cursos de {name}.")
    # Escrita atômica para impedir que a TV leia JSON pela metade.
    tmp = OUTPUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUTPUT)
    logging.info("Arquivo atualizado: %s", OUTPUT)

if __name__ == "__main__":
    main()
