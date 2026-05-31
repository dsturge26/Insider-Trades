#!/usr/bin/env python3
"""Catch Trump endorsing/buying a specific company ANYWHERE — events, interviews,
TV — not just Truth Social. This is the gap that missed "go out and buy a Dell".

Source: Google News RSS (free, no key). Adds market-looking headlines to
data/trump_signals.json as unclassified stubs; classify_signals.py then asks
Claude whether it's a real single-company endorsement and extracts the ticker.

Writes data/_debug_news.json. Run by the Action before classify_signals.py.
"""
import html, json, os, re, sys, urllib.parse, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from fetch_trump_posts import textkey, strip_html, load_rejected  # noqa: E402

PATH = os.path.join(ROOT, "data", "trump_signals.json")
DBG = os.path.join(ROOT, "data", "_debug_news.json")
CAP = 150
MAX_NEW = 25

# Targeted queries — high recall for endorsements; Claude filters precision.
QUERIES = [
    'Trump ("go buy" OR "buy a" OR "should buy" OR endorses OR endorsed OR praises) '
    '(stock OR shares OR company OR CEO) when:14d',
    'Trump praises company stock when:10d',
]
TAGS = re.compile(r"<[^>]+>")
debug = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "queries": {}}


def fetch_rss(query):
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(query) + "&hl=en-US&gl=US&ceid=US:en")
    req = urllib.request.Request(url, headers={"User-Agent": "trade-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read()


def parse_items(xml_bytes):
    out = []
    root = ET.fromstring(xml_bytes)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate")
        desc = strip_html(item.findtext("description") or "")
        try:
            date = parsedate_to_datetime(pub).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if title and link:
            out.append({"title": title, "link": link, "date": date, "desc": desc})
    return out


def main():
    with open(PATH) as f:
        doc = json.load(f)
    existing = doc.get("events", [])
    seen = {textkey(e.get("text", "")) for e in existing} | load_rejected()

    items = []
    for q in QUERIES:
        try:
            got = parse_items(fetch_rss(q))
            debug["queries"][q[:40]] = len(got)
            items += got
        except (urllib.error.URLError, ET.ParseError, ValueError, TimeoutError) as e:
            debug["queries"][q[:40]] = f"ERR {e}"
    items.sort(key=lambda x: x["date"], reverse=True)

    new_stubs = []
    for it in items:
        # The headline carries the signal (e.g. "Trump: 'go out and buy a Dell'").
        text = it["title"] + (f" — {it['desc'][:180]}" if it["desc"] else "")
        k = textkey(it["title"])
        if k in seen:
            continue
        seen.add(k)
        new_stubs.append({"date": it["date"], "platform": "News",
                          "text": text, "url": it["link"],
                          "tickers": [], "classified": False})
        if len(new_stubs) >= MAX_NEW:
            break

    events = existing + new_stubs
    curated = [e for e in events if e.get("curated")]
    rest = [e for e in events if not e.get("curated")]
    rest.sort(key=lambda e: e.get("date", ""), reverse=True)
    doc["events"] = curated + rest[:CAP]
    doc["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(PATH, "w") as f:
        json.dump(doc, f, indent=1)

    debug["new_candidates"] = len(new_stubs)
    with open(DBG, "w") as f:
        json.dump(debug, f, indent=1)
    print(f"Added {len(new_stubs)} news candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
