# 📈 Trump & Congress Trade Tracker

A personal dashboard that surfaces **public** market-moving signals in one place:

- 🚨 **Trump Signals** — a log of Trump's market-moving public posts (e.g. the April 2025 *"GREAT TIME TO BUY!!!"* before the tariff pause) and what the market did next.
- 🔥 **Top Buys** — the tickers the most members of Congress are buying, from their STOCK Act disclosures. A crowd of insiders piling into one name is the classic signal.
- 🎯 **Trump Tickers** — DJT and the "Trump trade" basket (SPY/QQQ/defense) with live price sparklines.
- 📋 **All Congress Trades** — every disclosed trade, searchable and filterable.

It's a **static site** (perfect for GitHub Pages) fed by a **scheduled GitHub Action** that fetches fresh data and commits it as JSON. No server to run, no keys exposed in the browser.

> ⚠️ **Read this — it's a tracker, not a strategy.** Everything here is *public record* — Trump's posts and legally-required disclosures. A **2-year backtest** of the AI Buy/Sell/Watch signals (`scripts/backtest.py`) found **no edge over simply buying and holding**: direction was ~50/50, the signals underperformed the buy-and-hold baseline, SELL calls were anti-predictive, and the strength score did **not** correlate with returns. So the tags mean *"what the post implies,"* not a recommendation. Disclosures also lag real trades by **30–45 days**. **This is not financial advice.** Do your own research.

---

## How it works

```
GitHub Pages (static dashboard)  ──reads──►  /data/*.json
                                                 ▲ commits fresh data daily
                                  GitHub Action (full network, hidden key)
                                  ├─ scripts/fetch_congress.py   STOCK Act trades (FMP)
                                  ├─ scripts/fetch_prices.py     ticker prices (Stooq)
                                  └─ scripts/stamp_meta.py       freshness stamp
```

The site ships with **real seed data** so it works the moment you turn on Pages. Add a free API key (below) to switch from seed to **live** data.

---

## Setup (10 minutes)

### 1. Turn on GitHub Pages
Repo **Settings → Pages → Build and deployment**:
- **Source:** *Deploy from a branch*
- **Branch:** `claude/personal-stock-tracker-HzJMK`, folder `/ (root)` → **Save**

Wait ~1 minute, then open the URL it shows (`https://<you>.github.io/Insider-Trades/`). You'll see the dashboard with seed data.

### 2. Go live (optional but recommended)
The free [Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs) key gives current **House + Senate** trades (250 requests/day, plenty).
1. Sign up → copy your API key.
2. Repo **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `FMP_API_KEY`
   - Value: *your key*
3. Repo **Actions → Update data → Run workflow**.

The Action will replace the seed data with live trades and refresh prices. After that it runs **automatically every day**. Ticker prices update even without the key.

---

## Add your own Trump signals

Edit [`data/trump_signals.json`](data/trump_signals.json) and add an entry to `events`:

```json
{
  "date": "2025-04-09T13:37:00Z",
  "platform": "Truth Social",
  "text": "THIS IS A GREAT TIME TO BUY!!!",
  "context": "What was happening",
  "market_reaction": "What the market did",
  "tickers": ["SPY", "DJT"],
  "signal": "bullish",
  "url": "https://truthsocial.com/@realDonaldTrump"
}
```

Commit it — Pages redeploys automatically. (Truth Social has no stable public API, so this feed is curated by design. `scripts/` has a clear hook if you later wire up an automated fetcher.)

To change which tickers appear on the **Trump Tickers** tab, edit `data/trump_tickers.json`.

---

## Run it locally

```bash
python3 -m http.server 8000   # then open http://localhost:8000
```

To regenerate data locally (needs network + optional `FMP_API_KEY`):
```bash
export FMP_API_KEY=your_key   # optional
python3 scripts/fetch_congress.py
python3 scripts/fetch_prices.py
python3 scripts/stamp_meta.py
```

## Data sources
- [House Clerk](https://disclosures-clerk.house.gov/) & [Senate EFD](https://efdsearch.senate.gov/) — official STOCK Act filings
- [Financial Modeling Prep](https://site.financialmodelingprep.com/) — congressional trades API (free tier)
- [Stooq](https://stooq.com/) — daily prices (no key)
- [Truth Social](https://truthsocial.com/@realDonaldTrump) — Trump's posts

*Personal project. Not affiliated with any official entity. Not financial advice.*
