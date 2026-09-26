---
name: portfolio-backtest
description: Use whenever the user asks to compare multiple ETF/stock portfolios, backtest allocation scenarios, or analyze "should I buy X, Y, Z together". Triggers: "backtest these ETFs", "compare portfolio allocation", "analyze VTI+QQQ+BND", "which portfolio is better", "show me returns for X+Y+Z", "N-ticker portfolio test". Takes N tickers (2-10) and scenarios (equal weight, custom weights, or predefined), returns performance table (total return, Sharpe, Calmar, max drawdown, win rate) with comparisons to SPY benchmark and actionable recommendations.
---

# Portfolio Backtest Skill — N-Ticker Analysis

**Purpose:** Test any combination of stocks/ETFs against each other and SPY over historical periods (2007-present or data availability), with weekly/daily rebalancing, to identify best risk-adjusted allocation.

**Core Logic:** 
- Fetch daily/weekly OHLCV data for N tickers
- Calculate equal-weight or custom-weight portfolio returns
- Compute Sharpe, Calmar, max drawdown, win rate
- Rank by return, risk-adjusted return, and recovery speed
- Compare vs SPY buy-and-hold benchmark
- Generate actionable recommendation table

**Scoring Metrics:**
- **Total Return %:** 19-year growth (2007-2026)
- **Annualized Return %:** Compound annual growth rate
- **Annualized Volatility %:** Annualized standard deviation (lower = smoother)
- **Max Drawdown %:** Worst peak-to-trough decline (less negative = safer)
- **Sharpe Ratio:** Return per unit of risk (>1.0 = excellent, >0.5 = good)
- **Calmar Ratio:** Return per unit of max drawdown (>0.5 = excellent, >0.25 = good)
- **Win Rate %:** % of periods with positive returns (>55% = good trend)

## How to run this

### Step 1: Gather inputs
```
User asks: "Backtest VTI + QQQ + BND with VTI + QQQ + VTV. Which is better?"

INPUT:
  - Portfolio A: [VTI, QQQ, BND] equal weight, daily rebalance (tool default)
  - Portfolio B: [VTI, QQQ, VTV] equal weight, daily rebalance (tool default)
  - Benchmark: SPY buy & hold
  - Date range: 2007-01-01 to present
```

