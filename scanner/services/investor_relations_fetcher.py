#!/usr/bin/env python3
"""
Investor Relations 10-Q Fetcher
Fetches 10-Q filings directly from company investor relations websites
(no SEC EDGAR rate limiting)
"""

import requests
import re
import logging
from datetime import datetime
from typing import Optional
from pathlib import Path
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / '.sec_edgar_cache'
CACHE_DIR.mkdir(exist_ok=True)

# Company name to ticker mapping
COMPANY_NAMES = {
    'AXON': 'Axon Enterprise',
    'AAPL': 'Apple',
    'MSFT': 'Microsoft',
    'NVDA': 'NVIDIA',
    'BDX': 'Becton Dickinson',
    'DUOL': 'Duolingo',
    'MNDY': 'monday.com',
    'AKAM': 'Akamai',
    'SMCI': 'Super Micro Computer',
    'ASTS': 'AST SpaceMobile',
}

# Common IR domain patterns to try
IR_DOMAIN_PATTERNS = [
    'investor.{domain}',
    'ir.{domain}',
    'investors.{domain}',
    '{domain}/investor-relations',
    '{domain}/investors',
]


class InvestorRelationsFetcher:
    """Fetch 10-Q from company investor relations website."""

    def __init__(self, ticker: str):
        self.ticker = ticker.upper()
        self.company_name = COMPANY_NAMES.get(ticker, ticker)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                         '(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def find_ir_website(self) -> Optional[str]:
        """
        Find company's investor relations website.
        Try common patterns first, then search.
        """
        logger.info(f"Finding IR website for {self.ticker}...")

        # Try common patterns
        company_domain = self.ticker.lower()

        patterns = [
            f'investor.{company_domain}.com',
            f'ir.{company_domain}.com',
            f'investors.{company_domain}.com',
            f'{company_domain}.com/investor-relations',
            f'{company_domain}.com/investors',
        ]

        for pattern in patterns:
            url = f'https://{pattern}' if not pattern.startswith('http') else pattern
            try:
                r = self.session.head(url, timeout=5, allow_redirects=True)
                if r.status_code < 400:
                    logger.info(f"Found IR website: {url}")
                    return url
            except:
                pass

        # If patterns don't work, try common full names
        common_domains = {
            'AXON': 'investor.axon.com',
            'AAPL': 'investor.apple.com',
            'MSFT': 'investor.microsoft.com',
            'NVDA': 'investor.nvidia.com',
            'BDX': 'investor.bd.com',
            'DUOL': 'investor.duolingo.com',
            'MNDY': 'investor.monday.com',
            'AKAM': 'investor.akamai.com',
            'SMCI': 'investor.supermicro.com',
            'ASTS': 'investor.asts.space',
        }

        url = f"https://{common_domains.get(self.ticker, '')}"
        if url != "https://":
            try:
                r = self.session.head(url, timeout=5, allow_redirects=True)
                if r.status_code < 400:
                    logger.info(f"Found IR website: {url}")
                    return url
            except:
                pass

        logger.warning(f"Could not find IR website for {self.ticker}")
        return None

    def find_10q_link(self, ir_url: str) -> Optional[str]:
        """
        Search IR website for latest 10-Q filing link.
        Returns the actual 10-Q document URL, not just the index page.
        """
        try:
            logger.info(f"Searching {ir_url} for 10-Q...")
            r = self.session.get(ir_url, timeout=10)
            r.raise_for_status()

            # First try to find direct 10-Q document links (.htm, .html files)
            patterns = [
                r'href="([^"]*?10-q[^"]*?\.htm[l]?)"',
                r'href="([^"]*?10-Q[^"]*?\.htm[l]?)"',
            ]

            for pattern in patterns:
                matches = re.findall(pattern, r.text, re.IGNORECASE)
                if matches:
                    link = matches[0]
                    full_url = urljoin(ir_url, link)
                    logger.info(f"Found 10-Q document link: {full_url}")
                    return full_url

            # If no direct link, look for SEC filings index page
            sec_filing_patterns = [
                r'href="([^"]*?sec-filings?[^"]*)"',
                r'href="([^"]*?sec-filing[^"]*)"',
                r'href="([^"]*?filings[^"]*)"',
            ]

            for pattern in sec_filing_patterns:
                matches = re.findall(pattern, r.text, re.IGNORECASE)
                if matches:
                    link = matches[0]
                    full_url = urljoin(ir_url, link)
                    logger.info(f"Found SEC filings page: {full_url}")

                    # Fetch the filings page and look for 10-Q documents there
                    try:
                        r2 = self.session.get(full_url, timeout=10)
                        doc_patterns = [
                            r'href="([^"]*?10-q[^"]*?\.htm[l]?)"',
                            r'href="([^"]*?10-Q[^"]*?\.htm[l]?)"',
                        ]
                        for doc_pattern in doc_patterns:
                            doc_matches = re.findall(doc_pattern, r2.text, re.IGNORECASE)
                            if doc_matches:
                                doc_link = doc_matches[0]
                                doc_url = urljoin(full_url, doc_link)
                                logger.info(f"Found 10-Q document in filings page: {doc_url}")
                                return doc_url
                    except:
                        pass

                    # Return filings page if no direct doc found (will fetch lists)
                    return full_url

            logger.warning(f"Could not find 10-Q link on {ir_url}")
            return None

        except Exception as e:
            logger.error(f"Error searching IR website: {e}")
            return None

    def fetch_10q_text(self) -> Optional[str]:
        """
        Fetch 10-Q from IR website and return as text.
        """
        # Check cache first
        cache_file = CACHE_DIR / f"{self.ticker}_10q_ir.txt"
        if cache_file.exists():
            age_hours = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).total_seconds() / 3600
            if age_hours < 7 * 24:  # 7 day cache
                logger.info(f"Using cached IR 10-Q for {self.ticker} ({age_hours:.1f}h old)")
                return cache_file.read_text(encoding='utf-8', errors='ignore')

        try:
            # Find IR website
            ir_url = self.find_ir_website()
            if not ir_url:
                logger.warning(f"No IR website found for {self.ticker}")
                return None

            # Find 10-Q link
            filing_link = self.find_10q_link(ir_url)
            if not filing_link:
                logger.warning(f"No 10-Q link found on {ir_url}")
                return None

            # Download 10-Q
            logger.info(f"Downloading 10-Q from {filing_link}...")
            r = self.session.get(filing_link, timeout=30)
            r.raise_for_status()

            text = r.text

            # Clean up HTML
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '\n', text)
            text = re.sub(r'\n\s*\n', '\n', text)
            text = re.sub(r' +', ' ', text)

            logger.info(f"Successfully fetched 10-Q from IR website ({len(text)} chars)")

            # Cache it
            cache_file.write_text(text, encoding='utf-8')

            return text

        except Exception as e:
            logger.error(f"Error fetching 10-Q from IR website: {e}")
            return None

    def extract_mda(self, text: str) -> Optional[str]:
        """Extract MD&A (Item 2) from 10-Q text."""
        if not text:
            return None

        pattern = r'(?:Item\s+2|ITEM\s+2).*?(?:Item\s+3|ITEM\s+3|$)'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)

        if match:
            mda = match.group(0)
            mda = re.sub(r'(?:Item\s+3|ITEM\s+3).*$', '', mda, flags=re.DOTALL | re.IGNORECASE)
            logger.info(f"Extracted MD&A from IR 10-Q ({len(mda)} chars)")
            return mda.strip()

        logger.warning("Could not find MD&A in IR 10-Q")
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
            logger.info(f"Extracted Risk Factors from IR 10-Q ({len(risks)} chars)")
            return risks.strip()

        logger.warning("Could not find Risk Factors in IR 10-Q")
        return None

    def extract_revenue_data(self, text: str) -> dict:
        """Extract revenue and segment data from 10-Q."""
        if not text:
            return {}

        data = {
            'total_revenue': None,
            'segments': {},
            'yoy_growth': None,
            'source': 'IR website',
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
            growth_pattern = r'(?:increased|grew|growth)\s+(?:by\s+)?([+-]?\d+(?:\.\d+)?)\s*%'
            growth_matches = re.findall(growth_pattern, text[:10000], re.IGNORECASE)

            if growth_matches:
                try:
                    data['yoy_growth'] = float(growth_matches[0])
                except:
                    pass

            logger.info(f"Extracted revenue data from IR 10-Q: {data}")
            return data

        except Exception as e:
            logger.error(f"Error extracting revenue data: {e}")
            return data
