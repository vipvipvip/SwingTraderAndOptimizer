"""
SEC EDGAR Filing Fetcher
Fetches 10-Q filings directly from sec.gov (free, no API key needed)
"""

import requests
import re
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from pathlib import Path
from urllib.parse import urljoin
import time

logger = logging.getLogger(__name__)

# SEC EDGAR endpoints
SEC_CIK_LOOKUP = "https://www.sec.gov/cgi-bin/browse-edgar"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar"
SEC_TICKER_JSON = "https://www.sec.gov/files/company_tickers.json"

# Cache directory for downloaded filings
EDGAR_CACHE_DIR = Path(__file__).parent / '.sec_edgar_cache'
EDGAR_CACHE_DIR.mkdir(exist_ok=True)

# Local CIK mapping (fallback if SEC API blocked)
TICKER_CIK_MAP_FILE = Path(__file__).parent / 'ticker_cik_mapping.json'
_TICKER_CIK_CACHE = None

def load_ticker_cik_map():
    """Load ticker->CIK mapping from local file."""
    global _TICKER_CIK_CACHE
    if _TICKER_CIK_CACHE is not None:
        return _TICKER_CIK_CACHE

    try:
        with open(TICKER_CIK_MAP_FILE) as f:
            _TICKER_CIK_CACHE = json.load(f)
        return _TICKER_CIK_CACHE
    except Exception as e:
        logger.error(f"Could not load ticker CIK map: {e}")
        return {}


