# Disclosure & limitations (compliance spine)

> **Treat this page as the label on everything.** Any distribution of the commercial package (one-pager, performance sheet, regime matrix, FAQ) must carry a link to — or a footer reading — "see Disclosure & limitations."

## 1. What the performance figures actually are

All backtested figures in this package are **hypothetical reconstructions** produced on **2026-09-28** from settled weekly closes of QQQ, VTI and VTV.

- **Data:** daily closes from a local database; settled (completed) weekly bars only. Decision taken on a week's Friday close; fill modeled at the **following Monday's close**; **0.05% one-way** cost (commission + a small slippage allowance).
- **Re-balancing:** long legs routed to equal thirds at every settled week; OFF legs sit in cash (no interest modeled).
- **Source:** the exact same signal series the live strategy consumes (a single canonical, DB-backed computation). There is no second implementation for backtesting; that is a deliberate integrity property.

## 2. Known limitations (we state them so they can't surprise you)

1. **Idealized fills.** The backtest fills at the next-day close of the decision. The live system fills during Monday's session via real market orders. Real-world friction — stale quotes, thin early-Monday tape, routing — can move live fills by a few basis points and, occasionally, more. The 0.05% model absorbs the typical case, not every case.
2. **In-sample selection.** P20w was *chosen* partly because its backtest looked good (the span sweep preferred it). We mitigate, not eliminate, this: the published start-date and span sweeps show the pick is stable across 2016→2022 launch dates — but a hypothetical is still a hypothetical.
3. **Drawdowns are historical, not guarantees.** The 9.4% (813d) and 19.2% (full-period) maximum drawdowns are *what happened under the backtest's exact rules*. Real markets can produce worse. Gap/overnight risk fundamentals: decisions settle Friday and fill Monday.
4. **Regime coverage.** 2016–2026 contains no sustained decade-long sideways/flat market. In such a regime P20w's trend-following design is expected to underperform buy-and-hold (2022 is the closest proxy and it did exactly that).
5. **No leverage, no hedging, no market-timing exotic.** Only the three listed ETFs are traded. No shorting, no options, no margin. Returns are on long-only, cash-resting capital.
6. **Market risk** (plain words): certain sessions (e.g., major macro releases, thin tape) can widen spreads exactly when the strategy wants to act. That is an unhedged cost, not modeled beyond the 0.05%.

## 3. The no-advice / no-guarantee statement

- **This is not investment advice.** Nothing in this package is tailored to any person's financial situation, goals, or risk tolerance, and nothing constitutes a recommendation to buy or sell any security.
- **No promise of returns.** Past or hypothetical performance does not predict future results. All investing involves risk, including the possible loss of principal. Do not risk money you cannot afford to lose.
- **Not an offer or solicitation** to buy or sell securities. The strategy, its output, and this literature are informational materials describing a trading methodology.
- **No fiduciary relationship** is created by receiving this material. For personalized guidance, consult a licensed investment adviser and a tax professional.
- **Jurisdictional note:** in many jurisdictions, providing investment advice or operating a paid signal/advice service the public — including to friends and family — triggers registration requirements. This project is not, and does not claim to be, registered by any regulator, and has not sought legal review of this literature. Operator intends to obtain such review **before** any paid distribution. Ask for the current status if it matters to you.

## 4. Live record status

- The live book is a **paper account** (Alpaca paper, account #PA3GKZYLVO68), initial capital reset 2026-09-12, running **P20w since 2026-09-28**.
- The paper track is **not audited**, is self-reported, and its singular purpose is to be compared honestly against the backtest (fills, slippage, flip accuracy) once it accumulates. Anyone may request the raw weekly action log.

## 5. Versioning

| Field | Value |
|---|---|
| Package version | v0.1 |
| As-of date | 2026-09-28 |
| Signal span | EMA(20), weekly settled |
| Symbols | QQQ, VTI, VTV (long-only) |
| Costs modeled | 0.05% one-way, no interest on cash |
| Live (paper) start | 2026-09-28 |

This package will be re-issued when: the paper record accumulates a meaningful reviewable span, the strategy/signals change, or a new regime requires a fresh regime-matrix row.