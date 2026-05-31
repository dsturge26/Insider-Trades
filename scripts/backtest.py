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
import json, os, sys, traceback, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from fetch_trump_posts import MARKET, CASHTAG, strip_html, textkey  # noqa: E402
import classify_signals as cls  # noqa: E402

KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MONTHS = int(os.environ.get("BACKTEST_MONTHS", "24"))
MAX_POSTS = int(os.environ.get("BACKTEST_MAX_POSTS", "4000"))
REUSE = os.environ.get("BACKTEST_REUSE", "").lower() in ("1", "true", "yes")
HORIZONS = [1, 3, 5]          # trading days after the post
INTRADAY_H = [1, 4]           # hours after the post (fast reaction)
ARCHIVE = "https://ix.cnn.io/data/truth-social/truth_archive.json"
RAW = os.path.join(ROOT, "data", "backtest_signals_raw.json")
RESULTS = os.path.join(ROOT, "data", "backtest_results.json")
REPORT = os.path.join(ROOT, "backtest_report.md")
DBG = os.path.join(ROOT, "data", "_debug_backtest.json")

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


def yahoo_hourly(ticker):
    """~2y of hourly bars: [(epoch, close)] sorted, or None. Captures the
    intraday reaction the daily-close test misses."""
    sym = CRYPTO.get(ticker, ticker)
    if sym is None:
        return None
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?range=730d&interval=1h")
    try:
        data = json.loads(get(url, 30).decode("utf-8", "replace"))
        res = data["chart"]["result"][0]
        ts, closes = res["timestamp"], res["indicators"]["quote"][0]["close"]
    except (urllib.error.URLError, ValueError, KeyError, IndexError, TypeError):
        return None
    out = [(int(t), float(c)) for t, c in zip(ts, closes) if c is not None]
    return out or None


