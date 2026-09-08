# MTF Audit Template

One entry point, one output contract for **any** present or future strategy that
runs on the `backtest_topn_multitf.py` engine. Instead of hand-writing a bespoke
report script per strategy (which drifts), point this template at the same CLI
args the engine takes and get a standard, reviewable audit package.

## Usage

```bash
python mtf_audit_template.py [--out DIR] [--label NAME] [--quiet] [-- <backtest args...>]
```

Everything after `--` (or any unrecognised tokens) is passed verbatim to
`backtest_topn_multitf.backtest()`. Any engine flag works:

```
--top-n --rebalance --detail --etf --score mtf|early|near|emasma
--tickers --above --min-score --infancy --stop-loss --top-trades
--ppo-filter --hourly-ema-gate --hourly-daily-gap --exit
--ratchet-atr-src --start --near-gap-k --near-atr-k
```

### Examples

```bash
# Sector ETF top-3 (the worked example in ../sector_etf_audit/)
python mtf_audit_template.py --out ../sector_etf_audit --label mtf_top3_sector_etfs -- \
    --etf --score emasma --top-n 3 \
    --tickers XLB,XLE,XLF,XLRE,XLV,XLI,XLK,XLP,XLU,XLY,XLC

# Stock universe, MTF score, ratchet-ATR exit (post-2023 hourly available)
python mtf_audit_template.py --out ../audit/outputs --label mtf_ratchet_top10 -- \
    --top-n 10 --exit ratchet-atr --start 2023-07-01
```

## Artifacts (each written into `--out`, prefixed by `--label`)

| File | Content |
|------|---------|
| `{label}_trades.csv` | Per-side ledger: every BUY/SELL with execution price, $ P/L, fee, hold days, exit reason, and the **signal snapshot** on the decision day before the fill. |
| `{label}_roundtrips.csv` | Closed trade pairs (BUY matched to its SELL) — the audit P/L ledger. Includes `sig_buy_*` / `sig_sell_*` summaries of the entry and exit decision bars. |
| `{label}_performance.csv` | Headline (return, CAGR, Sharpe, Sortino, vol, MaxDD, Calmar), trade distribution (win rate, profit factor, avg win/loss, expectancy, max losing streak), exposure, costs, benchmarks (SPY, VTI, equal-weight universe) plus config. |
| `{label}_monthly.csv` | Year x month return matrix with annual returns. |
| `{label}_by_symbol.csv` | Per-symbol activity: trades, win rate, net P/L, avg/best/worst return, avg hold. |
| `{label}_equity.csv` | Daily NAV / date / position-count series. |

## Metric definitions & integrity contract

- **Signal snapshot** — every fill happens at the *next trading day's OPEN* in
  the engine (no look-ahead). The snapshot reconstructs the weekly/daily/hourly
  bars and all four scores (`emasma`, `mtf`, `early`, `near`) on the decision
  day immediately before the fill from the DB directly — the same bars the
  engine's loop read. Hourly data only exists from 2023-06-30, so older
  snapshots carry blank hourly-derived fields (`atr_dist`, `mtf`, `near`)
  instead of fabricated values.
- **Cost basis** — buy fee is embedded in share sizing (`shares=(alloc/bp)*(1-COST)`).
  Round-trip net P/L = `gross − sell_fee`; summing `net_pnl` across ALL rows +
  initial capital equals the engine's end-of-sample equity within the display
  rounding (2 decimal places).
- **Open positions** — marked to the last available close with **no exit cost**
  (the engine's MTM adds no cost), so the ledger reconciles exactly. They are
  excluded from win-rate/profit-factor and flagged in `exit_reason` as
  `end-of-sample mark-to-market`.
- **Benchmarks** — SPY / VTI buy-and-hold over the same window, plus the
  equal-weight buy-and-hold of the backtested universe.
- **Deterministic tie-breaks** — candidate iteration ordering is whatever the
  engine produced; the audit replays the engine's own trade log, so any
  ordering nuance is captured, not re-derived.

## Adding a new strategy

1. Implement/enable it as an engine flag in `backtest_topn_multitf.py`.
2. Audit it with `python mtf_audit_template.py --out <dir> --label <name> -- <strategy args>`.
3. If the strategy's exits need richer reasons, map them in `EXIT_REASONS`.

No auditor-side code changes required — the output contract is fixed.