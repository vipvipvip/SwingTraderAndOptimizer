# How to Use the Portfolio Backtest Tool

---

## Where things live

```
SwingTraderAndOptimizer/
├── portfolio-backtest/
│   ├── portfolio-backtest-tool.py          (the tool)
│   ├── portfolio-backtest-readme.md        (one-page summary)
│   └── howTo.md                            (this file)
├── .claude/skills/portfolio-backtest/
│   └── SKILL.md                            (Claude skill — auto-triggers on "compare these portfolios")
└── scanner/.venv/                          (the venv to run it with)
```

---

## Step 1: Python environment — nothing to create

`scanner/.venv` already has everything the tool needs (yfinance, pandas, numpy). Use it directly:

```bash
cd /home/dikesh/data/dev/SwingTraderAndOptimizer/portfolio-backtest

# Set once per shell session; every command below uses $PY
# (absolute path on purpose — a "../scanner/..." path prints a harmless sys.prefix warning)
PY=/home/dikesh/data/dev/SwingTraderAndOptimizer/scanner/.venv/bin/python

# Verify
$PY portfolio-backtest-tool.py --help
```

No `activate` needed — calling the venv's `python` by path is enough. (`stock-analyzer/.venv` and
`swingtrader/services/optimizer/venv` do NOT have yfinance, so don't use those.)

> Running it on a different machine outside this repo? Then create a venv there:
> `python3 -m venv venv && source venv/bin/activate && pip install yfinance pandas numpy`

---

## Step 2: Run the script

Run from inside `portfolio-backtest/` so the CSV is saved there:

```bash
$PY portfolio-backtest-tool.py \
  --scenarios "VTI+QQQ+BND" "VTI+QQQ+VXUS" "VTI+QQQ+VTV"
```

Tickers are picked up from the scenarios automatically (and SPY as the benchmark).

**Output:** a printed report (metrics, rankings, calendar-year returns, stress windows,
correlations) and a CSV such as `portfolio_backtest_20260926_142938.csv`.

---

## Step 3: Use the Python module (Advanced)

The filename has hyphens, so a normal `import` won't work — load it with `importlib`:

```python
# File: my_portfolio_analysis.py  (run with $PY)
import importlib.util

spec = importlib.util.spec_from_file_location("pbt", "portfolio-backtest-tool.py")
pbt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pbt)

bt = pbt.PortfolioBacktester(['VTI', 'QQQ', 'BND', 'VXUS'], rebalance='daily')

scenarios = [
    (['VTI', 'QQQ', 'BND'], 'Conservative (Bonds)'),
    (['VTI', 'QQQ', 'VXUS'], 'International'),
    (['VTI', 'QQQ', 'BND', 'VXUS'], 'Balanced'),
]

results = bt.compare_with_benchmark(scenarios, benchmark='SPY')
bt.print_comparison(results)
bt.print_details()
results.to_csv('my_portfolio_analysis.csv', index=False)
```

Custom weights (applied to every scenario; tickers not listed get 0):
```python
bt.backtest([(['VTI', 'QQQ', 'BND'], '40/30/30')], weights={'VTI': .4, 'QQQ': .3, 'BND': .3})
```

---

## Quick Reference: CLI Usage Examples

### Example 1: Basic comparison
```bash
$PY portfolio-backtest-tool.py \
  --scenarios "VTI+QQQ" "VTI+QQQ+BND"
```

### Example 2: Compare 4 scenarios
```bash
$PY portfolio-backtest-tool.py \
  --scenarios "VTI+QQQ+VTV" "VTI+QQQ+VTV+BND" "VTI+QQQ+VTV+VXUS" "VTI+QQQ+VTV+BND+VXUS"
```

### Example 3: Custom date range
```bash
$PY portfolio-backtest-tool.py \
  --scenarios "VTI+QQQ" "VTI+QQQ+BND" \
  --start 2015-01-01 --end 2026-09-25
```

