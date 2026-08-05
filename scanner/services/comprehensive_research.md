# Comprehensive R&D Adoption Research

Combines **watchlist screening** (market signals) with **SEC filing analysis** (fundamental proof) for holistic candidate evaluation.

## Strategy

Two layers of analysis:

**Layer 1: Watchlist Screening** (Market Signals)
- Market cap filtering ($5B-$50B sweet spot)
- Sector screening (Tech, FinTech, Healthcare, Energy)
- Analyst activity (recent upgrades, price targets)
- Recent announcements (board changes, contracts, partnerships)
- Tier ranking: HIGH-PRIORITY → SECONDARY → CAUTION → NON-FIT

**Layer 2: SEC Filing Analysis** (Fundamental Proof)
- 10-Q MD&A: product mentions
- Revenue attribution: segment breakouts
- Risk factors: product materiality
- Growth rates: Q-over-Q acceleration
- 15-point scoring framework

**Combined Score** (0-20)
- Reflects alignment: high combined score = watchlist tier + 10-Q support
- Not just market hype, but backed by filing evidence

## Scoring

### SEC Filing Score (0-15)
Standard 15-point framework applied to 10-Q data.

### Watchlist Tier Bonus/Penalty
| Tier | Bonus | Meaning |
|------|-------|---------|
| HIGH-PRIORITY | +3 | Market cap, sector, analyst activity all confirm adoption signal |
| SECONDARY | +1 | Promising, but needs deeper research |
| CAUTION | -2 | Red flags present (down 50%, profitability issues) |
| NON-FIT | -5 | Doesn't match framework (mega-cap, micro-cap, wrong sector) |
| UNRANKED | 0 | Not in watchlist |

### Combined Score Interpretation
- **17-20:** STRONG CANDIDATE
  - Watchlist confirms market signal
  - 10-Q shows adoption proof
  - Action: Pursue aggressively, position for earnings
  
- **12-16:** WATCH
  - Mixed signals (either market OR 10-Q strong, not both)
  - Action: Listen to earnings call closely
  
- **7-11:** CAUTION
  - Weak fundamental support despite market interest
  - Action: Wait for stronger signals
  
- **<7:** AVOID
  - Doesn't fit framework

## Usage

### Load Watchlist and Analyze
```bash
# Analyze all tickers in watchlist
python3 services/comprehensive_research.py \
  --watchlist /home/dikesh/Downloads/Filtered_Watchlist_Analysis.md \
  --output /tmp/comprehensive_report.pdf

# Analyze specific tickers from watchlist
python3 services/comprehensive_research.py \
  --watchlist /home/dikesh/Downloads/Filtered_Watchlist_Analysis.md \
  --tickers AXON,DUOL,MNDY \
  --output /tmp/earnings_watch.pdf

# Analyze any tickers (ignore watchlist)
python3 services/comprehensive_research.py \
  --tickers AAPL,MSFT,NVDA \
  --output /tmp/ad_hoc_research.pdf
```

### Command-Line Options

| Option | Description |
|--------|-------------|
| `--watchlist PATH` | Markdown file with watchlist (default: Downloads/Filtered_Watchlist_Analysis.md) |
| `--tickers TICK1,TICK2` | Comma-separated list to analyze (overrides watchlist) |
| `--output PATH` | PDF output file path |
| `--db-only` | Save to database only (no PDF) |

## PDF Report Structure

### Page 1: Cover
- Analysis date and methodology
- Total tickers analyzed

### Page 2: Executive Summary
**Ranked by combined score** with tier and SEC score visible:

```
Rank  Ticker  Watchlist Tier     SEC Score  Combined  Status
────────────────────────────────────────────────────────────
1.    AXON    HIGH-PRIORITY      11/15      14/20     WATCH
2.    DUOL    SECONDARY          8/15       9/20      CAUTION
3.    MNDY    SECONDARY          7/15       8/20      CAUTION
```

Shows which tickers align (watchlist tier + SEC score both strong).

### Pages 3+: Detailed Analysis Per Ticker

For each ticker:
1. **Watchlist Position** — Why it's in watchlist (market cap, sector, analyst activity)
2. **Watchlist Summary** — Key signals from watchlist (announcements, board changes, etc.)
3. **SEC Filing Score Breakdown** — 15-point matrix from 10-Q
4. **MD&A Highlights** — What management said
5. **Risk Factors** — Key risks disclosed

### Last Pages: Scoring Explanation
- How SEC score is calculated
- How watchlist tier bonus works
- What combined score means

## Real Example: AXON (from watchlist)

**From Watchlist Analysis:**
```
Tier: HIGH-PRIORITY
Market Cap: $39.6B (perfect mid-cap)
Sector: Enterprise SaaS (law enforcement tech)
Earnings: Aug 5, 2026
Signals: New drones product, analyst upgrades, board expansion
```

**From SEC 10-Q:**
```
MD&A mentions: "Connected Devices (cameras, drones) expanding"
Revenue: Software & Services segment driving growth
Risk Factors: Product-specific risks disclosed
Score: 11/15
```

**Combined Analysis:**
```
SEC Score: 11/15
Watchlist Tier: HIGH-PRIORITY (+3 bonus)
Combined: 14/20 → WATCH

Status: Market signals (HIGH-PRIORITY) align with 10-Q proof (11/15).
On Aug 5 earnings, listen for: "Drone revenue contribution," "deployment count,"
"government contracts specific to drones/AI analytics"
```

If earnings confirms, score upgrades to 16-17/20 (STRONG CANDIDATE).

## Integration with Earnings Calendar

1. **Watchlist tiers** identify promising mid-caps
2. **Earnings calendar** shows when they report
3. **SEC analysis** verifies adoption with 10-Q data
4. **Combined score** tells you which to position for

Example flow:
- Watchlist: AXON is HIGH-PRIORITY (market signal strong)
- Earnings Calendar: AXON reports Aug 5
- SEC Research: AXON scores 11/15 in 10-Q (adoption signals visible)
- Combined: 14/20 → Set watchlist for earnings, ready to listen for confirmation

## Files

- `scanner/services/comprehensive_research.py` — Main analysis engine
- `scanner/services/sec_research_pdf.py` — Enhanced PDF with watchlist integration
- `scanner/services/comprehensive_research.md` — This file

## Next Steps

1. **Load your watchlist:**
   ```bash
   python3 services/comprehensive_research.py \
     --watchlist /home/dikesh/Downloads/Filtered_Watchlist_Analysis.md \
     --output /tmp/full_watchlist_analysis.pdf
   ```

2. **Review PDF** → See which watchlist tickers have 10-Q support

3. **Earnings week** → Focus on HIGH-PRIORITY candidates with combined score 12+

4. **Track over time** → Results stored in `tbl_sec_research_analysis` for quarterly comparison

## Troubleshooting

### "Watchlist file not found"
Check path:
```bash
ls -l /home/dikesh/Downloads/Filtered_Watchlist_Analysis.md
```

### All tickers showing low SEC scores
- SEC EDGAR is rate-limited (yfinance fallback is slower)
- First run might not have cached 10-Q data
- Run again after a few minutes for faster results

### PDF is missing watchlist data
Ensure `--watchlist` flag points to the correct markdown file
