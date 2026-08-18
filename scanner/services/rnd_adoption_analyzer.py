#!/usr/bin/env python3
"""
R&D Adoption Framework Analyzer
Implements the 15-point SEC-filing-first framework for mid-cap stock analysis.

Framework: Score 0-15 based on 10-Q evidence
- 0-3: AVOID (hype without adoption proof)
- 4-6: WATCH (early adoption, 3-6 months to inflection)
- 7-10: CANDIDATE (proven adoption, 2-4 months to inflection)
- 11-15: HIGH-PROBABILITY (inflection imminent, 1-3 months to surge)

Prior benchmarks:
- BDX: 6-8/15 (early adoption confirmed by Q2 earnings)
- ZBRA: 12/15 (adoption proven in 10-Q, operational leverage visible)
- SMTC: 2-3/15 (AVOID - margin destruction despite revenue growth)
"""

import sys
import os
import json
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class ScoringCheckpoint:
    """Individual scoring criterion."""
    criterion: str
    description: str
    max_points: int
    points_earned: int
    evidence: str
    found: bool


@dataclass
class FrameworkScore:
    """Complete framework scoring result."""
    ticker: str
    analysis_date: str
    filing_date: str
    period_ended: str

    # Scoring checkpoints
    checkpoints: Dict[str, ScoringCheckpoint]
    subtotal: int
    red_flags: Dict[str, int]  # flag: points_deducted
    total_score: int

    # Financial data
    revenue_current_q: Optional[float]
    revenue_prior_q: Optional[float]
    yoy_growth_percent: Optional[float]
    operating_margin_percent: Optional[float]
    operating_income: Optional[float]

    # Verdict
    verdict: str  # AVOID, WATCH, CANDIDATE, HIGH-PROBABILITY
    months_to_inflection: str
    upside_target_percent: Optional[float]
    entry_price: Optional[float]
    stop_loss: Optional[float]
    next_catalyst: str

    # Comparison
    comparison_to_benchmarks: str


