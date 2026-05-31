#!/usr/bin/env python3
"""Fetch current Congressional STOCK Act disclosures (House + Senate).

Primary source: Financial Modeling Prep (free tier, 250 req/day) when FMP_API_KEY
is set. Writes data/congress_trades.json in the dashboard's schema. If no key is
present (or the request fails), the existing seed file is left untouched so the
site never breaks.

Run by .github/workflows/update-data.yml. Network access is available in CI.
"""
import json, os, re, sys, urllib.request, urllib.error
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "congress_trades.json")
KEY = os.environ.get("FMP_API_KEY", "").strip()
MAX_ROWS = 1500


def amount_mid(text: str) -> int:
    nums = [int(x.replace(",", "")) for x in re.findall(r"\$?([\d,]+)", text or "")]
    return sum(nums) // len(nums) if nums else 0


def iso(d: str) -> str:
    for f in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(d[:19], f).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return d


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "trade-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


def fmp(chamber: str, path: str):
    """Pull paginated latest disclosures from FMP stable API."""
    rows, page, prev_first = [], 0, None
    while page < 12:
        url = f"https://financialmodelingprep.com/stable/{path}?page={page}&limit=100&apikey={KEY}"
        try:
            batch = get(url)
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as e:
            print(f"  {chamber} page {page} stopped: {e}", file=sys.stderr)
            break
        if not isinstance(batch, list) or not batch:
            break
        # Some FMP endpoints ignore ?page= and keep returning the same first
        # record. Detect that and stop, so we don't loop on duplicates.
        sig = json.dumps(batch[0], sort_keys=True)
        if sig == prev_first:
            break
        prev_first = sig
        for t in batch:
            sym = (t.get("symbol") or t.get("ticker") or "").strip().upper()
            if not sym:
                continue
            amt = t.get("amount") or t.get("range") or ""
            name = " ".join(x for x in [t.get("firstName"), t.get("lastName")] if x) or t.get("representative") or t.get("office") or ""
            rows.append({
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
            })
        page += 1
    print(f"  {chamber}: {len(rows)} rows")
    return rows


def main() -> int:
    if not KEY:
        print("No FMP_API_KEY set — keeping existing seed data. "
              "Add the secret to enable live updates.", file=sys.stderr)
        return 0

    rows = []
    rows += fmp("Senate", "senate-latest")
    rows += fmp("House", "house-latest")

    rows = [r for r in rows if r["date"] and r["ticker"]]
    if not rows:
        print("FMP returned no usable rows — keeping existing seed data.", file=sys.stderr)
        return 0

    # Drop duplicates (same filing/trade can recur across pages or chambers).
    seen, unique = set(), []
    for r in rows:
        k = (r["date"], r["politician"], r["ticker"], r["type"], r["amount"], r["disclosure_url"])
        if k in seen:
            continue
        seen.add(k)
        unique.append(r)
    rows = unique

    rows.sort(key=lambda r: r["date"], reverse=True)
    rows = rows[:MAX_ROWS]

    out = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Financial Modeling Prep (live)",
        "is_sample": False,
        "trades": rows,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print(f"Wrote {len(rows)} live trades -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
