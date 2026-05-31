#!/usr/bin/env python3
"""Corporate insider BUYS — SEC Form 4, via Financial Modeling Prep (same key as
congress). Executives/directors buying their own stock is the classic legal
'insider' signal; cluster buys (several insiders, one company) are the strongest.

Emits BUY signals into data/insider_signals.json with a strength scaled by dollar
size and how many distinct insiders bought the same name. Accumulates across runs.

Free tier serves page 0 only (~25 rows); self-throttles like fetch_congress.
Writes data/_debug_insiders.json. Run by the Action.
"""
import json, math, os, re, sys, urllib.request, urllib.error
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "insider_signals.json")
DBG = os.path.join(ROOT, "data", "_debug_insiders.json")
KEY = os.environ.get("FMP_API_KEY", "").strip()
MIN_VALUE = 100_000      # ignore token purchases
MAX_ROWS = 600

ENDPOINTS = [
    "https://financialmodelingprep.com/stable/insider-trading/latest?page=0&limit=25&apikey={key}",
    "https://financialmodelingprep.com/api/v4/insider-trading?page=0&apikey={key}",
]
debug = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "key_present": bool(KEY), "attempts": []}


def iso(d):
    for f in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(d)[:19], f).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return str(d)[:10]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "trade-tracker/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.load(r), str(r.status)
    except urllib.error.HTTPError as e:
        body = e.read(160).decode("utf-8", "replace") if e.fp else ""
        return None, f"HTTP {e.code} {body[:100]}"
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        return None, f"ERR {e}"


def is_buy(t):
    t = (t or "").upper()
    return t.startswith("P") or "PURCHASE" in t or "BUY" in t


def pull():
    for tmpl in ENDPOINTS:
        data, status = fetch(tmpl.format(key=KEY))
        debug["attempts"].append({"endpoint": tmpl.split("?")[0], "status": status,
                                   "rows": len(data) if isinstance(data, list) else 0})
        if isinstance(data, list) and data:
            return data
    return []


def main():
    if not KEY:
        debug["note"] = "FMP_API_KEY not set."
        json.dump(debug, open(DBG, "w"), indent=1)
        print("No FMP_API_KEY — keeping insider seed.", file=sys.stderr)
        return 0

    # Self-throttle to stay under FMP's free daily limit (manual runs force it).
    max_age = float(os.environ.get("INSIDER_MAX_AGE_HOURS", "6"))
    if max_age > 0:
        try:
            prev = json.load(open(OUT))
            if not prev.get("is_sample"):
                last = datetime.strptime(prev["last_updated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - last).total_seconds() / 3600 < max_age:
                    print(f"Insider data fresh (< {max_age}h) — skipping.")
                    return 0
        except (OSError, ValueError, KeyError):
            pass

    rows = pull()
    sigs = []
    for t in rows:
        if not is_buy(t.get("transactionType") or t.get("type")):
            continue
        sym = (t.get("symbol") or t.get("ticker") or "").upper()
        shares = float(t.get("securitiesTransacted") or t.get("shares") or 0)
        price = float(t.get("price") or 0)
        value = shares * price
        if not sym or value < MIN_VALUE:
            continue
        sigs.append({
            "date": iso(t.get("transactionDate") or t.get("filingDate") or ""),
            "ticker": sym, "direction": "BUY", "source": "Insider",
            "insider": (t.get("reportingName") or "").title(),
            "title": t.get("typeOfOwner") or "",
            "value": int(value),
            "url": t.get("link") or f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={t.get('reportingCik','')}&type=4",
        })

    if not sigs:
        debug["note"] = "No insider buys parsed (see attempts)."
        json.dump(debug, open(DBG, "w"), indent=1)
        print("No insider buys — keeping seed.", file=sys.stderr)
        return 0

    # Merge with prior signals so history accumulates despite the page-0 cap.
    try:
        prev = json.load(open(OUT))
        if not prev.get("is_sample"):
            sigs = prev.get("signals", []) + sigs
    except (OSError, ValueError):
        pass

    seen, uniq = set(), []
    for s in sigs:
        k = (s["date"], s["ticker"], s.get("insider"), s.get("value"))
        if k not in seen:
            seen.add(k)
            uniq.append(s)

    # Cluster strength: more distinct insiders buying one name = stronger.
    buyers = defaultdict(set)
    for s in uniq:
        buyers[s["ticker"]].add(s.get("insider"))
    for s in uniq:
        n = len(buyers[s["ticker"]])
        base = 40 + min(35, math.log10(max(s["value"], 1)) * 6)   # dollar size
        s["strength"] = int(min(100, base + (n - 1) * 12))         # + cluster
        s["reason"] = (f"{n} insiders buying " if n > 1 else "") + \
            f"{s.get('insider','insider')} bought ${s['value']:,}"

    uniq.sort(key=lambda s: s["date"], reverse=True)
    uniq = uniq[:MAX_ROWS]
    json.dump({"last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "source": "Financial Modeling Prep (Form 4)", "is_sample": False,
               "signals": uniq}, open(OUT, "w"), indent=1)
    debug["note"] = f"OK: {len(uniq)} insider buy signals."
    json.dump(debug, open(DBG, "w"), indent=1)
    print(f"Wrote {len(uniq)} insider buy signals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
