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
from services.sec_edgar import SECEdgarFetcher

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
    """Fetch and extract data from 10-Q filings via SEC EDGAR (free public access)."""

    def __init__(self, ticker: str):
        self.ticker = ticker
        self.fetcher = SECEdgarFetcher(ticker)
        self.text = None

    def fetch(self) -> bool:
        """Fetch latest 10-Q from SEC EDGAR. Returns True if successful."""
        try:
            self.text = self.fetcher.fetch_10q_text()
            return self.text is not None
        except Exception as e:
            logger.error(f"Error fetching 10-Q for {self.ticker}: {e}")
            return False

    def extract_mda(self) -> Optional[str]:
        """Extract MD&A (Item 2) from 10-Q text."""
        if not self.text:
            return None
        return self.fetcher.extract_mda(self.text)

    def extract_risk_factors(self) -> Optional[str]:
        """Extract risk factors (Item 1A) from 10-Q text."""
        if not self.text:
            return None
        return self.fetcher.extract_risk_factors(self.text)

    def extract_revenue_data(self) -> Optional[Dict]:
        """Extract revenue and segment data from 10-Q."""
        if not self.text:
            return None
        return self.fetcher.extract_revenue_data(self.text)


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
        """Analyze single ticker by fetching 10-Q from SEC EDGAR."""
        logger.info(f"Analyzing {ticker} (earnings: {earnings_date})...")

        filing = SECFiling(ticker)

        # Fetch latest 10-Q from SEC EDGAR
        if not filing.fetch():
            logger.warning(f"No 10-Q found for {ticker}")
            return self._empty_result(ticker, earnings_date)

        # Extract sections
        mda = filing.extract_mda()
        risk_factors = filing.extract_risk_factors()
        revenue_data = filing.extract_revenue_data()

        # Web research
        web = WebResearch()
        press_releases = web.search_press_releases(ticker, ticker)
        analyst_reports = web.search_analyst_reports(ticker)
        news = web.search_news(ticker)

        # Score based on actual 10-Q findings
        criteria = {
            'product_named': self._check_product_named(mda),
            'revenue_quantified': self._check_revenue_quantified(revenue_data),
            'qoq_growth_strong': self._check_growth_strong(revenue_data),
            'customer_names': self._check_customer_names(risk_factors),
            'guidance_updated': self._check_guidance(mda),
            'analyst_initiations': len(analyst_reports) > 0,
            'hiring_spike': False,         # TODO: LinkedIn API or scraping
            'backlog_pipeline': self._check_backlog(mda),
        }

        score_result = self.scorer.score(ticker, criteria)

        # Get 10-Q source for tracking
        filing_source = getattr(filing.fetcher, 'source', 'Unknown') if hasattr(filing, 'fetcher') else 'Unknown'

        return {
            'ticker': ticker,
            'earnings_date': earnings_date,
            'score': score_result['total_score'],
            'score_breakdown': score_result,
            'mda_summary': mda[:400] if mda else None,
            'risk_factors_summary': risk_factors[:400] if risk_factors else None,
            'revenue_data': revenue_data,
            'press_releases': press_releases,
            'analyst_reports': analyst_reports,
            'news': news,
            '10q_source': filing_source,
            'sources': {
                'press_releases_count': len(press_releases),
                'analyst_reports_count': len(analyst_reports),
                'news_count': len(news),
                'sec_filing': 'Found',
                '10q_source': filing_source,
            }
        }

    def _check_product_named(self, mda: Optional[str]) -> bool:
        """Check if product is mentioned in MD&A."""
        if not mda:
            return False
        # Look for common product keywords
        keywords = ['product', 'service', 'solution', 'platform', 'infrastructure', 'cloud']
        return any(kw in mda.lower() for kw in keywords)

    def _check_revenue_quantified(self, revenue_data: Optional[Dict]) -> bool:
        """Check if revenue is quantified in segments."""
        if not revenue_data:
            return False
        return bool(revenue_data.get('segments')) or bool(revenue_data.get('total_revenue'))

    def _check_growth_strong(self, revenue_data: Optional[Dict]) -> bool:
        """Check if QoQ/YoY growth >15%."""
        if not revenue_data:
            return False
        growth = revenue_data.get('yoy_growth')
        return growth is not None and growth > 15

    def _check_customer_names(self, risk_factors: Optional[str]) -> bool:
        """Check if customer names are disclosed."""
        if not risk_factors:
            return False
        # Look for customer concentration language
        patterns = ['customer', 'concentration', 'largest customer', 'major customer']
        return any(pat in risk_factors.lower() for pat in patterns)

    def _check_guidance(self, mda: Optional[str]) -> bool:
        """Check if guidance is updated in MD&A."""
        if not mda:
            return False
        patterns = ['expect', 'guidance', 'outlook', 'forecast', 'projected']
        return any(pat in mda.lower() for pat in patterns)

    def _check_backlog(self, mda: Optional[str]) -> bool:
        """Check for backlog or pipeline evidence."""
        if not mda:
            return False
        patterns = ['backlog', 'pipeline', 'remaining performance obligations', 'rpo', 'committed']
        return any(pat in mda.lower() for pat in patterns)

    def _empty_result(self, ticker: str, earnings_date: str) -> Dict:
        """Return empty result for ticker with no data."""
        return {
            'ticker': ticker,
            'earnings_date': earnings_date,
            'score': 0,
            'error': 'No 10-Q filing found',
            'score_breakdown': self.scorer.score(ticker, {}),
        }

    def run(self, days_ahead: int = 14, max_tickers: int = None):
        """Run full analysis for upcoming earnings. Can limit to max_tickers for speed."""
        upcoming = get_upcoming_earnings(days_ahead)

        if not upcoming:
            logger.info(f"No tickers with earnings in next {days_ahead} days")
            return self.results

        # Limit to max_tickers if specified (for faster testing)
        if max_tickers:
            upcoming = upcoming[:max_tickers]

        logger.info(f"Analyzing {len(upcoming)} tickers...")

        for i, (ticker, earnings_date, quarter, year) in enumerate(upcoming, 1):
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
    parser.add_argument('--max', type=int, default=None,
                        help='Limit to N tickers (for faster testing)')
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
        # All upcoming (optionally limited)
        analysis.run(args.upcoming, max_tickers=args.max)

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
