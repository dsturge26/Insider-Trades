#!/usr/bin/env python3
"""Catch big new federal contract awards to public companies — e.g. Dell's
$9.7B Pentagon deal. A concrete, tradeable-adjacent public catalyst, independent
of what Trump says.

Source: USAspending.gov API (free, no key). Adds large recent awards to
data/trump_signals.json as unclassified stubs; classify_signals.py maps the
recipient to a ticker (BUY) and scores it. Recipients with no public ticker get
dropped at classification.

Writes data/_debug_contracts.json. Run by the Action before classify_signals.py.
"""
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from fetch_trump_posts import textkey, load_rejected  # noqa: E402

PATH = os.path.join(ROOT, "data", "trump_signals.json")
DBG = os.path.join(ROOT, "data", "_debug_contracts.json")
API = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
CAP = 150
MIN_AMOUNT = 1_000_000_000   # $1B+ — only headline-sized awards
LOOKBACK_DAYS = 30
MAX_NEW = 20

debug = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def fetch_awards():
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=LOOKBACK_DAYS)
    body = {
        "filters": {
            "award_type_codes": ["A", "B", "C", "D"],  # contracts
            "time_period": [{"start_date": start.isoformat(), "end_date": end.isoformat(),
                             "date_type": "action_date"}],
            "award_amounts": [{"lower_bound": MIN_AMOUNT}],
        },
        "fields": ["Award ID", "Recipient Name", "Award Amount",
                   "Awarding Agency", "Start Date", "generated_internal_id"],
        "sort": "Award Amount", "order": "desc", "limit": 50,
    }
    req = urllib.request.Request(
        API, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "trade-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r).get("results", [])


def main():
    with open(PATH) as f:
        doc = json.load(f)
    existing = doc.get("events", [])
    seen = {textkey(e.get("text", "")) for e in existing} | load_rejected()

    try:
        awards = fetch_awards()
        debug["fetched"] = len(awards)
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        debug["error"] = str(e)
        with open(DBG, "w") as f:
            json.dump(debug, f, indent=1)
        print(f"USAspending fetch failed ({e}) — keeping existing.", file=sys.stderr)
        return 0

    new_stubs = []
    for a in awards:
        name = (a.get("Recipient Name") or "").strip()
        amt = a.get("Award Amount") or 0
        agency = (a.get("Awarding Agency") or "").strip()
        date = a.get("Start Date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not name or not amt:
            continue
        bn = amt / 1e9
        text = f"{name} was awarded a ${bn:.1f}B federal contract from {agency}."
        k = textkey(text)
        if k in seen:
            continue
        seen.add(k)
        gid = a.get("generated_internal_id", "")
        url = f"https://www.usaspending.gov/award/{gid}" if gid else "https://www.usaspending.gov/"
        new_stubs.append({"date": date + "T12:00:00Z", "platform": "Federal contract",
                          "text": text, "url": url, "tickers": [],
                          "contract_amount": round(bn, 2), "classified": False})
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
    print(f"Added {len(new_stubs)} contract candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
