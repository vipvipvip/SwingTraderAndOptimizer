# Advanced R&D Adoption Research

Extends comprehensive research with advanced signals from the VSCODE automation framework:
- Red flag detection (governance, revenue decline, press gaps)
- Stock performance tracking (90-day momentum)
- Analyst coverage (targets, recommendations, recent initiations)
- Earnings call analysis (customer mentions, CEO escalation)
- RPO/backlog extraction (remaining obligations)
- Forward guidance parsing
- Tracking log (analysis evolution over time)

## Features Added

### 1. Red Flag Detection

**Immediate Disqualifiers** (Auto-reject):

```
❌ Revenue declining YoY while product heavily hyped
❌ Governance concerns (auditor changes, executive indictments, restatements)
❌ Major press/10-Q gap (press hyped product but 10-Q shows zero revenue)
❌ Market cap >$200B (framework breaks down; market watches too closely)
❌ Market cap <$2B (illiquidity, execution risk too high)
❌ Pre-revenue with vague timeline (2+ years)
❌ Customer concentration >50% with single customer
```

**Caution Flags** (Monitor, don't auto-reject):

```
⚠️ Product in guidance but NOT yet in MD&A
⚠️ Recent analyst initiation/upgrade (price may already reflect thesis)
⚠️ Stock up >30% in past 3 months (some upside already realized)
⚠️ Execution risk visible in 10-Q (FDA, competitive pressure, supply chain)
```

**Positive Signals** (Increase score):

```
✅ Product named in MD&A with specific revenue number
✅ Customer names disclosed in 10-Q
✅ QoQ growth accelerating for new product
✅ Guidance explicitly updated for product
✅ Job hiring spike for implementation roles (predicts revenue 4-8 weeks out)
✅ Risk factors mention product adoption challenges (shows materiality)
```

### 2. Stock Performance Tracking

Monitors price action over 90 days:
- % change (📈 up or 📉 down)
- Current price
- 90-day high/low range
- Volatility (standard deviation)

**Red Flag:** Stock up >30% + new analyst initiation = upside may be realized already

**Positive Signal:** Stock flat or down + strong 10-Q score = contrarian opportunity

### 3. Analyst Coverage

Tracks:
- Average price target
- Number of analysts covering
- Recent recommendation (Buy/Hold/Sell)
- Recent initiations/upgrades

**Red Flag:** Analyst just initiated; price may already reflect bull case

**Positive Signal:** Multiple analyst coverage with consistent upgrades = market aligning with thesis

### 4. Earnings Call Analyzer

Extracts from earnings transcripts (when available):
- Customer name mentions (extracted from call)
- Deployment scale ("We have 150 customers piloting...")
- CEO language escalation (comparing Q-over-Q language intensity)
- Product-specific metrics (not in 10-Q)

**Note:** Earnings call fetching is TODO (requires SeekingAlpha API or similar)

### 5. RPO/Backlog Extraction

Remaining Performance Obligations = future revenue already committed (but not yet recognized).

From 10-Q:
```
Remaining Performance Obligations (RPO): $2.3B
- Short-term (current year): $1.1B
- Long-term (>1 year): $1.2B
```

**Positive Signal:** RPO growing faster than revenue = adoption acceleration coming

### 6. Forward Guidance

Extracts guidance statements from MD&A:
- "We expect [product] revenue to grow 30% in FY2027"
- "Guidance includes $X contribution from [product]"

**Positive Signal:** Explicit product guidance = management confidence in numbers

### 7. Tracking Log

Tracks analysis over time:

```
# BDX Tracking Log

## Aug 1, 2026
- Score: 3-4/15
- Verdict: WATCH/EARLY
- Notes: Products NOT yet in 10-Q, watch Q2 earnings

## Aug 6, 2026 (Post-Earnings)
- Score: 5-6/15
- Verdict: WATCH
- Notes: Earnings call confirmed Incada traction, not yet in revenue attribution
- Action: Re-score after next 10-Q update
```

Shows:
- Verdict evolution (Initial → After Earnings → After 10-Q update)
- Score changes quarter-over-quarter
- What changed and why
- Next trigger/catalyst

## Usage

All features are automatically integrated into `comprehensive_research.py`:

```bash
python3 services/comprehensive_research.py \
  --watchlist /home/dikesh/Downloads/Filtered_Watchlist_Analysis.md \
  --output /tmp/advanced_analysis.pdf
```

PDF output includes:
- Red flags (if any)
- Stock performance (90-day % change)
- Analyst coverage (target price, recommendation)
- RPO/backlog (if available)
- Forward guidance (if found)
- Stock performance chart context

## Example Output

```
Analysis #1: AXON | Combined Score: 14/20 | Tier: HIGH-PRIORITY

🚩 RED FLAGS DETECTED
(none - PASSED red flag check)

Stock Performance (90 Days)
📈 +6.3% | Price: $168.50 | Range: $155.00-$172.00

Analyst Coverage
Target Price: $724 (Piper Sandler), $750 (Needham)
Recommendation: Buy

Backlog & Obligations
RPO: $2.3B (growing at 15% YoY)

Forward Guidance
• "We expect Medication Management Solutions to accelerate in H2 2026"
• "New product deployments tracking ahead of plan"

SEC Filing Score Breakdown
✓ Product named: Drone/AI analytics (1 pt)
✓ Revenue growth: +40% (2 pts)
✓ Customer disclosure: Government contracts (2 pts)
...
```

## Data Sources

Current implementation uses:
- **10-Q/MD&A:** SEC EDGAR via sec_edgar.py (with yfinance fallback)
- **Stock Performance:** yfinance
- **Analyst Coverage:** yfinance (`info['targetMeanPrice']`, `info['recommendationKey']`)
- **Earnings Calls:** TODO (currently not fetching)
- **RPO/Backlog:** Parsed from 10-Q text (regex extraction)
- **Guidance:** Parsed from 10-Q MD&A text

Future enhancements:
- Earnings call transcripts (SeekingAlpha or Seeking Alpha API)
- LinkedIn job posting spikes (custom scraper)
- Press release dates (NewsAPI)
- Governance changes (10-K Item 8A auditor changes, Item 11 security matters)

## Integration with Watchlist

Red flags + analyst coverage + stock performance combined with watchlist tier:

```
Watchlist Tier: HIGH-PRIORITY
Stock: Up 6.3% in 90 days (modest momentum)
Analysts: Recent upgrades (Piper, Needham)
Red Flags: PASSED (no disqualifiers)
SEC Score: 11/15 (adoption signals visible)

Combined: 14/20 → WATCH → "Monitor earnings for product revenue attribution"
```

Tells you: Market is interested (analyst upgrades, stock up), but execution risk still exists. Wait for earnings confirmation.

## Scoring Impact

Red flags subtract points:
- Disqualifier → Auto-reject (score capped at <5)
- Caution flags → Reduce score by 1-2 points
- Positive signals → Boost score by 1-3 points

Example:
```
Base SEC Score: 11/15
+ Guidance includes product: +1
+ RPO growing 20%: +1
- Stock already up 35% (upside priced in): -1
- Analyst just initiated (early): -1

Adjusted: 11/15
Then watchlist tier bonus: +3 (HIGH-PRIORITY)
Combined: 14/20
```

## Next Steps / TODOs

- [ ] Implement earnings call transcript fetching (SeekingAlpha API)
- [ ] Add LinkedIn job posting spike detection (hiring predictor)
- [ ] Extract auditor changes from 10-K Item 8A
- [ ] Auto-fetch governance risk flags
- [ ] Build tracking log database (historical score tracking)
- [ ] Implement auto-email on red flag detection
- [ ] Create watchlist auto-rebalancing based on scores

## Files

- `scanner/services/advanced_research.py` — All advanced feature classes
- `scanner/services/comprehensive_research.py` — Integration point
- `scanner/services/sec_research_pdf.py` — Enhanced PDF output
- `scanner/services/advanced_research.md` — This file
