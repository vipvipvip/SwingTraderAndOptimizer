# MTCS — Multi-Timeframe Cycle Strategy (Signal Service)

## Overview

MTCS uses Hilbert Transform spectral analysis to detect dominant market cycles
and generate BUY/SELL signals at cycle turning points. It operates on **daily**
OHLC data and is designed to be **uncorrelated** from the CHAND trend-following
strategy (daily return correlation: -0.017).

- **Real trade execution** — BUY pools cash equally across signals, SELL liquidates via Alpaca
- **No candle building** — reads daily bars from shared `tbl_etf_tickers_1hour`
- **3 tickers**: QQQ, VTI, VTV
- **Slated for replacement** by MTF Top-N (strategy #4) after Phase 1 validation

## How It Works

1. **Detrend** — subtracts a 30-bar SMA to isolate cycle component
2. **Hilbert Transform** — computes the analytic signal from the detrended price,
   extracting instantaneous phase (0–360°) at each bar
3. **Sine / Lead-Sine** — `sin(phase)` tracks the cycle; `cos(phase)` (= lead)
   leads by 90° (¼ cycle)
4. **Signal trigger** — BUY when sine crosses **above** lead; SELL when sine crosses
   **below** lead

## Architecture

```
┌──────────┐    ┌──────────────┐    ┌───────────────────┐    ┌─────────────────┐
│ DB (PSQL)│───▶│  runner.py   │───▶│  strategy.py      │───▶│  Slack / DB     │
│ daily    │    │  (main loop) │    │  (signal detect)  │    │  (notify/log)   │
│ OHLC     │    │              │    │                   │    │                 │
└──────────┘    └──────────────┘    └───────────────────┘    └─────────────────┘
                     │ ▲
                     ▼ │
               ┌──────────────┐
               │  spectral.py │
               │  (Hilbert)   │
               └──────────────┘
```

## Files

All files live under `swingtrader/services/mtcs/`:

| File | Purpose |
|------|---------|
| `runner.py` | Main loop — polls every 30 min during RTH, checks for new daily bars, triggers signal detection, executes trades via executor, sends Slack |
| `strategy.py` | Loads daily closes, runs `spectral.dominant_cycle()`, checks last 2 bars for sine/lead cross |
| `spectral.py` | Hilbert Transform, FFT dominant cycle detection, smoothing functions |
| `executor.py` | Alpaca buy/sell — `buy_position()` pools cash equally, `sell_position()` liquidates full position |
| `db.py` | DB schema + CRUD for `mtcs_positions`, `mtcs_trades`; reads OHLC from `tbl_etf_tickers_1hour` |
| `config.py` | Tickers, MTCS parameters (detrend=30, smooth=5), DB/Slack config, Alpaca API key |
| `chart.py` | Matplotlib utility — visualizes Hilbert sine/lead for any ticker |
| `health_check.py` | Alpaca account balance + real position status |
| `.env` | Environment variables (DB creds, Slack webhook URL, Alpaca keys) |
| `systemd/mtcs-runner.service` | systemd unit for auto-start + restart |

## Parameters (tuned via grid search, no look-ahead bias)

| Parameter | Value | Description |
|-----------|-------|-------------|
| Detrend period | 30 | SMA window for trend removal |
| Smoothing | 5 | EMA smoothing on sine/lead signal |
| Warmup bars | 60 | Minimum bars before emitting signals |
| Poll interval | 1800s (30 min) | How often to check for new daily bars |

## Backtest Results (1487 daily bars, 2020-07-27 → 2026-06-29)

| Metric | QQQ | VTI | VTV | **Blended** |
|--------|-----|-----|-----|-------------|
| Return | 65.5% | 78.9% | 89.6% | **68.5%** |
| Sharpe | 0.38 | 0.81 | 1.21 | **1.14** |
| Win rate | 57% | 61% | 59% | **59%** |
| Max DD | 31.3% | 20.1% | 3.5% | **15.6%** |
| Trades | 35 | 54 | 58 | **147** |

### Combined with CHAND (50/50)

| Metric | CHAND | MTCS | **50/50 Blend** |
|--------|-------|------|-----------------|
| Sharpe | 1.03 | 1.14 | **1.70** |
| Return | 97.8% | 68.5% | **66.7%** |
| Max DD | 10.0% | 15.6% | **9.1%** |
| Daily return correlation | — | -0.017 | **uncorrelated** |

## Slack Messages

Messages are sent to the **same Slack webhook** as EMAC, tagged `[MTCS]`:

```
[MTCS] BUY VTV @ $218.57  |  cycles: 78.3d, 87.5d  |  D(30) S(5)
[MTCS] SELL VTV @ $225.10  |  PnL: +2.99%  |  D(30) S(5)
```

## CSV Trade Log

All signals (BUY and SELL) are logged to `swingtrader/services/mtcs/mtcs_trades.csv`:

```
symbol,side,price,date,extra
VTV,BUY,218.57,2026-06-15,cycles: 78.3d, 87.5d
VTV,SELL,225.10,2026-07-01,+2.99%
```

## Alpaca Account

| Property | Value |
|----------|-------|
| API Key | `PKQK45DA2ERAXX6XKPUDORIWSH` |
| Account # | PA3NCXU4O2CN |
| Type | Paper |
| Balance | $1,000,000 |
| Status | ACTIVE |

## Replacement Status

MTCS is **slated for replacement** by **MTF Top-N** (strategy #4).
See `common/docs/services_doc/mtf_daily_runner.md` for details.

| Phase | Action | Status |
|-------|--------|--------|
| 1 | Paper trading MTF picks alongside running MTCS | 🚧 In Progress |
| 2 | Stop MTCS, wire MTF picks into Alpaca executor | ⏳ Pending |

## Service Management

```bash
# Status
systemctl status mtcs-runner.service

# Logs
journalctl -u mtcs-runner.service -n 50 --no-pager

# Restart
sudo systemctl restart mtcs-runner.service

# Stop
sudo systemctl stop mtcs-runner.service
```

## DB Schema

```sql
-- Tracks open positions (virtual, no real capital)
CREATE TABLE mtcs_positions (
    id SERIAL PRIMARY KEY,
    ticker_id INTEGER REFERENCES tbl_etf_tickers(id) UNIQUE,
    symbol VARCHAR(20) NOT NULL,
    quantity NUMERIC(12,4) DEFAULT 1,
    entry_price NUMERIC(12,4),
    entry_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Trade log (BUY/SELL signals recorded)
CREATE TABLE mtcs_trades (
    id SERIAL PRIMARY KEY,
    ticker_id INTEGER REFERENCES tbl_etf_tickers(id),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    price NUMERIC(12,4) NOT NULL,
    signal_ts TIMESTAMP,
    executed_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

## References

The signal processing techniques used here originate from **John F. Ehlers**:

- **Detrend + SMA to isolate cycles** — *"Rocket Science for Traders"* (Wiley, 2001), Ch. 2
- **Hilbert Transform for instantaneous phase** — *"Rocket Science for Traders"*, Ch. 8–10; also *"Using the Hilbert Transform for Cycle Detection"* (Technical Analysis of Stocks & Commodities, 1994). Unlike FFT (which averages over the entire window), the Hilbert Transform gives the phase at each bar.
- **Sine/Lead-Sine crossover as entry signal** — *"Cycle Analytics for Traders"* (2014). cos(θ) = sin(θ + 90°) = sin(θ + ¼ cycle), so the cross of sin(θ) through cos(θ) catches cycle turns with zero lag.

Online: search "Ehlers Hilbert Transform trading" for practical articles on StockCharts, MQL5, or the MESA Software website.

## Notes

- Daily return correlation with CHAND: **-0.017** (essentially zero) — ideal for diversification
- MTCS performs best on **VTV** (value ETF, Sharpe 1.21) — value ETFs exhibit cleaner cycles
- MTCS performs worst on **QQQ** (tech, Sharpe 0.38) — tech trends more than it cycles
- The **50/50 CHAND + MTCS blend** yields Sharpe **1.70**, dramatically better than either alone
- No walk-forward optimization was done — parameters were selected from a simple grid search
- Backtest used expanding-window (walk-forward) Hilbert Transform to eliminate look-ahead bias
