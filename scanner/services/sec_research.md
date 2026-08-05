# SEC-Filing Research Analyzer

Automated research tool that analyzes upcoming earnings against SEC filings (10-Q/10-K), press releases, analyst reports, and news. Generates comprehensive PDF reports ranked by 15-point SEC-filing-first framework.

## Strategy

**Tier 1 Source Priority:** 10-Q MD&A (mandatory disclosure, audited, hardest to fake)
**Tier 2 Verification:** Press releases, analyst reports, earnings call transcripts
**Tier 3 Red Flags:** Governance issues, revenue misses, audit changes

## Scoring Framework (15 points max)

| Signal | Weight | 10-Q Location | Must Pass |
|--------|--------|---------------|-----------|
| Product named in MD&A | 1 | Item 2 | Yes |
| Revenue quantified | 2 | Footnote (segment breakdown) | Yes |
| QoQ growth >15% | 2 | Comparative statement | No |
| New customer names | 2 | Risk factors, disclosures | No |
| Guidance includes product | 2 | MD&A guidance section | No |
| Analyst initiations recent | 2 | Yahoo Finance / Seeking Alpha | No |
| Job hiring spike | 1 | LinkedIn | No |
| Backlog/pipeline evidence | 1 | Remaining performance obligations | No |

**Candidacy Tiers:**
- **12-15/15:** Strong Candidate (proven adoption in 10-Q)
- **8-11/15:** Watch (mixed signals, monitor earnings call)
- **5-7/15:** Caution (early stage, governance risk)
- **<5/15:** Avoid (venture stage, no revenue attribution)

## Usage

```bash
# Analyze next 14 days of upcoming earnings
python3 services/sec_research.py --upcoming 14

# Save to specific PDF path
python3 services/sec_research.py --upcoming 14 --output /tmp/analysis.pdf

# Analyze single ticker
python3 services/sec_research.py --ticker ASTS

# Save to database only (no PDF)
python3 services/sec_research.py --upcoming 14 --db-only
```

## PDF Report Structure

1. **Cover Page** — Run metadata, methodology reference
2. **Executive Summary** — Ranked candidates with tier badges (Strong / Watch / Caution / Avoid)
3. **Detailed Analysis per Ticker**
   - Score breakdown (15-point matrix)
   - MD&A highlights (Item 2)
   - Risk factors (Item 1A)
   - Sources found (press releases, analyst reports, news count)
4. **Board Comments & Notes** — Earnings call validation checklist, red flags to monitor
5. **Methodology Reference** — Framework explanation, Tier 1/2/3 definitions

## Database Storage

**Table: `tbl_sec_research_analysis`**

```sql
- run_id (UUID) — groups tickers from same analysis run
- ticker (VARCHAR)
- earnings_date (DATE)
- filing_date (DATE)
- score (INTEGER 0-15)
- rank_in_run (INTEGER)
- analysis_data (JSONB) — full analysis, MD&A, risk factors, sources
- board_comments (TEXT)
- sources (JSONB) — press count, analyst count, news count
- created_at, updated_at
```

## Systemd Service

| Service | Timer | Schedule |
|---------|-------|----------|
| sec-research | sec-research.timer | Daily at 3:00 PM ET |

### Installation

```bash
sudo cp common/docs/services_doc/sec-research.service /etc/systemd/system/
sudo cp common/docs/services_doc/sec-research.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sec-research.timer
```

### Run manually

```bash
sudo systemctl start sec-research.service
sudo journalctl -u sec-research -f
```

## Output Example

**PDF Summary Page:**
```
SEC-Filing Research Analysis
Earnings Event Analysis

Report Date: August 5, 2026
Run ID: 550e8400-e29b-41d4-a716-446655440000
Tickers Analyzed: 12

EXECUTIVE SUMMARY: CANDIDATE RANKINGS

Rank  Ticker  Score   Earnings Date   Status
──────────────────────────────────────────────
1.    AKAM    11/15   2026-08-06      WATCH
2.    SMCI     7/15   2026-08-21      CAUTION
3.    ASTS     2/15   2026-08-12      AVOID

KEY FINDINGS BY SCORE TIER

🔥 Strong Candidates (Score ≥ 12/15)
   (none in this run)

👀 Watch (Score 8-11/15)
   AKAM (11/15) — 2026-08-06

⚠️ Caution (Score 5-7/15)
   SMCI (7/15) — 2026-08-21

❌ Avoid (Score < 5/15)
   ASTS (2/15) — 2026-08-12
```

## Integration with Earnings Calendar

Automatically pulls upcoming earnings dates from `tbl_earnings_calendar` (maintained by `earnings_screener.py`).

### Workflow

1. Earnings screener caches upcoming earnings every Sunday
2. SEC research runs daily at 3 PM ET
3. Fetches latest 10-Q for each ticker with earnings in next 14 days
4. Extracts MD&A, revenue data, risk factors
5. Searches web for press, analyst reports, news
6. Scores against 15-point framework
7. Generates PDF + stores results in DB
8. Ready for review before earnings call

## Files

- `scanner/services/sec_research.py` — Main analysis engine
- `scanner/services/sec_research_pdf.py` — PDF report generation
- `scanner/services/sec_research.md` — This file
- `common/docs/services_doc/sec_research.md` — User-facing docs
- `common/docs/services_doc/sec-research.service` — Systemd service
- `common/docs/services_doc/sec-research.timer` — Daily scheduler
- `tbl_sec_research_analysis` — Database cache table

## Key Decisions

### Why 10-Q First?
- **Audited or reviewed** — misrepresentations have legal consequences
- **MD&A is mandatory** — required disclosure, hardest to fake
- **Segment revenue visible** — shows if new products actually contribute
- **Risk factors paradox** — if product in risks but NOT in revenue → adoption is future, not current

### Why Board Comments Section?
- Earnings calls often reveal real adoption momentum faster than filings lag
- Checklist helps listeners spot product revenue attribution in real-time
- Red flags (governance, audit changes) are often buried in Item 1A

### Why PDF Over Web Dashboard?
- Portable, shareable, can be reviewed on earnings-call calls
- Ranked summary forces prioritization (not everything is a candidate)
- Offline-ready (no dependency on live services during trading hours)

## Future Enhancements

- [ ] Integrate sec-api.com for automated 10-Q text parsing
- [ ] Add earnings call transcript fetching (Seeking Alpha, IR sites)
- [ ] Implement NewsAPI / Finnhub for automated press/analyst scraping
- [ ] Add competitor comparison (is this company's adoption faster than peers?)
- [ ] PDF email distribution (auto-send to watchlist subscribers)
- [ ] Historical tracking (compare Q4 scoring vs Q1 to see momentum)
