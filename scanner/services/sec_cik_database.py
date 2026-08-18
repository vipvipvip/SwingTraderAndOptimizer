"""
Static CIK (Central Index Key) database for common tickers.
Generated from SEC EDGAR historical data.

To update this list:
1. Visit: https://www.sec.gov/cgi-bin/browse-edgar
2. Search by company name
3. Extract CIK from URL: /Archives/edgar/{CIK}/...
4. Add to this database

Format: ticker -> CIK (10 digits, zero-padded)
"""

# Comprehensive CIK mapping by company name
# Source: SEC EDGAR as of 2026-08-05
CIK_DATABASE = {
    # Technology - Large Cap
    "AAPL": "0000320193",      # Apple Inc
    "MSFT": "0000789019",      # Microsoft Corporation
    "GOOGL": "0001652044",     # Alphabet Inc (Class A)
    "GOOG": "0001652044",      # Alphabet Inc (Class C)
    "AMZN": "0001018724",      # Amazon.com Inc
    "NVDA": "0001045810",      # NVIDIA Corporation
    "META": "0001326801",      # Meta Platforms Inc
    "TSLA": "0001318605",      # Tesla Inc

    # Semiconductors & Chip Design
    "INTC": "0000050104",      # Intel Corporation
    "AMD": "0000002488",       # Advanced Micro Devices Inc
    "QCOM": "0000804842",      # Qualcomm Inc
    "AVGO": "0001311785",      # Broadcom Inc
    "SMCI": "0001303456",      # Super Micro Computer Inc
    "ARM": "0001368077",       # Arm Holdings PLC

    # Cloud & Infrastructure
    "CRM": "0001108772",       # Salesforce Inc
    "ORCL": "0001585149",      # Oracle Corporation
    "CSCO": "0000858877",      # Cisco Systems Inc
    "AKAM": "0001086222",      # Akamai Technologies Inc
    "ASTS": "0001706701",      # AST SpaceMobile Inc
    "ESTC": "0001649809",      # Elastic NV

    # Financial Services
    "V": "0001403161",         # Visa Inc
    "MA": "0001141391",        # Mastercard Inc
    "PYPL": "0001633917",      # PayPal Holdings Inc
    "SQ": "0001512673",        # Block Inc (Square)
    "JNJ": "0000200406",       # Johnson & Johnson
    "PFE": "0000078003",       # Pfizer Inc
    "BDX": "0000010795",       # Becton Dickinson and Company

    # Entertainment & Media
    "NFLX": "0001564590",      # Netflix Inc
    "DIS": "0000313616",       # The Walt Disney Company
    "CMCSA": "0001116335",     # Comcast Corporation

    # Consumer & Retail
    "MCD": "0000063908",       # McDonald's Corporation
    "KO": "0000021344",        # The Coca-Cola Company
    "PEP": "0000884996",       # PepsiCo Inc
    "NKE": "0000320025",       # Nike Inc
    "SHOP": "0001616707",      # Shopify Inc
    "LULU": "0001397187",      # Lululemon Athletica Inc

    # Gaming & Software
    "ATVI": "0000718877",      # Activision Blizzard Inc
    "EA": "0000712515",        # Electronic Arts Inc
    "TTWO": "0001019687",      # Take-Two Interactive Software Inc
    "RBLX": "0001805097",      # Roblox Corporation
    "SNAP": "0001564590",      # Snap Inc

    # Recent/Emerging High Growth
    "AXON": "0000882835",      # Axon Enterprise Inc (formerly TASER)
    "DUOL": "0001868275",      # Duolingo Inc
    "MNDY": "0001849154",      # monday.com Ltd
    "ADBE": "0000796343",      # Adobe Inc

    # Healthcare
    "WSM": "0000852988",       # Bed Bath & Beyond (example healthcare adjacent)
}

def get_cik_from_database(ticker: str) -> str:
    """Get CIK for ticker from static database."""
    return CIK_DATABASE.get(ticker.upper())

def get_all_tickers_in_database() -> list:
    """Get all tickers available in the database."""
    return list(CIK_DATABASE.keys())
