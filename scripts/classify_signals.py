#!/usr/bin/env python3
"""Classify candidate Trump posts into trade signals using Claude (Haiku 4.5).

For each unclassified, non-curated event in data/trump_signals.json, Claude
returns: is_market, ticker, direction (BUY/SELL/WATCH), strength (0-100), and a
one-line reason. Non-market posts are dropped. Market posts also get a
"price since post" move for their ticker (Yahoo Finance, free).

Design notes:
- Incremental: only unclassified events are sent (cheap — a few posts/run).
- Batched: up to BATCH posts per API call.
- Prompt caching: the system prompt (instructions + ticker map) is cached.
- Structured output: a JSON schema constrains the response, so no fragile parsing.

Needs ANTHROPIC_API_KEY. Writes data/_debug_classify.json.
Run by .github/workflows/update-data.yml after fetch_trump_posts.py.
"""
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "trump_signals.json")
DBG = os.path.join(ROOT, "data", "_debug_classify.json")
KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

MODEL = "claude-haiku-4-5"
BATCH = 20
PRICE_LOOKBACK_DAYS = 50   # only compute price-since for posts this recent
PRICE_MAX = 40             # cap Yahoo calls per run

SYSTEM = """You classify public Donald Trump social-media posts by their likely \
US stock-market implication. You are NOT giving financial advice — you are \
reading what a post implies and tagging it so a human can decide.

For each post, decide:
- is_market: true only if the post plausibly moves a stock, sector, the broad \
market, or a Trump-linked asset. Pure politics/culture with no market read = false.
- ticker: the single most affected US-listed symbol. Prefer a specific stock when \
named; otherwise use a representative ETF. If none applies, set "".
- direction: BUY (post implies the asset goes up / bullish), SELL (implies down / \
bearish), or WATCH (market-relevant but direction is ambiguous or two-sided).
- strength: 0-100, how strong/actionable the signal is. Weigh: explicitness \
(a literal "buy"/"great time" >> vague mention), emphasis (ALL CAPS, !!!), \
specificity (a named ticker > vague macro), and topic weight (tariffs/Fed/rates \
move the whole market hard; praising one company moves one stock).
- reason: ONE short clause explaining the call (e.g. "new tariffs -> broad market down").

Ticker mapping guidance:
- Broad market / tariffs / Fed / economy / rates -> SPY (or QQQ if tech-specific)
- Truth Social, Trump Media, "DJT", his own company/stock -> DJT
- $TRUMP coin / crypto / bitcoin -> TRUMP for the coin, else BTC-USD / COIN
- Oil, drilling, energy, "drill baby drill" -> XLE (or USO for oil)
- Defense, war, military spending -> XAR
- Tariffs ON a country/sector -> that sector's ETF down, or SPY down
- A specific company praised -> that ticker BUY; attacked -> that ticker SELL
- Semiconductors / chips -> SMH ; China trade -> FXI / SPY

Tariff ANNOUNCED/raised is usually bearish (SELL, market down). Tariff PAUSED/cut \
or a trade DEAL is usually bullish (BUY). A "great time to buy" type post is BUY, \
high strength. Be decisive but honest; use WATCH when genuinely unsure.

IMPORTANT — reject noise: campaign endorsements, rally speeches, and political \
attacks that only contain boilerplate slogans ("energy dominance", "grow the \
economy", "America First") with NO specific, near-term market catalyst are NOT \
market signals — set is_market=false. Only set is_market=true when there is a \
concrete, tradable read (a policy action, a deal, a named company/sector \
catalyst, an explicit market call)."""

SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "is_market": {"type": "boolean"},
                    "ticker": {"type": "string"},
                    "direction": {"type": "string", "enum": ["BUY", "SELL", "WATCH"]},
                    "strength": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["index", "is_market", "ticker", "direction", "strength", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

debug = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "model": MODEL, "key_present": bool(KEY)}


def classify_batch(client, posts):
    """posts: list of (index, text). Returns {index: result dict}."""
    listing = "\n\n".join(f"[{i}] {t[:600]}" for i, t in posts)
    user = ("Classify each post. Return one result per index.\n\n" + listing)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    debug.setdefault("cache_read", 0)
    debug["cache_read"] += getattr(resp.usage, "cache_read_input_tokens", 0) or 0
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    out = {}
    for r in json.loads(text).get("results", []):
        out[r["index"]] = r
    return out


