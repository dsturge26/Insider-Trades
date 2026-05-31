#!/usr/bin/env python3
"""Fetch current Congressional STOCK Act disclosures (House + Senate) from FMP.

Tries several FMP endpoints (the free plan exposes different ones than paid),
and writes data/_debug.json with the exact HTTP status of each attempt so
failures are diagnosable without digging through Actions logs.

If nothing usable comes back, the existing seed file is left untouched so the
site never breaks. Run by .github/workflows/update-data.yml.
"""
import json, os, re, sys, urllib.request, urllib.error
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "congress_trades.json")
DBG = os.path.join(ROOT, "data", "_debug.json")
KEY = os.environ.get("FMP_API_KEY", "").strip()
MAX_ROWS = 1500

# FMP "stable" disclosure endpoints. The free tier caps limit at 25, so we
# request 25 per page and walk pages. (Legacy v4 endpoints are dead — 403.)
ENDPOINTS = {
    "Senate": [
        "https://financialmodelingprep.com/stable/senate-latest?page={page}&limit=25&apikey={key}",
    ],
    "House": [
        "https://financialmodelingprep.com/stable/house-latest?page={page}&limit=25&apikey={key}",
    ],
}

debug = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "key_present": bool(KEY), "attempts": []}


def amount_mid(text):
    nums = [int(x.replace(",", "")) for x in re.findall(r"\$?([\d,]+)", text or "")]
    return sum(nums) // len(nums) if nums else 0


def iso(d):
    for f in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(d)[:19], f).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return str(d)


def fetch(url):
    """Return (rows_json, status_str). status is HTTP code or error label."""
    req = urllib.request.Request(url, headers={"User-Agent": "trade-tracker/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.load(r), str(r.status)
    except urllib.error.HTTPError as e:
        body = e.read(200).decode("utf-8", "replace") if e.fp else ""
        return None, f"HTTP {e.code} {body[:120]}"
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        return None, f"ERR {e}"


def normalize(t, chamber):
    sym = (t.get("symbol") or t.get("ticker") or "").strip().upper()
    if not sym:
        return None
    amt = t.get("amount") or t.get("range") or ""
    name = " ".join(x for x in [t.get("firstName"), t.get("lastName")] if x) \
        or t.get("representative") or t.get("office") or ""
    return {
        "date": iso(t.get("transactionDate") or t.get("date") or ""),
        "politician": name.strip(),
        "chamber": chamber,
        "party": (t.get("party") or "").strip(),
        "ticker": sym,
        "company": (t.get("assetDescription") or t.get("company") or sym).strip(),
        "type": (t.get("type") or t.get("transactionType") or "").strip(),
        "owner": (t.get("owner") or "").strip(),
        "amount": str(amt).strip(),
        "amount_mid": amount_mid(str(amt)),
        "disclosure_url": (t.get("link") or t.get("ptr_link") or "").strip(),
    }


def pull_chamber(chamber):
    for tmpl in ENDPOINTS[chamber]:
        rows, prev_first = [], None
        page, status, base = 0, "", tmpl.split("?")[0]
        while page < 24:  # 24 pages x 25 = up to 600 rows/chamber
            data, status = fetch(tmpl.format(page=page, key=KEY))
            if not isinstance(data, list) or not data:
                break
            sig = json.dumps(data[0], sort_keys=True)
            if sig == prev_first:
                break
            prev_first = sig
            for t in data:
                n = normalize(t, chamber)
                if n:
                    rows.append(n)
            page += 1
        debug["attempts"].append({"chamber": chamber, "endpoint": base,
                                   "last_status": status, "rows": len(rows)})
        print(f"  {chamber} {base} -> status {status}, {len(rows)} rows")
        if rows:
            return rows
    return []


def write_debug():
    with open(DBG, "w") as f:
        json.dump(debug, f, indent=1)


def throttled():
    """On frequent schedules, skip the FMP call if the live data is still fresh.
    Keeps us well under FMP's 250-req/day free limit. CONGRESS_MAX_AGE_HOURS=0
    (set on manual runs) forces a refresh."""
    max_age = float(os.environ.get("CONGRESS_MAX_AGE_HOURS", "6"))
    if max_age <= 0:
        return False
    try:
        with open(OUT) as f:
            prev = json.load(f)
        if prev.get("is_sample"):
            return False
        last = datetime.strptime(prev["last_updated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        if age_h < max_age:
            print(f"Congress data is {age_h:.1f}h old (< {max_age}h) — skipping FMP fetch.")
            return True
    except (OSError, ValueError, KeyError):
        pass
    return False


def main():
    if not KEY:
        debug["note"] = "FMP_API_KEY not set in the workflow environment."
        write_debug()
        print("No FMP_API_KEY — keeping seed data.", file=sys.stderr)
        return 0

    if throttled():
        return 0

    rows = pull_chamber("Senate") + pull_chamber("House")
    rows = [r for r in rows if r["date"] and r["ticker"]]
    if not rows:
        debug["note"] = "Key present but no endpoint returned rows (see statuses above)."
        write_debug()
        print("No usable rows from FMP — keeping seed data.", file=sys.stderr)
        return 0

    # The free tier only serves page 0 (~25 rows/chamber per run), so merge with
    # what we already saved. Over daily runs the history accumulates instead of
    # being capped at one page.
    try:
        with open(OUT) as f:
            prev = json.load(f)
        if not prev.get("is_sample"):
            rows = prev.get("trades", []) + rows
    except (OSError, ValueError):
        pass

    seen, unique = set(), []
    for r in rows:
        k = (r["date"], r["politician"], r["ticker"], r["type"], r["amount"], r["disclosure_url"])
        if k not in seen:
            seen.add(k)
            unique.append(r)
    unique.sort(key=lambda r: r["date"], reverse=True)
    unique = unique[:MAX_ROWS]

    with open(OUT, "w") as f:
        json.dump({
            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "Financial Modeling Prep (live)",
            "is_sample": False,
            "trades": unique,
        }, f, indent=1)
    debug["note"] = f"OK: wrote {len(unique)} live trades."
    write_debug()
    print(f"Wrote {len(unique)} live trades -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
