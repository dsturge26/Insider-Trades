#!/usr/bin/env python3
"""Collect Trump's latest Truth Social posts as candidate signals.

Source: CNN's public Truth Social archive (free, no key, refreshed ~every 5 min):
  https://ix.cnn.io/data/truth-social/truth_archive.json

This step is a cheap keyword PREFILTER only — it adds market-looking posts to
data/trump_signals.json as unclassified stubs. scripts/classify_signals.py then
asks Claude to make the real call (ticker / direction / strength / reason) and
drops anything that isn't genuinely market-relevant. Curated entries are kept.

Writes data/_debug_posts.json. Run by .github/workflows/update-data.yml.
"""
import html, json, os, re, sys, urllib.request, urllib.error
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "trump_signals.json")
DBG = os.path.join(ROOT, "data", "_debug_posts.json")
ARCHIVE = "https://ix.cnn.io/data/truth-social/truth_archive.json"

SCAN = 250    # scan this many most-recent posts for candidates
CAP = 80      # max non-curated events stored

# Coarse prefilter — intentionally broad; the LLM rejects false positives.
MARKET = re.compile(
    r"\b(tariff|tariffs|stock|stocks|market|markets|econom|buy|sell|selling|"
    r"fed|federal reserve|interest rate|rates|inflation|recession|oil|gold|"
    r"crypto|bitcoin|btc|ethereum|dollar|nasdaq|dow|s&p|semiconductor|chips|"
    r"trade deal|deal with|gdp|jobs report|wall street|djt|earnings|powell|"
    r"china|rate cut|soft landing|drill|energy|boeing|apple|tesla)\b", re.I)
CASHTAG = re.compile(r"\$([A-Za-z]{1,5})\b")
TAGS = re.compile(r"<[^>]+>")

debug = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "source": ARCHIVE}


def strip_html(s):
    return html.unescape(TAGS.sub("", s or "")).strip()


def textkey(s):
    """Normalized key for de-duping reposts of the same content."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())[:120]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "trade-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    with open(PATH) as f:
        doc = json.load(f)
    existing = doc.get("events", [])
    existing_urls = {e.get("url") for e in existing}
    # Collapse reposts: a normalized text key catches the same content posted
    # under different URLs/timestamps.
    seen_text = {textkey(e.get("text", "")) for e in existing}

    try:
        posts = fetch(ARCHIVE)
        debug["fetched"] = len(posts) if isinstance(posts, list) else 0
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, TimeoutError) as e:
        debug["error"] = str(e)
        with open(DBG, "w") as f:
            json.dump(debug, f, indent=1)
        print(f"Archive fetch failed ({e}) — keeping existing signals.", file=sys.stderr)
        return 0

    posts = [p for p in posts if isinstance(p, dict) and p.get("created_at")]
    posts.sort(key=lambda p: p["created_at"], reverse=True)

    new_stubs = []
    for p in posts[:SCAN]:
        text = strip_html(p.get("content", ""))
        if not MARKET.search(text):
            continue
        url = p.get("url", "")
        tk = textkey(text)
        if not url or url in existing_urls or tk in seen_text:
            continue
        existing_urls.add(url)
        seen_text.add(tk)
        new_stubs.append({
            "date": p["created_at"],
            "platform": "Truth Social",
            "text": text or "(media post — no text)",
            "tickers": sorted({t.upper() for t in CASHTAG.findall(text)}),
            "engagement": p.get("favourites_count", 0),
            "url": url,
            "classified": False,
        })

    events = existing + new_stubs
    # Keep all curated; cap the rest to the newest CAP.
    curated = [e for e in events if e.get("curated")]
    rest = [e for e in events if not e.get("curated")]
    rest.sort(key=lambda e: e.get("date", ""), reverse=True)
    events = curated + rest[:CAP]

    doc["events"] = events
    doc["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(PATH, "w") as f:
        json.dump(doc, f, indent=1)

    debug["new_candidates"] = len(new_stubs)
    debug["total_events"] = len(events)
    debug["unclassified"] = sum(1 for e in events if not e.get("classified"))
    with open(DBG, "w") as f:
        json.dump(debug, f, indent=1)
    print(f"Added {len(new_stubs)} candidates; {debug['unclassified']} await classification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
