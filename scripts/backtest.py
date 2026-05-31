#!/usr/bin/env python3
"""Backtest the signal logic against ~2 years of history.

Replays past Trump posts through the SAME classifier we run live, then measures
the ticker's forward return at 1/3/5 trading days after each post. Reports hit
rate and average return by direction and by strength bucket, with a buy-and-hold
baseline so we can tell real edge from market drift.

Honest limits (see report): daily-close granularity (no intraday reaction),
small sample of strong signals (overfitting risk), backtested != future.

Outputs data/backtest_results.json (machine) and backtest_report.md (human).
Run on demand via .github/workflows/backtest.yml. Needs ANTHROPIC_API_KEY.
"""
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from fetch_trump_posts import MARKET, CASHTAG, strip_html, textkey  # noqa: E402
import classify_signals as cls  # noqa: E402

KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MONTHS = int(os.environ.get("BACKTEST_MONTHS", "24"))
MAX_POSTS = int(os.environ.get("BACKTEST_MAX_POSTS", "4000"))
HORIZONS = [1, 3, 5]          # trading days after the post
ARCHIVE = "https://ix.cnn.io/data/truth-social/truth_archive.json"

# Map classifier tickers to Yahoo symbols; None = skip (no reliable series).
CRYPTO = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
          "DOGE": "DOGE-USD", "TRUMP": None, "MELANIA": None}


def get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "trade-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def yahoo_history(ticker):
    """Return sorted [(YYYY-MM-DD, close)] for ~5y, or None."""
    sym = CRYPTO.get(ticker, ticker)
    if sym is None:
        return None
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?range=5y&interval=1d")
    try:
        data = json.loads(get(url, 30).decode("utf-8", "replace"))
        res = data["chart"]["result"][0]
        ts, closes = res["timestamp"], res["indicators"]["quote"][0]["close"]
    except (urllib.error.URLError, ValueError, KeyError, IndexError, TypeError):
        return None
    out = []
    for t, c in zip(ts, closes):
        if c is not None:
            out.append((datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"), round(float(c), 4)))
    return out or None


def fwd_returns(series, post_day):
    """Entry = first close on/after post_day; returns pct at each horizon."""
    base_idx = next((i for i, (d, _) in enumerate(series) if d >= post_day), None)
    if base_idx is None:
        return None
    base = series[base_idx][1]
    if base == 0:
        return None
    out = {}
    for h in HORIZONS:
        j = base_idx + h
        if j < len(series):
            out[h] = (series[j][1] - base) / base * 100
    return out or None


def classify_all(posts):
    import anthropic
    client = anthropic.Anthropic(api_key=KEY)
    signals = []
    for s in range(0, len(posts), cls.BATCH):
        chunk = posts[s:s + cls.BATCH]
        try:
            res = cls.classify_batch(client, [(i, p["text"]) for i, p in enumerate(chunk)])
        except Exception as exc:
            print(f"  batch {s} failed: {exc}", file=sys.stderr)
            continue
        for i, p in enumerate(chunk):
            r = res.get(i)
            if not r or not r.get("is_market"):
                continue
            tk = (r.get("ticker") or "").upper()
            if not tk:
                continue
            signals.append({"date": p["date"], "ticker": tk,
                            "direction": r.get("direction", "WATCH"),
                            "strength": max(0, min(100, int(r.get("strength", 50)))),
                            "text": p["text"][:160]})
        print(f"  classified {min(s+cls.BATCH, len(posts))}/{len(posts)}")
    return signals


def main():
    if not KEY:
        print("ANTHROPIC_API_KEY required.", file=sys.stderr)
        return 1

    print("Fetching archive…")
    posts = json.loads(get(ARCHIVE))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MONTHS * 30)).strftime("%Y-%m-%d")
    seen, cand = set(), []
    for p in posts:
        if not isinstance(p, dict) or not p.get("created_at"):
            continue
        if p["created_at"][:10] < cutoff:
            continue
        text = strip_html(p.get("content", ""))
        if not MARKET.search(text):
            continue
        k = textkey(text)
        if k in seen:
            continue
        seen.add(k)
        cand.append({"date": p["created_at"], "text": text})
    cand.sort(key=lambda x: x["date"])
    if len(cand) > MAX_POSTS:
        cand = cand[-MAX_POSTS:]
    print(f"{len(cand)} market candidate posts since {cutoff}")

    signals = classify_all(cand)
    print(f"{len(signals)} market signals classified")

    # price histories (cached per ticker)
    hist, missing = {}, set()
    for sig in signals:
        tk = sig["ticker"]
        if tk not in hist and tk not in missing:
            h = yahoo_history(tk)
            if h:
                hist[tk] = h
            else:
                missing.add(tk)

    # evaluate
    evaluated = []
    for sig in signals:
        series = hist.get(sig["ticker"])
        if not series:
            continue
        fr = fwd_returns(series, sig["date"][:10])
        if fr:
            sig = dict(sig, returns=fr)
            evaluated.append(sig)

    results = summarize(evaluated, signals, missing)
    with open(os.path.join(ROOT, "data", "backtest_results.json"), "w") as f:
        json.dump(results, f, indent=1)
    with open(os.path.join(ROOT, "backtest_report.md"), "w") as f:
        f.write(render_report(results))
    print(f"Done: {len(evaluated)} signals evaluated. See backtest_report.md")
    return 0


