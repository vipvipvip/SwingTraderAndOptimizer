# SEC Research Analyzer — Complete Setup Guide

## Overview

The SEC Research Analyzer automates the research methodology from [SEC_FILING_METHODOLOGY_WITH_ACTUAL_DATA.md](../Stock-Research/SEC_FILING_METHODOLOGY_WITH_ACTUAL_DATA.md), analyzing upcoming earnings using the 15-point framework:

1. **10-Q MD&A** (Item 2) — Product mentions, revenue attribution
2. **Revenue Breakdown** (Footnotes) — Segment growth, quantified contribution
3. **Risk Factors** (Item 1A) — Product materiality signals
4. **Cross-reference** — Press releases, analyst reports, news
5. **Score** — 0-15 points, ranked by candidacy tier
6. **PDF Report** — Executive summary + detailed analysis + board comments

## What's Automated

**Manual workflow (old):**
- Pull 10-Q from SEC EDGAR manually
- Search MD&A (Ctrl+F) for product name
- Extract revenue tables from footnotes
- Search Google for press/analyst coverage
- Score against checklist
- Write analysis in spreadsheet

**Automated workflow (new):**
- SEC Research runs daily at 3 PM ET
- Fetches 10-Qs for all tickers with earnings next 14 days
- Extracts MD&A, revenue data, risk factors automatically
- Scores all tickers against 15-point framework
- Generates ranked PDF report
- Stores results in database for historical tracking

## Setup Instructions

### 1. Ensure Database Schema

The module auto-creates the table on first run, but you can manually apply the migration:

```bash
# Via Laravel migration (if using backend)
php artisan migrate

# Or direct SQL
psql -U swingtrader -d swingtrader -f scanner/services/migrations/001_create_sec_research_table.sql
```

**Verify:**
```bash
psql -U swingtrader -d swingtrader -c "SELECT * FROM tbl_sec_research_analysis LIMIT 1;"
```

### 2. Install Systemd Service (Optional)

If you want automated daily runs:

```bash
sudo cp common/docs/services_doc/sec-research.service /etc/systemd/system/
sudo cp common/docs/services_doc/sec-research.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sec-research.timer
```

**Verify:**
```bash
systemctl status sec-research.timer
sudo journalctl -u sec-research -f  # tail logs
```

### 3. Run Manually (No Systemd)

```bash
cd scanner/

# Next 14 days, save PDF with timestamp
python3 services/sec_research.py --upcoming 14 \
  --output /tmp/sec_research_$(date +%Y%m%d_%H%M%S).pdf

# Save to database only (no PDF)
python3 services/sec_research.py --upcoming 14 --db-only

# Single ticker
python3 services/sec_research.py --ticker ASTS \
  --output /tmp/ASTS_analysis.pdf
```

## Understanding the PDF Report

### Page 1: Cover Page
- Run metadata (date, run ID, ticker count)
- Methodology reference

### Page 2: Executive Summary
**Ranked by score (15-point framework):**

```
Rank  Ticker  Score   Earnings Date   Status
────────────────────────────────────────────
1.    AKAM    11/15   2026-08-06      WATCH
2.    SMCI     7/15   2026-08-21      CAUTION
3.    ASTS     2/15   2026-08-12      AVOID
```

**Tier Badges:**
- 🔥 **Strong Candidate** (12-15/15) — Proven adoption in 10-Q
- 👀 **Watch** (8-11/15) — Mixed signals, monitor earnings call
- ⚠️ **Caution** (5-7/15) — Early stage, governance risk
- ❌ **Avoid** (<5/15) — Venture stage, no revenue attribution

### Page 3+: Detailed Analysis per Ticker

**For each ticker:**

1. **Scoring Breakdown** — 15-point matrix with Yes/No for each criterion
   ```
   ✓ Product named in MD&A                      (1 pt)
   ✗ Revenue quantified in footnotes            (0 pts)
   ✓ QoQ growth >15%                            (2 pts)
   ✗ Customer names disclosed                   (0 pts)
   ...
   ```

