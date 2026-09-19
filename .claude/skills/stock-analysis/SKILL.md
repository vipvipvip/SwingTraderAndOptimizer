---
name: stock-analysis
description: Use whenever the user asks to analyze a stock, score a ticker against "my/the framework", or asks "is TICKER a buy?" (e.g. "analyze ESTC", "score PAYX against my framework", "is CBRS a buy?", "what's the adoption score for X?"). Applies the user's 15-point R&D Adoption Framework for mid-cap ($5-50B) stocks in an early product-adoption cycle, backed by scanner/services/rnd_adoption_analyzer.py and scanner/services/sec_edgar.py in this repo.
---

# Stock Analysis Skill — R&D Adoption Framework

**Core thesis:** mid-cap stocks ($5B-$50B) 3-6 months into a new product launch offer a 4-5 month window for 20-35% returns before the broader market prices in the adoption story.

**Don't force-fit this framework onto:** mega-caps (>$50B, one product can't move the needle), pre-revenue biotech, or a stock already up 50%+ on the thesis (edge already expired — score it anyway if asked, but say so explicitly).

## How to run this in this repo

1. **Fetch the latest filing text** (10-K or 10-Q, whichever is more recent):
   ```python
   # from scanner/, using scanner/.venv
   from services.sec_edgar import SECEdgarFetcher
   f = SECEdgarFetcher("TICKER")
   text = f.fetch_10q_text()
   print(f.source)  # confirms real filing vs "yfinance (synthetic fallback ⚠️)"
   ```
   - If `f.source` comes back as the yfinance synthetic fallback, the ticker's CIK is missing from `scanner/services/sec_cik_database.py`. Look it up at `https://www.sec.gov/files/company_tickers.json` (works with a declared User-Agent, e.g. `"SwingTraderResearch <email>"`) and add it — one line, zero-padded to 10 digits.
   - `SECEdgarFetcher.get_latest_filing_via_submissions_api()` (added 2026-09-17) is the reliable path — it uses `data.sec.gov/submissions/CIK{cik}.json`, which SEC's legacy `cgi-bin/browse-edgar` scraping no longer serves reliably to scripts (403/503). Don't reintroduce browser-UA-spoofing for that legacy endpoint — SEC's own policy wants a declared identity UA, not a spoofed browser one.

2. **Run the scorer:**
   ```bash
   scanner/.venv/bin/python3 scanner/services/rnd_adoption_analyzer.py --ticker TICKER --filing /path/to/filing.txt
   ```

3. **Sanity-check the output before trusting it** — the scorer is keyword-matching, not semantic:
   - `growth_strong` fires if the words "growth"/"increase"/"accelerat" appear *anywhere* in the filing — even if that's one segment growing while total company revenue is falling. **Always manually confirm the actual total-revenue YoY trend** (search the filing for the summary revenue table, e.g. `grep -n "Net revenues were\|Revenue" `) before accepting a high subtotal at face value.
   - Red flags (`revenue_declining`, `goodwill_impairment`, `press_gap`) fire on bare keyword presence too — e.g. routine "we test goodwill for impairment annually, none occurred" boilerplate will trip `goodwill_impairment` even with zero actual impairment. Grep the surrounding context for each triggered red flag before deducting it in your written verdict.
   - `revenue_declining` deserves the most trust of the three — cross-check it against the actual revenue table regardless.

4. **Cross-check technicals from this repo's own scanner DB** (`tbl_scanner_tickers_daily`, keyed by `ticker_id` from `tbl_stock_tickers`) — price trend, MACD/PPO crossover state, and `atr_stop` — before calling something a "buy" on fundamentals alone. This is a swing-trading project; entry timing matters as much as the adoption score.

## 15-point scoring criteria (must match `rnd_adoption_analyzer.py::SCORING_CRITERIA`)

| Criterion | Max pts | What it looks for |
|---|---|---|
| Product named in MD&A | 2 | Specific product name, not just "our products" |
| Revenue itemized by product/segment | 2 | Segment breakdown or footnote |
| QoQ/YoY growth >15% | 2 | Real, company-wide, not one segment |
| Customer names disclosed | 2 | Named customers, concentration cohorts |
| Guidance is product-specific | 2 | Product named in forward guidance, not just press release |
| Risk factors mention the product | 1 | Material enough to appear in Item 1A |
| Backlog/RPO disclosed | 1 | RPO, cRPO, or backlog growth |
| Supporting operational metrics | 1 | Hiring, capacity expansion, partnerships |
| Profitability proof | 1 | Margins stable/expanding despite growth (not cost-cutting) |
| Earnings call quantification | 1 | Management gives specific adoption numbers |

**Red flags (subtract):** revenue declining while product hyped (-2) · goodwill impairment >2% of market cap (-2) · margin compression despite growth (-1) · press-release claims not found in the filing (-2).

## Verdict bands

| Score | Verdict | Timeline | Expected return |
|---|---|---|---|
| 0-3 | AVOID | N/A | -15 to -25% |
| 4-6 | WATCH | 3-6 months | 0-10% |
| 7-10 | CANDIDATE | 2-4 months | 15-35% |
| 11-15 | HIGH-PROBABILITY | 1-3 months | 20-40%+ |

## Benchmarks (from prior analyses, for comparison)

- **BDX** — 6-8/15, CANDIDATE. Pyxis Pro / Incada AI platforms; 75% competitive win rate, CEO quantified adoption.
- **ZBRA** — 12/15, HIGH-PROBABILITY. Connected Frontline; segment revenue $825M +20.6% YoY, margins stable at 20.5%.
- **SMTC** — 2-3/15, AVOID. Revenue +15.9% but operating income -28%, $847.9M goodwill impairment — growth claims not supported by the 10-Q.

## Output format

Give: score breakdown (which criteria hit/missed, with the actual evidence quoted), red flags after context-checking, final score and verdict, how this compares to the benchmarks above, then a technical-entry note from the scanner DB, and a plain-English bottom line on whether it's a buy *right now* vs. worth watching.
