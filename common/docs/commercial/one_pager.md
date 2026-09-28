# SwingTrader P20w — How it works

> **One sentence:** P20w holds three broad US ETFs only while each one's own weekly price is above its 20-week average — and whenever a leg is "on", it gets re-balanced to an equal share of the money every week, so winners are trimmed and losers are parked in cash.

No intraday trading. No options. No leverage. One decision per week, three simple yes/no switches.

## The three rules

1. **The line.** Each of QQQ, VTI and VTV is *long* while **its own settled weekly close > its own 20-week exponential average** (EMA20). The moment a leg closes a week below its line, that leg goes **to cash** (100% of that leg's money).
2. **Equal weight among the legs that are on.** Any legs still long are re-balanced so each holds exactly one-third of the invested money. Re-balancing happens **every new settled week**, not continuously.
3. **Settled bars only.** The decision is made on a **completed** weekly bar (Friday's close), never on a live/partial one. The trade happens the following **Monday** — one action per week per leg, max.

Nothing else happens between Mondays. There is no market-timing overlay, no sector bet, no news trading. The whole strategy is rule 1 meeting rule 2, applied weekly.

## The weekday rhythm

```
Mon–Thu   nothing to do (positions ride)
Fri       4 PM ET — each leg's weekly bar closes → compare to its EMA20
Mon       act once on whatever Friday decided (trim, top-up, enter, exit)
Repeat    one settled week per action, forever
```

This cadence is deliberate: it ignores everything that happens *inside* a week (earnings scares, FOMC noise, daily chop) and only reacts to what survives into a full weekly close.

## Why these three ETFs

| Ticker | What it is | Role in the trio |
|---|---|---|
| **QQQ** | Nasdaq-100 | Growth / tech engine |
| **VTI** | Whole US market | Market beta |
| **VTV** | US large-cap value | Defensive angle |

They are broad, deep, liquid instruments — no single-stock or single-sector fragility — and they alternate leadership across regimes (growth leads some years, value leads others). P20w does not predict which one leads; it just stays long each one while *its own* trend holds, and pockets cash when a leg's trend breaks.

## Why the weekly EMA20

The 20-week exponential average is a slow, trend-following filter. Its properties, shown in `performance.md`:

- In a **sustained leg up**, price keeps printing above it and the leg stays long — you stay invested instead of trading in and out.
- In a **drawdown**, price breaking below it gets you out faster than buy-and-hold, which is why P20w's historical maximum drawdown is roughly **half** of buy-and-hold's over the same decade.

We did not pick this filter blindly. We tested the whole family — faster spans (5, 10) and slower (50) — plus a daily-close version of the same idea. The daily version **churns**: 30 trades per leg per year, ~55% of the return, almost the same drawdown as buy-and-hold (that's the "research graveyard" in `performance.md`). The weekly version was chosen precisely because it survives the sweep of starting dates and spans robustly — the evidence is in `performance.md`, not suppressed.

## What it costs

- About **0.05% per side** (commission + slippage modeled), i.e. roughly **0.1% worst case on a full round-trip**.
- Historical turnover (10y, hypothetical): **747 buys / 687 sells total** across all three legs — about **2–3 small orders per week**, most of them penny-dribble re-balancing trims, not full-outs.

Because decisions are weekly and not daily, taxable events are fewer than in an intraday system — but re-balancing and exits do realize gains. Tax treatment depends on the account; that's a conversation with a tax professional, not a promise.

## The part you can verify yourself

Every join and exit P20w has ever made is a dated, price-stamped event. Pull up any charting platform that draws weekly EMA(20) on QQQ, VTI or VTV and check:

- **COVID, Feb 2020:** all three legs exited at the weekly bar of **Feb 24, 2020** — VTV closed that week at **$89.82**, below its EMA20, so it went to cash before the worst of the panic bottom — and each leg only re-entered after the line confirmed, VTV on **May 25, 2020 at $87.10**.
- **The 2023–24 run:** VTV went long the week of **Nov 13, 2023 at $132.42** and stayed long until **Dec 16, 2024 at $163.98** — a 14-month capture of a +27% (peak) move.
- **The Oct 2018 selloff:** exited the week of **Oct 8, 2018 at $87.39**.

If any of those dates disagree with your chart, it's a bug we want to know about — the flip log is machine-generated from settled weekly closes and should match any reputable data source to the day. That's the standard we hold ourselves to: no black box, every decision reproducible by hand.

## What this is not

- **Not investment advice.** It's a disclosed methodology we run on a paper account.
- **Not a guarantee.** Every historical figure here is hypothetical backtest, not a promise. The strategy has drawn down ~19% historically and can lose money in real markets — see `disclosure.md`.
- **Not "beats the market, always."** In the 2022 bear market it whipsawed — exited, re-entered, exited again for months (the details are in `regime_matrix.md`). You're buying a *mechanism* with known strengths and known costs, disclosed on the label.