#!/usr/bin/env python3
"""Refresh ~60 days of daily closes for each Trump-linked ticker.

Primary source: FMP historical-price-eod (uses FMP_API_KEY, reliable from the
GitHub Actions runners). Fallback: Stooq CSV (no key, but it sometimes blocks
datacenter IPs, which is why it's the fallback). Each ticker keeps its previous
prices on failure. Writes price-fetch diagnostics into data/_debug_prices.json.
"""
import csv, io, json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "trump_tickers.json")
DBG = os.path.join(ROOT, "data", "_debug_prices.json")
KEY = os.environ.get("FMP_API_KEY", "").strip()
DAYS = 60

debug = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "key_present": bool(KEY), "tickers": {}}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "trade-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def from_yahoo(ticker):
    """Free, no key, uniform across symbols. Returns (prices, meta, status).
    meta carries the latest intraday quote (regularMarketPrice updates during
    the session, ~15-min delayed for stocks; real-time for crypto)."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?range=3mo&interval=1d")
    try:
        data = json.loads(_get(url).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return None, None, f"HTTP {e.code}"
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        return None, None, f"ERR {e}"
    try:
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        closes = res["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return None, None, "no data"
    out = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        out.append({"date": datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"),
                    "close": round(float(c), 2)})
    m = res.get("meta", {}) if isinstance(res, dict) else {}
    meta = None
    price = m.get("regularMarketPrice")
    if price is not None:
        prev = m.get("previousClose") or m.get("chartPreviousClose")
        mt = m.get("regularMarketTime")
        meta = {
            "price": round(float(price), 2),
            "prev_close": round(float(prev), 2) if prev else None,
            "as_of": datetime.utcfromtimestamp(mt).strftime("%Y-%m-%dT%H:%M:%SZ") if mt else None,
        }
        if meta["prev_close"]:
            meta["day_pct"] = round((meta["price"] - meta["prev_close"]) / meta["prev_close"] * 100, 2)
    return (out[-DAYS:] if out else None, meta, "ok" if out else "empty")


def from_fmp(ticker):
    if not KEY:
        return None, "no key"
    url = (f"https://financialmodelingprep.com/stable/historical-price-eod/full"
           f"?symbol={ticker}&apikey={KEY}")
    try:
        data = json.loads(_get(url).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        return None, f"ERR {e}"
    rows = data.get("historical", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return None, "unexpected shape"
    out = []
    for row in rows:
        try:
            out.append({"date": row["date"], "close": round(float(row["close"]), 2)})
        except (KeyError, ValueError, TypeError):
            continue
    out.sort(key=lambda x: x["date"])
    return (out[-DAYS:], "ok") if out else (None, "empty")


def from_stooq(symbol):
    try:
        text = _get(f"https://stooq.com/q/d/l/?s={symbol}&i=d").decode("utf-8", "replace")
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, TimeoutError) as e:
        return None, f"ERR {e}"
    out = []
    for row in list(csv.DictReader(io.StringIO(text)))[-DAYS:]:
        try:
            out.append({"date": row["Date"], "close": round(float(row["Close"]), 2)})
        except (KeyError, ValueError):
            continue
    return (out, "ok") if out else (None, "empty")


def main():
    with open(PATH) as f:
        doc = json.load(f)
    for t in doc.get("tickers", []):
        prices, meta, src = None, None, ""
        prices, meta, st = from_yahoo(t["ticker"])
        src = f"yahoo:{st}"
        if not prices:
            prices, st = from_fmp(t["ticker"])
            src += f" | fmp:{st}"
        if not prices:
            sym = t.get("stooq") or (t["ticker"].lower() + ".us")
            prices, st = from_stooq(sym)
            src += f" | stooq:{st}"
        if prices:
            t["prices"] = prices
            # Live-ish quote (intraday). Fall back to last close if no meta.
            if meta and meta.get("price") is not None:
                t["last"] = meta["price"]
                t["prev_close"] = meta.get("prev_close")
                t["day_pct"] = meta.get("day_pct")
                t["as_of"] = meta.get("as_of")
            else:
                t["last"] = prices[-1]["close"]
                t.pop("day_pct", None); t.pop("as_of", None)
            print(f"  {t['ticker']}: {len(prices)} closes, last {t['last']} ({src})")
        else:
            print(f"  {t['ticker']}: kept previous ({src})", file=sys.stderr)
        debug["tickers"][t["ticker"]] = {"source": src, "count": len(prices or []),
                                         "last": t.get("last")}
    doc["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(PATH, "w") as f:
        json.dump(doc, f, indent=1)
    with open(DBG, "w") as f:
        json.dump(debug, f, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