def _stats(rows, h):
    """signed return = +fwd for BUY, -fwd for SELL (the side you'd take)."""
    vals, signed, hits = [], [], 0
    for r in rows:
        fr = r["returns"].get(h)
        if fr is None:
            continue
        vals.append(fr)
        if r["direction"] == "BUY":
            signed.append(fr);  hits += fr > 0
        elif r["direction"] == "SELL":
            signed.append(-fr); hits += fr < 0
    n = len(signed)
    return {
        "n": n,
        "hit_rate": round(hits / n * 100, 1) if n else None,
        "avg_signed_return": round(sum(signed) / n, 2) if n else None,
        "avg_raw_return": round(sum(vals) / len(vals), 2) if vals else None,
    }


def summarize(evaluated, all_signals, missing):
    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "months": MONTHS, "model": cls.MODEL, "horizons": HORIZONS,
        "signals_classified": len(all_signals),
        "signals_evaluated": len(evaluated),
        "tickers_missing_price": sorted(missing),
        "by_horizon": {}, "by_direction": {}, "by_strength": {}, "by_ticker": {},
    }
    dirs = ["BUY", "SELL", "WATCH"]
    for h in HORIZONS:
        directional = [r for r in evaluated if r["direction"] in ("BUY", "SELL")]
        out["by_horizon"][h] = _stats(directional, h)
        # baseline: mean forward return of the same tickers regardless of side
        base = [r["returns"][h] for r in evaluated if h in r["returns"]]
        out["by_horizon"][h]["baseline_long_return"] = round(sum(base) / len(base), 2) if base else None
        out["by_direction"][h] = {}
        for d in dirs:
            rows = [r for r in evaluated if r["direction"] == d]
            if d == "WATCH":
                moves = [abs(r["returns"][h]) for r in rows if h in r["returns"]]
                out["by_direction"][h][d] = {"n": len(moves),
                    "avg_abs_move": round(sum(moves) / len(moves), 2) if moves else None}
            else:
                out["by_direction"][h][d] = _stats(rows, h)
        # strength buckets at the middle horizon
    mid = HORIZONS[len(HORIZONS) // 2]
    buckets = [(0, 40), (40, 60), (60, 80), (80, 101)]
    for lo, hi in buckets:
        rows = [r for r in evaluated if lo <= r["strength"] < hi and r["direction"] in ("BUY", "SELL")]
        out["by_strength"][f"{lo}-{hi-1}"] = _stats(rows, mid)
    # top tickers by count
    from collections import Counter
    cnt = Counter(r["ticker"] for r in evaluated)
    out["by_ticker"] = dict(cnt.most_common(15))
    out["_mid_horizon"] = mid
    return out


def render_report(r):
    L = []
    L.append(f"# Signal Backtest — last {r['months']} months\n")
    L.append(f"_Generated {r['generated']} · model {r['model']}_\n")
    L.append(f"- Signals classified: **{r['signals_classified']}**")
    L.append(f"- Signals with price data (evaluated): **{r['signals_evaluated']}**")
    if r["tickers_missing_price"]:
        L.append(f"- Tickers skipped (no price series): {', '.join(r['tickers_missing_price'])}")
    L.append("\n## Directional edge by horizon")
    L.append("BUY hits = return > 0; SELL hits = return < 0. `avg signed` = return on the side the signal implied. Compare to `baseline` (just being long the same tickers).\n")
    L.append("| Horizon | N | Hit rate | Avg signed return | Baseline (long) |")
    L.append("|---|---|---|---|---|")
    for h in r["horizons"]:
        s = r["by_horizon"][str(h)] if str(h) in r["by_horizon"] else r["by_horizon"][h]
        L.append(f"| {h}d | {s['n']} | {s['hit_rate']}% | {s['avg_signed_return']}% | {s['baseline_long_return']}% |")
    L.append("\n## By direction")
    for h in r["horizons"]:
        d = r["by_direction"][h] if h in r["by_direction"] else r["by_direction"][str(h)]
        L.append(f"\n**{h}-day:** "
                 f"BUY n={d['BUY']['n']} hit={d['BUY']['hit_rate']}% avg={d['BUY']['avg_signed_return']}% · "
                 f"SELL n={d['SELL']['n']} hit={d['SELL']['hit_rate']}% avg={d['SELL']['avg_signed_return']}% · "
                 f"WATCH n={d['WATCH']['n']} avg|move|={d['WATCH']['avg_abs_move']}%")
    L.append(f"\n## Does strength matter? (signed return at {r['_mid_horizon']}d)")
    L.append("If the model's strength score is informative, average signed return should rise with the bucket.\n")
    L.append("| Strength | N | Hit rate | Avg signed return |")
    L.append("|---|---|---|---|")
    for k, s in r["by_strength"].items():
        L.append(f"| {k} | {s['n']} | {s['hit_rate']}% | {s['avg_signed_return']}% |")
    L.append("\n## Most-signaled tickers")
    L.append(", ".join(f"{k} ({v})" for k, v in r["by_ticker"].items()))
    L.append("\n---")
    L.append("**Caveats:** daily-close granularity (misses intraday reaction); small sample of strong "
             "signals (overfitting risk); transaction costs/slippage ignored; backtested performance is "
             "**not** indicative of future results. Not financial advice.")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
