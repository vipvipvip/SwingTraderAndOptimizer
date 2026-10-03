# CoreEW P20w — Out-of-Sample Backtest Analysis

**Date:** 2026-10-03
**Strategy:** CoreEW variant P20w ("LegEMA"), live on paper account #PA3GKZYLVO68 since 2026-09-28
**Script:** `swingtrader/services/mtf/p20w_yf_backtest.py`
**Data:** Yahoo Finance Adj Close (split + dividend adjusted), QQQ / VTI / VTV, 2004-01-30 → 2026-10-02

## Summary

P20w is drawdown insurance, not a return enhancer. Out of sample (2004–2015, data the strategy was not chosen on) it cut the worst drawdown from 55.5% to 24.7% and protected well through 2008. That protection cost about 2.8% a year in return, and its Sharpe matched buy-and-hold rather than beating it. Over the full 22 years the cost is about 2.4% a year: $100k grows to $867k against $1.41M for equal-weight buy-and-hold.

The 2016+ backtest used to select P20w understated the cost by roughly 3×. Planning figures should come from the full history: about **10% CAGR with a ~25% worst drawdown**, against about 12.4% CAGR with a ~55% drawdown for buy-and-hold.

The EMA span is robust. Spans 15–25 form a stable plateau and 20 sits in the middle of it. No span changes the core trade-off.

**Decision:** keep span 20 and keep watching it in the paper account. The open question is whether halving the worst drawdown is worth about 2.4% a year, not which span to use.

## Strategy definition (as tested)

- **Signal:** each of QQQ, VTI and VTV is long while its settled weekly close is above its own EMA(20), computed as `ewm(span=20, adjust=False)` seeded at the first weekly close. A leg below its EMA sits in cash.
- **Settled weeks only:** a week counts once `week_date + 7 <= today`. Week W's Friday close is acted on the following Monday.
- **Sizing:** the legs that are long are rebalanced to equal weight every week. If all legs are off, the whole book is in cash.
- **Execution model:** decision on Monday, fill at the next session's close (Tuesday), 5 bp per side, cash earns 0%.
- **Benchmarks:**
  - **A:** always long all three, rebalanced to equal weight weekly.
  - **C:** equal-weight buy-and-hold, never rebalanced.

## Method and validation

The test was built so it can be trusted to match live trading, and three checks confirm it does:

1. **Shared code, not a rewrite.** `run_sim`, `settled_weekly_ref` and `pos_of` are loaded directly from `backtest_trio_ew.py` (via `ast`, not re-typed). The signal is a line-for-line port of PHP `replayLegEmaSeries()`.
2. **Weekly bars.** Weekly closes built from daily data (Monday-dated, last close of each week) match the DB's native Alpaca weekly bars on every settled week.
3. **Parity with the DB.**
   - Fed the DB's own closes, the script reproduces the DB backtest exactly: +362.8%, 19.2% MaxDD, leg flips QQQ 45 / VTI 41 / VTV 63, identical calendar years.
   - Fed Yahoo prices with the EMA seeded in 2016 like the DB, it gives +363.0% and 19.2% MaxDD, so the Yahoo data matches Alpaca's.

**Sensitivity note:** seeding the EMA in 2004 instead of 2016 changes the 2016+ result from +363% to +351%. That 12-point swing comes purely from where the EMA starts, which shows how much ordinary implementation details move these figures.

## Results — span 20

### By period

| Period | Strategy | Return | CAGR | MaxDD | Sharpe | Calmar | Worst-DD recovery |
|---|---|---|---|---|---|---|---|
| **2004–2015 (out of sample)** | P20w | +95.1% | 5.8% | **24.7%** | 0.49 | **0.23** | 746 d |
| | A: EW weekly | +165.9% | 8.6% | 55.3% | 0.52 | 0.15 | 1,578 d |
| | C: EW buy & hold | +167.0% | 8.6% | 55.5% | 0.52 | 0.15 | 1,578 d |
| **2016–2026 (selection window)** | P20w | +351.1% | 15.1% | **19.2%** | **1.14** | **0.78** | 707 d |
| | A: EW weekly | +394.5% | 16.0% | 33.1% | 0.92 | 0.48 | 168 d |
| | C: EW buy & hold | +409.6% | 16.4% | 32.6% | 0.92 | 0.50 | 152 d |
| **2004–2026 (full)** | P20w | +766.7% | 10.0% | **24.7%** | **0.80** | **0.40** | 746 d |
| | A: EW weekly | +1,195.2% | 12.0% | 55.3% | 0.70 | 0.22 | 1,578 d |
| | C: EW buy & hold | +1,311.3% | 12.4% | 55.5% | 0.70 | 0.22 | 1,578 d |

In the selection window P20w gave up about 1 point of CAGR and clearly won on Sharpe. Out of sample it gave up 2.8 points and only matched buy-and-hold's Sharpe. The drawdown reduction is the one advantage that held in both periods.

### Crash windows

Each window starts just before the market peak, with the strategy already running (EMA warmed since 2004).