# ---- price since post (Yahoo, free) ----
def price_since(ticker, post_iso):
    if not ticker:
        return None
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?range=6mo&interval=1d")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "trade-tracker/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        res = data["chart"]["result"][0]
        ts, closes = res["timestamp"], res["indicators"]["quote"][0]["close"]
    except (urllib.error.URLError, ValueError, KeyError, IndexError, TypeError):
        return None
    post_day = post_iso[:10]
    base = last = None
    for t, c in zip(ts, closes):
        if c is None:
            continue
        day = datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        if base is None and day >= post_day:
            base = (day, round(float(c), 2))
        last = (day, round(float(c), 2))
    if not base or not last or base[1] == 0 or base[0] == last[0]:
        return None  # no trading time elapsed since the post yet
    pct = round((last[1] - base[1]) / base[1] * 100, 1)
    return {"ticker": ticker, "pct": pct, "base": base[1], "last": last[1],
            "base_date": base[0], "last_date": last[1] and last[0]}


def main():
    with open(PATH) as f:
        doc = json.load(f)
    events = doc.get("events", [])

    pending = [(i, e) for i, e in enumerate(events)
               if not e.get("curated") and not e.get("classified")]
    debug["pending"] = len(pending)

    if not KEY:
        debug["note"] = "ANTHROPIC_API_KEY not set — candidates left unclassified."
        with open(DBG, "w") as f:
            json.dump(debug, f, indent=1)
        print("No ANTHROPIC_API_KEY — skipping classification.", file=sys.stderr)
        return 0

    if pending:
        try:
            import anthropic
        except ImportError:
            debug["note"] = "anthropic SDK not installed."
            with open(DBG, "w") as f:
                json.dump(debug, f, indent=1)
            print("anthropic not installed.", file=sys.stderr)
            return 0
        client = anthropic.Anthropic(api_key=KEY)

        results = {}
        for s in range(0, len(pending), BATCH):
            chunk = pending[s:s + BATCH]
            try:
                results.update(classify_batch(client, [(i, e["text"]) for i, e in chunk]))
            except Exception as exc:  # keep the run alive; leave these unclassified
                debug.setdefault("errors", []).append(str(exc)[:200])
                print(f"Batch failed: {exc}", file=sys.stderr)

        kept = dropped = 0
        for i, e in pending:
            r = results.get(i)
            if not r:
                continue
            if not r.get("is_market"):
                e["_drop"] = True
                dropped += 1
                continue
            e["classified"] = True
            e["is_market"] = True
            e["direction"] = r.get("direction", "WATCH")
            e["primary_ticker"] = (r.get("ticker") or "").upper()
            e["strength"] = max(0, min(100, int(r.get("strength", 50))))
            e["reason"] = r.get("reason", "")
            if e["primary_ticker"] and e["primary_ticker"] not in e.get("tickers", []):
                e.setdefault("tickers", []).insert(0, e["primary_ticker"])
            kept += 1
        events = [e for e in events if not e.get("_drop")]
        debug["classified_market"] = kept
        debug["dropped_nonmarket"] = dropped

    # Refresh "price since post" for recent market events (bounded).
    cutoff = (datetime.now(timezone.utc) - timedelta(days=PRICE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    n = 0
    for e in events:
        if e.get("curated") or not e.get("is_market"):
            continue
        if e.get("date", "")[:10] < cutoff or not e.get("primary_ticker"):
            continue
        if n >= PRICE_MAX:
            break
        ps = price_since(e["primary_ticker"], e["date"])
        if ps:
            e["price_since"] = ps
        else:
            e.pop("price_since", None)  # clear stale/same-day 0% entries
        n += 1
    debug["price_updates"] = n

    # Collapse any reposts already stored (same normalized text); keep curated,
    # and for live dups keep the highest-engagement copy.
    import re as _re
    def tkey(s):
        return _re.sub(r"[^a-z0-9]", "", (s or "").lower())[:120]
    best = {}
    deduped = []
    for e in events:
        if e.get("curated"):
            deduped.append(e)
            continue
        k = tkey(e.get("text", ""))
        prev = best.get(k)
        if prev is None:
            best[k] = e
            deduped.append(e)
        elif (e.get("engagement", 0) or 0) > (prev.get("engagement", 0) or 0):
            deduped[deduped.index(prev)] = e
            best[k] = e
    events = deduped
    debug["after_dedupe"] = len(events)

    events.sort(key=lambda e: e.get("date", ""), reverse=True)
    doc["events"] = events
    doc["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(PATH, "w") as f:
        json.dump(doc, f, indent=1)
    with open(DBG, "w") as f:
        json.dump(debug, f, indent=1)
    print(f"Classified {debug.get('classified_market', 0)} market signals, "
          f"dropped {debug.get('dropped_nonmarket', 0)}, priced {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