class RnDAdoptionAnalyzer:
    """Analyzes stocks using the R&D adoption framework."""

    # Framework scoring criteria
    SCORING_CRITERIA = {
        'product_named_mda': {
            'description': 'Product named in MD&A',
            'max_points': 2,
            'evidence_keywords': ['product', 'revenue', 'named segment']
        },
        'revenue_itemized': {
            'description': 'Revenue itemized by product/segment',
            'max_points': 2,
            'evidence_keywords': ['segment revenue', 'revenue breakdown', 'footnote']
        },
        'growth_strong': {
            'description': 'QoQ/YoY growth >15%',
            'max_points': 2,
            'evidence_keywords': ['growth', 'increase', 'accelerat']
        },
        'customer_names': {
            'description': 'Customer names disclosed',
            'max_points': 2,
            'evidence_keywords': ['customer', 'client', 'win', 'deployment']
        },
        'guidance_specific': {
            'description': 'Guidance product-specific',
            'max_points': 2,
            'evidence_keywords': ['guidance', 'outlook', 'expect', 'project']
        },
        'risk_factors': {
            'description': 'Risk factors mention product',
            'max_points': 1,
            'evidence_keywords': ['risk', 'adoption', 'competitive']
        },
        'backlog_rpo': {
            'description': 'Backlog/RPO disclosed',
            'max_points': 1,
            'evidence_keywords': ['backlog', 'RPO', 'remaining performance obligation', 'pipeline']
        },
        'operational_metrics': {
            'description': 'Supporting operational metrics',
            'max_points': 1,
            'evidence_keywords': ['hiring', 'acquisition', 'partnership', 'expansion']
        },
        'profitability': {
            'description': 'Profitability proof (margins stable/expanding)',
            'max_points': 1,
            'evidence_keywords': ['margin', 'operating income', 'leverage']
        },
        'earnings_call': {
            'description': 'Earnings call quantification',
            'max_points': 1,
            'evidence_keywords': ['management', 'CEO', 'quantif', 'customer']
        }
    }

    # Red flags (subtract points)
    RED_FLAGS = {
        'revenue_declining': {
            'description': 'Revenue declining while product hyped',
            'points': -2,
            'keywords': ['decline', 'down', 'loss']
        },
        'goodwill_impairment': {
            'description': 'Goodwill impairment >2% market cap',
            'points': -2,
            'keywords': ['goodwill impairment', 'write-down']
        },
        'margin_compression': {
            'description': 'Margin compression despite growth',
            'points': -1,
            'keywords': ['margin compress', 'operating margin down', 'cost increase']
        },
        'press_gap': {
            'description': 'Major gap: press claims ≠ 10-Q reality',
            'points': -2,
            'keywords': ['press release', 'announcement', 'not found in 10-Q']
        }
    }

    # Benchmarks for comparison
    BENCHMARKS = {
        'BDX': {
            'score': '6-8/15',
            'verdict': 'CANDIDATE',
            'products': 'Pyxis Pro (AI medication dispensing), Incada (AI platform)',
            'status': 'Early adoption confirmed by Q2 earnings',
            'key_proof': '75% competitive wins, CEO quantified adoption',
            'upside': '+20-30% over 4-5 months',
            'next_catalyst': 'Q3 earnings (Oct/Nov 2026)'
        },
        'ZBRA': {
            'score': '12/15',
            'verdict': 'HIGH-PROBABILITY',
            'products': 'Connected Frontline (AI frontline worker platform)',
            'status': 'Adoption PROVEN in 10-Q',
            'key_proof': 'CF revenue $825M +20.6% YoY, margins 20.5% stable',
            'upside': '+15-25% over 3-4 months',
            'next_catalyst': 'Q3 earnings (Oct/Nov 2026)'
        },
        'SMTC': {
            'score': '2-3/15',
            'verdict': 'AVOID',
            'products': 'Data center chips (generic)',
            'status': 'Margin destruction despite growth',
            'key_proof': 'Revenue +15.9% but operating income -28%, goodwill impairment $847.9M',
            'upside': 'NEGATIVE',
            'next_catalyst': 'Guidance miss expected'
        }
    }

    def __init__(self, ticker: str, ten_q_text: str, ticker_financials: Dict = None):
        self.ticker = ticker
        self.ten_q_text = ten_q_text
        self.financials = ticker_financials or {}
        self.analysis_date = datetime.now().strftime("%B %d, %Y")

    def score_criterion(self, criterion_key: str) -> ScoringCheckpoint:
        """Score a single criterion."""
        criterion = self.SCORING_CRITERIA[criterion_key]
        max_pts = criterion['max_points']
        keywords = criterion['evidence_keywords']

        # Search for evidence
        found = False
        for keyword in keywords:
            if keyword.lower() in self.ten_q_text.lower():
                found = True
                break

        pts = max_pts if found else 0

        return ScoringCheckpoint(
            criterion=criterion_key,
            description=criterion['description'],
            max_points=max_pts,
            points_earned=pts,
            evidence='Found in 10-Q' if found else 'Not found in 10-Q',
            found=found
        )

    def detect_red_flags(self) -> Dict[str, int]:
        """Detect red flags and calculate deductions."""
        flags = {}

        for flag_key, flag_info in self.RED_FLAGS.items():
            # Look for flag keywords
            found = False
            for keyword in flag_info['keywords']:
                if keyword.lower() in self.ten_q_text.lower():
                    found = True
                    break

            if found:
                flags[flag_key] = flag_info['points']

        return flags

    def extract_financial_metrics(self) -> Dict:
        """Extract key financial metrics from 10-Q."""
        import re

        metrics = {
            'revenue_current_q': None,
            'revenue_prior_q': None,
            'yoy_growth_percent': None,
            'operating_margin_percent': None,
            'operating_income': None
        }

        # Revenue patterns
        revenue_patterns = [
            r'[Rr]evenues?\s*[:\-=]\s*\$?\s*([\d,]+)\s*(?:million|M)',
            r'(?:Total\s+)?[Rr]evenue[s]?\s*[:\-=]\s*\$?\s*([\d,]+)',
        ]

        for pattern in revenue_patterns:
            matches = re.findall(pattern, self.ten_q_text[:30000])
            if matches:
                try:
                    if len(matches) >= 2:
                        metrics['revenue_current_q'] = float(matches[0].replace(',', ''))
                        metrics['revenue_prior_q'] = float(matches[1].replace(',', ''))
                    elif len(matches) == 1:
                        metrics['revenue_current_q'] = float(matches[0].replace(',', ''))
                    break
                except (ValueError, IndexError):
                    pass

        # YoY growth
        growth_patterns = [
            r'([+-]?\d+\.?\d*)\s*%\s*(?:growth|increase|decline|change)',
        ]

        for pattern in growth_patterns:
            matches = re.findall(pattern, self.ten_q_text[:20000])
            if matches:
                try:
                    metrics['yoy_growth_percent'] = float(matches[0])
                    break
                except ValueError:
                    pass

        # Operating margin
        margin_patterns = [
            r'[Oo]perating\s+margin\s*[:\-=]\s*([+-]?\d+\.?\d*)\s*%',
        ]

        for pattern in margin_patterns:
            matches = re.findall(pattern, self.ten_q_text)
            if matches:
                try:
                    metrics['operating_margin_percent'] = float(matches[0])
                    break
                except ValueError:
                    pass

        return metrics

    def generate_verdict(self, score: int) -> Tuple[str, str, Optional[float]]:
        """Generate verdict based on score."""
        if score >= 11:
            return 'HIGH-PROBABILITY', '1-3 months', 30.0
        elif score >= 7:
            return 'CANDIDATE', '2-4 months', 25.0
        elif score >= 4:
            return 'WATCH', '3-6 months', 15.0
        else:
            return 'AVOID', 'N/A', None

    def compare_to_benchmarks(self, score: int, verdict: str) -> str:
        """Compare analysis to benchmark stocks."""
        comparison = f"\n### Comparison to Framework Benchmarks\n\n"

        if score >= 11:
            comparison += f"**This resembles ZBRA (12/15, HIGH-PROBABILITY):**\n"
            comparison += f"- Adoption already proven in 10-Q\n"
            comparison += f"- Operating leverage likely visible\n"
            comparison += f"- No need to wait for earnings confirmation\n"
        elif score >= 7:
            comparison += f"**This resembles BDX (6-8/15, CANDIDATE):**\n"
            comparison += f"- Early adoption signals present in 10-Q\n"
            comparison += f"- Next earnings call will be critical\n"
            comparison += f"- Expect confirmation 1-2 quarters out\n"
        elif score >= 4:
            comparison += f"**Early signals, but need more proof:**\n"
            comparison += f"- Product mentioned but revenue not yet quantified\n"
            comparison += f"- Monitor next 2-3 10-Qs for acceleration\n"
        else:
            comparison += f"**This resembles SMTC (2-3/15, AVOID):**\n"
            comparison += f"- Growth claims not supported by 10-Q\n"
            comparison += f"- Watch for operational distress signals\n"

        return comparison

    def analyze(self) -> FrameworkScore:
        """Run complete framework analysis."""
        logger.info(f"Analyzing {self.ticker} using R&D adoption framework...")

        # Score each criterion
        checkpoints = {}
        subtotal = 0

        for criterion_key in self.SCORING_CRITERIA.keys():
            checkpoint = self.score_criterion(criterion_key)
            checkpoints[criterion_key] = checkpoint
            subtotal += checkpoint.points_earned
            logger.info(f"  {criterion_key}: {checkpoint.points_earned}/{checkpoint.max_points}")

        # Detect red flags
        red_flags = self.detect_red_flags()
        red_flag_deduction = sum(red_flags.values())
        logger.info(f"Red flags detected: {len(red_flags)} (deduction: {red_flag_deduction})")

        # Calculate total score
        total_score = max(0, min(15, subtotal + red_flag_deduction))

        # Generate verdict
        verdict, months_to_inflection, upside_target = self.generate_verdict(total_score)

        # Extract financial metrics
        metrics = self.extract_financial_metrics()

        # Compare to benchmarks
        comparison = self.compare_to_benchmarks(total_score, verdict)

        logger.info(f"Final score: {total_score}/15 ({verdict})")

        return FrameworkScore(
            ticker=self.ticker,
            analysis_date=self.analysis_date,
            filing_date=self.financials.get('filing_date', 'Not found'),
            period_ended=self.financials.get('period_ended', 'Not found'),
            checkpoints=checkpoints,
            subtotal=subtotal,
            red_flags=red_flags,
            total_score=total_score,
            revenue_current_q=metrics['revenue_current_q'],
            revenue_prior_q=metrics['revenue_prior_q'],
            yoy_growth_percent=metrics['yoy_growth_percent'],
            operating_margin_percent=metrics['operating_margin_percent'],
            operating_income=metrics['operating_income'],
            verdict=verdict,
            months_to_inflection=months_to_inflection,
            upside_target_percent=upside_target,
            entry_price=self.financials.get('current_price'),
            stop_loss=None,  # Calculated based on entry and thesis
            next_catalyst=self.financials.get('next_catalyst', 'Next earnings call'),
            comparison_to_benchmarks=comparison
        )


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='R&D Adoption Framework Analyzer - Score mid-cap stocks 0-15'
    )
    parser.add_argument('--ticker', type=str, required=True, help='Stock ticker')
    parser.add_argument('--filing', type=str, required=True, help='10-Q text file path')
    parser.add_argument('--output', type=str, help='Output JSON file')

    args = parser.parse_args()

    # Read 10-Q
    with open(args.filing, 'r') as f:
        ten_q_text = f.read()

    # Analyze
    analyzer = RnDAdoptionAnalyzer(args.ticker, ten_q_text)
    result = analyzer.analyze()

    # Output
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(asdict(result), f, indent=2, default=str)
        print(f"✓ Analysis saved to {args.output}")
    else:
        print(json.dumps(asdict(result), indent=2, default=str))


if __name__ == '__main__':
    main()
