# WeeklyAndDailyPPO — Experiment Findings (CLOSED, 2026-08-01)

## Purpose
Test a TOS-style WeeklyAndDailyPPO rotation strategy as an alternative to MTF Top-N.
**Verdict: NOT adopted. Do not revisit unless MTF production underperforms.**

## Strategy definition (exact TOS formula, Vitaly Apirine)
- Weekly PPO = `(EMA60_wk − EMA130_wk) / EMA130_wk × 100`
- Daily PPO = `(EMA12_dy − EMA26_dy) / EMA130_wk × 100`  (denominator = weekly 130 EMA, same for both lines)
- WeeklyAndDailyPPO = Weekly PPO + Daily PPO
- Signal tested: long when WDPPO > 0, out when ≤ 0 (next-day open fills)

## Code
- `backtest.py` — per-ticker long/flat state machine (`--universe etf|stocks`, `--limit`, `--random`, `--symbols`)
- `backtest_topn.py` — top-N rotation (mirrors MTF construction) for apples-to-apples comparison
- `db.py`, `config.py` — data load + params

## Results (2020–2026 data)
### Stocks (top-10 rotation, same window as MTF backtest, Jul 2023–Jul 2026)
| Strategy | Return | Max DD | Win |
|---|---|---|---|
| MTF top-10 | **+9,031%** | 21.1% | 69% |
| Hybrid (MTF rank + WDPPO>0 filter) | +4,530% | 22.4% | 68% |
| PPO top-10 | +611% | 59.4% | 46% |

### ETFs (28 ETFs, equal weight, 2020-07-27 → 2026-07-31)
| Strategy | Return | Max DD |
|---|---|---|
| PPO | +113.1% | 21.2% |
| MTF top-10 | +69.7% | 15.3% |
| Equal-weight B&H | +143.8% | — |
| SPY B&H | +150.4% | 24.5% |

### SPY / VTI / QQQ individually
PPO ≈ buy-and-hold with rare exits (SPY = 1 round trip in 8 years). Slightly worse
return than B&H; signal stays positive almost the entire time on broad indices.

## Conclusions
1. **PPO is a poor stock selector** — top-10 rotation returns +611% vs MTF's +9,031% with ~3x the drawdown.
2. **PPO adds nothing as an MTF filter** — halves return, no DD improvement.
3. **PPO "wins" the ETF rotation contest** (+113% vs MTF +70%) but still loses to SPY/VTI B&H (+150%).
4. **PPO on broad indices = degenerate buy-and-hold** — the weekly 130-EMA scaling keeps the signal positive most of the time.
5. **Adopted strategies unchanged:** MTF Top-N for stocks; no PPO deployment anywhere.

## Why MTF wins on stocks
MTF's score (weekly gap_w + atr_dist + freshness) ranks explosive momentum; PPO's
zero-cross filter removes exactly the trades MTF makes money on. MTF's weekly+daily
bullish + freshness scoring already captures PPO's regime-filter value.
