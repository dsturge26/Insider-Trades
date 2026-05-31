#!/usr/bin/env python3
"""Retail buzz — tickers spiking in WallStreetBets mentions, via ApeWisdom (free,
no key, no Reddit auth needed). This is a DIFFERENT signal from the others: retail
crowd momentum (GME/AMC-style), high-variance — kept separate, not a buy/sell call.

Writes data/wsb_signals.json + data/_debug_wsb.json. Run by the Action.
"""
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "wsb_signals.json")
DBG = os.path.join(ROOT, "data", "_debug_wsb.json")
API = "https://apewisdom.io/api/v1.0/filter/wallstreetbets/page/1"
TOP = 25

debug = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def main():
    req = urllib.request.Request(API, headers={"User-Agent": "trade-tracker/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, TimeoutError) as e:
        debug["error"] = str(e)
        json.dump(debug, open(DBG, "w"), indent=1)
        print(f"ApeWisdom fetch failed ({e}) — keeping seed.", file=sys.stderr)
        return 0

    out = []
    for r in (data.get("results") or [])[:TOP]:
        m = int(r.get("mentions") or 0)
        prev = int(r.get("mentions_24h_ago") or 0)
        chg = round((m - prev) / prev * 100, 1) if prev else None
        out.append({
            "ticker": (r.get("ticker") or "").upper(),
            "name": r.get("name") or "",
            "mentions": m, "mentions_24h_ago": prev, "change_pct": chg,
            "rank": int(r.get("rank") or 0),
            "upvotes": int(r.get("upvotes") or 0),
        })
    out = [s for s in out if s["ticker"]]
    json.dump({"last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "source": "ApeWisdom / r/wallstreetbets", "signals": out},
              open(OUT, "w"), indent=1)
    debug["count"] = len(out)
    json.dump(debug, open(DBG, "w"), indent=1)
    print(f"Wrote {len(out)} WSB buzz tickers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
