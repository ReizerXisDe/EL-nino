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
    ("Pequenos animais", '("medicina veterinária" OR veterinário OR veterinária) (cães OR gatos OR felinos OR caninos OR pets) (saúde OR doença OR prevenção OR tratamento OR vacinação)', "pt"),
    ("Zoonoses e saúde pública", '(zoonose OR zoonoses OR raiva OR leishmaniose OR leptospirose OR esporotricose OR febre maculosa) (vigilância OR prevenção OR animais OR Brasil)', "pt"),
    ("Animais de produção", '(sanidade animal OR saúde animal OR veterinária) (bovinos OR caprinos OR ovinos OR suínos OR aves OR equinos) (doença OR vacina OR diagnóstico OR prevenção)', "pt"),
    ("Pesquisa e inovação veterinária", '("medicina veterinária" OR veterinária OR "saúde animal") (pesquisa OR estudo OR universidade OR diagnóstico OR vacina OR tratamento)', "pt"),
    ("Saúde Única e clima", '("saúde animal" OR veterinária OR zoonoses) ("saúde única" OR calor OR seca OR enchente OR "mudanças climáticas" OR "El Niño")', "pt"),
    ("Pequenos animais", '(veterinary OR veterinarian) (dogs OR cats OR canine OR feline) (health OR disease OR treatment OR vaccination OR prevention)', "en"),
    ("Zoonoses e saúde pública", '(zoonotic disease OR zoonoses OR rabies OR leptospirosis OR leishmaniasis) (animal health OR public health OR surveillance)', "en"),
    ("Animais de produção", '(veterinary OR livestock health) (cattle OR sheep OR goats OR poultry OR pigs OR horses) (disease OR vaccine OR diagnosis OR prevention)', "en"),
    ("Pesquisa e inovação veterinária", '("veterinary medicine" OR "animal health") (research OR study OR diagnostics OR vaccine OR treatment)', "en"),
    ("Saúde Única e clima", '("One Health" OR "animal health") (climate OR heat OR drought OR flood OR "climate change")', "en"),
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


def fetch_query(category, query, days, language="pt"):
    q = f"({query}) when:{days}d"
    if language == "en":
        url = "https://news.google.com/rss/search?q=" + quote_plus(q) + "&hl=en-US&gl=US&ceid=US:en"
    else:
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
        raw_description = text(item, "description")
        description = strip_html(raw_description)
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
            "language": "English" if language == "en" else "Português",
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
    # Prioridade: notícias veterinárias dos últimos 30 dias, com cinco consultas temáticas.
    for category, query, language in QUERIES:
        items.extend(fetch_query(category, query, 30, language))
        time.sleep(0.25)
    items = unique_sorted(items)
    used_window = 30
    # Amplia a janela somente quando a variedade de fontes resulta em poucas manchetes.
    if len(items) < MIN_ITEMS_BEFORE_EXPANDING:
        print("Menos de oito notícias nos últimos 30 dias; ampliando a busca para 90 dias.")
        for category, query, language in QUERIES:
            items.extend(fetch_query(category, query, 90, language))
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
