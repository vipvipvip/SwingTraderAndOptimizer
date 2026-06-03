### Current Strategy (6/3/26)

**Chandelier Exit — Always-In Trend Following**

| Ticker | ATR Period | Exit Mult | Entry Mult |
|--------|-----------|-----------|-----------|
| QQQ    | 18        | 3.5×      | 1.0×      |
| VTI    | 14        | 3.0×      | 1.0×      |
| VTV    | 14        | 2.5×      | 2.0×      |

**Entry rule:** `close > rolling_high(period) − ATR × entry_mult`
- entry_mult=1.0 (QQQ/VTI): only enter when price is within 1 ATR of the rolling high — confirmed uptrend only
- entry_mult=2.0 (VTV): allows entry with up to 2 ATR pullback from rolling high

**Exit rule:** `stop = highest_high_since_entry − ATR(period) × exit_mult`
- Trailing stop from highest high since entry; sell when close crosses below stop

**Capital allocation:** Single shared pool ($100k), split equally among tickers that signal on the same bar. Cash from exits sits idle until that ticker's next entry signal (no redistribution to other positions).

**Backtest results (2-year, daily bars, 0.05% round-trip cost):**

| Metric     | Value   |
|------------|---------|
| Return     | 169.2%  |
| Sharpe     | 1.19    |
| Win Rate   | 56.9%   |
| Max DD     | 18.1%   |
| Trades     | 72      |

**P&L by ticker:** QQQ $56k | VTI $62k | VTV $54k (well balanced)

**Key design decisions:**
- No redistribution on exit: prevents cascade risk when one ticker exits during a downturn
- entry_mult=1.0 is the tightest filter — only entering confirmed uptrends near recent highs
- Sharpe chosen as primary optimization target; return as secondary check
- nightly optimizer runs at 2 AM via systemd, updates parameters if Sharpe improves


### Learnings

Yes, entirely. `markov_regime.py` uses plain Gaussian HMM with 3 states and log-return/vol/momentum features — not the paper's GMM-HMM (4 states, 5 mixtures, OHLC ratios).

The paper approach is what's in `stock_hmm_model.py`. The issue is just that the state labeling is too aggressive — PULLBACK threshold of -0.002 catches 53% of days. Better fix: tighten the thresholds so PULLBACK requires genuinely negative features, and add a recent-trend override.

### Swing trading process
The model says PULLBACK but QQQ has rallied 11% in 3 weeks. Here's why:
Root cause: The HMM is stuck in State 2 because it entered it on May 22 and the transition matrix has high inertia — 52.7% of ALL days get labeled PULLBACK, including days with positive returns. The (close-open)/open feature captures daily noise, not trend.
State 2 (PULLBACK) mean daily return is only -0.5% — barely negative. Yet the Viterbi algorithm clings to it because the model learned on 500 days (including 2022's bear) that PULLBACK is persistent.
Fix options:
1. Switch to markov_regime.py (already built in common/scripts/) — uses log-returns + volatility + momentum, much better trend awareness. Overkill for this branch.
2. Tweak state labeling — raise PULLBACK threshold from -0.002 to -0.005 so only genuinely negative clusters get that label.
3. Fix the transition matrix — penalize PULLBACK stickiness by post-processing: if last 5d avg fc > 0, force DRIFT.
Which approach? Option 2 is the simplest — just a threshold change in characterize_states() in stock_hmm_regime.py.

