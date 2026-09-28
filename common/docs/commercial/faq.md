# FAQ — the objections, answered honestly

> All historical figures are **hypothetical backtests**, not promises. Live trading is paper-only since 2026-09-28. Not investment advice.

**Why not just buy and hold an index fund?**
Buy-and-hold bought and held a 32.6% drawdown in 2016–2026. P20w's equivalent was 19.2% — roughly half — while keeping ~92% of the same return (+364% vs +410%). That's the entire deal: **the same market, a smaller bill**. There is no free lunch: the strategy is worse in sideways chop (see 2022 in the regime matrix), and it spends ~19% of the time in cash, which a pure buy-and-holder never does.

**Why QQQ, VTI and VTV specifically?**
Three broad, liquid ETFs with *different* leadership: growth (QQQ), whole-market beta (VTI), value (VTV). P20w doesn't predict which leads — it just stays long each while its own trend holds. That's nine years of data showing one of them is usually trending while another is flat, which is why the trio historically has held returns up while the drawdown insurance worked.

**How is a decision actually made?**
Once a week. Friday's settled weekly close for each ETF is compared to its own 20-week exponential average:

- close > EMA20 → that leg stays/becomes **long**
- close < EMA20 → that leg **goes to cash**
- whichever legs are long get re-balanced Monday to equal thirds.

No intraday, no market-timing, no gut calls. If you want, you can hand-compute last week's decision for any of the three in ten minutes.

**What is the biggest risk?**
Three honest ones, in order:
1. **Whipsaw in sideways markets.** The 2022 bear whipsawed ~11 times in 8 months and paid a churn tax. If markets mean-revert for years, this strategy trails buy-and-hold.
2. **Gap / overnight risk.** The decision is made on Friday's close but fills Monday. A weekend gap can move a limit away from the Friday close — usually small for these three ETFs, but it's a real, unhedged risk.
3. **Backtest ≠ live.** The 9.4%/19.2% drawdowns are hypothetical, computed under idealized next-day-close fills. Live fills happen during Monday's session and can differ by a few basis points. Nothing in this package is a maximum-loos guaranteed.

**Can it beat the market?**
We do not make that claim, and you should not either. Historically it ends up near buy-and-hold with a much smaller drawdown — that is a factual, disclosed, hypothetical observation. Whether it "beats" any future period depends on the regime. Assume it can lose money in real trading; it has a track record of drawing down ~19% and a failure mode (sustained chop) we print in the literature.

**How much money does it need?**
The logic is proportional — it works on $1,000 or $100,000. Practical note: below ~$10k the fixed-cost economics of 2–3 tiny weekly re-balance orders get relatively worse; and in any account, watch that a $1 minimum-variance rebalance trim isn't more expensive than the drift it removes (the live system already skips sub-$1 trims).

**How does it treat taxes?**
Trading activity is low: ~2–3 small orders per week, most trims. Exits and trims realize gains; holding periods are usually months to over a year. This is far less taxable churn than a daily system, but taxes depend on your jurisdiction and account type (IRA vs taxable). Ask a tax professional — we don't give tax advice.

**Can I verify your claim that this is not a black box?**
Yes, and we want you to. Pick any flip date out of the regime matrix, draw weekly EMA(20) on the ticker, and the date should reconcile to the week. The flip log is machine-generated from settled weekly closes using the identical series the live strategy consumes — the backtest never touches a different data path. If a date disagrees with your feed, report it: it would be a bug, and we'd fix it fast.

**What did you test and throw away?** *(because claiming a strategy without its graveyard is marketing)*
Daily-close crossover (churned, +144% vs +364%), faster spans P5w/P10w and slower P50w (all worse), plus the strategy's own on-this-account predecessors — Variant S and EG100 — both of which were run live then replaced on evidence, not on whims. The published span sweep, start-date sweep, and this FAQ are the "what we hid" insurance: nothing gets cherry-picked after the fact.

**Is this investment advice? Am I being sold a promise?**
No to both. This is a disclosed methodology we run on a paper account, presented as an informational tool. It is not tailored to your goals, not a fiduciary opinion on your portfolio, and every historical number is hypothetical. The moment anyone (including us) phrases any of this as "you will make," "guaranteed," or "can't lose more than N%" — it is misrepresentation and should be ignored. See `disclosure.md`.

**What do you actually want (fine print of the offer)?**
Depending on channel: the tool/methodology itself, the live paper track record, or an educational walkthrough of how it works — all informational. Nothing here is an offer to buy or sell securities, and nothing here is personalized advice. Refer serious "invest for me" interest to a licensed investment adviser.