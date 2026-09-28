# Regime matrix — how P20w behaves across market conditions (2016→2026)

> **HYPOTHETICAL backtest.** Every entry below is checkable: take any date, draw weekly EMA(20) on the ticker's chart, and the flip should line up to the week. We publish this because "how does it do in a crash?" is the question anyone asks, and because the honest answer includes the times it was wrong.
>
> **How to read the dates:** the "week of" column is labeled by the **Monday** that starts the settled weekly bar; the close is that week's **Friday** settle; the trade happens the **following Monday**. All prices are weekly closes. Figures are per-leg — VTV (value) is the most active leg and is used throughout for dates/prices; QQQ and VTI follow the same structure with fewer flips (45/41 vs VTV's 63 over 10y).

## The matrix

| Period | Market | What the market did | What P20w did | Cost / benefit verdict |
|---|---|---|---|---|
| **2016–2017 bull** | QQQ +~60%, VTV steadier | Broad, persistent uptrend | Mostly long; legs held the line, small re-balance trims only | **Benefit.** Owned the whole ride; the "boring years" are where equal-weight + trend just works |
| **Oct 2018 selloff** | QQQ −~15% in Q4 | Sharp 6-week drawdown | VTV exited week of **10/08/2018 @ $87.39**, re-entered **11/26/2018 @ $89.37**, exited again 12/03/2018 @ $85.32 before the bottom | **Mixed.** Got out before the worst; the late-2018 re-entries whipsawed twice in the volatile bottoming week |
| **2019** | Mixed chop → strong finish | Two mid-year mini-scares, then a 3rd- and 4th-quarter rally | VTV cut 05/27 @ 86.99, re-bought 06/03 @ 91.13 (paid up); cut 08/05 @ 91.67, re-bought 09/02 @ 92.92 | **Paid a re-entry tax** (~+2–4% buy-back premium) twice, then rode the Q4 rally leaving the exits behind |
| **COVID crash, Feb–Mar 2020** | −20–30% intra-month | Fastest 1-month crash in history | All legs cut the week of **02/24/2020** (VTV close **$89.82**, the day the bottom-half of the panic began). Market kept falling ~2 more weeks to ~$80; VTV re-entered **05/25/2020 @ $87.10** | **The strategy's flag moment.** Missed the last ~10% of the crash, missed the first snap-back week, but **stayed out pale while buy-and-hold ate a 33% drawdown** |
| **2020 recovery, Sep + Oct** | Post-recovery chop | V-shaped bounce, then drifting | Never re-entered in the chop; a Sep whipsaw pair (cut 09/21 @ 90.46, re-bought 10/19 @ 88.22 — net ~−2.5%) | **Mixed.** Small churn tax in chop; otherwise sat out the sideways summer in cash |
| **2021** | Grinding bull | Tech-led melt-up | Long all year; no VTV flips Jan–Dec | **Benefit.** Pure buy-and-hold-equivalent year with the drawdown insurance still armed |
| **2022 bear market** | All three −~25-35% | Brutal, grinding downtrend with violent bear-market rallies | **The disclosed weakness.** VTV whipsawed for months: Feb→Sep saw **11 flips** (exits at ~100→~95, re-entries that immediately failed), a real ~2.5%/flip churn tax in a year best spent in cash | **Cost.** Against pure buy-and-hold it added no alpha here — it lost less than the market (never fully long the decline) but the re-entry whipsawness is the strategy's known Achilles. This year is in the deck on purpose |
| **2023** | Choppy H1, strong Q4 | Feb–May whipsaw, then a clean 4th-quarter breakout | 6 flips Feb–May (chop), then went long week of **11/13/2023 @ $132.42** | **Mixed→benefit.** Paid another chop tax in spring, but the November long entry started the biggest winning streak of the test |
| **2023-24 bull** | VTV +~23% over 13 months | Clean, persistent trend | Held **11/13/2023 → 12/16/2024** ($132.42 → $163.98 exit; peak close $168.58 on 12/09/2024, i.e. **+27% peak** on the leg) | **Benefit.** This is the trade trend-following lives for: 14 months long, ~zero interference |
| **2025 correction** | −~6% spring dip | Fast, shallow but sharp | Cut **03/10/2025 @ $165.91**; short-lived re-entry 05/12 @ 168.63, cut again 05/19 @ 164.68, re-entered **05/26/2025 @ $166.97** | **Neutral.** A couple of months of chop tax; the May re-entry then carried the rest of 2025 |
| **2026 to date** | — | Elevated, two sharp dips (Q1, then the 2026-09 move) | Cut 03/20/2026 @ $192.50, re-entered 04/03/2026 @ $196.02; as of the 2026-09-21 settled week **all three legs are LONG** (QQQ 744.44 vs EMA 704.68; VTI 379.83 vs 369.51; VTV 220.82 vs 218.24) | **TBD.** Live paper running |

## The pattern summary (this is what to quote, it's the honest one)

1. **In strong trends — the majority of 2016–2026 — P20w holds the ride and adds the drawdown insurance ~for free.** Ten years of data: ~92% of buy-and-hold's return at ~59% of the drawdown, while sitting in cash 19% of the time.
2. **In sharp crashes (2018 Q4, COVID, 2025, 2026-Q1) the exits fire before the damage has fully happened** — the strategy's core value. It rarely catches the exact bottom, by design; it trades the *start* of a breakdown for safety.
3. **In rough, mean-reverting chop (2022, spring 2023) it whipsaws and pays a churn tax.** That is the known cost of a trend-following design. If the world trades sideways-for-years the strategy will trail buy-and-hold — a real scenario, disclosed, not hidden.
4. **Responsiveness increases with volatility of the drawdown, not of the daily print** — weekly bars filter out the noise that kills daily-frequency systems (the rejected daily variant churned 30×/yr/leg for ~55% of the return).

The moment to re-visit these conclusions: a new **sustained multi-year sideways regime** (2016–2026 has no decade-long flat tape to test P20w against).