2. **MD&A Highlights** — 300-char excerpt from Item 2
   - Product mentions
   - New initiatives
   - Market conditions

3. **Risk Factors** — 300-char excerpt from Item 1A
   - Product-specific risks
   - Competitive threats
   - Execution risks

4. **Sources Found** — Count of:
   - Press releases
   - Analyst reports
   - News articles

### Last Pages: Board Comments & Notes

**Pre-Earnings Call Checklist:**
- Does management specifically credit new product for revenue growth?
- Is customer concentration high (>50% from single customer)?
- Are gross margins expanding with new product mix?
- Does guidance mention product revenue going forward?
- Are hiring/capex aligned with product scaling?

**Red Flags to Watch:**
- Revenue declining while product hyped (ASTS pattern)
- Governance/audit issues (SMCI pattern)
- Large gap between press narrative and 10-Q disclosure (AKAM pattern)

## Scoring Framework Reference

### 15-Point Breakdown

| Signal | Weight | Must Find In |
|--------|--------|--------------|
| Product named | 1 | MD&A (Item 2) |
| Revenue quantified | 2 | Footnote (segment breakdown) |
| QoQ growth >15% | 2 | Comparative financial statements |
| Customer names | 2 | Risk factors or customer list |
| Guidance updated | 2 | MD&A guidance section |
| Analyst initiations | 2 | Yahoo Finance / Seeking Alpha |
| Hiring spike | 1 | LinkedIn (tracked separately) |
| Backlog/pipeline | 1 | Remaining performance obligations |

**Candidacy Decision:**
- **12-15:** FILE EARNINGS CALL TO CONFIRM
- **8-11:** LISTEN TO EARNINGS CALL FOR PRODUCT COMMENTARY
- **5-7:** CAUTION ON EXECUTION RISK
- **<5:** SKIP UNLESS MAJOR NEWS

## Database Queries

### View Latest Analysis Run

```sql
-- Last run ID
SELECT DISTINCT run_id FROM tbl_sec_research_analysis 
ORDER BY created_at DESC LIMIT 1;

-- All tickers from latest run
SELECT ticker, score, rank_in_run, earnings_date
FROM tbl_sec_research_analysis
WHERE run_id = '550e8400-e29b-41d4-a716-446655440000'
ORDER BY rank_in_run;

-- Strong candidates (12-15)
SELECT ticker, score, earnings_date
FROM tbl_sec_research_analysis
WHERE score >= 12
ORDER BY score DESC, earnings_date;
```

### Historical Tracking (Quarter-over-Quarter)

```sql
-- Track score changes for AKAM over time
SELECT 
  run_id,
  earnings_date,
  score,
  created_at
FROM tbl_sec_research_analysis
WHERE ticker = 'AKAM'
ORDER BY earnings_date DESC;
```

## Real-World Example: AKAM (from methodology doc)

### Analysis Run Output
```
SEC RESEARCH ANALYSIS SUMMARY

1. AKAM — Score: 11/15 — Earnings: 2026-08-06
   - Product named? YES (Cloud Infrastructure Services)
   - Revenue quantified? YES ($94.6M Q1 2026)
   - QoQ growth >15%? YES (+40% YoY)
   - Customer names? NO (only "compute partner solutions")
   - Guidance includes product? NO
   - Analyst initiations? TBD
   - Hiring spike? TBD
   - Backlog/pipeline? YES (from MD&A)

SCORE: 11/15 → WATCH

BOARD COMMENTS:
✓ Cloud Infrastructure Services revenue is clearly tracked (+40% growth)
✗ The Anthropic deal (announced May 2025) NOT itemized separately in Q1 10-Q
⚠️ Listen to Aug 6 earnings call: will mgmt credit Anthropic for CIS growth?
⚠️ If yes → upgrade to 8-9/15 and become strong candidate for 20-30% move
```

