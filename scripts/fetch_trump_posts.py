#!/usr/bin/env python3
"""Pull Trump's latest Truth Social posts and merge market-relevant ones into
data/trump_signals.json.

Source: CNN's public Truth Social archive (free, no key, refreshed ~every 5 min):
  https://ix.cnn.io/data/truth-social/truth_archive.json
Schema per post: id, created_at, content (HTML), url, media, *_count.

We keep posts that look market-relevant (tariffs, stocks, Fed, crypto, etc.)
plus the few most recent, extract any $TICKERS, and preserve all hand-written
"curated": true entries. Sentiment is NOT auto-labelled — the raw post is shown.

Writes data/_debug_posts.json. Run by .github/workflows/update-data.yml.
"""
import html, json, os, re, sys, urllib.request, urllib.error
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "trump_signals.json")
DBG = os.path.join(ROOT, "data", "_debug_posts.json")
ARCHIVE = "https://ix.cnn.io/data/truth-social/truth_archive.json"

KEEP_LATEST = 6      # always include this many most-recent posts
SCAN = 200           # how many recent posts to scan for market relevance
CAP = 60             # max events stored

MARKET = re.compile(
    r"\b(tariff|tariffs|stock|stocks|market|markets|econom|buy|sell|selling|"
    r"fed|federal reserve|interest rate|rates|inflation|recession|oil|gold|"
    r"crypto|bitcoin|btc|ethereum|dollar|nasdaq|dow jones|s&p|semiconductor|"
    r"chips|trade deal|deal with|gdp|jobs report|wall street|djt|earnings|"
    r"china trade|rate cut|soft landing)\b", re.I)
CASHTAG = re.compile(r"\$([A-Za-z]{1,5})\b")
TAGS = re.compile(r"<[^>]+>")

debug = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "source": ARCHIVE}


def strip_html(s):
    return html.unescape(TAGS.sub("", s or "")).strip()


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "trade-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    with open(PATH) as f:
        doc = json.load(f)
    curated = [e for e in doc.get("events", []) if e.get("curated")]

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

    live, seen = [], set()
    for i, p in enumerate(posts[:SCAN]):
        text = strip_html(p.get("content", ""))
        relevant = bool(MARKET.search(text))
        if not relevant and i >= KEEP_LATEST:
            continue
        url = p.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        tickers = sorted({t.upper() for t in CASHTAG.findall(text)})
        live.append({
            "date": p["created_at"],
            "platform": "Truth Social",
            "text": text or "(media post — no text)",
            "tickers": tickers,
            "is_market": relevant,
            "url": url,
            "engagement": p.get("favourites_count", 0),
        })

    # Merge: curated highlights + live posts, newest first.
    events = curated + live
    events.sort(key=lambda e: e.get("date", ""), reverse=True)
    events = events[:CAP]

    doc["events"] = events
    doc["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(PATH, "w") as f:
        json.dump(doc, f, indent=1)

    debug["kept_live"] = len(live)
    debug["curated"] = len(curated)
    debug["newest"] = live[0]["date"] if live else None
    with open(DBG, "w") as f:
        json.dump(debug, f, indent=1)
    print(f"Kept {len(live)} live posts (newest {debug['newest']}) + {len(curated)} curated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
