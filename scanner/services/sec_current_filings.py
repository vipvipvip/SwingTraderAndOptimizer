#!/usr/bin/env python3
"""
SEC Current Filings Fetcher
Fetches 10-Q documents from SEC's current filings feed
https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent
Much more efficient than hitting individual company sites
"""

import requests
import re
import logging
from datetime import datetime
from typing import Optional, Dict, List
from pathlib import Path
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / '.sec_edgar_cache'
CACHE_DIR.mkdir(exist_ok=True)

SEC_CURRENT_FILINGS_XML = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=10-Q&dateb=&owner=exclude&count=100&output=xml"
SEC_CURRENT_FILINGS_HTML = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=10-Q&dateb=&owner=exclude&count=100"


class SECCurrentFilingsFetcher:
    """Fetch 10-Q from SEC's current filings feed (single source for all tickers)."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.filings_cache = {}
        self.last_fetch = None

    def fetch_current_10qs(self) -> Dict[str, Dict]:
        """
        Fetch all current 10-Q filings from SEC in one call.
        Returns dict: {ticker: {cik, filing_date, accession, url, ...}}
        """
        logger.info("Fetching current 10-Q filings from SEC (XML feed)...")

        try:
            r = self.session.get(SEC_CURRENT_FILINGS_XML, timeout=30)
            r.raise_for_status()

            filings = {}

            # Try XML parsing first
            try:
                root = ET.fromstring(r.text)

                # XML structure: <feed><entry><title>, <link href=...>, <content>...</content></entry></feed>
                for entry in root.findall('.//{http://www.w3.org/2005/Atom}entry'):
                    # Get ticker/CIK from title
                    title_elem = entry.find('{http://www.w3.org/2005/Atom}title')
                    if title_elem is None:
                        continue

                    title = title_elem.text or ""

                    # Parse title format: "CompanyName (CIK: 0000123456) 10-Q 2026-08-05"
                    cik_match = re.search(r'CIK[:\s]+(\d+)', title)
                    ticker_match = re.search(r'\(([A-Z]+)\)', title)

                    if not cik_match:
                        continue

                    cik = cik_match.group(1).lstrip('0') or '0'

                    # Get filing link
                    link_elem = entry.find('{http://www.w3.org/2005/Atom}link')
                    if link_elem is None:
                        continue

                    filing_url = link_elem.get('href', '')

                    # Get filing date from summary
                    summary_elem = entry.find('{http://www.w3.org/2005/Atom}summary')
                    filing_date = None
                    if summary_elem is not None and summary_elem.text:
                        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', summary_elem.text)
                        if date_match:
                            filing_date = date_match.group(1)

                    # Get ticker from title if available
                    ticker = ticker_match.group(1) if ticker_match else None

                    if not ticker or not filing_url:
                        continue

                    filings[ticker] = {
                        'cik': cik,
                        'ticker': ticker,
                        'filing_date': filing_date,
                        'filing_url': filing_url,
                        'title': title,
                        'source': 'SEC current filings XML',
                    }

                    logger.info(f"Found {ticker}: {filing_url}")

            except ET.ParseError:
                # Fallback to HTML parsing if XML fails
                logger.warning("XML parsing failed, trying HTML fallback...")
                filings = self._parse_html_filings(r.text)

            logger.info(f"Fetched {len(filings)} current 10-Q filings from SEC")
            self.filings_cache = filings
            self.last_fetch = datetime.now()
            return filings

        except Exception as e:
            logger.error(f"Error fetching current 10-Qs from SEC: {e}")
            return {}

    def _parse_html_filings(self, html: str) -> Dict[str, Dict]:
        """Fallback HTML parser for SEC filings page."""
        filings = {}

        # Look for filing rows in HTML
        # Pattern: ticker in parentheses, followed by links
        ticker_pattern = r'\(([A-Z]{1,5})\).*?href="([^"]*?[/0-9]+/)"'

        for match in re.finditer(ticker_pattern, html, re.IGNORECASE | re.DOTALL):
            ticker = match.group(1)
            filing_url = urljoin("https://www.sec.gov", match.group(2))

            filings[ticker] = {
                'ticker': ticker,
                'filing_url': filing_url,
                'source': 'SEC HTML fallback',
            }

        return filings

    def get_10q_for_ticker(self, ticker: str) -> Optional[str]:
        """
        Get 10-Q for a specific ticker from the current filings feed.
        """
        # Refresh cache if empty or stale (1 hour)
        if (
            not self.filings_cache
            or not self.last_fetch
            or (datetime.now() - self.last_fetch).total_seconds() > 3600
        ):
            self.fetch_current_10qs()

        if ticker not in self.filings_cache:
            logger.warning(f"{ticker} not found in current SEC filings")
            return None

        filing_info = self.filings_cache[ticker]
        filing_url = filing_info.get('filing_url')

        if not filing_url:
            logger.warning(f"No filing URL for {ticker}")
            return None

        # Check cache first
        cache_file = CACHE_DIR / f"{ticker}_10q_sec_current.txt"
        if cache_file.exists():
            age_hours = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).total_seconds() / 3600
            if age_hours < 7 * 24:  # 7-day cache
                logger.info(f"Using cached 10-Q for {ticker} ({age_hours:.1f}h old)")
                return cache_file.read_text(encoding='utf-8', errors='ignore')

        # Fetch the filing index page
        try:
            logger.info(f"Fetching filing index for {ticker}: {filing_url}")
            r = self.session.get(filing_url, timeout=30)
            r.raise_for_status()

            # Find the actual 10-Q document link in the index
            doc_patterns = [
                r'href="([^"]*?10-q[^"]*?\.htm[l]?)"',
                r'href="([^"]*?0+[^"]*?\.htm[l]?)"',  # Sometimes named with zeros
            ]

            doc_url = None
            for pattern in doc_patterns:
                matches = re.findall(pattern, r.text, re.IGNORECASE)
                if matches:
                    doc_url = urljoin(filing_url, matches[0])
                    break

            if not doc_url:
                logger.warning(f"Could not find 10-Q document in index for {ticker}")
                return None

            # Download the actual 10-Q document
            logger.info(f"Downloading 10-Q document: {doc_url}")
            r = self.session.get(doc_url, timeout=30)
            r.raise_for_status()

            text = r.text

            # Clean up HTML
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '\n', text)
            text = re.sub(r'\n\s*\n', '\n', text)
            text = re.sub(r' +', ' ', text)

            logger.info(f"Successfully fetched 10-Q from SEC current filings ({len(text)} chars)")

            # Cache it
            cache_file.write_text(text, encoding='utf-8')

            return text

        except Exception as e:
            logger.error(f"Error fetching 10-Q for {ticker}: {e}")
            return None

    def extract_mda(self, text: str) -> Optional[str]:
        """Extract MD&A (Item 2) from 10-Q text."""
        if not text:
            return None

        pattern = r'(?:Item\s+2|ITEM\s+2|Management.*?Discussion).*?(?:Item\s+3|ITEM\s+3|$)'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)

        if match:
            mda = match.group(0)
            mda = re.sub(r'(?:Item\s+3|ITEM\s+3).*$', '', mda, flags=re.DOTALL | re.IGNORECASE)
            logger.info(f"Extracted MD&A ({len(mda)} chars)")
            return mda.strip()

        logger.warning("Could not find MD&A in 10-Q")
        return None

    def extract_risk_factors(self, text: str) -> Optional[str]:
        """Extract Risk Factors (Item 1A) from 10-Q text."""
        if not text:
            return None

        pattern = r'(?:Item\s+1A|Risk\s+Factors).*?(?:Item\s+1B|Item\s+2|$)'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)

        if match:
            risks = match.group(0)
            risks = re.sub(r'(?:Item\s+1B|Item\s+2).*$', '', risks, flags=re.DOTALL | re.IGNORECASE)
            logger.info(f"Extracted Risk Factors ({len(risks)} chars)")
            return risks.strip()

        logger.warning("Could not find Risk Factors in 10-Q")
        return None

    def extract_revenue_data(self, text: str) -> dict:
        """Extract revenue and segment data from 10-Q."""
        if not text:
            return {}

        data = {
            'total_revenue': None,
            'segments': {},
            'yoy_growth': None,
            'source': 'SEC current filings',
        }

        try:
            # Look for revenue figures
            revenue_pattern = r'(?:Total\s+)?[Rr]evenue[s]?\s*[:\-\s]*\$?([\d,]+(?:\.\d+)?)\s*[MB]?'
            matches = re.findall(revenue_pattern, text[:10000])

            if matches:
                try:
                    rev_str = matches[0].replace(',', '')
                    data['total_revenue'] = float(rev_str)
                except:
                    pass

            # Look for YoY growth
            growth_pattern = r'(?:increased|grew|growth|decline)\s+(?:by\s+)?([+-]?\d+(?:\.\d+)?)\s*%'
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