| Window (start) | P20w 1y | B&H 1y | P20w 2y | B&H 2y | P20w 2y MaxDD | B&H 2y MaxDD |
|---|---|---|---|---|---|---|
| GFC pre-peak (2007-10-01) | −22.5% | −24.2% | **+8.2%** | −25.7% | **23.9%** | 55.4% |
| GFC pre-Lehman (2008-09-02) | **+30.4%** | −17.9% | **+33.2%** | −6.7% | **16.6%** | 46.2% |
| 2010 flash crash (2010-04-15) | +5.3% | +12.4% | −5.0% | +21.5% | 24.7% | 18.1% |
| 2011 US downgrade (2011-07-01) | −11.3% | +5.2% | +4.4% | +25.3% | 21.0% | 17.8% |
| 2015–16 selloff (2015-07-15) | −7.4% | +3.9% | +8.5% | +24.2% | 17.0% | 14.0% |
| 2018 Q4 (2018-09-20) | +0.4% | +3.1% | **+29.9%** | +21.0% | **12.8%** | 32.9% |
| COVID (2020-02-14) | **+35.0%** | +24.4% | **+52.0%** | +36.8% | **12.8%** | 33.1% |
| 2022 bear (2021-12-27) | −16.7% | −18.7% | +4.4% | +4.1% | **19.2%** | 24.5% |
| 2025 tariffs (2025-02-14) | **+17.5%** | +14.7% | +32.6% | +31.8% | **9.4%** | 18.6% |

**Checked against the equity curve:** from 2008-09-02, P20w was in cash through the 2009-03-09 low (−1.0% against −46.3% for buy-and-hold, 144 all-cash sessions in 2008–09). It then re-entered and captured about 30% of the 53% rebound.

**Pattern:** P20w wins clearly in sustained declines (2008, 2020, Q4 2018, 2025) and loses in choppy, quickly-recovering markets (2010, 2011, 2015–16). Its worst drawdown in 22 years was the 2011 whipsaw, not 2008.

### Calendar-year returns (full history)

| Year | P20w | A: EW weekly | C: B&H | P20w − A |
|---|---|---|---|---|
| 2004 | 3.4% | 10.9% | 10.8% | −7.5 |
| 2005 | −3.3% | 5.1% | 5.1% | −8.4 |
| 2006 | 10.3% | 15.0% | 15.3% | −4.7 |
| 2007 | 8.2% | 7.9% | 7.3% | +0.3 |
| 2008 | −19.8% | −38.1% | −38.2% | **+18.3** |
| 2009 | 48.5% | 33.9% | 33.6% | **+14.6** |
| 2010 | 4.3% | 17.4% | 17.5% | −13.1 |
| 2011 | −15.1% | 1.9% | 1.9% | **−17.0** |
| 2012 | 11.1% | 16.6% | 16.7% | −5.5 |
| 2013 | 34.8% | 34.4% | 34.5% | +0.3 |
| 2014 | 7.4% | 15.0% | 15.3% | −7.5 |
| 2015 | −3.6% | 2.9% | 3.5% | −6.5 |
| 2016 | 7.2% | 12.4% | 11.7% | −5.1 |
| 2017 | 23.6% | 23.6% | 24.6% | 0.0 |
| 2018 | −3.5% | −3.5% | −3.1% | 0.0 |
| 2019 | 18.4% | 31.7% | 32.9% | −13.3 |
| 2020 | 33.6% | 23.0% | 28.7% | **+10.6** |
| 2021 | 26.8% | 26.8% | 26.8% | 0.0 |
| 2022 | −16.5% | −18.7% | −22.8% | +2.2 |
| 2023 | 25.2% | 29.0% | 35.0% | −3.7 |
| 2024 | 19.0% | 22.0% | 23.1% | −2.9 |
| 2025 | 20.9% | 17.9% | 18.7% | +3.0 |
| 2026 YTD | 15.2% | 17.4% | 18.9% | −2.3 |

P20w beat A in 9 of 23 years. Its advantage comes from a few large years (2008–09, 2020, 2022, 2025). In most other years it trails by a few points.

## Span sweep (EMA 10 / 15 / 20 / 25 / 30 weeks)

| Span | 2004–15 CAGR | 2004–15 MaxDD | 2004–15 Sharpe | 2016+ CAGR | 2016+ MaxDD | Full CAGR | Full MaxDD | Full Sharpe | Full Calmar | Beat B&H (years) |
|---|---|---|---|---|---|---|---|---|---|---|
| 10w | 2.9% | 38.0% | 0.28 | 13.8% | 14.4% | 7.8% | 38.0% | 0.65 | 0.21 | 3 / 23 |
| 15w | 6.1% | 24.8% | 0.53 | 13.8% | 20.1% | 9.6% | 24.8% | 0.79 | 0.39 | 6 / 23 |
| **20w (live)** | **5.8%** | **24.7%** | **0.49** | **15.1%** | **19.2%** | **10.0%** | **24.7%** | **0.80** | **0.40** | — |
| 25w | 6.6% | 25.5% | 0.55 | 15.8% | 19.7% | 10.8% | 25.5% | 0.85 | 0.42 | 9 / 23 |
| 30w | 6.0% | 27.3% | 0.50 | 12.7% | 26.6% | 9.0% | 27.3% | 0.69 | 0.33 | 8 / 23 |
| Buy & hold | 8.6% | 55.5% | 0.52 | 16.4% | 32.6% | 12.4% | 55.5% | 0.70 | 0.22 | — |