### Example 4: Each portfolio over its own full history
```bash
$PY portfolio-backtest-tool.py \
  --scenarios "VTI+QQQ+BND" "VTI+QQQ+VXUS" "VTI+QQQ+VTV" --own-window
```

### Example 5: Monthly rebalance, QQQ as benchmark
```bash
$PY portfolio-backtest-tool.py \
  --scenarios "VTI+QQQ" "VTI+QQQ+BND" --rebalance monthly --benchmark QQQ
```

---

## Command Line Arguments

| Argument | Required? | Example | Notes |
|---|---|---|---|
| `--scenarios` | YES | `"VTI+QQQ" "VTI+QQQ+BND"` | Space-separated; `+` joins tickers in one portfolio |
| `--tickers` | NO | `VTI QQQ` | Extra tickers to pre-fetch; scenario tickers are added automatically |
| `--start` | NO | `2015-01-01` | Start date (default 2007-01-01) |
| `--end` | NO | `2026-09-25` | End date (default today) |
| `--benchmark` | NO | `SPY` | Benchmark ticker (default SPY) |
| `--rebalance` | NO | `monthly` | `daily` (default), `weekly` or `monthly` back to equal weight |
| `--own-window` | NO | | Each scenario uses its own full history (default: one common window for all) |
| `--help` | NO | | Show all options |

---

## Understanding the Output

### Common window vs own window

By default every scenario and the benchmark are measured over the **same dates**, starting at the
latest-launched ticker's first bar (e.g. VXUS launched 2011-01-28, so a run containing VXUS starts
2011). That makes the numbers comparable, but it also **hides earlier crises like 2008**. Run
`--own-window` as well and compare — e.g. VTI+QQQ+VTV's max drawdown is -33% on the 2011+ window but
-55% on its own 2007+ history. Prices are never back-filled before a ticker exists.

### Performance Comparison

```
VTI+QQQ+BND
  Total Return:       483.0%
  Ann. Return:         11.9%  |  Ann. Vol:   12.7%
  Max Drawdown:       -25.3%
  Sharpe Ratio:        0.80  |  Calmar:   0.47  |  Win Rate:   55.4%
```

- **Total Return %:** cumulative return over the window shown in the header
- **Ann. Return %:** compound annual growth rate
- **Ann. Vol %:** annualized volatility (lower = smoother)
- **Max Drawdown %:** worst peak-to-trough decline
- **Sharpe Ratio:** return per unit of risk, 2% risk-free (>1.0 = excellent, >0.5 = good)
- **Calmar Ratio:** annual return / max drawdown (>0.5 = excellent, >0.25 = good)
- **Win Rate %:** % of trading days with positive returns (rarely separates portfolios)

### Rankings, then extras

After the per-portfolio blocks the tool prints rankings (highest return, best Sharpe, best Calmar,
smallest drawdown), then **calendar-year returns**, **stress windows** (COVID crash, 2022 bear)
and a **daily-return correlation matrix**.

### CSV Output

All metrics plus the start/end dates of each portfolio's window. Open in Excel / Google Sheets.

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'yfinance'"

You ran a Python that isn't `scanner/.venv`. Call it by path from `portfolio-backtest/`:
`$PY portfolio-backtest-tool.py ...`

### "No data for XXXX — scenarios using it will be skipped"

Ticker doesn't exist on Yahoo Finance or is misspelled (use `VTI`, not `VTI.US`). Other scenarios
still run.

### "HTTP Error 403" / connection errors

Network is blocking Yahoo Finance (common on corporate networks). Try another network or a VPN.

### "externally-managed-environment"

You tried `pip install` into the system Python. Don't — use `scanner/.venv` (Step 1).

---

## Tips

- **Compare many scenarios in one run** rather than several runs — they then share one window.
- **Re-run periodically:** data extends to the latest close each run, so rerun to refresh.
- **Rebalance frequency barely matters** for ETF mixes like these (daily vs monthly moved 15-yr
  total return by <15 pts), so leave it on the default unless testing something specific.
