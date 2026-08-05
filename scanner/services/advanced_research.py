#!/usr/bin/env python3
"""
Advanced R&D Adoption Research
Adds to comprehensive_research.py:
  - Red flag detection (governance, auditor changes, revenue declines)
  - Earnings call transcripts & customer mentions
  - Analyst coverage tracking
  - Remaining Performance Obligations (RPO/backlog)
  - Guidance statement extraction
  - Stock performance tracking
  - Detailed tracking log (verdict evolution)
"""

import json
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import logging

logger = logging.getLogger(__name__)


class RedFlagDetector:
    """Detect immediate disqualifiers and caution flags."""

    IMMEDIATE_DISQUALIFIERS = [
        ('revenue_decline', 'Revenue declining YoY while product hyped'),
        ('governance_concerns', 'Governance concerns (auditor changes, executive indictments)'),
        ('press_gap', 'Press hyped product but 10-Q shows zero revenue'),
        ('mega_cap', 'Market cap >$200B (framework breaks down)'),
        ('micro_cap', 'Market cap <$2B (illiquidity, execution risk)'),
        ('pre_revenue_vague', 'Pre-revenue with vague deployment timeline (2+ years)'),
        ('customer_concentration', 'Customer concentration >50% with single customer'),
    ]

    CAUTION_FLAGS = [
        ('guidance_not_mda', 'Product in guidance but NOT in MD&A yet'),
        ('analyst_recent', 'Recent analyst initiation/upgrade (price may reflect thesis)'),
        ('stock_rally', 'Stock up >30% in past 3 months (upside may be realized)'),
        ('execution_risk', 'Execution risk visible in 10-Q (FDA, competitive, supply chain)'),
    ]

    def __init__(self):
        self.disqualifiers = []
        self.cautions = []

    def check_revenue_decline(self, revenue_data: Dict) -> bool:
        """Check if revenue is declining YoY."""
        if not revenue_data:
            return False
        growth = revenue_data.get('yoy_growth')
        return growth is not None and growth < 0

    def check_governance_concerns(self, sec_text: str) -> bool:
        """Check for auditor changes, executive issues, etc."""
        if not sec_text:
            return False

        concerns = [
            r'auditor changes?',
            r'indictment',
            r'regulatory action',
            r'restatement',
            r'going concern',
            r'internal control.*weakness',
        ]
        return any(re.search(pattern, sec_text, re.IGNORECASE) for pattern in concerns)

    def check_press_10q_gap(self, press_mentions: List[str], mda_text: str) -> bool:
        """Check if product heavily promoted in press but not in MD&A."""
        if not press_mentions or not mda_text:
            return False

        # If press mentions product multiple times but MD&A doesn't mention it
        press_count = sum(1 for p in press_mentions if p)
        mda_lower = mda_text.lower() if mda_text else ""

        product_keywords = ['product', 'solution', 'platform', 'service']
        mda_mentions = sum(mda_lower.count(kw) for kw in product_keywords)

        return press_count >= 3 and mda_mentions == 0

    def detect(self, result: Dict) -> Dict:
        """Run all red flag checks."""
        flags = {
            'disqualifiers': [],
            'cautions': [],
            'severity': 'PASS',
        }

        sec_data = result.get('sec_data', {})
        revenue = sec_data.get('revenue_data', {})
        mda = sec_data.get('mda_summary', '')

        # Check disqualifiers
        if self.check_revenue_decline(revenue):
            flags['disqualifiers'].append('revenue_decline')

        if self.check_governance_concerns(mda):
            flags['disqualifiers'].append('governance_concerns')

        # Set severity
        if flags['disqualifiers']:
            flags['severity'] = 'DISQUALIFIED'
        elif flags['cautions']:
            flags['severity'] = 'CAUTION'

        return flags