### Two-year crash windows by span (equity-curve basis)

| Window | B&H | P10w | P15w | P25w | P30w |
|---|---|---|---|---|---|
| GFC pre-peak — return | −28.0% | −17.4% | +3.8% | +3.1% | +2.7% |
| GFC pre-peak — MaxDD | 55.5% | 38.0% | 24.8% | 21.7% | 21.6% |
| GFC pre-Lehman — return | −6.7% | +11.3% | +36.6% | +30.9% | +19.9% |
| 2011 downgrade — return | +26.2% | +6.8% | +8.8% | +7.3% | +4.9% |
| COVID — MaxDD | 32.0% | 14.4% | 12.8% | 12.8% | 26.6% |
| 2022 bear — MaxDD | 27.8% | 13.8% | 20.1% | 19.7% | 25.9% |

### What the sweep shows

- **15–25 weeks is a real plateau.** Results stay within about a point of CAGR and a few points of drawdown across those spans, which is what a robust parameter looks like.
- **Both edges fail, for opposite reasons.** At 10 weeks the signal reacts too fast and gets whipsawed (38% drawdown, 2.9% out-of-sample CAGR). At 30 weeks it reacts too slowly (26.6% drawdown in COVID, −22.8% in 2022).
- **Span 25 is slightly better than 20 on every metric, but not by enough to switch.** The gap (about 0.8% a year of CAGR, 0.05 of Sharpe) is smaller than the 12-point swing from EMA seeding alone, and picking 25 now would mean tuning on the very data that was the out-of-sample test.
- **Choppy markets hurt every span.** All of them lost 13.5–16.6% in 2011, so this weakness belongs to the signal family, not the span setting.
- **Out of sample, every good span lands near buy-and-hold's Sharpe** (0.49–0.55 against 0.52). Choosing a different span doesn't change the return cost.

## Caveats

1. **Cash earns 0% in the backtest.** P20w held about 19% cash on average. With T-bills at 1–5% in 2004–08 and 2023–26, counting cash yield would recover roughly 0.3–0.6% a year of the cost.
2. **Fills are modelled at Tuesday's close.** Live fills happen Monday at about 10:05 ET. On the 2016+ data that one-session difference was about 4 points over 10 years and can go either way.
3. **Survivorship.** QQQ, VTI and VTV were chosen in hindsight, though all three are broad, liquid index ETFs.
4. **Pre-tax.** Weekly rebalancing realizes gains, which matters in a taxable account.
5. **This is a backtest analysis, not investment advice.**

## Related changes made during this review

- **`getCurrentPrice()` uses a live price** (`getCurrentPrice-live-first.patch`). CoreEW order sizing now uses Alpaca's latest IEX trade, with the hourly-table price as fallback and a 15% guard against bad prints. Disabling the 09:10 hourly sampler on 2026-10-02 had left sizing on the previous session's post-close capture. The effect on the backtest was small (+362.8% vs +362.3%), but sizing off a stale price allowed up to about 2% cash overdraw when prices gapped up.
- **HCO / hourly removal.** No negative effect on live strategies. The CoreEW signal never read hourly data, and the MTF emasma strategy scores on weekly and daily bars only. The deleted hourly buy veto was never part of the backtest the strategy was validated on (its support was 0 wins in 7 paper trades). The readiness-gate change in 42b4fa3 was required, because without it the stock leg would have skipped every day once the hourly timer was disabled.

## Reproduce

```bash
cd ~/data/dev/SwingTraderAndOptimizer/swingtrader/services/mtf
source ../../../portfolio-backtest/venv/bin/activate

python3 p20w_yf_backtest.py --span 10,15,20,25,30 --outdir p20w_yf_spans      # sweep + crash windows
python3 p20w_yf_backtest.py --start 2016-01-04 --outdir p20w_yf_parity        # parity with DB
python3 p20w_yf_backtest.py --refresh                                          # re-download prices
```

Prices are cached in `trio_yf_adjclose.csv`. Keep it and the output folders out of git, since Yahoo's terms don't permit republishing its data.

## Next steps

1. Watch the paper account through at least one leg flip. Compare fills and weights against the backtest with `alpaca_report.py --strategy coreew`.
2. Apply the `getCurrentPrice()` patch before the next leg flip.
3. Optional: add a T-bill cash yield to the sim (e.g. `^IRX`) to get a fairer comparison against buy-and-hold.
4. Decide whether the drawdown protection is worth about 2.4% a year. That's a judgment about risk tolerance, not something more backtesting will settle.