def post_epoch(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def intraday_returns(series_h, epoch):
    """Entry = first hourly bar at/after the post; returns pct at +Nh."""
    if epoch is None:
        return None
    base_i = next((i for i, (t, _) in enumerate(series_h) if t >= epoch), None)
    if base_i is None:
        return None
    base = series_h[base_i][1]
    if base == 0:
        return None
    out = {}
    for h in INTRADAY_H:
        j = next((i for i, (t, _) in enumerate(series_h) if t >= epoch + h * 3600), None)
        if j is not None and j < len(series_h):
            out[h] = (series_h[j][1] - base) / base * 100
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
            if not r.get("is_market") or not tk:
                continue
            signals.append({"date": p["date"], "ticker": tk,
                            "direction": r.get("direction", "WATCH"),
                            "strength": max(0, min(100, int(r.get("strength", 50)))),
                            "explicit": bool(r.get("explicit")),
                            "source": p.get("source", "Trump"),
                            "text": p["text"][:160]})
        print(f"  classified {min(s+cls.BATCH, len(posts))}/{len(posts)}")
    return signals


def gather_contracts(cutoff):
    """Historical $1B+ federal awards over the lookback (USAspending). Each becomes
    a 'Contract' candidate; the classifier maps recipient -> ticker (BUY)."""
    body = {
        "filters": {
            "award_type_codes": ["A", "B", "C", "D"],
            "time_period": [{"start_date": cutoff, "end_date":
                             datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                             "date_type": "action_date"}],
            "award_amounts": [{"lower_bound": 1_000_000_000}],
        },
        "fields": ["Recipient Name", "Award Amount", "Awarding Agency", "Start Date"],
        "sort": "Award Amount", "order": "desc", "limit": 100,
    }
    cand, seen = [], set()
    for page in range(1, 4):
        body["page"] = page
        try:
            req = urllib.request.Request(
                "https://api.usaspending.gov/api/v2/search/spending_by_award/",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "User-Agent": "trade-tracker/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                results = json.load(r).get("results", [])
        except (urllib.error.URLError, ValueError, TimeoutError):
            break
        if not results:
            break
        for a in results:
            name = (a.get("Recipient Name") or "").strip()
            amt = a.get("Award Amount") or 0
            if not name or not amt:
                continue
            text = f"{name} was awarded a ${amt/1e9:.1f}B federal contract from {a.get('Awarding Agency','')}."
            k = textkey(text)
            if k in seen:
                continue
            seen.add(k)
            cand.append({"date": (a.get("Start Date") or cutoff) + "T12:00:00Z",
                         "text": text, "source": "Contract"})
    print(f"{len(cand)} federal-contract candidates")
    return cand


def classify_history():
    """Fetch each backtestable source, classify, and PERSIST raw signals
    immediately so a later reporting bug never costs the classification again."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MONTHS * 30)).strftime("%Y-%m-%d")
    print("Fetching Truth Social archive…")
    posts = json.loads(get(ARCHIVE))
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
        cand.append({"date": p["created_at"], "text": text, "source": "Trump"})
    cand.sort(key=lambda x: x["date"])
    if len(cand) > MAX_POSTS:
        cand = cand[-MAX_POSTS:]
    print(f"{len(cand)} market candidate posts since {cutoff}")

    cand += gather_contracts(cutoff)   # add the federal-contract source

    signals = classify_all(cand)
    with open(RAW, "w") as f:
        json.dump({"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "months": MONTHS, "signals": signals}, f, indent=1)
    print(f"{len(signals)} market signals classified → cached to {RAW}")
    return signals


def main():
    debug = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "months": MONTHS, "reuse": REUSE}
    try:
        if REUSE and os.path.exists(RAW):
            signals = json.load(open(RAW)).get("signals", [])
            print(f"Reusing {len(signals)} cached signals (no classification cost).")
        elif not KEY:
            raise RuntimeError("ANTHROPIC_API_KEY required (or set BACKTEST_REUSE=true with cached signals).")
        else:
            signals = classify_history()
        debug["signals_classified"] = len(signals)

        hist, hist_h, missing = {}, {}, set()
        for sig in signals:
            tk = sig["ticker"]
            if tk and tk not in hist and tk not in missing:
                h = yahoo_history(tk)
                if h:
                    hist[tk] = h
                    hh = yahoo_hourly(tk)
                    if hh:
                        hist_h[tk] = hh
                else:
                    missing.add(tk)

        evaluated = []
        spy = hist.get("SPY") or yahoo_history("SPY")   # market benchmark for alpha
        for sig in signals:
            series = hist.get(sig["ticker"])
            if not series:
                continue
            fr = fwd_returns(series, sig["date"][:10])
            if not fr:
                continue
            rec = dict(sig, returns=fr)
            if spy:  # excess return vs SPY over the same window = alpha
                spy_fr = fwd_returns(spy, sig["date"][:10]) or {}
                ex = {h: fr[h] - spy_fr[h] for h in fr if h in spy_fr}
                if ex:
                    rec["excess"] = ex
            seh = hist_h.get(sig["ticker"])
            if seh:
                ir = intraday_returns(seh, post_epoch(sig["date"]))
                if ir:
                    rec["intraday"] = ir
            evaluated.append(rec)
        debug["signals_evaluated"] = len(evaluated)
        debug["with_intraday"] = sum(1 for r in evaluated if "intraday" in r)

        results = summarize(evaluated, signals, missing)
        with open(RESULTS, "w") as f:
            json.dump(results, f, indent=1)
        with open(REPORT, "w") as f:
            f.write(render_report(results))
        debug["status"] = "ok"
        print(f"Done: {len(evaluated)} signals evaluated. See backtest_report.md")
    except Exception:
        debug["status"] = "error"
        debug["traceback"] = traceback.format_exc()
        print(debug["traceback"], file=sys.stderr)
    with open(DBG, "w") as f:
        json.dump(debug, f, indent=1)
    return 0  # never fail the job — artifacts + debug are committed either way


def _stats(rows, h, field="returns"):
    """signed return = +fwd for BUY, -fwd for SELL (the side you'd take)."""
    vals, signed, hits = [], [], 0
    for r in rows:
        fr = r.get(field, {}).get(h)
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
        "with_intraday": sum(1 for r in evaluated if "intraday" in r),
        "tickers_missing_price": sorted(missing),
        "intraday_hours": INTRADAY_H,
        "by_horizon": {}, "by_intraday": {}, "by_direction": {},
        "by_strength": {}, "by_segment": {}, "by_source": {}, "by_ticker": {},
    }
    intr = [r for r in evaluated if r.get("intraday") and r["direction"] in ("BUY", "SELL")]
    for h in INTRADAY_H:
        s = _stats(intr, h, "intraday")
        base = [r["intraday"][h] for r in evaluated if r.get("intraday", {}).get(h) is not None]
        s["baseline_long_return"] = round(sum(base) / len(base), 2) if base else None
        out["by_intraday"][h] = s
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
    # segment: single-name (Dell-type) vs broad-market, plus explicit if tagged
    BROAD = {"SPY", "QQQ", "DIA", "IWM", "VOO", "VTI", "DBC", "USO"}
    directional = [r for r in evaluated if r["direction"] in ("BUY", "SELL")]
    out["by_segment"]["single_name"] = _stats([r for r in directional if r["ticker"] not in BROAD], mid)
    out["by_segment"]["broad_market"] = _stats([r for r in directional if r["ticker"] in BROAD], mid)
    expl = [r for r in directional if r.get("explicit")]
    if expl:
        out["by_segment"]["explicit_endorsement"] = _stats(expl, mid)

    # per-source leaderboard — the headline: which source actually has edge?
    sources = sorted({r.get("source", "Trump") for r in directional})
    for src in sources:
        rows = [r for r in directional if r.get("source", "Trump") == src]
        s = _stats(rows, mid)
        s["alpha_vs_spy"] = _stats(rows, mid, "excess")["avg_signed_return"]
        out["by_source"][src] = s

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
    L.append(f"- Signals with intraday (hourly) data: **{r.get('with_intraday', 0)}**")
    L.append("\n## Fast reaction — intraday (hours after post)")
    L.append("This is the signal the daily-close test misses. `avg signed` = return on the implied side.\n")
    L.append("| After | N | Hit rate | Avg signed return | Baseline (long) |")
    L.append("|---|---|---|---|---|")
    for h in r.get("intraday_hours", []):
        s = r["by_intraday"].get(h) or r["by_intraday"].get(str(h)) or {}
        L.append(f"| {h}h | {s.get('n')} | {s.get('hit_rate')}% | {s.get('avg_signed_return')}% | {s.get('baseline_long_return')}% |")
    L.append("\n## Directional edge by horizon (trading days)")
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
    L.append(f"\n## 🏆 Per-source leaderboard (signed return at {r['_mid_horizon']}d)")
    L.append("**Alpha vs SPY** = return after subtracting the market's move over the same window — this is the real test (strips out 'the market/sector just went up'). (WSB, congress, insiders aren't here — no free history to backtest.)\n")
    L.append("| Source | N | Hit rate | Avg signed return | **Alpha vs SPY** |")
    L.append("|---|---|---|---|---|")
    for src, s in sorted(r["by_source"].items(), key=lambda kv: (kv[1].get("alpha_vs_spy") or -99), reverse=True):
        L.append(f"| {src} | {s['n']} | {s['hit_rate']}% | {s['avg_signed_return']}% | {s.get('alpha_vs_spy')}% |")

    L.append(f"\n## By signal type (signed return at {r['_mid_horizon']}d)")
    L.append("The key question: do **single-name** calls (the Dell type) beat the **broad-market** macro noise?\n")
    L.append("| Segment | N | Hit rate | Avg signed return |")
    L.append("|---|---|---|---|")
    for k, lbl in [("single_name", "Single-name (specific company)"),
                   ("broad_market", "Broad market (SPY/QQQ/…)"),
                   ("explicit_endorsement", "Explicit endorsement")]:
        s = r["by_segment"].get(k)
        if s:
            L.append(f"| {lbl} | {s['n']} | {s['hit_rate']}% | {s['avg_signed_return']}% |")
    L.append("\n## Most-signaled tickers")
    L.append(", ".join(f"{k} ({v})" for k, v in r["by_ticker"].items()))
    L.append("\n---")
    L.append("**Caveats:** daily-close granularity (misses intraday reaction); small sample of strong "
             "signals (overfitting risk); transaction costs/slippage ignored; backtested performance is "
             "**not** indicative of future results. Not financial advice.")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
