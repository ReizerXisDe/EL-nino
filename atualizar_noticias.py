#!/usr/bin/env python3
"""Agrega manchetes do Google News RSS sem API key e grava noticias.json."""
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
import json, re, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "noticias.json"
MAX_ITEMS = 12
MIN_ITEMS_BEFORE_EXPANDING = 8
MAX_AGE_DAYS = 90
QUERIES = [
    ("Clima e El Niño", '("El Niño" OR ENSO OR "mudanças climáticas") (clima OR seca OR chuva OR calor)'),
    ("Saúde animal", '(veterinária OR "saúde animal" OR "sanidade animal") (cães OR gatos OR animais OR vacinação)'),
    ("Zoonoses e vetores", '(zoonoses OR leptospirose OR leishmaniose OR carrapatos OR arboviroses) (Brasil OR clima OR chuva)'),
    ("Meio ambiente", '("meio ambiente" OR biodiversidade OR "fauna silvestre" OR ecossistema) (seca OR enchente OR calor OR clima)'),
    ("Produção animal", '(Embrapa OR pecuária OR bovinos OR caprinos OR aves) (seca OR "estresse térmico" OR "saúde animal")'),
]

def text(node, path, default=""):
    found = node.find(path)
    return (found.text or "").strip() if found is not None else default

def parse_date(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def strip_html(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = value.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
    return re.sub(r"\s+", " ", value).strip()

def fetch_query(category, query, days):
    q = f"({query}) when:{days}d"
    url = "https://news.google.com/rss/search?q=" + quote_plus(q) + "&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    req = Request(url, headers={"User-Agent": "PortalVetExtensaoNewsBot/1.0 (+GitHub Actions; RSS reader)"})
    try:
        with urlopen(req, timeout=20) as response:
            payload = response.read()
        root = ET.fromstring(payload)
    except Exception as exc:
        print(f"Aviso: falha no feed '{category}' ({days} dias): {exc}")
        return []
    results = []
    for item in root.findall("./channel/item"):
        title = strip_html(text(item, "title"))
        link = text(item, "link")
        description = strip_html(text(item, "description"))
        published = parse_date(text(item, "pubDate"))
        source_node = item.find("source")
        source = (source_node.text or "").strip() if source_node is not None else "Google News / fonte jornalística"
        if not title or not link or not link.startswith(("https://", "http://")):
            continue
        if not published or published > datetime.now(timezone.utc) + timedelta(days=1):
            continue
        if (datetime.now(timezone.utc) - published).days > MAX_AGE_DAYS:
            continue
        results.append({
            "title": title,
            "link": link,
            "pubDate": published.isoformat(),
            "description": description[:1200],
            "source": source or "Fonte jornalística",
            "category": category,
        })
    return results

def unique_sorted(items):
    seen, out = set(), []
    for item in sorted(items, key=lambda x: x.get("pubDate", ""), reverse=True):
        key = re.sub(r"[^a-z0-9áéíóúãõç]+", " ", item["title"].lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out

def balanced(items, limit=MAX_ITEMS):
    """Limita repetição de uma mesma categoria para dar diversidade ao feed."""
    selected, deferred, counts = [], [], {}
    for item in items:
        cat = item.get("category", "Saúde animal")
        if counts.get(cat, 0) < 4 and len(selected) < limit:
            selected.append(item); counts[cat] = counts.get(cat, 0) + 1
        else:
            deferred.append(item)
    for item in deferred:
        if len(selected) >= limit:
            break
        selected.append(item)
    return sorted(selected, key=lambda x: x.get("pubDate", ""), reverse=True)[:limit]

def main():
    items = []
    # Prioridade: publicações dos últimos 30 dias, com cinco consultas temáticas.
    for category, query in QUERIES:
        items.extend(fetch_query(category, query, 30))
        time.sleep(0.25)
    items = unique_sorted(items)
    used_window = 30
    # Amplia a janela somente quando a variedade de fontes resulta em poucas manchetes.
    if len(items) < MIN_ITEMS_BEFORE_EXPANDING:
        print("Menos de oito notícias nos últimos 30 dias; ampliando a busca para 90 dias.")
        for category, query in QUERIES:
            items.extend(fetch_query(category, query, 90))
            time.sleep(0.25)
        items = unique_sorted(items)
        used_window = 90
    final_items = balanced(items)
    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": used_window,
        "items": final_items,
        "count": len(final_items),
        "note": "Manchetes agregadas via Google News RSS. Verifique a publicação original e fontes oficiais antes de usar informações sanitárias.",
    }
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Arquivo atualizado: {len(final_items)} notícias (janela priorizada: {used_window} dias).")

if __name__ == "__main__":
    main()