### Step 2: Run the tool (preferred)
The tool lives in the repo at `portfolio-backtest/portfolio-backtest-tool.py`. Run it with the
existing scanner venv (has yfinance/pandas/numpy — do NOT create a new venv), from inside
`portfolio-backtest/` so the CSV lands there:
```bash
cd /home/dikesh/data/dev/SwingTraderAndOptimizer/portfolio-backtest
PY=/home/dikesh/data/dev/SwingTraderAndOptimizer/scanner/.venv/bin/python   # absolute: a ../ path warns
$PY portfolio-backtest-tool.py \
  --scenarios "VTI+QQQ+BND" "VTI+QQQ+VTV" \
  [--rebalance daily|weekly|monthly] [--own-window] [--start YYYY-MM-DD] [--benchmark SPY]
```
It prints the Table 1 metrics, rankings, calendar-year returns, stress windows (COVID crash,
2022 bear), a correlation matrix, and saves a CSV. By default all scenarios + benchmark share ONE
common window (starting at the latest-launched ticker's first bar) so numbers are comparable;
`--own-window` gives each scenario its full history. Report the window used with every result.

If you hand-roll it instead, follow the tool's data rules — `Adj Close` needs `auto_adjust=False`,
and prices are never back-/forward-filled across a ticker's inception:
```python
import yfinance as yf
import pandas as pd
import numpy as np

tickers = ['VTI', 'QQQ', 'BND', 'VTV', 'SPY']
data = yf.download(tickers, start='2007-01-01', auto_adjust=False, progress=False)['Adj Close']
start = data.apply(lambda s: s.first_valid_index()).max()   # common window: latest inception
returns = data.loc[start:].dropna().pct_change().dropna()
```

### Step 3: Calculate portfolio stats
```python
def portfolio_stats(returns, portfolio_tickers, name):
    """
    Inputs:
      - returns: DataFrame of daily/weekly returns
      - portfolio_tickers: list of tickers in this portfolio
      - name: str, portfolio name for output
    
    Outputs:
      - dict with keys: 
        'Total Return %', 'Annualized Return %', 'Annualized Volatility %',
        'Max Drawdown %', 'Sharpe Ratio', 'Calmar Ratio', 'Win Rate %'
    """
    
    # Equal-weight portfolio
    port_returns = returns[portfolio_tickers].mean(axis=1)
    cumulative = (1 + port_returns).cumprod()
    
    # Total return
    total_ret = (cumulative.iloc[-1] - 1) * 100
    
    # Annualized (19.7 years = 2007-2026)
    years = len(cumulative) / 252
    ann_ret = ((cumulative.iloc[-1] ** (1/years)) - 1) * 100
    ann_vol = port_returns.std() * np.sqrt(252) * 100
    
    # Max drawdown
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max
    max_dd = drawdown.min() * 100
    
    # Sharpe Ratio (2% risk-free rate)
    rf = 0.02 / 252
    excess = port_returns - rf
    sharpe = (excess.mean() / excess.std()) * np.sqrt(252) if excess.std() > 0 else 0
    
    # Calmar Ratio
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0
    
    # Win rate
    win_rate = (port_returns > 0).sum() / len(port_returns) * 100
    
    return {
        'Portfolio': name,
        'Total Return %': total_ret,
        'Ann. Return %': ann_ret,
        'Ann. Vol %': ann_vol,
        'Max DD %': max_dd,
        'Sharpe': sharpe,
        'Calmar': calmar,
        'Win Rate %': win_rate
    }
```

### Step 4: Build comparison table
```python
results = []
results.append(portfolio_stats(returns, ['VTI', 'QQQ', 'BND'], 'A: VTI+QQQ+BND'))
results.append(portfolio_stats(returns, ['VTI', 'QQQ', 'VTV'], 'B: VTI+QQQ+VTV'))
results.append(portfolio_stats(returns, ['SPY'], 'SPY Buy & Hold'))

comparison_df = pd.DataFrame(results)
print(comparison_df.to_string())
```

### Step 5: Rank and recommend
```python
# Rank by metric
by_return = sorted(results, key=lambda x: x['Total Return %'], reverse=True)
by_sharpe = sorted(results, key=lambda x: x['Sharpe'], reverse=True)
by_calmar = sorted(results, key=lambda x: x['Calmar'], reverse=True)

# Output: 
# "Portfolio A wins on Sharpe (0.92 vs B's 0.81)"
# "Portfolio B has higher return (620% vs A's 560%)"
# "Recommendation: Choose A for risk-adjusted returns, B for max growth"
```

## Input specification

**Required:**
- `tickers` (list of str): 2-10 ticker symbols (e.g., ['VTI', 'QQQ', 'BND'])
- `scenarios` (list of dict OR list of lists): 
  - Option A: List of dicts with 'name' and 'tickers' keys
    ```python
    [
      {'name': 'A: VTI+QQQ+BND', 'tickers': ['VTI', 'QQQ', 'BND']},
      {'name': 'B: VTI+QQQ+VTV', 'tickers': ['VTI', 'QQQ', 'VTV']}
    ]
    ```
  - Option B: Shorthand list of lists
    ```python
    [
      (['VTI', 'QQQ', 'BND'], 'A: VTI+QQQ+BND'),
      (['VTI', 'QQQ', 'VTV'], 'B: VTI+QQQ+VTV')
    ]
    ```

**Optional:**
- `weights` (dict): Custom weights per ticker (default: equal weight)
  ```python
  {'VTI': 0.40, 'QQQ': 0.30, 'BND': 0.30}
  ```
- `start_date` (str): 'YYYY-MM-DD' (default: '2007-01-01')
- `end_date` (str): 'YYYY-MM-DD' (default: today)
- `rebalance` (str): 'daily', 'weekly' or 'monthly' (default: 'daily'; results are near-identical across all three for ETF mixes — daily vs monthly moved 15-yr total return by <15 pts)

## Output format

**Table 1: Performance Comparison**

| Portfolio | Total Return | Ann. Return | Ann. Vol | Max DD | Sharpe | Calmar | Win % |
|---|---|---|---|---|---|---|---|
| A: VTI+QQQ+BND | 560% | 8.8% | 8.2% | -28.4% | 0.92 | 0.31 | 55.2% |
| B: VTI+QQQ+VTV | 620% | 9.4% | 10.1% | -35.8% | 0.81 | 0.26 | 54.8% |
| SPY Buy & Hold | 610% | 9.2% | 10.3% | -37.5% | 0.79 | 0.25 | 54.3% |

**Table 2: Rankings**

| Category | Winner | Metric | Note |
|---|---|---|---|
| Highest Return | B: VTI+QQQ+VTV | 620% | But with higher volatility |
| Best Risk-Adjusted | A: VTI+QQQ+BND | Sharpe 0.92 | Better return per unit of risk |
| Best Crash Recovery | A: VTI+QQQ+BND | Calmar 0.31 | Faster recovery from drawdowns |
| Smoothest Ride | A: VTI+QQQ+BND | Max DD -28.4% | 25% less downside than B |

**Table 3: Decision Matrix**

| If You Want... | Choose... | Why |
|---|---|---|
| Maximum return (30+ year horizon, tolerate volatility) | B: VTI+QQQ+VTV | +60 bps annual return |
| Stable returns, sleep at night | A: VTI+QQQ+BND | Sharpe 0.92, max DD -28% |
| Beat SPY | A or B (both beat SPY) | Both outperform benchmark |
| Balance of both | Hybrid: 60% B + 40% A | Capture growth + stability |

## Interpretation guide

**Sharpe Ratio:**
- `>1.0` = Excellent (rare, very efficient)
- `0.5-1.0` = Good (solid risk-adjusted returns)
- `0-0.5` = Weak (not compensating for volatility)

**Calmar Ratio:**
- `>0.5` = Excellent (strong recovery)
- `0.25-0.5` = Good (decent recovery)
- `<0.25` = Weak (takes long time to recover)

**Max Drawdown:**
- `>-20%` = Conservative (good for risk-averse)
- `-20% to -40%` = Moderate (typical for diversified portfolios)
- `<-40%` = Aggressive (for long horizons only)

**Win Rate:**
- `>55%` = Good (more up weeks than down)
- `50-55%` = OK (roughly balanced)
- `<50%` = Rare (negative skew)

## Example outputs

### Example 1: User asks "Should I add bonds to my VTI+QQQ portfolio?"

**Input:**
```
Scenario A: VTI + QQQ
Scenario B: VTI + QQQ + BND (30% bonds)
Benchmark: SPY
```

**Output:**

| Portfolio | Total Return | Sharpe | Max DD | Win Rate |
|---|---|---|---|---|
| A: VTI+QQQ | 680% | 0.75 | -42.6% | 54.1% |
| B: VTI+QQQ+BND | 560% | 0.92 | -28.4% | 55.2% |
| SPY | 610% | 0.79 | -37.5% | 54.3% |

**Recommendation:**
- **If adding bonds:** You lose 120% total return (680% → 560%) but gain 0.17 Sharpe points and cut max drawdown by 14.2%
- **Trade-off:** In 2008 crisis, A lost -43%, B lost -28%. A recovered in 4 years, B in 1.5 years
- **Verdict:** Add bonds if age >50 or risk-averse; skip if age <40 and high risk tolerance

---

### Example 2: User asks "Compare 5 different allocations"

**Input:**
```
Tickers: VTI, QQQ, VTV, BND, VXUS (5 tickers)
Scenarios:
  1. VTI + QQQ + VTV (100% equities)
  2. VTI + QQQ + VTV + BND (20% bonds)
  3. VTI + QQQ + VTV + VXUS (intl diversification)
  4. VTI + QQQ + VTV + BND + VXUS (balanced, 5-ETF)
  5. SPY (benchmark)
```

**Output:** Ranked table showing which allocation wins on each metric

---

## Red flags to mention

- **Data gaps:** If ticker has <10 years history, mention "data starts YYYY"
- **Common-window bias:** A late-launched ticker (e.g. VXUS 2011) truncates every portfolio to its start and hides earlier crises (2008 is excluded from the 2011+ window; VTI+QQQ+VTV max DD is -33% there vs -55% over 2007+). Always also run `--own-window` and cite both when they disagree.
- **Survivorship bias:** Backtesting assumes no delists; actual returns may differ
- **Rebalancing costs:** Not modeled; real costs = bid-ask + taxes
- **Past performance:** Doesn't guarantee future results
- **Correlations change:** During crashes, diversification breaks down (2008, 2020)

## Success criteria

✓ Returns decision table with 6+ metrics per portfolio  
✓ Compares to SPY benchmark  
✓ Ranks by return, Sharpe, Calmar, max DD  
✓ Provides actionable recommendation (e.g., "Choose A if risk-averse, B if growth-focused")  
✓ Mentions trade-offs explicitly  
✓ Includes interpretation of why one portfolio outperforms  

---

## Files to reference

- `portfolio-backtest/portfolio-backtest-tool.py` (repo root; run with `scanner/.venv/bin/python` — see Step 2)
- www.portfoliolab.com (free online backtester, alternative)
- www.backtest.curvo.eu (Backtrader engine)
