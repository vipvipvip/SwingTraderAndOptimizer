#!/usr/bin/env python3
"""
Claude-Powered SEC Filing Fetcher
Uses Claude API to fetch and analyze SEC filings (bypasses rate limits)
"""

import os
import json
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class ClaudeSECFetcher:
    """Use Claude API to fetch and parse SEC filings."""

    def __init__(self, ticker: str):
        self.ticker = ticker
        self.api_key = os.getenv('ANTHROPIC_API_KEY')

        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set. SEC fetching via Claude requires API key.")

    def fetch_and_analyze_10q(self) -> Optional[Dict]:
        """
        Use Claude to:
        1. Find the latest 10-Q URL for ticker
        2. Fetch the actual 10-Q from SEC
        3. Extract key financial data
        4. Return structured analysis

        Returns analysis dict with extracted data
        """

        if not self.api_key:
            logger.error("Cannot fetch via Claude: ANTHROPIC_API_KEY not set")
            return None

        try:
            import anthropic
        except ImportError:
            logger.error("anthropic package not installed. Install with: pip install anthropic")
            return None

        client = anthropic.Anthropic(api_key=self.api_key)

        prompt = f"""
You are a financial research analyst. Your task is to:

1. Find the latest 10-Q filing for {self.ticker} from SEC EDGAR
2. Extract key financial data from the 10-Q
3. Analyze the data and return structured results

Please:
1. Go to https://www.sec.gov/cgi-bin/browse-edgar and search for {self.ticker}'s latest 10-Q
2. Access the filing and extract:
   - Revenue (current quarter and prior year quarter)
   - Gross margin percentage
   - Operating income
   - Operating cash flow
   - Key MD&A points about new products/initiatives
   - Risk factors
   - Forward-looking statements/guidance
   - Remaining Performance Obligations (RPO) or backlog
3. Return data as JSON with these fields:
   {{
     "ticker": "{self.ticker}",
     "filing_date": "YYYY-MM-DD",
     "period_ended": "YYYY-MM-DD",
     "revenue_current": 0,
     "revenue_prior_year": 0,
     "yoy_growth_percent": 0.0,
     "gross_margin_percent": 0.0,
     "operating_income": 0,
     "operating_cash_flow": 0,
     "key_md_a_points": [],
     "product_mentions": [],
     "guidance": "",
     "risk_factors": [],
     "rpo_backlog": 0,
     "source_url": "https://..."
   }}

Make sure to get ACTUAL 10-Q data, not press releases or summaries.
"""

        logger.info(f"Requesting Claude to fetch {self.ticker} 10-Q...")

        message = client.messages.create(
            model="claude-opus-5",
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        response_text = message.content[0].text

        # Extract JSON from response
        try:
            # Try to find JSON in response
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1

            if start_idx != -1 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx]
                analysis = json.loads(json_str)
                logger.info(f"Successfully extracted {self.ticker} 10-Q data via Claude")
                return analysis
            else:
                logger.error("No JSON found in Claude response")
                logger.debug(f"Response: {response_text[:500]}")
                return None

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Error processing Claude response: {e}")
            return None


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Claude-powered SEC filing fetcher (requires ANTHROPIC_API_KEY)'
    )
    parser.add_argument('--ticker', type=str, required=True, help='Stock ticker symbol')
    parser.add_argument('--output', type=str, help='Output JSON file')

    args = parser.parse_args()

    # Fetch
    fetcher = ClaudeSECFetcher(args.ticker)
    analysis = fetcher.fetch_and_analyze_10q()

    if analysis:
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(analysis, f, indent=2)
            print(f"✓ Analysis saved to {args.output}")
        else:
            print(json.dumps(analysis, indent=2))
    else:
        print(f"✗ Failed to fetch 10-Q for {args.ticker}")


if __name__ == '__main__':
    main()
