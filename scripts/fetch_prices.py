#!/usr/bin/env python3
"""Refresh ~60 days of daily closes for each Trump-linked ticker.

Source: Stooq CSV (no API key, no signup). Updates the `prices` array in
data/trump_tickers.json in place. Safe to run repeatedly; on any fetch error a
ticker keeps its previous prices.

Run by .github/workflows/update-data.yml.
"""
import csv, io, json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "trump_tickers.json")
DAYS = 60


def stooq(symbol: str):
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    req = urllib.request.Request(url, headers={"User-Agent": "trade-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode("utf-8", "replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    out = []
    for row in rows[-DAYS:]:
        try:
            out.append({"date": row["Date"], "close": round(float(row["Close"]), 2)})
        except (KeyError, ValueError):
            continue
    return out


def main() -> int:
    with open(PATH) as f:
        doc = json.load(f)
    for t in doc.get("tickers", []):
        sym = t.get("stooq") or (t["ticker"].lower() + ".us")
        try:
            prices = stooq(sym)
            if prices:
                t["prices"] = prices
                print(f"  {t['ticker']}: {len(prices)} closes, last {prices[-1]['close']}")
            else:
                print(f"  {t['ticker']}: no rows, keeping previous", file=sys.stderr)
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as e:
            print(f"  {t['ticker']}: {e} — keeping previous", file=sys.stderr)
    doc["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(PATH, "w") as f:
        json.dump(doc, f, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
