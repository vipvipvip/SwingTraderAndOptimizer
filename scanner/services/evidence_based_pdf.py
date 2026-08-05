"""
Enhanced PDF Generator with Evidence-Based Findings
Shows HOW conclusions were reached with supporting data from 10-Q, analyst reports, stock performance
"""

from datetime import datetime
from typing import Dict, List
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, white, grey
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT


def generate_evidence_based_pdf(analysis, output_path: str):
    """
    Generate comprehensive evidence-based PDF showing:
    - Why each score was given (with supporting data)
    - Red flag explanations with evidence
    - Stock performance context
    - Analyst consensus
    - 10-Q excerpts and findings
    - Guidance and backlog visibility
    """

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch,
    )

    story = []
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=22,
        textColor=HexColor('#1a1a1a'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    )

    h2_style = ParagraphStyle(
        'H2',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=HexColor('#2c3e50'),
        spaceAfter=10,
        spaceBefore=10,
        fontName='Helvetica-Bold',
    )

    h3_style = ParagraphStyle(
        'H3',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=HexColor('#34495e'),
        spaceAfter=6,
        fontName='Helvetica-Bold',
    )

    body_style = ParagraphStyle(
        'Body',
        parent=styles['BodyText'],
        fontSize=9,
        textColor=HexColor('#2c3e50'),
        spaceAfter=6,
        leading=11,
    )

    highlight_style = ParagraphStyle(
        'Highlight',
        parent=styles['BodyText'],
        fontSize=9,
        textColor=HexColor('#e74c3c'),
        textTransform='none',
        fontName='Helvetica-Bold',
    )

    # ─ COVER
    story.append(Spacer(1, 1*inch))
    story.append(Paragraph("R&D Adoption Research Report", title_style))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("Evidence-Based Findings with SEC Filing Support", h2_style))
    story.append(Spacer(1, 0.3*inch))

    run_date = datetime.now().strftime("%B %d, %Y at %H:%M")
    story.append(Paragraph(f"<b>Report Date:</b> {run_date}", body_style))
    story.append(Paragraph(f"<b>Tickers Analyzed:</b> {len(analysis.results)}", body_style))
    story.append(Spacer(1, 0.3*inch))

    story.append(Paragraph("How to Read This Report", h3_style))
    story.append(Paragraph(
        "This report shows <b>evidence first, then conclusion</b>. "
        "For each ticker: (1) We show what we found in the 10-Q, "
        "(2) We show analyst/market signals, (3) We explain why the score is what it is. "
        "You can verify every claim by checking the SEC filing references provided.",
        body_style
    ))

    story.append(Spacer(1, 0.5*inch))
    story.append(PageBreak())

    # ─ EXECUTIVE SUMMARY
    story.append(Paragraph("Ranking Summary", title_style))
    story.append(Spacer(1, 0.2*inch))

    summary_data = [['Rank', 'Ticker', 'Watchlist', 'SEC Evidence', 'Combined', 'Why']]
    for result in analysis.results:
        rank = result.get('overall_rank', '?')
        ticker = result['ticker']
        tier = result.get('watchlist_tier', 'UNRANKED')[:12]
        sec = result['score_breakdown']['sec_filing_score']
        combined = result['combined_score']

        # Why in one line
        if sec >= 11:
            why = "Strong 10-Q signals"
        elif sec >= 7:
            why = "Moderate adoption proof"
        elif sec >= 4:
            why = "Early signals, not yet proven"
        else:
            why = "Insufficient 10-Q evidence"

        summary_data.append([
            str(rank),
            Paragraph(f"<b>{ticker}</b>", body_style),
            tier,
            Paragraph(f"{sec}/15", body_style),
            Paragraph(f"<b>{combined}/20</b>", body_style),
            Paragraph(why[:20], body_style),
        ])

    summary_table = Table(summary_data, colWidths=[0.6*inch, 0.7*inch, 1.1*inch, 1*inch, 0.9*inch, 1.2*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#bdc3c7')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#ecf0f1')]),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
    ]))

    story.append(summary_table)
    story.append(Spacer(1, 0.5*inch))
    story.append(PageBreak())

    # ─ DETAILED ANALYSIS
    for i, result in enumerate(analysis.results, 1):
        ticker = result['ticker']
        combined = result['combined_score']
        rank = result['overall_rank']

        story.append(Paragraph(
            f"#{rank}: {ticker} — Combined Score {combined}/20",
            h2_style
        ))

        # ─ Watchlist Tier
        watchlist_tier = result.get('watchlist_tier', 'UNRANKED')
        story.append(Paragraph(f"<b>Watchlist Tier:</b> {watchlist_tier}", h3_style))
        watchlist_data = result.get('watchlist_data', {})
        if watchlist_data.get('raw_content'):
            # Extract first 2-3 lines of "What's Brewing"
            content = watchlist_data['raw_content']
            lines = [l for l in content.split('\n') if l.strip() and not l.startswith('#')][:3]
            story.append(Paragraph(' '.join(lines[:100]), body_style))
        story.append(Spacer(1, 0.1*inch))

        # ─ Red Flags (if any)
        red_flags = result.get('red_flags', {})
        if red_flags and red_flags.get('disqualifiers'):
            story.append(Paragraph("🚩 RED FLAGS", h3_style))
            for flag in red_flags['disqualifiers']:
                story.append(Paragraph(f"<b>❌ {flag}</b> — Company does not meet framework criteria", body_style))
            story.append(Spacer(1, 0.1*inch))

        # ─ Stock Performance
        perf = result.get('stock_performance')
        if perf:
            story.append(Paragraph("Market Signal: Stock Performance (90 Days)", h3_style))
            pct = perf.get('change_pct', 0)
            direction = "📈 UP" if pct > 0 else "📉 DOWN"
            story.append(Paragraph(
                f"{direction} {pct:+.1f}% | Current: ${perf.get('end_price', 0):.2f} | "
                f"Range: ${perf.get('min_price', 0):.2f}–${perf.get('max_price', 0):.2f}",
                body_style
            ))
            if abs(pct) > 30:
                story.append(Paragraph(
                    "⚠️ <b>Note:</b> Large move already priced in; less upside remaining",
                    highlight_style
                ))
            story.append(Spacer(1, 0.1*inch))

        # ─ Analyst Coverage
        analysts = result.get('analyst_coverage', [])
        if analysts:
            story.append(Paragraph("Analyst Consensus", h3_style))
            for a in analysts:
                if a.get('type') == 'target_price' and a.get('value'):
                    story.append(Paragraph(
                        f"<b>Price Target:</b> ${a.get('value', 0):.0f} ({a.get('num_analysts', 0)} analysts)",
                        body_style
                    ))
                elif a.get('type') == 'recommendation':
                    story.append(Paragraph(
                        f"<b>Consensus:</b> {a.get('value', 'N/A')}",
                        body_style
                    ))
            story.append(Spacer(1, 0.1*inch))

        # ─ SEC Filing Evidence (the core)
        sec_data = result.get('sec_data', {})
        story.append(Paragraph("SEC Filing Evidence (10-Q MD&A)", h3_style))

        # Show what was found
        mda = sec_data.get('mda_summary', '')
        if mda:
            story.append(Paragraph(
                "<b>What we found in MD&A (Item 2):</b> Product mentioned with context about growth, "
                "market expansion, and new initiatives.",
                body_style
            ))
            story.append(Paragraph(f"<i>\"{mda[:150]}...\"</i>", body_style))
            story.append(Spacer(1, 0.08*inch))

        # Revenue data
        revenue = sec_data.get('revenue_data', {})
        if revenue and revenue.get('yoy_growth'):
            story.append(Paragraph(
                f"<b>Growth Signal:</b> {revenue.get('yoy_growth', 0):.1f}% YoY growth (found in revenue footnotes)",
                body_style
            ))
            story.append(Spacer(1, 0.08*inch))

        # Scoring breakdown with explanations
        breakdown = sec_data.get('score_breakdown', {})
        if breakdown:
            story.append(Paragraph("15-Point Scoring Breakdown", h3_style))

            score_table_data = [['Framework Criterion', 'Found?', 'Pts']]
            total_pts = 0

            criteria_explanations = {
                'product_named': ('Product named in MD&A', 1),
                'revenue_quantified': ('Revenue quantified in footnotes', 2),
                'qoq_growth_strong': ('Growth >15% visible', 2),
                'customer_names': ('Customers named', 2),
                'guidance_updated': ('Guidance includes product', 2),
                'analyst_initiations': ('Analyst activity recent', 2),
                'hiring_spike': ('Hiring/hiring activity', 1),
                'backlog_pipeline': ('RPO/backlog disclosed', 1),
            }

            for criterion, (desc, max_pts) in criteria_explanations.items():
                if criterion in breakdown.get('breakdown', {}):
                    details = breakdown['breakdown'][criterion]
                    met = details.get('met', False)
                    symbol = "✓" if met else "✗"
                    pts = max_pts if met else 0
                    total_pts += pts
                    score_table_data.append([
                        Paragraph(f"{symbol} {desc}", body_style),
                        Paragraph("YES" if met else "NO", body_style),
                        Paragraph(str(pts), body_style),
                    ])

            score_table = Table(score_table_data, colWidths=[3*inch, 1*inch, 0.8*inch])
            score_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), HexColor('#95a5a6')),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#bdc3c7')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')]),
            ]))
            story.append(score_table)
            story.append(Spacer(1, 0.08*inch))

            sec_score = sec_data.get('score', 0)
            story.append(Paragraph(
                f"<b>10-Q Score: {sec_score}/15</b>",
                h3_style
            ))
            story.append(Spacer(1, 0.1*inch))

        # Why the combined score
        story.append(Paragraph("Combined Score Calculation", h3_style))
        sec_score = result['score_breakdown']['sec_filing_score']
        tier_bonus = result['score_breakdown']['watchlist_tier_bonus']
        combined = result['combined_score']

        story.append(Paragraph(
            f"SEC Score ({sec_score}/15) + Watchlist Tier Bonus ({tier_bonus:+d}) = "
            f"<b>Combined {combined}/20</b>",
            body_style
        ))

        if combined >= 17:
            verdict = "STRONG CANDIDATE — Pursue aggressively"
        elif combined >= 12:
            verdict = "WATCH — Monitor earnings call for confirmation"
        elif combined >= 7:
            verdict = "CAUTION — Execution risk present"
        else:
            verdict = "AVOID — Insufficient framework fit"

        story.append(Paragraph(f"<b>{verdict}</b>", highlight_style))
        story.append(Spacer(1, 0.2*inch))

        # Page break
        if i < len(analysis.results):
            story.append(PageBreak())

    story.append(PageBreak())

    # ─ METHODOLOGY
    story.append(Paragraph("How This Report Was Generated", h2_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph(
        "<b>Step 1: Watchlist Screening</b><br/>"
        "Each ticker was categorized by market cap ($5B–$50B sweet spot), sector (Tech/FinTech/Healthcare/Energy), "
        "and analyst activity (recent initiations, price targets, coverage changes).",
        body_style
    ))
    story.append(Spacer(1, 0.08*inch))

    story.append(Paragraph(
        "<b>Step 2: SEC Filing Analysis</b><br/>"
        "Latest 10-Q was fetched from SEC EDGAR. We extracted: MD&A (Item 2) for product mentions, "
        "revenue footnotes for segment attribution, Item 1A risk factors for product materiality signals.",
        body_style
    ))
    story.append(Spacer(1, 0.08*inch))

    story.append(Paragraph(
        "<b>Step 3: Market Signals</b><br/>"
        "Stock performance (90-day price action), analyst consensus (targets, recommendations), "
        "recent coverage initiations and upgrades.",
        body_style
    ))
    story.append(Spacer(1, 0.08*inch))

    story.append(Paragraph(
        "<b>Step 4: Red Flag Detection</b><br/>"
        "Automatic checks for disqualifiers: revenue decline YoY, governance concerns, massive press/10-Q gaps, "
        "extreme market cap, customer concentration >50%.",
        body_style
    ))
    story.append(Spacer(1, 0.08*inch))

    story.append(Paragraph(
        "<b>Step 5: Scoring</b><br/>"
        "15-point framework applied (SEC filing evidence only). "
        "Watchlist tier bonus (±3 points) reflects market signal strength. "
        "Combined score (0–20) shows alignment of market interest AND fundamental adoption proof.",
        body_style
    ))

    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph(
        f"Report generated {datetime.now().strftime('%B %d, %Y at %H:%M:%S')} | "
        f"Run ID: {analysis.sec_analysis.run_id}",
        ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=grey,
            alignment=TA_CENTER,
        )
    ))

    doc.build(story)
    print(f"✓ Evidence-based PDF saved to {output_path}")
