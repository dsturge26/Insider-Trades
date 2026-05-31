# Signal Backtest — last 24 months

_Generated 2026-05-31T15:38:59Z · model claude-haiku-4-5_

- Signals classified: **800**
- Signals with price data (evaluated): **780**
- Tickers skipped (no price series): GOYA, HYMTF, TRUMP, X, XLX
- Signals with intraday (hourly) data: **780**

## Fast reaction — intraday (hours after post)
This is the signal the daily-close test misses. `avg signed` = return on the implied side.

| After | N | Hit rate | Avg signed return | Baseline (long) |
|---|---|---|---|---|
| 1h | 658 | 18.7% | -0.01% | 0.02% |
| 4h | 658 | 23.6% | 0.02% | 0.02% |

## Directional edge by horizon (trading days)
BUY hits = return > 0; SELL hits = return < 0. `avg signed` = return on the side the signal implied. Compare to `baseline` (just being long the same tickers).

| Horizon | N | Hit rate | Avg signed return | Baseline (long) |
|---|---|---|---|---|
| 1d | 658 | 50.6% | -0.0% | 0.07% |
| 3d | 656 | 50.6% | 0.03% | 0.22% |
| 5d | 653 | 51.9% | -0.07% | 0.12% |

## By direction

**1-day:** BUY n=502 hit=55.0% avg=0.07% · SELL n=156 hit=36.5% avg=-0.23% · WATCH n=122 avg|move|=1.04%

**3-day:** BUY n=500 hit=56.6% avg=0.2% · SELL n=156 hit=31.4% avg=-0.51% · WATCH n=122 avg|move|=1.55%

**5-day:** BUY n=497 hit=54.9% avg=0.04% · SELL n=156 hit=42.3% avg=-0.4% · WATCH n=117 avg|move|=2.32%

## Does strength matter? (signed return at 3d)
If the model's strength score is informative, average signed return should rise with the bucket.

| Strength | N | Hit rate | Avg signed return |
|---|---|---|---|
| 0-39 | 36 | 52.8% | 0.07% |
| 40-59 | 193 | 49.7% | -0.02% |
| 60-79 | 379 | 52.8% | 0.06% |
| 80-100 | 48 | 35.4% | 0.02% |

## Most-signaled tickers
SPY (482), XLE (112), USO (37), XAR (18), COIN (11), F (10), BTC-USD (7), TSLA (7), AAPL (7), DJT (5), QQQ (5), NVDA (5), BA (5), DBC (5), UNH (5)

---
**Caveats:** daily-close granularity (misses intraday reaction); small sample of strong signals (overfitting risk); transaction costs/slippage ignored; backtested performance is **not** indicative of future results. Not financial advice.
