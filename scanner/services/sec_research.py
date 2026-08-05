#!/usr/bin/env python3
"""
SEC-Filing Research Analyzer
-------------------------------
Analyzes upcoming earnings against SEC filings, press releases, analyst reports.
Generates PDF reports with rankings and cross-referenced evidence.

Usage:
    python sec_research.py --upcoming 14                    # Analyze next 14 days
    python sec_research.py --ticker ASTS                    # Single ticker
    python sec_research.py --upcoming 14 --output /path.pdf # Save to path
"""

import argparse
import json
import sys
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from pathlib import Path
import logging

import psycopg2
from psycopg2.extras import Json
import yfinance as yf
from dotenv import load_dotenv

# Local imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DB_CONFIG

# Load environment
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', 'swingtrader', 'services', 'mtf', '.env'))

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.path.dirname(__file__)) / '.sec_research_cache'
CACHE_DIR.mkdir(exist_ok=True)


def get_db_conn():
    return psycopg2.connect(**DB_CONFIG)


def ensure_schema():
    """Ensure tbl_sec_research_analysis table exists."""
    conn = get_db_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tbl_sec_research_analysis (
            id SERIAL PRIMARY KEY,
            run_id UUID NOT NULL,
            ticker VARCHAR(10) NOT NULL,
            earnings_date DATE,
            filing_date DATE,
            filing_type VARCHAR(10),
            score INTEGER,
            rank_in_run INTEGER,
            analysis_data JSONB,
            board_comments TEXT,
            sources JSONB,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(run_id, ticker)
        );

        CREATE INDEX IF NOT EXISTS idx_sec_research_ticker ON tbl_sec_research_analysis(ticker);
        CREATE INDEX IF NOT EXISTS idx_sec_research_run_id ON tbl_sec_research_analysis(run_id);
        CREATE INDEX IF NOT EXISTS idx_sec_research_earnings ON tbl_sec_research_analysis(earnings_date);
    """)

    conn.commit()
    cur.close()
    conn.close()


def get_upcoming_earnings(days_ahead: int = 14) -> List[tuple]:
    """Get tickers with earnings in next N days from earnings_calendar."""
    conn = get_db_conn()
    cur = conn.cursor()

    cutoff = datetime.now().date() + timedelta(days=days_ahead)
    cur.execute("""
        SELECT ticker, earnings_date, quarter, year
        FROM tbl_earnings_calendar
        WHERE earnings_date BETWEEN CURRENT_DATE AND %s
        ORDER BY earnings_date
    """, (cutoff,))

    results = cur.fetchall()
    cur.close()
    conn.close()
    return results


class SECFiling:
    """Fetch and extract data from 10-Q filings via SEC EDGAR."""

    def __init__(self, ticker: str):
        self.ticker = ticker
        self.cik = None
        self.latest_10q = None

    def get_latest_10q_text(self) -> Optional[str]:
        """Fetch the latest 10-Q filing text from SEC EDGAR."""
        try:
            # Try to get 10-Q via yfinance
            t = yf.Ticker(self.ticker)
            # Note: yfinance doesn't directly expose 10-Q text
            # We'll fetch from SEC EDGAR via CIK lookup
            logger.info(f"Fetching 10-Q for {self.ticker}...")

            # For now, we'll cache locally and assume filing is available
            # In production, integrate with sec-api.com or direct EDGAR parsing
            return self._get_cached_filing()

        except Exception as e:
            logger.error(f"Error fetching 10-Q for {self.ticker}: {e}")
            return None

    def _get_cached_filing(self) -> Optional[str]:
        """Return cached filing if available."""
        cache_file = CACHE_DIR / f"{self.ticker}_10q_latest.txt"
        if cache_file.exists():
            return cache_file.read_text()
        return None

    def extract_mda(self, text: str) -> Optional[str]:
        """Extract MD&A (Item 2) from 10-Q text."""
        if not text:
            return None

        # Simple extraction: look for Item 2 markers
        mda_start = text.find("Item 2")
        if mda_start == -1:
            return None

        mda_end = text.find("Item 3", mda_start)
        if mda_end == -1:
            mda_end = len(text)

        return text[mda_start:mda_end]

    def extract_risk_factors(self, text: str) -> Optional[str]:
        """Extract risk factors (Item 1A) from 10-Q text."""
        if not text:
            return None

        risk_start = text.find("Item 1A")
        if risk_start == -1:
            return None

        risk_end = text.find("Item 1B", risk_start)
        if risk_end == -1:
            risk_end = text.find("Item 2", risk_start)
        if risk_end == -1:
            risk_end = len(text)

        return text[risk_start:risk_end]


class WebResearch:
    """Search web for press releases, analyst reports, news."""

    @staticmethod
    def search_press_releases(ticker: str, company_name: str) -> List[Dict]:
        """Search for recent press releases."""
        results = []

        # In production, use NewsAPI, Finnhub, or similar
        # For now, return empty list (to be enhanced)
        logger.info(f"Searching press releases for {ticker}...")

        return results

    @staticmethod
    def search_analyst_reports(ticker: str) -> List[Dict]:
        """Search for recent analyst reports (Yahoo Finance, Seeking Alpha)."""
        results = []

        try:
            t = yf.Ticker(ticker)
            # yfinance exposes analyst info
            info = t.info

            if 'targetMeanPrice' in info:
                results.append({
                    'source': 'Yahoo Finance',
                    'type': 'analyst_target',
                    'data': {
                        'target_price': info.get('targetMeanPrice'),
                        'num_analysts': info.get('numberOfAnalysts'),
                    }
                })

            if 'recommendationKey' in info:
                results.append({
                    'source': 'Yahoo Finance',
                    'type': 'recommendation',
                    'data': {
                        'recommendation': info.get('recommendationKey'),
                    }
                })

        except Exception as e:
            logger.error(f"Error fetching analyst data for {ticker}: {e}")

        return results

    @staticmethod
    def search_news(ticker: str) -> List[Dict]:
        """Search for recent news articles."""
        results = []

        # In production, use NewsAPI or Google News RSS
        logger.info(f"Searching news for {ticker}...")

        return results


class FrameworkScorer:
    """Score ticker candidacy against 15-point SEC-filing-first framework."""

    CRITERIA = {
        'product_named': {
            'weight': 1,
            'source': 'MD&A Item 2',
            'description': 'Product mentioned by name',
        },
        'revenue_quantified': {
            'weight': 2,
            'source': 'Revenue Footnote',
            'description': 'Revenue line item or customer list',
        },
        'qoq_growth_strong': {
            'weight': 2,
            'source': 'Comparative financials',
            'description': 'QoQ growth >15%',
        },
        'customer_names': {
            'weight': 2,
            'source': 'Risk factors / disclosures',
            'description': 'Named customer wins',
        },
        'guidance_updated': {
            'weight': 2,
            'source': 'MD&A guidance section',
            'description': 'Guidance includes product estimate',
        },
        'analyst_initiations': {
            'weight': 2,
            'source': 'Verified separately',
            'description': 'Recent analyst initiations/upgrades',
        },
        'hiring_spike': {
            'weight': 1,
            'source': 'LinkedIn',
            'description': 'Job hiring spike',
        },
        'backlog_pipeline': {
            'weight': 1,
            'source': 'Remaining performance obligations',
            'description': 'Backlog/pipeline evidence',
        },
    }

    def __init__(self):
        self.scores = {}
        self.notes = {}

    def score(self, ticker: str, criteria_dict: Dict[str, bool]) -> Dict:
        """Score ticker. Returns dict with score (0-15) and breakdown."""
        total_score = 0
        breakdown = {}

        for criterion, met in criteria_dict.items():
            if criterion in self.CRITERIA and met:
                weight = self.CRITERIA[criterion]['weight']
                total_score += weight
                breakdown[criterion] = {
                    'weight': weight,
                    'met': True,
                    'source': self.CRITERIA[criterion]['source'],
                }
            elif criterion in self.CRITERIA:
                breakdown[criterion] = {
                    'weight': self.CRITERIA[criterion]['weight'],
                    'met': False,
                    'source': self.CRITERIA[criterion]['source'],
                }

        return {
            'total_score': total_score,
            'max_score': 15,
            'percentage': (total_score / 15) * 100,
            'breakdown': breakdown,
        }


class Analysis:
    """Main analysis orchestrator."""

    def __init__(self, run_id: Optional[str] = None):
        self.run_id = run_id or str(uuid.uuid4())
        self.results = []
        self.scorer = FrameworkScorer()

    def analyze_ticker(self, ticker: str, earnings_date: str) -> Dict:
        """Analyze single ticker."""
        logger.info(f"Analyzing {ticker} (earnings: {earnings_date})...")

        filing = SECFiling(ticker)
        filing_text = filing.get_latest_10q_text()

        if not filing_text:
            logger.warning(f"No 10-Q found for {ticker}")
            return self._empty_result(ticker, earnings_date)

        # Extract sections
        mda = filing.extract_mda(filing_text)
        risk_factors = filing.extract_risk_factors(filing_text)

        # Web research
        web = WebResearch()
        press_releases = web.search_press_releases(ticker, ticker)
        analyst_reports = web.search_analyst_reports(ticker)
        news = web.search_news(ticker)

        # Score
        criteria = {
            'product_named': bool(mda),
            'revenue_quantified': False,  # Would extract from footnotes
            'qoq_growth_strong': False,   # Would extract from financials
            'customer_names': False,       # Would extract from risk factors
            'guidance_updated': False,     # Would extract from MD&A
            'analyst_initiations': len(analyst_reports) > 0,
            'hiring_spike': False,         # Would check LinkedIn
            'backlog_pipeline': False,     # Would extract from disclosure
        }

        score_result = self.scorer.score(ticker, criteria)

        return {
            'ticker': ticker,
            'earnings_date': earnings_date,
            'score': score_result['total_score'],
            'score_breakdown': score_result,
            'mda_summary': mda[:500] if mda else None,
            'risk_factors_summary': risk_factors[:500] if risk_factors else None,
            'press_releases': press_releases,
            'analyst_reports': analyst_reports,
            'news': news,
            'sources': {
                'press_releases_count': len(press_releases),
                'analyst_reports_count': len(analyst_reports),
                'news_count': len(news),
            }
        }

    def _empty_result(self, ticker: str, earnings_date: str) -> Dict:
        """Return empty result for ticker with no data."""
        return {
            'ticker': ticker,
            'earnings_date': earnings_date,
            'score': 0,
            'error': 'No 10-Q filing found',
            'score_breakdown': self.scorer.score(ticker, {}),
        }

    def run(self, days_ahead: int = 14):
        """Run full analysis for upcoming earnings."""
        upcoming = get_upcoming_earnings(days_ahead)

        if not upcoming:
            logger.info(f"No tickers with earnings in next {days_ahead} days")
            return self.results

        logger.info(f"Analyzing {len(upcoming)} tickers...")

        for ticker, earnings_date, quarter, year in upcoming:
            result = self.analyze_ticker(ticker, str(earnings_date))
            self.results.append(result)

        # Sort by score (descending)
        self.results.sort(key=lambda x: x.get('score', 0), reverse=True)

        # Add rank
        for i, result in enumerate(self.results, 1):
            result['rank'] = i

        return self.results

    def save_to_db(self):
        """Save analysis results to database."""
        conn = get_db_conn()
        cur = conn.cursor()

        for result in self.results:
            try:
                cur.execute("""
                    INSERT INTO tbl_sec_research_analysis
                    (run_id, ticker, earnings_date, score, rank_in_run, analysis_data, sources)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id, ticker) DO UPDATE SET
                        score = EXCLUDED.score,
                        rank_in_run = EXCLUDED.rank_in_run,
                        analysis_data = EXCLUDED.analysis_data,
                        sources = EXCLUDED.sources,
                        updated_at = NOW()
                """, (
                    self.run_id,
                    result['ticker'],
                    result.get('earnings_date'),
                    result.get('score', 0),
                    result.get('rank'),
                    Json(result),
                    Json(result.get('sources', {})),
                ))
            except Exception as e:
                logger.error(f"Error saving {result['ticker']}: {e}")

        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"Saved {len(self.results)} results with run_id {self.run_id}")


def main():
    parser = argparse.ArgumentParser(
        description='SEC-Filing Research Analyzer for Earnings'
    )
    parser.add_argument('--upcoming', type=int, default=14,
                        help='Days ahead to analyze (default: 14)')
    parser.add_argument('--ticker', type=str,
                        help='Analyze single ticker')
    parser.add_argument('--output', type=str,
                        help='PDF output path')
    parser.add_argument('--db-only', action='store_true',
                        help='Save to database only (no PDF)')

    args = parser.parse_args()

    ensure_schema()

    analysis = Analysis()

    if args.ticker:
        # Single ticker
        result = analysis.analyze_ticker(args.ticker, str(datetime.now().date()))
        analysis.results = [result]
    else:
        # All upcoming
        analysis.run(args.upcoming)

    analysis.save_to_db()

    # Print summary
    print(f"\n{'='*80}")
    print(f"SEC RESEARCH ANALYSIS SUMMARY (Run ID: {analysis.run_id})")
    print(f"{'='*80}\n")

    for result in analysis.results:
        score = result.get('score', 0)
        rank = result.get('rank', '?')
        ticker = result['ticker']
        earnings = result.get('earnings_date', 'N/A')
        print(f"{rank:2}. {ticker:6} — Score: {score:2}/15 — Earnings: {earnings}")

    if args.output:
        from sec_research_pdf import generate_pdf
        generate_pdf(analysis, args.output)
        logger.info(f"PDF saved to {args.output}")


if __name__ == '__main__':
    main()
