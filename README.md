# 📈 Trump & Congress Trade Tracker

A personal dashboard that surfaces **public** market-related signals in one place:

- 📊 **Summary** — a one-screen snapshot of what Trump's latest posts *imply* (buy / sell / watch), strongest first.
- 🚨 **Trump Signals** — his market-relevant Truth Social posts, **AI-classified** into ticker + direction + a 0–100 strength score + a one-line reason, filterable by time window and sortable.
- 🔥 **Top Buys** — the tickers the most members of Congress are buying, from their STOCK Act disclosures (publicly disclosed, lagged 30–45 days).
- 🎯 **Trump Tickers** — DJT and the "Trump trade" basket (SPY/QQQ/PLTR/defense) with **live intraday prices** and trend sparklines.
- 📋 **All Congress Trades** — every disclosed trade, searchable and filterable.

It's a **static site** (perfect for GitHub Pages) fed by a **scheduled GitHub Action** that fetches fresh data and commits it as JSON. No server to run, no keys exposed in the browser.

> ⚠️ **Read this — it's a tracker, not a strategy.** Everything here is *public record* — Trump's posts and legally-required disclosures. A **2-year backtest** of the AI Buy/Sell/Watch signals (`scripts/backtest.py`) found **no edge over simply buying and holding**: direction was ~50/50, the signals underperformed the buy-and-hold baseline, SELL calls were anti-predictive, and the strength score did **not** correlate with returns. So the tags mean *"what the post implies,"* not a recommendation. Disclosures also lag real trades by **30–45 days**. **This is not financial advice.** Do your own research.

---

## How it works

```
GitHub Pages (static dashboard)  ──reads──►  /data/*.json
                                                 ▲ commits fresh data on a schedule
                              GitHub Action (full network, secrets stay server-side)
                              ├─ fetch_congress.py     STOCK Act trades        (FMP, ~6h)
                              ├─ fetch_trump_posts.py  candidate posts         (CNN archive)
                              ├─ classify_signals.py   ticker/direction/score  (Claude Haiku)
                              ├─ fetch_prices.py       intraday ticker prices  (Yahoo)
                              └─ stamp_meta.py         freshness stamp
```

Runs every ~15 minutes (posts + prices refresh fast; congressional trades self-throttle to ~6h to stay under the FMP free limit). The site ships with **real seed data** so it works the moment you turn on Pages.

---

## Setup

### 1. Turn on GitHub Pages
Repo **Settings → Pages → Build and deployment**: **Source** = *Deploy from a branch*, **Branch** = `main` / `/ (root)` → **Save**. Open the URL it shows (`https://<you>.github.io/Insider-Trades/`).

### 2. Add secrets (Settings → Secrets and variables → Actions)
| Secret | Enables | Free? |
|---|---|---|
| `FMP_API_KEY` | Live House + Senate trades ([Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs), 250 req/day) | Yes |
| `ANTHROPIC_API_KEY` | AI classification of Trump posts ([console.anthropic.com](https://console.anthropic.com), runs on Haiku — pennies/month) | Yes (credits) |

Prices (Yahoo) need no key. Then **Actions → Update data → Run workflow** once; after that it's automatic.

---

## The signal feed (auto-populated)

The Trump Signals feed is **automatic**: `fetch_trump_posts.py` pulls his latest posts from CNN's archive and keyword-prefilters market-looking ones; `classify_signals.py` asks Claude to make the real call and drops non-market noise. You don't hand-curate it.

To **pin a hand-written highlight**, add an entry to `events` in [`data/trump_signals.json`](data/trump_signals.json) with `"curated": true`:

```json
{
  "curated": true, "classified": true, "is_market": true,
  "date": "2025-04-09T13:37:00Z", "platform": "Truth Social",
  "text": "THIS IS A GREAT TIME TO BUY!!!",
  "direction": "BUY", "primary_ticker": "SPY", "tickers": ["SPY", "DJT"],
  "strength": 95, "reason": "Why it mattered",
  "market_reaction": "What the market did", "url": "https://truthsocial.com/@realDonaldTrump"
}
```

To change which tickers appear on the **Trump Tickers** tab, edit `data/trump_tickers.json`.

---

## Backtest it yourself

**Actions → Backtest signals → Run workflow.** It replays history through the same classifier and measures forward returns (1h/4h intraday + 1/3/5-day) vs a buy-and-hold baseline, then commits `backtest_report.md`. Re-run with **`reuse: true`** to re-measure cached signals for **$0** — handy for testing a narrower idea ("only tariff posts", "only DJT").

---

## Run it locally

```bash
python3 -m http.server 8000          # open http://localhost:8000
```

Regenerate data (needs network; keys optional):
```bash
export FMP_API_KEY=...                # optional, for congress trades
export ANTHROPIC_API_KEY=...          # optional, for classification
python3 scripts/fetch_congress.py
python3 scripts/fetch_trump_posts.py
python3 scripts/classify_signals.py
python3 scripts/fetch_prices.py
python3 scripts/stamp_meta.py
```

## Data sources
- [House Clerk](https://disclosures-clerk.house.gov/) & [Senate EFD](https://efdsearch.senate.gov/) — official STOCK Act filings
- [Financial Modeling Prep](https://site.financialmodelingprep.com/) — congressional trades API (free tier)
- [CNN Truth Social archive](https://ix.cnn.io/data/truth-social/truth_archive.json) — Trump's posts (originals on [Truth Social](https://truthsocial.com/@realDonaldTrump))
- [Anthropic Claude](https://www.anthropic.com/) (Haiku) — post classification
- [Yahoo Finance](https://finance.yahoo.com/) — intraday & historical prices ([Stooq](https://stooq.com/) as fallback)

*Personal project. Not affiliated with any official entity. Not financial advice.*