class EarningsCallAnalyzer:
    """Extract key data from earnings call transcripts."""

    def __init__(self):
        self.transcript = None
        self.findings = {}

    def load_transcript(self, ticker: str, date: str) -> Optional[str]:
        """
        Fetch earnings call transcript.
        Placeholder: In production, use SeekingAlpha API or similar.
        """
        # TODO: Implement transcript fetching via:
        # - Seeking Alpha (free tier)
        # - Yahoo Finance
        # - Company IR websites
        logger.info(f"Earnings call transcript fetching for {ticker} on {date} (TODO: implement)")
        return None

    def extract_customer_mentions(self, text: str) -> List[Dict]:
        """Extract customer names and deployment scales from transcript."""
        if not text:
            return []

        findings = []

        # Look for patterns like "customer X deployed", "X pilots", etc.
        patterns = [
            r'(?:customer|client|partner)\s+([A-Z][a-zA-Z\s&.]*?)\s+(?:deployed|signed|won|piloting)',
            r'(\d+)\s+(?:pilots?|deployments?|customers?)',
            r'scale.*?(\d+[KMB])',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                findings.append({'type': 'customer_mention', 'value': match})

        return findings

    def detect_ceo_escalation(self, current_call: str, prior_call: str) -> bool:
        """Check if CEO language is escalating Q-over-Q."""
        if not current_call or not prior_call:
            return False

        # Look for escalation keywords
        escalation = ['excited', 'momentum', 'accelerating', 'inflection', 'breakthrough']
        current_escalations = sum(current_call.lower().count(kw) for kw in escalation)
        prior_escalations = sum(prior_call.lower().count(kw) for kw in escalation)

        return current_escalations > prior_escalations


class AnalystCoverageTracker:
    """Track analyst initiations, upgrades, price targets."""

    def __init__(self):
        self.analysts = []

    def get_recent_coverage(self, ticker: str) -> List[Dict]:
        """
        Fetch recent analyst activity.
        Placeholder: Use Yahoo Finance yfinance in production.
        """
        # TODO: Implement via:
        # - Yahoo Finance API
        # - Finnhub free tier
        # - Seeking Alpha scraping
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            info = t.info

            coverage = []
            if 'targetMeanPrice' in info:
                coverage.append({
                    'type': 'target_price',
                    'value': info.get('targetMeanPrice'),
                    'num_analysts': info.get('numberOfAnalysts', 0),
                })

            if 'recommendationKey' in info:
                coverage.append({
                    'type': 'recommendation',
                    'value': info.get('recommendationKey'),
                })

            return coverage

        except Exception as e:
            logger.error(f"Error fetching analyst coverage: {e}")
            return []


class RPOBacklogExtractor:
    """Extract Remaining Performance Obligations (RPO) and backlog."""

    @staticmethod
    def extract_from_10q(text: str) -> Optional[Dict]:
        """Extract RPO, backlog, or remaining obligations from 10-Q."""
        if not text:
            return None

        data = {
            'rpo_total': None,
            'rpo_short_term': None,
            'rpo_long_term': None,
            'backlog': None,
            'committed_orders': None,
        }

        # Look for RPO/backlog mentions with numbers
        patterns = {
            'rpo_total': r'(?:remaining\s+performance\s+obligations?|RPO)[:\s]+\$?([\d,]+)\s*[MB]',
            'backlog': r'(?:backlog|order\s+backlog)[:\s]+\$?([\d,]+)\s*[MB]',
            'committed': r'(?:committed\s+orders?)[:\s]+\$?([\d,]+)\s*[MB]',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1).replace(',', ''))
                    data[key] = value
                except:
                    pass

        return data if any(data.values()) else None


class GuidanceExtractor:
    """Extract guidance statements and forward-looking language."""

    @staticmethod
    def extract_from_mda(text: str) -> List[Dict]:
        """Extract guidance and forward-looking statements from MD&A."""
        if not text:
            return []

        statements = []

        # Look for guidance patterns
        patterns = [
            r'(?:expect|anticipate|guidance|outlook|forecast)[:\s]+([^.]+\.)',
            r'(?:we\s+expect|we\s+anticipate)[:\s]+([^.]+\.)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                statements.append({
                    'type': 'forward_guidance',
                    'text': match[:150],  # First 150 chars
                })

        return statements


class StockPerformanceTracker:
    """Track stock price changes and momentum."""

    @staticmethod
    def get_performance(ticker: str, days: int = 90) -> Optional[Dict]:
        """Get stock performance over past N days."""
        try:
            import yfinance as yf
            from datetime import datetime, timedelta

            t = yf.Ticker(ticker)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            hist = t.history(start=start_date, end=end_date)

            if len(hist) < 2:
                return None

            start_price = hist['Close'].iloc[0]
            end_price = hist['Close'].iloc[-1]
            change_pct = ((end_price - start_price) / start_price) * 100
            max_price = hist['Close'].max()
            min_price = hist['Close'].min()

            return {
                'start_price': start_price,
                'end_price': end_price,
                'change_pct': change_pct,
                'max_price': max_price,
                'min_price': min_price,
                'volatility': hist['Close'].std(),
            }

        except Exception as e:
            logger.error(f"Error fetching stock performance: {e}")
            return None


class TrackingLog:
    """Track analysis evolution over time."""

    def __init__(self, ticker: str):
        self.ticker = ticker
        self.entries = []

    def add_entry(self, analysis_date: str, score: int, verdict: str, notes: str):
        """Add analysis entry."""
        self.entries.append({
            'date': analysis_date,
            'score': score,
            'verdict': verdict,
            'notes': notes,
        })

    def generate_markdown(self) -> str:
        """Generate tracking log markdown."""
        text = f"# Tracking Log: {self.ticker}\n\n"

        for entry in reversed(self.entries):  # Newest first
            text += f"## {entry['date']}\n"
            text += f"- **Score:** {entry['score']}/15\n"
            text += f"- **Verdict:** {entry['verdict']}\n"
            text += f"- **Notes:** {entry['notes']}\n\n"

        return text

    def detect_verdict_evolution(self) -> str:
        """Compare initial vs current verdict."""
        if len(self.entries) < 2:
            return "Insufficient history"

        first = self.entries[0]['verdict']
        last = self.entries[-1]['verdict']

        if first == last:
            return f"Consistent: {first}"
        else:
            return f"Evolved: {first} → {last}"
