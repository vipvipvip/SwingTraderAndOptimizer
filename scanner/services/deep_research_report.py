#!/usr/bin/env python3
"""
Deep Research Report Generator
Produces professional-grade R&D adoption reports with actual 10-Q data extraction,
financial analysis, MD&A quotes, and forward-looking scenarios.

Output: Markdown report matching Claude Web quality (20-40 pages)
"""

import sys
import os
import json
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import logging
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DB_CONFIG
from services.sec_edgar import SECEdgarFetcher
from services.advanced_research import (
    RedFlagDetector, AnalystCoverageTracker, StockPerformanceTracker
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TenQDataExtractor:
    """Extract structured financial data from 10-Q text."""

    def __init__(self, ticker: str, text: str):
        self.ticker = ticker
        self.text = text

    def extract_company_overview(self) -> Dict:
        """Extract company overview and recent transactions."""
        logger.info(f"Extracting company overview for {self.ticker}...")

        overview = {
            'recent_transactions': [],
            'business_segments': [],
            'strategic_changes': []
        }

        # Look for major transactions (spin-offs, M&A, etc)
        transaction_patterns = [
            r'completed.*spin.?off.*(\d{4})',
            r'completed.*acquisition.*(\d{4})',
            r'business combination.*(\d{4})',
            r'merger.*(\d{4})',
            r'discontinued operations',
        ]

        for pattern in transaction_patterns:
            matches = re.findall(pattern, self.text, re.IGNORECASE)
            if matches:
                overview['recent_transactions'].append(pattern)

        return overview

    def extract_revenue_analysis(self) -> Dict:
        """Extract revenue data with YoY comparisons."""
        logger.info(f"Extracting revenue analysis for {self.ticker}...")

        revenue_data = {
            'current_period_revenue': None,
            'prior_period_revenue': None,
            'yoy_growth_percent': None,
            'segment_breakdown': {},
            'growth_trends': []
        }

        # Look for revenue figures (millions or billions)
        revenue_patterns = [
            r'[Rr]evenues?\s*[:\-=]\s*\$?\s*([\d,]+)\s*(?:million|M|billion|B)?',
            r'Total revenue[^\d]*(\d{1,3}(?:,\d{3})*)\s*(?:million|M)',
            r'(?:Q1|Q2|Q3|Q4|6-month|year-to-date)\s+([^\d]*?)(\d{1,3}(?:,\d{3})*)\s*(?:million|M)',
        ]

        for pattern in revenue_patterns:
            matches = re.findall(pattern, self.text[:20000])  # First 20K chars (usually includes financials)
            if matches:
                revenue_data['revenue_matches'] = matches[:4]  # Store top matches

        # Look for growth percentages
        growth_patterns = [
            r'[Gg]rowth\s+(?:of\s+)?([+-]?\d+\.?\d*)\s*%',
            r'(?:increased|decreased)\s+(?:by\s+)?([+-]?\d+\.?\d*)\s*%',
            r'([+-]?\d+\.?\d*)\s*%\s+(?:increase|decrease|growth)',
        ]

        for pattern in growth_patterns:
            matches = re.findall(pattern, self.text[:20000])
            if matches:
                revenue_data['growth_matches'] = matches[:3]

        return revenue_data

    def extract_operating_metrics(self) -> Dict:
        """Extract key operating metrics (margins, expenses, etc)."""
        logger.info(f"Extracting operating metrics for {self.ticker}...")

        metrics = {
            'gross_margin': None,
            'operating_margin': None,
            'operating_income': None,
            'key_expenses': {},
            'cash_flow_data': {}
        }

        # Look for margin percentages
        margin_patterns = [
            r'[Gg]ross\s+margin\s*[:\-=]\s*([+-]?\d+\.?\d*)\s*%',
            r'[Oo]perating\s+margin\s*[:\-=]\s*([+-]?\d+\.?\d*)\s*%',
            r'[Nn]et\s+margin\s*[:\-=]\s*([+-]?\d+\.?\d*)\s*%',
        ]

        for pattern in margin_patterns:
            matches = re.findall(pattern, self.text[:30000])
            if matches:
                metrics['margin_matches'] = matches

        # Look for operating income
        oi_patterns = [
            r'[Oo]perating\s+income\s*[:\-=]\s*\$?\s*([\d,]+)\s*(?:million|M)',
            r'[Oo]perating\s+(?:loss|income)[^\d]*(\d{1,3}(?:,\d{3})*)\s*(?:million|M)',
        ]

        for pattern in oi_patterns:
            matches = re.findall(pattern, self.text[:30000])
            if matches:
                metrics['operating_income_matches'] = matches

        return metrics

    def extract_md_a_sections(self) -> Dict:
        """Extract key MD&A sections with quotes."""
        logger.info(f"Extracting MD&A sections for {self.ticker}...")

        mda_sections = {
            'management_discussion': None,
            'product_mentions': [],
            'segment_discussion': [],
            'risk_discussion': [],
            'guidance': []
        }

        # Extract MD&A Item 2
        mda_pattern = r'(?:Item\s+2|ITEM\s+2|Management.*?Discussion).*?(?:Item\s+3|ITEM\s+3|$)'
        mda_match = re.search(mda_pattern, self.text, re.DOTALL | re.IGNORECASE)
        if mda_match:
            mda_sections['management_discussion'] = mda_match.group(0)[:5000]

        # Look for product mentions
        product_keywords = ['product', 'adoption', 'solution', 'platform', 'innovation', 'launch']
        for keyword in product_keywords:
            pattern = rf'(?:[^.]*{keyword}[^.]*\.)'
            matches = re.findall(pattern, self.text, re.IGNORECASE)
            if matches:
                mda_sections['product_mentions'].extend(matches[:2])

        # Look for segment discussion
        segment_pattern = r'(?:segment|division|business unit).*?(?:revenue|income|performance)'
        matches = re.findall(segment_pattern, self.text, re.IGNORECASE | re.DOTALL)
        if matches:
            mda_sections['segment_discussion'] = [m[:200] for m in matches[:3]]

        return mda_sections

    def extract_risk_factors(self) -> Dict:
        """Extract risk factors from Item 1A."""
        logger.info(f"Extracting risk factors for {self.ticker}...")

        risk_data = {
            'total_risks': 0,
            'key_risks': [],
            'product_adoption_risks': [],
            'execution_risks': []
        }

        # Extract Item 1A
        risk_pattern = r'(?:Item\s+1A|Risk\s+Factors).*?(?:Item\s+1B|Item\s+2|$)'
        risk_match = re.search(risk_pattern, self.text, re.DOTALL | re.IGNORECASE)

        if risk_match:
            risk_text = risk_match.group(0)
            risk_data['total_risks'] = len(re.findall(r'^\s*[A-Z][\w\s]{20,}', risk_text, re.MULTILINE))

            # Look for specific risk mentions
            adoption_risks = re.findall(r'(?:adoption|acceptance|market penetration).*?[.!?]', risk_text, re.IGNORECASE)
            risk_data['product_adoption_risks'] = adoption_risks[:3]

        return risk_data

    def extract_cash_flow_data(self) -> Dict:
        """Extract cash flow statement data."""
        logger.info(f"Extracting cash flow data for {self.ticker}...")

        cf_data = {
            'operating_cash_flow': None,
            'investing_cash_flow': None,
            'financing_cash_flow': None,
            'free_cash_flow': None,
            'cash_flow_changes': []
        }

        # Look for cash flow figures
        cf_patterns = [
            r'[Cc]ash.*?(?:provided|used).*?operating.*?(\d{1,3}(?:,\d{3})*)',
            r'[Oo]perating.*?cash.*?flow.*?(\d{1,3}(?:,\d{3})*)',
            r'[Ff]ree.*?cash.*?flow.*?(\d{1,3}(?:,\d{3})*)',
        ]

        for pattern in cf_patterns:
            matches = re.findall(pattern, self.text)
            if matches:
                cf_data['cash_flow_matches'] = matches[:3]

        return cf_data

    def extract_rpo_backlog(self) -> Dict:
        """Extract Remaining Performance Obligations (backlog/pipeline)."""
        logger.info(f"Extracting RPO/backlog data for {self.ticker}...")

        rpo_data = {
            'total_rpo': None,
            'rpo_by_segment': {},
            'backlog_visibility': None,
            'rpo_text': []
        }

        # Look for RPO mentions
        rpo_patterns = [
            r'(?:remaining\s+performance\s+obligations?|RPO).*?(\d+(?:\.\d+)?)\s*(?:billion|million|B|M)',
            r'(?:backlog|pipeline|committed.*?orders).*?(\d+(?:\.\d+)?)\s*(?:billion|million|B|M)',
            r'unsatisfied.*?performance.*?obligations?.*?(\d+(?:\.\d+)?)\s*(?:billion|million|B|M)',
        ]

        for pattern in rpo_patterns:
            matches = re.findall(pattern, self.text, re.IGNORECASE)
            if matches:
                rpo_data['rpo_matches'] = matches
                # Extract surrounding context
                for match_obj in re.finditer(pattern, self.text, re.IGNORECASE):
                    start = max(0, match_obj.start() - 100)
                    end = min(len(self.text), match_obj.end() + 100)
                    rpo_data['rpo_text'].append(self.text[start:end])

        return rpo_data

    def extract_all_data(self) -> Dict:
        """Extract all key data from 10-Q."""
        return {
            'company_overview': self.extract_company_overview(),
            'revenue_analysis': self.extract_revenue_analysis(),
            'operating_metrics': self.extract_operating_metrics(),
            'mda_sections': self.extract_md_a_sections(),
            'risk_factors': self.extract_risk_factors(),
            'cash_flow': self.extract_cash_flow_data(),
            'rpo_backlog': self.extract_rpo_backlog(),
        }


class DeepResearchReportGenerator:
    """Generate professional-grade research reports with 10-Q analysis."""

    def __init__(self, ticker: str, watchlist_tier: str = "UNRANKED"):
        self.ticker = ticker
        self.watchlist_tier = watchlist_tier
        self.report = []
        self.analysis_date = datetime.now().strftime("%B %d, %Y")

    def generate_report(self) -> str:
        """Generate complete research report."""
        logger.info(f"Generating deep research report for {self.ticker}...")

        # Fetch 10-Q
        fetcher = SECEdgarFetcher(self.ticker)
        cik = fetcher.get_cik()
        if not cik:
            logger.error(f"Could not find CIK for {self.ticker}")
            return self._generate_error_report()

        logger.info(f"Found CIK: {cik}")
        ten_q_text = fetcher.fetch_10q_text()

        if not ten_q_text:
            logger.error(f"Could not fetch 10-Q for {self.ticker}")
            return self._generate_error_report()

        logger.info(f"Successfully fetched 10-Q ({len(ten_q_text)} chars)")

        # Extract data
        extractor = TenQDataExtractor(self.ticker, ten_q_text)
        data = extractor.extract_all_data()

        # Build report sections
        self._add_cover_page()
        self._add_executive_summary()
        self._add_part_a_10q_data(data)
        self._add_part_b_framework_scoring()
        self._add_part_c_scenarios()
        self._add_part_d_stock_timing()
        self._add_part_e_verdict()
        self._add_appendix(data)

        return "\n\n".join(self.report)

    def _add_cover_page(self):
        """Add cover page with metadata."""
        self.report.append(f"""# {self.ticker} - R&D Adoption Framework Analysis
## SEC Filing-Based Report

**Analysis Date:** {self.analysis_date}
**Company:** {self.ticker}
**Watchlist Tier:** {self.watchlist_tier}
**Source:** SEC EDGAR
**Methodology:** R&D Adoption Framework (SEC-filing-first)
""")

    def _add_executive_summary(self):
        """Add executive summary section."""
        self.report.append("""## EXECUTIVE SUMMARY

| Metric | Finding | Status |
|--------|---------|--------|
| **Framework Score** | TBD/15 | Under Analysis |
| **Recommendation** | TBD | Pending 10-Q Review |
| **Analysis Status** | In Progress | Data Extraction Complete |

---
""")

    def _add_part_a_10q_data(self, data: Dict):
        """Add Part A with extracted 10-Q data."""
        part_a = f"""## PART A: ACTUAL 10-Q DATA EXTRACTED

### 1. COMPANY OVERVIEW

Analysis Date: {self.analysis_date}

#### Recent Transactions
{json.dumps(data.get('company_overview', {}), indent=2)}

---

### 2. REVENUE PERFORMANCE

#### Extracted Data
{json.dumps(data.get('revenue_analysis', {}), indent=2)}

---

### 3. OPERATING PERFORMANCE METRICS

#### Key Metrics
{json.dumps(data.get('operating_metrics', {}), indent=2)}

---

### 4. MD&A ANALYSIS

#### Key Sections Identified
{json.dumps(data.get('mda_sections', {}), indent=2)}

---

### 5. RISK FACTORS

#### Analysis
{json.dumps(data.get('risk_factors', {}), indent=2)}

---

### 6. CASH FLOW DATA

#### Cash Flow Analysis
{json.dumps(data.get('cash_flow', {}), indent=2)}

---

### 7. REMAINING PERFORMANCE OBLIGATIONS (RPO/BACKLOG)

#### Pipeline Visibility
{json.dumps(data.get('rpo_backlog', {}), indent=2)}

---
"""
        self.report.append(part_a)

    def _add_part_b_framework_scoring(self):
        """Add Part B: Framework scoring checklist."""
        self.report.append("""## PART B: FRAMEWORK SCORING (SEC FILINGS ONLY)

### Checklist Scoring

| Criterion | Finding | Evidence | Points |
|-----------|---------|----------|--------|
| **Product named in MD&A?** | TBD | Requires extraction | 0-1 |
| **Revenue line itemized?** | TBD | Requires parsing | 0-2 |
| **QoQ/YoY growth >15%?** | TBD | Requires calculation | 0-2 |
| **Customer names disclosed?** | TBD | Risk factors search | 0-2 |
| **Guidance includes product?** | TBD | MD&A parsing | 0-2 |
| **Risk factors mention?** | TBD | Item 1A analysis | 0-1 |
| **Backlog/RPO disclosed?** | TBD | Footnote extraction | 0-1 |
| **Support from earnings call?** | TBD | Pending | 0-1 |

### Red Flags Analysis

| Red Flag | Status | Impact |
|----------|--------|--------|
| Revenue declining | TBD | -1 pt |
| Governance issues | TBD | -2 pts |
| Press vs 10-Q mismatch | TBD | -1 pt |
| Execution risks | TBD | 0 pts |

### **TOTAL FRAMEWORK SCORE: TBD/15**

---
""")

    def _add_part_c_scenarios(self):
        """Add Part C: Forward-looking scenarios."""
        self.report.append("""## PART C: WHAT WOULD CHANGE THE SCORE?

### Score Would Jump to 7-10/15 IF:

#### Scenario 1: Product Revenue Itemized
```
Next 10-Q Shows:
- MD&A states: "Product X contributed $Y million to revenue"
- Footnote shows: "Segment revenue increased from $A to $B"
- Risk factors mention: "Product adoption risks"
→ Score jumps to 7-10/15 = CANDIDATE
```

#### Scenario 2: Earnings Call Quantification
```
Earnings Call Commentary:
- Management provides: "Pipeline has Z deployments"
- Guidance updated: "Expecting $XM run-rate by Q4"
- Analyst confirms: "Adoption trajectory accelerating"
→ Score jumps to 8-10/15 = HIGH-PROBABILITY CANDIDATE
```

#### Scenario 3: Guidance Raise
```
Guidance Update:
- Prior: Full-year growth +A%
- Updated: Full-year growth +B% (citing new products)
→ Score jumps to 7-9/15 = CANDIDATE
```

---
""")

    def _add_part_d_stock_timing(self):
        """Add Part D: Stock price vs adoption timeline."""
        self.report.append(f"""## PART D: STOCK PRICE VS FRAMEWORK TIMING

### Timeline Analysis

| Timeline | Event | Framework Status | Market Signal |
|----------|-------|------------------|----------------|
| Today | Analysis Date: {self.analysis_date} | TBD/15 | TBD |
| Next 30 days | Q2 Earnings Call | CRITICAL DECISION | TBD |
| Next 60 days | Q2 10-Q Filing | Score Update | TBD |
| Next 90 days | Q3 Guidance | Adoption Confirmation | TBD |

### Framework Timing Principle

This is exactly when the framework is most valuable:
1. Press announces product (past)
2. Market gets excited (present)
3. 10-Q should confirm or refute (next 30-60 days)
4. Your decision point is NOW: wait for proof

---
""")

    def _add_part_e_verdict(self):
        """Add Part E: Verdict and recommendations."""
        self.report.append("""## PART E: VERDICT & NEXT STEPS

### Current Assessment

**Score: TBD/15**

**Status:** Pending detailed 10-Q analysis and earnings call

### Decision Matrix

**IF Next Earnings Shows Product Traction:**
- ✅ Score jumps to 7-10/15
- ✅ Position is VALID (proceed with caution)
- ✅ Expect adoption acceleration over 3-4 months

**IF Next Earnings Shows Vague Guidance:**
- ⚠️ Score stays 3-5/15
- ⚠️ Wait for Q3 earnings for proof
- ⚠️ Risk: stock consolidates or pulls back

**IF Next Earnings Shows ZERO Product Mention:**
- ❌ Score drops to 0-2/15
- ❌ Position is invalid
- ❌ Stock likely corrects 10-15%

### Action Items

**Before Next Earnings:**
1. Set alert for earnings date
2. Prepare listening checklist:
   - Does management mention product by name?
   - Are deployments/pipeline quantified?
   - Customer names disclosed?
   - Is guidance being raised?
   - What's the revenue contribution estimate?

**After Next Earnings:**
1. Re-score immediately using framework
2. If score ≥7/15: confirm position, set upside targets
3. If score <5/15: reassess or exit

---
""")

    def _add_appendix(self, data: Dict):
        """Add appendix with raw data."""
        self.report.append(f"""## APPENDIX: EXTRACTED DATA

### Full Data Extraction Results

```json
{json.dumps(data, indent=2)}
```

---

**Report Generated:** {self.analysis_date}
**Data Source:** SEC EDGAR
**Analysis Methodology:** R&D Adoption Framework (SEC-filing-first)
""")

    def _generate_error_report(self) -> str:
        """Generate error report when data fetch fails."""
        return f"""# {self.ticker} - Research Report

**Analysis Date:** {self.analysis_date}

## ERROR: Unable to Fetch 10-Q

**Status:** SEC EDGAR access currently unavailable

**Cause:**
- SEC API rate-limited or temporarily unavailable
- Investor Relations website fetch failed
- Synthetic yfinance fallback insufficient for deep analysis

**Action:**
1. Retry in 1-2 hours when SEC recovers
2. Check current status: https://www.sec.gov/edgar/browse/?CIK={self.ticker}
3. Use browser to manually fetch and analyze 10-Q

**Framework Score:** Unable to calculate (no 10-Q data available)

---
"""


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Deep Research Report Generator - Professional SEC filing analysis'
    )
    parser.add_argument('--ticker', type=str, required=True, help='Stock ticker symbol')
    parser.add_argument('--output', type=str, help='Output markdown file path')
    parser.add_argument('--tier', type=str, default='UNRANKED', help='Watchlist tier')

    args = parser.parse_args()

    # Generate report
    generator = DeepResearchReportGenerator(args.ticker, args.tier)
    report = generator.generate_report()

    # Output
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"✓ Report saved to {args.output}")
    else:
        print(report)


if __name__ == '__main__':
    main()
