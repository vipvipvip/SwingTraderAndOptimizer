# VSCode Prompt Template - R&D Adoption Framework
## Copy & Paste for Quick Stock Analysis

---

## QUICK ANALYSIS TEMPLATE

**Copy everything below and paste into Claude VSCode extension:**

```
Analyze [STOCK_TICKER] using the R&D Adoption Framework (SEC-filing-first methodology).

Framework scoring (0-15 points):
- 0-3: AVOID
- 4-6: WATCH (early adoption, 3-6 months to inflection)
- 7-10: CANDIDATE (proven adoption, 2-4 months to inflection)
- 11-15: HIGH-PROBABILITY (inflection imminent, 1-3 months to surge)

Scoring checklist (SEC 10-Q ONLY):
- Product named in MD&A? (2 pts)
- Revenue itemized by segment? (2 pts)
- QoQ/YoY growth >15%? (2 pts)
- Customer names disclosed? (2 pts)
- Guidance product-specific? (2 pts)
- Risk factors mention product? (1 pt)
- Backlog/RPO disclosed? (1 pt)
- Supporting metrics visible? (1 pt)
- Profitability/margins? (1 pt)
- Earnings call quantification? (1 pt)

Red flags (subtract):
- Revenue declining while hyped: -2
- Goodwill impairment: -1 to -2
- Margin compression despite growth: -1
- Press claims ≠ 10-Q reality: -2

PRIOR BENCHMARKS (for comparison):
- BDX: Score 6-8/15 (early adoption, Q2 earnings confirmed Pyxis Pro 75% wins)
- ZBRA: Score 12/15 (proven adoption, CF revenue $825M +20.6% YoY, margins stable)
- SMTC: Score 2-3/15 (AVOID: revenue +15.9% but operating income -28%, margin compression)

OUTPUT REQUIRED:
1. Latest 10-Q filing (period & date)
2. Revenue (current Q, prior Q, YoY %)
3. Product/segment revenue breakdown (if visible)
4. Operating margin trend
5. Customer wins disclosed? Which ones?
6. Risk factor keywords
7. Backlog/RPO amount
8. Framework score (0-15)
9. Verdict (AVOID/WATCH/CANDIDATE/HIGH-PROBABILITY)
10. Upside target % over ___ months
11. Next catalyst date
12. Comparison to BDX/ZBRA/SMTC scoring

Do NOT use analyst estimates or press releases. Base entire analysis on SEC 10-Q MD&A, segment tables, and risk factors.
```

---

## STANDALONE (NO CONTEXT) VERSION

**Use this if starting fresh conversation without uploading prior files:**

```
I'm using a 15-point R&D adoption framework for mid-cap stocks ($5B-$50B).

Rules:
1. SEC 10-Q filings are primary evidence (audited, legal consequences)
2. Search MD&A section for product name (must be there to count as material)
3. Extract revenue by segment (footnotes show adoption proof)
4. Calculate YoY growth rates
5. Read risk factors (material adoption = company discloses risk)
6. Check earnings call for management quantification
7. Look for red flags: margin compression, goodwill impairment, cost bloat

Scoring (15 points total):
- Product named in MD&A: 2 pts
- Revenue itemized: 2 pts
- Growth >15%: 2 pts
- Customer names: 2 pts
- Guidance update: 2 pts
- Risk factors: 1 pt
- Backlog: 1 pt
- Operational metrics: 1 pt
- Profitability proof: 1 pt
- Earnings call detail: 1 pt
Red flags: -1 to -2 pts each

Verdict:
0-3 = AVOID
4-6 = WATCH
7-10 = CANDIDATE
11-15 = HIGH-PROBABILITY

Analyze [STOCK] now. Pull latest 10-Q, extract data, score 0-15, give verdict with timeline and upside target.
```

---

## FOR COMPARING TO PRIORS

**Use when you want to compare new stock to BDX/ZBRA/SMTC:**

```
I've previously analyzed three stocks using the R&D Adoption Framework:

**BDX (Becton Dickinson) - Score 6-8/15**
- Products: Pyxis Pro (AI medication dispensing), Incada (AI platform)
- Status: Early adoption confirmed (Q2 earnings Aug 6: 75% competitive wins)
- Q1 10-Q showed: No product revenue yet (launched April)
- Q2 Earnings showed: CEO quantified Pyxis Pro "early customer response strong"
- Upside: +20-30% over 4-5 months (waiting for Q3 inflection confirmation)
- Next catalyst: Q3 earnings (Oct/Nov 2026) - will CF show 8-10%+ growth?

**ZBRA (Zebra Technologies) - Score 12/15**
- Product: Connected Frontline (AI frontline worker platform)
- Status: Adoption PROVEN in 10-Q (CF revenue $825M +20.6% YoY)
- Operating margin: 20.5% maintained (proof of operational leverage)
- Upside: +15-25% over 3-4 months (adoption already visible, no need to wait)
- Next catalyst: Q3 earnings (Oct/Nov 2026) - will CF maintain >18% growth?

**SMTC (Semtech) - Score 2-3/15 - AVOID**
- Revenue +15.9% but operating income -28% (margin destruction)
- Goodwill impairment: $847.9M (prior bets failed)
- No named products (generic data center chips)
- Verdict: Growth masking operational distress (opposite of framework)

Now analyze [NEW STOCK]. Score it 0-15 and compare directly to BDX/ZBRA/SMTC patterns. 
Which one does it most resemble?
```

---

## EARNINGS CALL FOCUSED

**Use when stock just reported earnings:**