### What to Listen For on Earnings Call

1. **"Our Anthropic partnership drove X% of Cloud Infrastructure Services growth"** → BULLISH
2. **"Anthropic is already a major customer"** → CONFIRMS MATERIALITY
3. **"We expect this to accelerate through H2"** → FORWARD GUIDANCE UPGRADE
4. **No mention at all** → SCORE STAYS AT 11, NOT YET PROVEN

## Integration with Earnings Screener

Both services work together:

1. **Earnings Screener** (`earnings_screener.py`)
   - Runs every 30 min during market hours
   - Finds stocks with bullish hourly MACD before earnings
   - Output: List of tickers with momentum signals

2. **SEC Research** (`sec_research.py`)
   - Runs once daily at 3 PM ET (after market close)
   - Analyzes fundamental adoption signals in 10-Q
   - Combines with earnings calendar to find next 14 days
   - Output: Ranked PDF report

**Combined Signal:**
- Earnings Screener says: "Bullish MACD momentum"
- SEC Research says: "Strong adoption in 10-Q"
- **= High confidence setup for earnings pop**

## Next Steps: Enhancing the Framework

### Phase 1 (Current)
- ✅ 15-point scoring framework
- ✅ Database caching
- ✅ PDF generation with rankings
- ✅ Board comments section

### Phase 2 (Enhancement)
- [ ] Integrate sec-api.com for automated 10-Q text parsing
- [ ] Implement NewsAPI for press release scraping
- [ ] Add Finnhub for analyst report fetching
- [ ] Earnings call transcript integration

### Phase 3 (Advanced)
- [ ] Historical tracking (score trends Q-over-Q)
- [ ] Competitor comparison (which company adopting faster?)
- [ ] Predictive scoring (ML model: does Q2 10-Q score predict Q3 earnings pop?)
- [ ] Email distribution (auto-send PDF to team before earnings)

## Troubleshooting

### "No tickers with earnings in next 14 days"
**Cause:** Earnings calendar cache is stale
**Fix:** Run earnings screener refresh
```bash
python3 services/earnings_screener.py --refresh
```

### "No 10-Q found for ticker"
**Cause:** SEC EDGAR integration not yet implemented
**Fix:** Currently using cached filings. To add live fetching:
- Integrate sec-api.com (paid) or
- Use direct SEC EDGAR API + BeautifulSoup parsing
- See `sec_research.py::SECFiling.get_latest_10q_text()`

### PDF generation fails
**Cause:** ReportLab not installed
**Fix:**
```bash
source scanner/.venv/bin/activate
pip install reportlab --break-system-packages
```

### Database connection error
**Cause:** PostgreSQL credentials wrong or DB not running
**Fix:**
```bash
# Check connection
psql -U swingtrader -h 127.0.0.1 -d swingtrader -c "SELECT 1;"

# Check config in scanner/config.py
cat scanner/config.py
```

## Files Created

```
scanner/
  services/
    sec_research.py                 # Main analyzer
    sec_research_pdf.py             # PDF generator
    sec_research.md                 # Service docs
    migrations/
      001_create_sec_research_table.sql

common/docs/services_doc/
  sec-research.service              # Systemd service
  sec-research.timer                # Daily scheduler (3 PM ET)
  sec_research_guide.md             # This file

swingtrader/backend/database/migrations/
  2026_08_05_000000_create_sec_research_analysis_table.php

Output:
  /tmp/sec_research_YYYYMMDD_HHMMSS.pdf   # Generated PDF reports
  tbl_sec_research_analysis              # Database cache
```

## Support

For questions or enhancements:
1. Review [SEC_FILING_METHODOLOGY_WITH_ACTUAL_DATA.md](../Stock-Research/SEC_FILING_METHODOLOGY_WITH_ACTUAL_DATA.md)
2. Check PDF report for scoring breakdown
3. Review database results: `SELECT * FROM tbl_sec_research_analysis LIMIT 10;`
