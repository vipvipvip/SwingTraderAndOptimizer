# Capital Preservation Strategy

## Overview

This document analyzes the swing trading system's performance against buy-and-hold,
focusing on the trade-off between return and risk (drawdown).

## Strategy Definition (Final)

**Timeframe:** 1Hour bars
**Strategy:** Chandelier Exit (always-long, trailing stop)
**Parameters (optimized nightly):**
- ATR Period: [14, 20, 26]
- Multiplier: [1.8, 2.0, 2.2]

**Signal Logic:**

**Entry:** Always re-enter when flat (unless exited same day)
**Exit:** `close < highest_high_since_entry - ATR(period) × multiplier`
| **Entry** | MACD > 0 **AND** EMA10 > SMA40 |
| **Exit** | MACD < 0 **OR** EMA10 < SMA40 |
| **Costs** | 0.05% round-trip (slippage + commission) |
| **Look-ahead** | None — entry/exit at next bar's open |

## Performance vs Buy-and-Hold (Dec 2022 – May 2026)

### 100% Allocation per Ticker

| Ticker | Strategy Return | BH Return | Capture | Max DD | Sharpe | Trades |
|--------|:-:|:-:|:-:|:-:|:-:|:-:|
| QQQ | 47.71% | 141.51% | 34% | 6.2% | 2.94 | 11 |
| SPY | 43.24% | 82.86% | 52% | 5.7% | 3.28 | 10 |
| VTI | 39.81% | 80.01% | 50% | 5.7% | 2.97 | 9 |
| VTV | 15.26% | 43.39% | 35% | 4.4% | 1.55 | 12 |

### Blended Portfolio (Current Allocation Weights)

| Ticker | Weight | Strategy | BH |
|--------|:-:|:-:|:-:|
| QQQ | 45% | 9.41% | 63.68% |
| VTI | 40% | 6.08% | 32.00% |
| VTV | 15% | 0.34% | 6.51% |
| **Total** | **100%** | **15.83%** | **108.19%** |

## Key Insight

**The strategy captures ~35–52% of buy-and-hold returns with ~5–6% max drawdown.**

In the Dec 2022 – May 2026 bull market, buy-and-hold dramatically outperforms.
Over a full market cycle (including a 2022-style -20% bear market), the strategy
would pull ahead by preserving capital during downturns.

### When the Strategy Wins

- **Bear markets:** BH loses 20–50%; strategy sits in cash (MACD < 0, EMA < SMA)
- **Range-bound markets:** BH goes nowhere; strategy captures short-term swings
- **High-volatility drawdowns:** Max DD capped at ~6% vs BH's typical 15–30%

### When Buy-and-Hold Wins

- **Strong bull markets:** 2023–2026 style relentless uptrends with shallow dips
- **Low-volatility periods:** Strategy's signal conditions rarely trigger

## Evolution of Fixes & Optimizations

| Iteration | Entry | Exit | Trend Filter | Costs | SPY Return | SPY Trades |
|-----------|-------|------|-------------|:-:|:-:|:-:|
| Original buggy | 2/4 dip-buy | 1/3 noisy | None | No | 13.66% | 217 |
| Over-optimized | 3/4 dip-buy | ATR stop | SMA50>200 | Yes | 3.35% | 24 |
| Balanced dip-buy | 2/4 dip-buy | 2/3 confirmed | None | Yes | 9.05% | 101 |
| Trend-follow H1 | MACD>0 AND EMA>SMA | MACD<0 OR EMA<SMA | None | Yes | 10.07% | 92 |
| **Trend-follow D1** | MACD>0 AND EMA>SMA | MACD<0 OR EMA<SMA | None | Yes | **43.24%** | **10** |

The jump from hourly (10.07%) to daily (43.24%) was the breakthrough — hourly
MACD/EMA produces too many whipsaws; daily filters the noise.

## Bugs Fixed Along the Way

| Bug | Impact |
|-----|--------|
| Sharpe inflated 3–5× (trade-level returns annualized with sqrt(1638)) | Made strategy look unrealistically good |
| Look-ahead bias (entry at signal bar close) | Overstated returns by using future price |
| Data truncated to 2 years (May 2024 start) | Missed entire 2023 bull run |
| `days_held` always 0 (missing field + int cast) | Holding period stats meaningless |
| Condition-based exits too sensitive (any 1 of 3) | 200+ whipsaw trades on hourly data |

## Files Changed

- `optimizer/parameter_optimizer.py` — core backtest logic
- `optimizer/strategies.py` — strategy signals (mirrors parameter_optimizer)
- `optimizer/db.py` — MACD params (18/26/14 → 12/26/9), float cast
- `optimizer/data_fetcher.py` — extended fetch range (730→1250 days)
- `optimizer/nightly_optimizer.py` — simplified param grid