```
[STOCK] reported earnings on [DATE]. Prior 10-Q score: [X/15]

Extract from earnings call/press release:
1. Did management mention product by name?
2. What metrics did they quantify? (customer count, revenue contribution, pipeline)
3. Did they raise guidance? (signals confidence in adoption)
4. Did they hire leadership? (organizational commitment)
5. Did they make acquisitions? (strategic bets on platform)
6. What growth rates did they project next quarter?

Then update framework score:
- Did earnings call quantify adoption? +1-2 pts
- Did guidance raise? +1 pt
- Did they name customers? +1 pt
- Does new data support prior 10-Q signals? Confirm or downgrade

Give me:
1. New score (0-15)
2. What changed from prior 10-Q analysis
3. Updated upside target
4. Next catalyst date
5. Comparison to BDX/ZBRA trajectory
```

---

## RED FLAG INVESTIGATION

**Use when something looks suspicious:**

```
Red flags detected in [STOCK]:

From 10-Q:
- Revenue growth: _____
- Operating margin: _____  (vs prior year: _____)
- Goodwill impairment: $_____M
- SG&A expense change: _____
- Share-based compensation: $_____M (vs prior: $_____M)

Using R&D Adoption Framework red flag rules:
1. Is revenue growing but profitability declining? (SMTC pattern = AVOID)
2. Is there major goodwill impairment? (>5% of market cap = major red flag)
3. Is margin compression visible? (means business is deteriorating)
4. Is cost bloat outpacing revenue growth? (inefficiency)
5. Is equity comp spiking? (retention concerns / insider selling?)

Framework guidance: True R&D adoption EXPANDS margins and improves operational efficiency. 
If growth is destroying profitability, it's not real adoption - it's margin destruction.

Analyze the red flags and determine if this is AVOID or still viable.
```

---

## MULTI-STOCK COMPARISON

**Use when analyzing 3+ stocks together:**

```
I'm analyzing [STOCK_A], [STOCK_B], [STOCK_C] using R&D Adoption Framework.

For each, extract:
- Latest 10-Q (date & period)
- Revenue (current & prior year, YoY %)
- Operating margin (current & prior year, trend)
- Product adoption proof (revenue itemized? Customer names?)
- Next earnings catalyst

Then rank by framework score (0-15):
- Highest score = best adoption signal
- Compare margin trends = operational health
- Compare customer traction = market validation
- Identify which will inflect first (3-month timeline)

Output as comparison table:
| Stock | Score | Revenue YoY | Op Margin Trend | Customer Proof | Upside % | Catalyst Date |
|-------|-------|---|---|---|---|---|
| A | __/15 | ___% | ↑/→/↓ | Yes/No | __% | __/2026 |
| B | __/15 | ___% | ↑/→/↓ | Yes/No | __% | __/2026 |
| C | __/15 | ___% | ↑/→/↓ | Yes/No | __% | __/2026 |

Rank them: 1st choice / 2nd choice / 3rd choice (with reasoning)
```

---

## QUICK SCREEN (FAST VERSION)

**For when you just want a fast 5-minute verdict:**

```
Quick screen [STOCK]:

1. Latest 10-Q revenue growth: ___%
2. Latest 10-Q operating margin: __% (vs prior year __%)
3. Product mentioned by name in MD&A? YES / NO
4. Customer names disclosed? YES / NO
5. Goodwill impairment? YES (___M) / NO

Framework fast-track:
- Revenue >15% growth + margins stable/expanding = likely 7+/15 (CANDIDATE+)
- Revenue >15% growth + margins DECLINING = likely 2-3/15 (AVOID)
- No named products + generic market = likely <5/15 (WATCH at best)

Preliminary score: __/15
Preliminary verdict: AVOID / WATCH / CANDIDATE / HIGH-PROBABILITY

Justify in 1-2 sentences why this score.
```

---

## COPY-PASTE READY

All templates above are ready to paste directly into Claude VSCode. Just:

1. **Copy the [template]**
2. **Replace [STOCK] with ticker**
3. **Replace [DATE] with actual date**
4. **Paste into Claude chat**
5. **Claude returns scored analysis**

---

## COMMON FOLLOW-UPS

**After initial score, you might ask:**

```
"BDX scored 6-8/15. When will it become 9-10/15?"

→ Answer: When Q3 earnings shows Connected Care growing 8-10%+ and Incada/Pyxis Pro are itemized in revenue.
Timeline: Oct/Nov 2026 earnings call.
Odds: 60% (if adoption accelerating) vs 40% (if adoption slowing).

"How does [NEW STOCK] compare to ZBRA's trajectory?"

→ If new stock is 8-10/15 like current BDX: It's 3-6 months behind ZBRA's current timing.
If new stock is 11-13/15: It's on ZBRA trajectory NOW and will inflect sooner.

"Should I wait for Q3 earnings or buy BDX now at $170?"

→ Framework says: Adoption is confirmed but inflection not yet visible in 10-Q.
Risk/Reward: +20-30% if Q3 confirms, but could consolidate if Q3 disappoints.
Probability: 60% higher, 40% consolidate.
Decision: Your risk tolerance.
```

---

## SAVE THIS FILE LOCALLY

**Store at:** `/home/dikesh/data/dev/SwingTraderAndOptimizer/R&D_Analysis/01_VSCODE_PROMPT_TEMPLATE.md`

**Use it for:**
- Quick stock screening in VSCode
- Rapid framework application
- Consistent methodology across new analyses
- Zero re-explanation needed in future conversations

---

**End of VSCode Prompt Template**