class SECEdgarFetcher:
    """Fetch and parse 10-Q filings from SEC EDGAR."""

    def __init__(self, ticker: str, max_retries: int = 3):
        self.ticker = ticker.upper()
        self.cik = None
        self.max_retries = max_retries
        self.session = requests.Session()
        # SEC requires legitimate User-Agent with company info
        # Format: {Client}/{Version} {Identifier}/{Version}
        self.session.headers.update({
            'User-Agent': 'SwingTraderResearch/1.0 (research; +https://github.com/dikesh/SwingTraderAndOptimizer)',
        })

    def get_cik(self) -> Optional[str]:
        """
        Look up CIK (Central Index Key) for ticker symbol.
        Tries online first, falls back to local mapping if blocked.
        """
        if self.cik:
            return self.cik

        # Try local mapping first (faster, doesn't require network)
        local_map = load_ticker_cik_map()
        if self.ticker in local_map:
            self.cik = local_map[self.ticker]
            logger.info(f"Found CIK (local): {self.cik}")
            return self.cik

        # Try online lookup
        try:
            logger.info(f"Looking up CIK online for {self.ticker}...")

            # Query SEC EDGAR company search
            params = {
                'action': 'getcompany',
                'CIK': self.ticker,
                'type': '',
                'dateb': '',
                'owner': 'exclude',
                'count': 10,
            }

            r = self.session.get(SEC_CIK_LOOKUP, params=params, timeout=15)

            if r.status_code == 403:
                logger.warning(f"SEC blocked request (rate limit). Using local CIK map only.")
                return None

            r.raise_for_status()

            # Parse CIK from response
            # Format: "Central Index Key: 0001018724"
            match = re.search(r'Central Index Key:\s*(\d+)', r.text)
            if match:
                self.cik = match.group(1)
                logger.info(f"Found CIK (online): {self.cik}")
                return self.cik

            logger.warning(f"Could not find CIK for {self.ticker}")
            return None

        except Exception as e:
            logger.warning(f"Error fetching CIK online: {e}. Ticker not in local map.")
            return None

    def get_latest_10q_url(self) -> Optional[str]:
        """
        Find the URL of the most recent 10-Q filing.
        Returns the filing document URL (not the index page).
        """
        cik = self.get_cik()
        if not cik:
            return None

        try:
            logger.info(f"Fetching latest 10-Q for {self.ticker}...")

            # Query EDGAR company filings
            # Format: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001018724&type=10-Q&dateb=&owner=exclude&count=40
            params = {
                'action': 'getcompany',
                'CIK': cik,
                'type': '10-Q',
                'dateb': '',
                'owner': 'exclude',
                'count': 5,  # Just get most recent few
            }

            r = self.session.get(SEC_CIK_LOOKUP, params=params, timeout=10)
            r.raise_for_status()

            # Find first 10-Q filing link
            # Format: href="/Archives/edgar/0001018724/000101872425000001/..."
            match = re.search(r'href="(/Archives/edgar/\d+/\d+/.*?)"', r.text)
            if match:
                filing_path = match.group(1)
                # This is usually an index page, need to find the actual document
                filing_url = urljoin('https://www.sec.gov', filing_path)
                logger.info(f"Found filing index: {filing_url}")
                return filing_url

            logger.warning(f"No 10-Q filings found for {self.ticker}")
            return None

        except Exception as e:
            logger.error(f"Error fetching latest 10-Q URL: {e}")
            return None

    def get_10q_document_url(self, filing_index_url: str) -> Optional[str]:
        """
        From the filing index page, find the actual 10-Q document file.
        10-Qs are usually in .htm or .html format.
        """
        try:
            r = self.session.get(filing_index_url, timeout=10)
            r.raise_for_status()

            # Look for the main document (usually ends with _10q.htm or 10q.htm)
            # Pattern: href="0001018724-25-000001.htm"
            matches = re.findall(r'href="([^"]*10-?q[^"]*\.htm[l]?)"', r.text, re.IGNORECASE)

            if matches:
                # Prefer the one that's not a note/exhibit
                for match in matches:
                    if not re.search(r'(ex|exhibit|note|toc)', match, re.IGNORECASE):
                        # Construct full URL
                        doc_url = urljoin(filing_index_url, match)
                        logger.info(f"Found 10-Q document: {doc_url}")
                        return doc_url

                # If all have exhibit/note, just use first
                doc_url = urljoin(filing_index_url, matches[0])
                logger.info(f"Found 10-Q document (from exhibits): {doc_url}")
                return doc_url

            logger.warning(f"No 10-Q document found in index")
            return None

        except Exception as e:
            logger.error(f"Error fetching 10-Q document URL: {e}")
            return None

    def fetch_10q_text(self, use_cache: bool = True) -> Optional[str]:
        """
        Fetch the latest 10-Q filing and return as plain text.
        Checks local cache first. If no cache and SEC is blocked, uses yfinance fallback.
        """
        # Check cache first
        cache_file = EDGAR_CACHE_DIR / f"{self.ticker}_10q_latest.txt"
        if use_cache and cache_file.exists():
            age_hours = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).total_seconds() / 3600
            if age_hours < 7 * 24:  # Use cache if less than 7 days old
                logger.info(f"Using cached 10-Q for {self.ticker} ({age_hours:.1f}h old)")
                return cache_file.read_text(encoding='utf-8', errors='ignore')

        try:
            # Try online fetch first
            filing_index_url = self.get_latest_10q_url()
            if filing_index_url:
                doc_url = self.get_10q_document_url(filing_index_url)
                if doc_url:
                    logger.info(f"Downloading 10-Q for {self.ticker}...")
                    r = self.session.get(doc_url, timeout=30)
                    r.raise_for_status()

                    # Extract text from HTML
                    text = r.text

                    # Clean up HTML
                    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<[^>]+>', '\n', text)
                    text = re.sub(r'\n\s*\n', '\n', text)
                    text = re.sub(r' +', ' ', text)

                    logger.info(f"Successfully fetched 10-Q ({len(text)} chars)")

                    # Cache it
                    cache_file.write_text(text, encoding='utf-8')
                    return text

            # If SEC is blocked, use yfinance fallback
            logger.warning(f"SEC EDGAR blocked or filing not found. Using yfinance data fallback for {self.ticker}")
            return self._create_yfinance_fallback()

        except Exception as e:
            logger.warning(f"Error fetching 10-Q text: {e}. Falling back to yfinance.")
            return self._create_yfinance_fallback()

    def _create_yfinance_fallback(self) -> Optional[str]:
        """
        Create synthetic 10-Q-like text from yfinance quarterly data.
        Not a real 10-Q, but provides MD&A and revenue sections for analysis.
        """
        try:
            import yfinance as yf

            logger.info(f"Fetching quarterly data from yfinance for {self.ticker}...")
            t = yf.Ticker(self.ticker)

            # Get quarterly financials
            info = t.info
            quarterly_financials = t.quarterly_financials

            if quarterly_financials is None or len(quarterly_financials.columns) == 0:
                logger.warning(f"No quarterly financials available for {self.ticker}")
                return None

            # Build synthetic MD&A-like text from available data
            text = f"""
FORM 10-Q QUARTERLY REPORT
Company: {self.ticker}
Generated from yfinance data (not official SEC filing)

ITEM 2. MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS

RESULTS OF OPERATIONS

Total Revenue
"""

            # Add revenue data
            if 'Total Revenue' in quarterly_financials.index:
                revenues = quarterly_financials.loc['Total Revenue']
                if len(revenues) > 0:
                    text += f"\nCurrent Quarter Revenue: ${revenues.iloc[0]:,.0f}\n"
                    if len(revenues) > 1:
                        text += f"Prior Year Quarter Revenue: ${revenues.iloc[1]:,.0f}\n"
                        yoy_growth = ((revenues.iloc[0] - revenues.iloc[1]) / revenues.iloc[1]) * 100
                        text += f"Year-over-Year Growth: {yoy_growth:.1f}%\n"

            # Add other financial metrics
            for metric in ['Operating Income', 'Net Income', 'Gross Profit', 'Operating Expense']:
                if metric in quarterly_financials.index:
                    val = quarterly_financials.loc[metric, quarterly_financials.columns[0]]
                    text += f"\n{metric}: ${val:,.0f}"

            text += "\n\nITEM 1A. RISK FACTORS\n\n"
            text += f"Market risks and operational risks are inherent to {self.ticker}'s business.\n"

            # Add analyst data if available
            if 'targetMeanPrice' in info:
                text += f"\nAnalyst Target Price: ${info.get('targetMeanPrice', 'N/A')}\n"
            if 'recommendationKey' in info:
                text += f"Analyst Recommendation: {info.get('recommendationKey', 'N/A')}\n"

            logger.info(f"Created yfinance fallback document ({len(text)} chars)")
            return text

        except Exception as e:
            logger.error(f"Error creating yfinance fallback: {e}")
            return None

    def extract_mda(self, text: str) -> Optional[str]:
        """Extract MD&A (Item 2) from 10-Q text."""
        if not text:
            return None

        # Look for "Item 2" or "ITEM 2" (10-Q format varies)
        # Stop at "Item 3" or "ITEM 3"
        pattern = r'(?:Item\s+2|ITEM\s+2).*?(?:Item\s+3|ITEM\s+3|$)'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)

        if match:
            mda = match.group(0)
            # Remove the "Item 3" part if matched
            mda = re.sub(r'(?:Item\s+3|ITEM\s+3).*$', '', mda, flags=re.DOTALL | re.IGNORECASE)
            logger.info(f"Extracted MD&A ({len(mda)} chars)")
            return mda.strip()

        logger.warning("Could not find MD&A section")
        return None

    def extract_risk_factors(self, text: str) -> Optional[str]:
        """Extract Risk Factors (Item 1A) from 10-Q text."""
        if not text:
            return None

        # Look for "Item 1A" or "Risk Factors"
        pattern = r'(?:Item\s+1A|Risk\s+Factors).*?(?:Item\s+1B|Item\s+2|$)'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)

        if match:
            risks = match.group(0)
            # Remove the next item if matched
            risks = re.sub(r'(?:Item\s+1B|Item\s+2).*$', '', risks, flags=re.DOTALL | re.IGNORECASE)
            logger.info(f"Extracted Risk Factors ({len(risks)} chars)")
            return risks.strip()

        logger.warning("Could not find Risk Factors section")
        return None

    def extract_revenue_data(self, text: str) -> Optional[Dict]:
        """
        Extract revenue and segment data from 10-Q text.
        Looks for revenue tables and comparative financial data.
        """
        if not text:
            return None

        data = {
            'total_revenue': None,
            'segments': {},
            'yoy_growth': None,
            'qoq_growth': None,
        }

        try:
            # Look for revenue mentions with numbers
            # Pattern: "Revenue" or "Revenues" followed by dollar amounts
            revenue_pattern = r'(?:Total\s+)?[Rr]evenue[s]?\s+[:\-\s]*(\$[\d,]+)'
            matches = re.findall(revenue_pattern, text[:5000])  # Look in first 5000 chars

            if matches:
                # Extract first revenue number (usually total)
                revenue_str = matches[0].replace('$', '').replace(',', '')
                try:
                    data['total_revenue'] = float(revenue_str) * 1_000_000 if 'M' in matches[0] else float(revenue_str)
                except:
                    pass

            # Look for segment revenue
            # Pattern: "Cloud Services: $XXM" or similar
            segment_pattern = r'([A-Z][a-zA-Z\s]+[Ss]ervices|[A-Z][a-zA-Z\s]+Products?)\s*[:\-\s]*\$?([\d,]+)[M]?'
            segment_matches = re.findall(segment_pattern, text[:10000])

            for segment_name, segment_revenue in segment_matches:
                try:
                    seg_val = float(segment_revenue.replace(',', ''))
                    data['segments'][segment_name.strip()] = seg_val
                except:
                    pass

            # Look for growth rates (e.g., "growth of 40%" or "+40%")
            growth_pattern = r'(?:growth|increase|decline)\s+(?:of\s+)?([+-]?\d+(?:\.\d+)?)\s*%'
            growth_matches = re.findall(growth_pattern, text[:10000], re.IGNORECASE)

            if growth_matches:
                try:
                    data['yoy_growth'] = float(growth_matches[0])
                except:
                    pass

            logger.info(f"Extracted revenue data: {data}")
            return data

        except Exception as e:
            logger.error(f"Error extracting revenue data: {e}")
            return data

    def analyze(self) -> Dict:
        """
        Full analysis: fetch 10-Q, extract all sections, return structured data.
        """
        text = self.fetch_10q_text()
        if not text:
            return {'error': f'Could not fetch 10-Q for {self.ticker}'}

        return {
            'ticker': self.ticker,
            'cik': self.cik,
            'fetched_at': datetime.now().isoformat(),
            'text_length': len(text),
            'mda': self.extract_mda(text),
            'risk_factors': self.extract_risk_factors(text),
            'revenue_data': self.extract_revenue_data(text),
        }
