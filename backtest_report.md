# Signal Backtest — last 24 months

_Generated 2026-06-01T01:40:09Z · model claude-haiku-4-5_

- Signals classified: **1016**
- Signals with price data (evaluated): **987**
- Tickers skipped (no price series): AJRD, BAE, CBS, DXY, GDW, GYO, HRS, PACCAR, SPACE, TRUMP, TXVG, X, XLX, XMM
- Signals with intraday (hourly) data: **987**

## Fast reaction — intraday (hours after post)
This is the signal the daily-close test misses. `avg signed` = return on the implied side.

| After | N | Hit rate | Avg signed return | Baseline (long) |
|---|---|---|---|---|
| 1h | 868 | 15.2% | -0.01% | 0.0% |
| 4h | 868 | 20.0% | -0.01% | -0.0% |

## Directional edge by horizon (trading days)
BUY hits = return > 0; SELL hits = return < 0. `avg signed` = return on the side the signal implied. Compare to `baseline` (just being long the same tickers).

| Horizon | N | Hit rate | Avg signed return | Baseline (long) |
|---|---|---|---|---|
| 1d | 868 | 54.3% | 0.07% | 0.11% |
| 3d | 867 | 54.6% | 0.31% | 0.43% |
| 5d | 862 | 55.5% | 0.21% | 0.25% |

## By direction

**1-day:** BUY n=708 hit=58.6% avg=0.12% · SELL n=160 hit=35.0% avg=-0.16% · WATCH n=119 avg|move|=0.85%

**3-day:** BUY n=707 hit=59.8% avg=0.48% · SELL n=160 hit=31.2% avg=-0.44% · WATCH n=119 avg|move|=1.71%

**5-day:** BUY n=703 hit=59.2% avg=0.33% · SELL n=159 hit=39.0% avg=-0.32% · WATCH n=115 avg|move|=2.78%

## Does strength matter? (signed return at 3d)
If the model's strength score is informative, average signed return should rise with the bucket.

| Strength | N | Hit rate | Avg signed return |
|---|---|---|---|
| 0-39 | 83 | 43.4% | -0.34% |
| 40-59 | 285 | 56.1% | 0.18% |
| 60-79 | 345 | 49.9% | 0.2% |
| 80-100 | 154 | 68.2% | 1.15% |

## 🏆 Per-source leaderboard (signed return at 3d)
**Alpha vs SPY** = return after subtracting the market's move over the same window — this is the real test (strips out 'the market/sector just went up'). (WSB, congress, insiders aren't here — no free history to backtest.)

| Source | N | Hit rate | Avg signed return | **Alpha vs SPY** |
|---|---|---|---|---|
| Contract | 174 | 67.8% | 1.02% | 0.46% |
| Trump | 693 | 51.2% | 0.14% | 0.08% |

## By signal type (signed return at 3d)
The key question: do **single-name** calls (the Dell type) beat the **broad-market** macro noise?

| Segment | N | Hit rate | Avg signed return |
|---|---|---|---|
| Single-name (specific company) | 433 | 55.2% | 0.43% |
| Broad market (SPY/QQQ/…) | 434 | 53.9% | 0.2% |
| Explicit endorsement | 228 | 62.7% | 0.76% |

## 🪖 Defense-beta control (signed return at 3d)
Defense-sector names (most of the contract signals). **If alpha vs SPY is positive but alpha vs XAR is ~0, the 'contract edge' was just defense beta.**

- N defense signals: **171** · hit rate 69.6%
- Avg signed return: **1.17%**
- Alpha vs SPY (broad market): **0.6%**
- Alpha vs XAR (defense ETF): **0.27%**  ← the decisive number

## Most-signaled tickers
SPY (514), XLE (145), LMT (60), BA (41), RTX (33), HII (17), USO (15), XAR (14), TSLA (12), BTC-USD (10), AAPL (9), NOC (8), COIN (7), QQQ (6), FXI (6)

---
**Caveats:** daily-close granularity (misses intraday reaction); small sample of strong signals (overfitting risk); transaction costs/slippage ignored; backtested performance is **not** indicative of future results. Not financial advice.
