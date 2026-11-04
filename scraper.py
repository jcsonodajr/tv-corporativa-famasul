#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coletor da TV Corporativa FAMASUL / SENAR-MS.

Novidades desta versão:
- Retry automático e pausa entre requisições.
- Resumos de notícia cortados em fim de frase, sem legenda "(Foto: ...)".
- Cursos: resolve o ano, descarta encerrados, ordena por data e só então limita a 5.
- Praça/região de soja, milho, boi e vaca validadas contra o que o portal publica.
- Trava de segurança: se a coleta do SENAR vier suspeitamente vazia, mantém o anterior.
- Gera dados_tv.json (completo) e dados/<slug>.json (leve, um por município).
"""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
try:
    import segno  # gera o QR code das notícias (pip install segno)
except ImportError:  # sem a biblioteca, a TV só não mostra o QR
    segno = None
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "dados_tv.json"
DADOS_DIR = ROOT / "dados"
FAMASUL = "https://portal.sistemafamasul.com.br/"
NEWS_URL = urljoin(FAMASUL, "noticias")
COTACOES = urljoin(FAMASUL, "cotacoes-online")
SENAR = "https://senarms.org.br/municipios"
TIMEOUT = 20
MAX_NEWS = 8
MAX_COURSES = 8
HORIZON_DAYS = 45
TZ = ZoneInfo("America/Campo_Grande")
MS = "Mato Grosso do Sul"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
session = requests.Session()
session.headers.update(HEADERS)
_retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=_retry))
session.mount("http://", HTTPAdapter(max_retries=_retry))

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

# Praças de cidade (milho e vaca).
PRACAS = {
    "dourados": "Dourados", "douradina": "Dourados", "itapora": "Dourados", "caarapo": "Dourados",
    "fatima-do-sul": "Dourados", "gloria-de-dourados": "Dourados", "deodapolis": "Dourados",
    "rio-brilhante": "Dourados", "maracaju": "Maracaju", "sidrolandia": "Sidrolândia",
    "campo-grande": "Campo Grande", "chapadao-do-sul": "Chapadão do Sul",
    "sao-gabriel-do-oeste": "São Gabriel do Oeste", "sonora": "Sonora", "ponta-pora": "Ponta Porã"
}
# Regiões (soja e boi). Confirme a divisão oficial do portal e complete os municípios que faltam.
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
DATE_FULL = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def make_qr(url: str) -> str:
    """QR code como imagem SVG embutida (data URI). Vazio se a biblioteca não estiver instalada."""
    if not segno:
        if not getattr(make_qr, "_avisou", False):
            logging.warning("Biblioteca 'segno' não instalada: QR codes desativados. Adicione 'segno' ao requirements.txt.")
            make_qr._avisou = True
        return ""
    if not url:
        return ""
    try:
        return segno.make(url, error="m", micro=False).svg_data_uri(
            scale=5, border=2, dark="#000000", light="#ffffff")
    except Exception as exc:
        logging.warning("Falha ao gerar QR de %s: %s", url, exc)
        return ""


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def clean(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def text_of(node) -> str:
    return clean(node.get_text(" ", strip=True)) if node else ""


def shorten(text: str, limit: int = 320) -> str:
    """Remove legenda de foto, conserta frases coladas e corta em fim de frase."""
    text = clean(text)
    text = re.sub(r"^\(Foto:[^)]*\)\s*", "", text)
    text = re.sub(r"([a-zà-ú])([.!?])([A-ZÀ-Ú])", r"\1\2 \3", text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end > limit * 0.5:
        return cut[: end + 1]
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"


def https(url: str) -> str:
    return url.replace("http://", "https://", 1) if url.startswith("http://") else url


def fetch_soup(url: str) -> BeautifulSoup:
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    # bytes: o BeautifulSoup lê o charset declarado no HTML (mais rápido e confiável).
    return BeautifulSoup(response.content, "html.parser")


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
    return https(urljoin(base_url, src)) if src else ""


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
        if not title or title.lower() in {"leia mais", "mais informações"} or len(title) < 18:
            continue
        if href.rstrip("/") == NEWS_URL.rstrip("/") or href in seen:
            continue
        seen.add(href)
        links.append((title, href))
    news = []
    for listing_title, link in links[:MAX_NEWS]:
        item = {"titulo": listing_title, "link": link, "imagem": "", "resumo": "", "fonte": "Sistema FAMASUL", "data": "", "qr": ""}
        try:
            # Data: texto dd/mm/aaaa imediatamente antes do link do título na listagem.
            title_a = next((a for a in listing.select('a[href*="/noticias/"]')
                            if urljoin(NEWS_URL, a.get("href", "")) == link and text_of(a) == listing_title), None)
            if title_a:
                for s in title_a.find_all_previous(string=True, limit=8):
                    if DATE_FULL.match(clean(s)):
                        item["data"] = clean(s)
                        break
        except Exception:
            pass
        try:
            # Compara pelo href absoluto (o href original costuma ser relativo).
            anchor = next((a for a in listing.select('a[href*="/noticias/"]')
                           if urljoin(NEWS_URL, a.get("href", "")) == link), None)
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
            if not item["data"]:
                meta = detail.select_one('meta[property="article:published_time"]')
                iso = re.match(r"(\d{4})-(\d{2})-(\d{2})", meta.get("content", "")) if meta else None
                if iso:
                    item["data"] = f"{iso.group(3)}/{iso.group(2)}/{iso.group(1)}"
            for selector in ['meta[property="og:image"]', 'meta[name="twitter:image"]', 'meta[property="og:image:url"]']:
                meta = detail.select_one(selector)
                if meta and meta.get("content"):
                    item["imagem"] = abs_img(meta.get("content"), link)
                    break
            if not item["imagem"]:
                for selector in ["article img", "main .field--name-field-imagem img", "main .field-name-field-foto img",
                                 "main .node__content img", "main img", ".field--name-body img"]:
                    for img in detail.select(selector):
                        src = abs_img(img, link)
                        if src and not any(x in src.lower() for x in ["logo", "icon", "avatar", "banner", "placeholder"]):
                            item["imagem"] = src
                            break
                    if item["imagem"]:
                        break
            for selector in ['meta[property="og:description"]', 'meta[name="description"]', 'meta[name="twitter:description"]']:
                meta = detail.select_one(selector)
                if meta and meta.get("content"):
                    item["resumo"] = shorten(meta.get("content"))
                    break
            if not item["resumo"]:
                for selector in ["article .field--name-body p", "article .field-name-body p", "main article p", "main p"]:
                    for p in detail.select(selector):
                        candidate = shorten(text_of(p))
                        if len(candidate) > 60:
                            item["resumo"] = candidate
                            break
                    if item["resumo"]:
                        break
        except Exception as exc:
            logging.warning("Não foi possível abrir notícia %s: %s", link, exc)
        item["qr"] = make_qr(link)
        news.append(item)
        time.sleep(0.3)
    return news


def scrape_famasul() -> dict:
    home = fetch_soup(FAMASUL)
    return {"banners": scrape_banners(home), "noticias": scrape_news()}


def parse_brl(value: str):
    value = clean(value).replace("R$", "").replace(" ", "")
    if not value:
        return None
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
            date_s = next((c for c in cells if DATE_RE.search(c)), "")
            if not date_s:
                continue
            # Primeira célula numérica = valor divulgado. Confirme no portal se é "com" ou "sem" Funrural.
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
                if cell == date_s or DATE_RE.search(cell) or "R$" in cell or parse_brl(cell) is not None:
                    continue
                if clean(cell).lower() in {"data", "praça", "praca", "valor", "com funrural"}:
                    continue
                if clean(cell):
                    place = clean(cell)
                    break
            if place:
                data[key].append({"data": date_s, "praca": place, "valor": price})
    for key, rows in data.items():
        dedup = {}
        for item in rows:
            dedup[(item["data"], slugify(item["praca"]))] = item
        data[key] = list(dedup.values())
        logging.info("Cotações %s: %d registros", key, len(data[key]))
    return data


def pick(items: list[dict], preferred: str) -> str:
    """Usa a praça/região preferida só se o portal realmente a publica; senão, média do estado."""
    available = {slugify(i["praca"]) for i in items}
    return preferred if slugify(preferred) in available else MS


def _dmy(value: str, year: int) -> date:
    p = value.split("/")
    return date(int(p[2]) if len(p) > 2 else year, int(p[1]), int(p[0]))


def resolve_dates(start_s: str, end_s: str, today: date):
    """Infere o ano das datas (o portal publica só dd/mm)."""
    try:
        start, end = _dmy(start_s, today.year), _dmy(end_s, today.year)
    except ValueError:
        return None
    if end < start:  # ex.: 24/11 até 05/11 -> termina no ano seguinte
        end = end.replace(year=end.year + 1)
    if end < today - timedelta(days=60):  # ex.: 08/04 até 07/05 -> ciclo do ano seguinte
        start = start.replace(year=start.year + 1)
        end = end.replace(year=end.year + 1)
    return start, end


def scrape_cursos(slug: str, today: date) -> list[dict]:
    """Coleta todos os cursos do município, filtra encerrados/distantes e limita a 5."""
    municipality_by_slug = {slugify(name): name for name in MUNICIPIOS}
    city = municipality_by_slug.get(slug)
    if not city:
        logging.warning("Slug de município não reconhecido: %s", slug)
        return []

    url = f"{SENAR}?{urlencode({'municipio': city.upper()})}"
    soup = fetch_soup(url)
    courses: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for button in soup.select("button.accordion"):
        match = DATE_RANGE.match(text_of(button))
        if not match:
            continue
        start, end, title = match.groups()
        title = clean(title).strip(" -–—:")
        if len(title) < 4 or title.lower() in {"mais informações", "leia mais"}:
            continue
        dates = resolve_dates(start, end, today)
        if not dates:
            continue
        d_start, d_end = dates

        detail_nodes = []
        sibling = button.find_next_sibling()
        while sibling is not None:
            if sibling.name == "button" and "accordion" in (sibling.get("class") or []):
                break
            detail_nodes.append(sibling)
            sibling = sibling.find_next_sibling()
        blob = clean(" ".join(text_of(node) for node in detail_nodes))

        if not blob or not any(t in blob.casefold() for t in ("carga horária", "localização", "confirmado", "aberto")):
            pieces = []
            for node in button.find_all_next(True):
                if node.name == "button" and "accordion" in (node.get("class") or []):
                    break
                if node.name in {"div", "p", "a", "span", "strong", "b", "li"}:
                    pieces.append(node)
                    if len(pieces) >= 30:
                        break
            fallback_blob = clean(" ".join(text_of(node) for node in pieces))
            if len(fallback_blob) > len(blob):
                blob = fallback_blob

        hours = re.search(r"Carga\s+horária\s*:\s*(\d+)", blob, re.I)
        vacancies = re.search(r"Total\s+de\s+vagas\s*:\s*(\d+)", blob, re.I)
        local = re.search(r"Localização\s*:\s*(.+?)(?=\s+(?:Parceiro|Telefone|E-mail)\s*:|$)", blob, re.I)
        status = re.search(r"\b(CONFIRMADO|INSCRIÇÕES ABERTAS|ABERTO)\b", blob, re.I)

        more_link = ""
        for node in detail_nodes:
            for anchor in node.select("a[href]"):
                if "mais informações" in text_of(anchor).casefold():
                    more_link = urljoin(url, anchor.get("href", ""))
                    break
            if more_link:
                break
        if not more_link:
            anchor = button.find_next("a", string=re.compile(r"mais informações", re.I))
            if anchor:
                more_link = urljoin(url, anchor.get("href", ""))

        key = (slug, d_start.isoformat(), slugify(title))
        if key in seen:
            continue
        seen.add(key)
        periodo = f"{start} até {end}"
        if d_end.year != d_start.year:
            periodo = f"{start} até {d_end:%d/%m/%Y}"
        courses.append({
            "titulo": title[:180],
            "periodo": periodo,
            "data_inicio": start,
            "data_fim": end,
            "data_inicio_iso": d_start.isoformat(),
            "data_fim_iso": d_end.isoformat(),
            "carga_horaria": int(hours.group(1)) if hours else None,
            "vagas": int(vacancies.group(1)) if vacancies else None,
            "local": clean(local.group(1)) if local else "",
            "status": status.group(1).upper() if status else "",
            "municipio_slug": slug,
            "link": https(more_link or url),
            "fonte": url,
        })

    horizon = (today + timedelta(days=HORIZON_DAYS)).isoformat()
    courses = [c for c in courses if c["data_fim_iso"] >= today.isoformat() and c["data_inicio_iso"] <= horizon]
    courses.sort(key=lambda c: c["data_inicio_iso"])
    logging.info("SENAR %s: %d cursos válidos (máx. %d exibidos)", city, len(courses), MAX_COURSES)
    return courses[:MAX_COURSES]


def main() -> None:
    previous = {}
    if OUTPUT.exists():
        try:
            previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
        except Exception:
            logging.warning("JSON anterior inválido; será reconstruído.")
    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now(TZ).date()
    old_famasul = previous.get("famasul", {"banners": [], "noticias": []})
    old_quotes = previous.get("cotacoes", {"soja": [], "milho": [], "boi": [], "vaca": []})
    payload = {
        "schema_version": 2,
        "gerado_em": now,
        "fontes": {"famasul": FAMASUL, "noticias": NEWS_URL, "cotacoes": COTACOES, "senar": SENAR},
        "municipios": {},
        "famasul": old_famasul,
        "cotacoes": old_quotes,
        "avisos": [],
    }
    try:
        collected = scrape_famasul()
        if collected.get("banners") or collected.get("noticias"):
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

    quotes = payload["cotacoes"]
    old_municipios = previous.get("municipios", {})
    for name in MUNICIPIOS:
        slug = slugify(name)
        regiao = REGIOES.get(slug, MS)
        praca = PRACAS.get(slug, MS)
        base = {
            "nome": name,
            "slug": slug,
            "praca_milho": pick(quotes.get("milho", []), praca),
            "praca_vaca": pick(quotes.get("vaca", []), praca),
            "regiao_soja": pick(quotes.get("soja", []), regiao),
            "regiao_boi": pick(quotes.get("boi", []), regiao),
        }
        try:
            courses = scrape_cursos(slug, today)
            if not courses:
                payload["avisos"].append(f"Nenhum curso vigente na página do SENAR para {name}.")
            payload["municipios"][slug] = {**base, "cursos": courses}
        except Exception as exc:
            logging.warning("Falha SENAR %s: %s", name, exc)
            old = old_municipios.get(slug, {})
            payload["municipios"][slug] = {**base, "cursos": old.get("cursos", [])}
            payload["avisos"].append(f"Falha ao atualizar cursos de {name}; preservada a lista anterior.")
        time.sleep(0.3)

    # Trava: estrutura do SENAR mudou e zerou tudo?
    total = sum(len(m["cursos"]) for m in payload["municipios"].values())
    old_total = sum(len(m.get("cursos", [])) for m in old_municipios.values())
    if old_total and total < old_total * 0.3:
        for slug, m in payload["municipios"].items():
            m["cursos"] = old_municipios.get(slug, {}).get("cursos", [])
        payload["avisos"].append("Coleta do SENAR suspeita (queda brusca); preservados cursos anteriores.")
        logging.warning("Coleta do SENAR suspeita: %d cursos contra %d antes.", total, old_total)

    tmp = OUTPUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUTPUT)

    DADOS_DIR.mkdir(exist_ok=True)
    for slug, m in payload["municipios"].items():
        slim = {
            "schema_version": 2, "gerado_em": now, "municipio": m,
            "famasul": payload["famasul"], "cotacoes": payload["cotacoes"],
        }
        (DADOS_DIR / f"{slug}.json").write_text(json.dumps(slim, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    logging.info("Arquivos atualizados: %s e %s/", OUTPUT, DADOS_DIR)
    logging.info("Resumo: noticias=%d, soja=%d, milho=%d, boi=%d, vaca=%d, avisos=%d",
                 len(payload["famasul"].get("noticias", [])),
                 *(len(quotes.get(k, [])) for k in ("soja", "milho", "boi", "vaca")), len(payload["avisos"]))


if __name__ == "__main__":
    main()
