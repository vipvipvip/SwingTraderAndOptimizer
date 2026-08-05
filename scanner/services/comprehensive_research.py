#!/usr/bin/env python3
"""
Comprehensive R&D Adoption Research
Combines watchlist screening + SEC filing analysis + market data + news

Integrates:
  - Watchlist tier (HIGH-PRIORITY, SECONDARY, CAUTION, NON-FIT)
  - Market cap, sector, analyst activity
  - Recent announcements and news
  - SEC 10-Q filing data
  - Framework scoring (15-point)
  - Earnings catalyst timing
"""

import argparse
import json
import sys
import os
from datetime import datetime
from typing import Optional, List, Dict
from pathlib import Path
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DB_CONFIG
from services.sec_research import Analysis as SECAnalysis
from services.advanced_research import (
    RedFlagDetector, EarningsCallAnalyzer, AnalystCoverageTracker,
    RPOBacklogExtractor, GuidanceExtractor, StockPerformanceTracker,
    TrackingLog
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class WatchlistData:
    """Load and parse watchlist analysis data."""

    def __init__(self, watchlist_file: str):
        self.file = Path(watchlist_file)
        self.data = {}
        self.load()

    def load(self):
        """Load watchlist from markdown file."""
        if not self.file.exists():
            logger.warning(f"Watchlist file not found: {self.file}")
            return

        try:
            with open(self.file) as f:
                content = f.read()

            # Parse markdown file into structured data
            self.data = self._parse_markdown(content)
            logger.info(f"Loaded watchlist with {len(self.data)} tickers")

        except Exception as e:
            logger.error(f"Error loading watchlist: {e}")

    def _parse_markdown(self, content: str) -> Dict:
        """Parse markdown watchlist into ticker data."""
        data = {}

        # Extract tickers by section
        sections = {
            'HIGH-PRIORITY': [],
            'SECONDARY': [],
            'CAUTION': [],
            'NON-FIT': [],
        }

        # Split by main sections
        if '🎯 HIGH-PRIORITY' in content:
            high_section = content.split('🎯 HIGH-PRIORITY')[1].split('## 📊')[0]
            # Extract tickers (e.g., "### 1. AXON Enterprise")
            import re
            tickers = re.findall(r'### \d+\. ([A-Z]+)\s', high_section)
            sections['HIGH-PRIORITY'] = tickers

        if '📊 SECONDARY' in content:
            sec_section = content.split('📊 SECONDARY')[1].split('## 🏥')[0] if '## 🏥' in content else content.split('📊 SECONDARY')[1]
            tickers = re.findall(r'### \d+\. ([A-Z]+)\s', sec_section)
            sections['SECONDARY'] = tickers

        if '🏥 HEALTHCARE' in content:
            health_section = content.split('🏥 HEALTHCARE')[1].split('## 🚫')[0] if '## 🚫' in content else content.split('🏥 HEALTHCARE')[1]
            tickers = re.findall(r'([A-Z]{3,4})\s', health_section)
            sections['CAUTION'] = tickers

        if '🚫 LIKELY NON-FITS' in content:
            nonfit_section = content.split('🚫 LIKELY NON-FITS')[1]
            tickers = re.findall(r'\*\*([A-Z]{3,4})\*\*', nonfit_section)
            sections['NON-FIT'] = tickers

        # Create ticker entries
        for tier, tickers in sections.items():
            for ticker in set(tickers):  # Remove duplicates
                if ticker not in data:
                    data[ticker] = {
                        'ticker': ticker,
                        'watchlist_tier': tier,
                        'raw_content': self._extract_ticker_section(content, ticker),
                    }

        return data

    def _extract_ticker_section(self, content: str, ticker: str) -> str:
        """Extract the full section for a ticker."""
        import re
        pattern = rf'### \d+\. {ticker}\s.*?(?=###|##|$)'
        match = re.search(pattern, content, re.DOTALL)
        return match.group(0) if match else ""

    def get_ticker_data(self, ticker: str) -> Optional[Dict]:
        """Get watchlist data for a ticker."""
        return self.data.get(ticker)

    def get_all_tickers(self) -> List[str]:
        """Get all tickers in watchlist."""
        return list(self.data.keys())


class ComprehensiveAnalysis:
    """Combine watchlist data + SEC analysis."""

    def __init__(self, watchlist_file: Optional[str] = None):
        self.watchlist = None
        if watchlist_file:
            self.watchlist = WatchlistData(watchlist_file)

        self.sec_analysis = SECAnalysis()
        self.results = []

    def analyze(self, tickers: Optional[List[str]] = None) -> List[Dict]:
        """Analyze tickers (from watchlist or specific list)."""
        if tickers is None:
            if self.watchlist:
                tickers = self.watchlist.get_all_tickers()
            else:
                logger.error("No tickers provided and no watchlist loaded")
                return []

        logger.info(f"Analyzing {len(tickers)} tickers (watchlist + SEC filing data)...")

        for ticker in tickers:
            result = self.analyze_ticker(ticker)
            if result:
                self.results.append(result)

        # Rank by combined score
        self.results.sort(key=lambda x: x.get('combined_score', 0), reverse=True)

        # Add rank
        for i, result in enumerate(self.results, 1):
            result['overall_rank'] = i

        return self.results

    def analyze_ticker(self, ticker: str) -> Optional[Dict]:
        """Analyze single ticker: watchlist + SEC filing + advanced signals."""
        logger.info(f"Analyzing {ticker}...")

        # Get watchlist data
        watchlist_data = {}
        if self.watchlist:
            watchlist_data = self.watchlist.get_ticker_data(ticker) or {}

        # Get SEC filing data
        sec_data = self.sec_analysis.analyze_ticker(ticker, str(datetime.now().date()))

        # Combine
        combined = {
            'ticker': ticker,
            'watchlist_tier': watchlist_data.get('watchlist_tier', 'UNRANKED'),
            'watchlist_data': watchlist_data,
            'sec_data': sec_data,
            'data_sources': {
                '10q_source': sec_data.get('10q_source', 'Unknown'),
                'analyst_source': 'yfinance',
                'stock_performance_source': 'yfinance',
            }
        }

        # Calculate combined score
        sec_score = sec_data.get('score', 0)

        # Watchlist tier bonus
        tier_bonus = {
            'HIGH-PRIORITY': 3,
            'SECONDARY': 1,
            'CAUTION': -2,
            'NON-FIT': -5,
            'UNRANKED': 0,
        }
        bonus = tier_bonus.get(combined['watchlist_tier'], 0)

        combined['combined_score'] = max(0, min(20, sec_score + bonus))  # Boost by tier, cap at 20
        combined['score_breakdown'] = {
            'sec_filing_score': sec_score,
            'watchlist_tier_bonus': bonus,
            'combined': combined['combined_score'],
        }

        # Advanced analysis
        # Red flags
        red_flag_detector = RedFlagDetector()
        combined['red_flags'] = red_flag_detector.detect(combined)

        # Stock performance (last 90 days)
        combined['stock_performance'] = StockPerformanceTracker.get_performance(ticker, days=90)

        # Analyst coverage
        analyst_tracker = AnalystCoverageTracker()
        combined['analyst_coverage'] = analyst_tracker.get_recent_coverage(ticker)

        # RPO/Backlog (from 10-Q text)
        sec_text = sec_data.get('sec_data', {}) if isinstance(sec_data, dict) else ""
        mda = sec_data.get('mda_summary', '')
        combined['rpo_backlog'] = RPOBacklogExtractor.extract_from_10q(mda)

        # Forward guidance (from MD&A)
        combined['guidance'] = GuidanceExtractor.extract_from_mda(mda)

        return combined

    def save_to_db(self):
        """Save combined results to database."""
        # Use SEC analysis to save
        self.sec_analysis.results = [r.get('sec_data') for r in self.results if r.get('sec_data')]
        self.sec_analysis.save_to_db()


def main():
    parser = argparse.ArgumentParser(
        description='Comprehensive R&D Adoption Research (Watchlist + SEC Filing)'
    )
    parser.add_argument('--watchlist', type=str,
                        default='/home/dikesh/Downloads/Filtered_Watchlist_Analysis.md',
                        help='Watchlist markdown file path')
    parser.add_argument('--tickers', type=str,
                        help='Comma-separated tickers (e.g., "BDX,AXON" or "BDX, AXON" with quotes)')
    parser.add_argument('--output', type=str,
                        help='PDF output path')
    parser.add_argument('--db-only', action='store_true',
                        help='Save to database only (no PDF)')

    args = parser.parse_args()

    # Parse tickers (handle spaces after commas)
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(',') if t.strip()]
    else:
        tickers = None

    # Run analysis
    analysis = ComprehensiveAnalysis(watchlist_file=args.watchlist)
    analysis.analyze(tickers)

    analysis.save_to_db()

    # Print summary
    print(f"\n{'='*80}")
    print(f"COMPREHENSIVE RESEARCH ANALYSIS")
    print(f"{'='*80}\n")

    for result in analysis.results:
        ticker = result['ticker']
        tier = result['watchlist_tier']
        sec_score = result['score_breakdown']['sec_filing_score']
        combined = result['combined_score']
        rank = result['overall_rank']

        print(f"{rank:2}. {ticker:6} | Tier: {tier:15} | SEC: {sec_score:2}/15 | Combined: {combined:2}/20")

    # Generate evidence-based PDF if requested
    if args.output and not args.db_only:
        from evidence_based_pdf import generate_evidence_based_pdf
        generate_evidence_based_pdf(analysis, args.output)
        logger.info(f"Evidence-based PDF saved to {args.output}")


if __name__ == '__main__':
    main()
