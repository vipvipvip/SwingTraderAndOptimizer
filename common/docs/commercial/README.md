# Commercial — Retail Marketing Package (P20w)

Retail/social-facing collateral for **CoreEW-LegEMA (variant P20w)**, built to survive a FINRA-style communications review: every performance figure is labeled **hypothetical**, risks get equal space, and there are no guarantees anywhere.

> **Status:** v0.1 draft — generated 2026-09-28. Numbers are canonical as of this date. Live paper record on Alpaca (paper) since 2026-09-28; this package is a snapshot and must be refreshed on any strategy change or major regime event.
>
> **Not investment advice. Hypothetical performance is not a promise of future results.**

## File map

| File | Purpose | When the reader needs it |
|---|---|---|
| `one_pager.md` | Plain-English explanation of the strategy (the rules, the rhythm, why weekly, what to verify) | First touch — friends, family, social clips, landing page top |
| `performance.md` | Indicator tables with honest framing (full period, recent, start-date sweeps, what was rejected) | Anyone who asks "how does it do?" |
| `regime_matrix.md` | How P20w behaved across market conditions (2016→2026) with verifiable flip dates/prices | Doubters — this turns claims into checkable evidence |
| `faq.md` | Objections and honest answers (whipsaw, taxes, gaps, "can it beat the market?") | Q&A, DM replies, live Q&A prep |
| `disclosure.md` | Compliance spine: hypothetical method, limitations, no-advice / no-guarantee statement | Every distribution of the other files must carry a link or footer to this |

## The six red lines this package self-audits against

These are the rules a compliance reviewer (and an honest customer) will hold us to:

1. **Fair and balanced.** Every weakness we know about is written down in the same places the strengths are (2022 whipsaw lives in `performance.md` and `regime_matrix.md`, not just in an appendix).
2. **Every number labeled hypothetical.** Any page showing a return/drawdown carries the "hypothetical, not a promise" marker on the same frame.
3. **No guarantees, ever.** No "you will make", "can't lose more than N%", "beats the market". MaxDD figures are historical worst-cases, not limits.
4. **No cherry-picking.** Full period + start-date sweeps + span sweeps are all shown, so nobody can accuse us of picking the pretty window (we show the ugly ones ourselves).
5. **No testimonials / social proof** until there is a real, disclosable record. "My uncle made money" is a FINRA testimonial trap — do not quote members, friends, or family.
6. **Configured people protection.** The product is presented as a *tool with a disclosed methodology*, not investment advice — helps conversational channel legality, but get a lawyer's review before *any* paid distribution.

## Provenance — where the numbers come from (reproducible)

All figures derive from the **canonical shared signal** (the same PHP series the live strategy executes), not from re-implementations:

- Signal: `php artisan trades:coreew-leg-ema-series --span=20` (settled weekly bars, dates labeled by the Monday starting the week; close = that week's Friday settle; decision acted the following Monday)
- Backtest: `python3 backtest_trio_ew.py --leg-ema 20` and `--start ...` variants (fills at next-day close, 0.05% one-way cost, weekly EW trim among ON legs)
- Flip log: parsed from the above series (per-leg LONG/CASH transitions)

To refresh: re-run those two commands after the DB settles new weeks, update the tables, bump the "as of" date, and re-check the red lines above.

## Deliverable order for friends & family rollout

1. `one_pager.md` (read it with them, invite a chart check of any flip date)
2. `regime_matrix.md` if they want the history
3. `performance.md` only after they ask (lead with the mechanism, not the scoreboard)
4. `disclosure.md` footer on everything you forward