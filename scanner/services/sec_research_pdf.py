"""
PDF Report Generator for SEC Research Analysis + Comprehensive Watchlist
Generates professional reports combining SEC filing analysis with watchlist screening.
"""

import os
from datetime import datetime
from typing import List, Dict
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, white, grey, lightgrey
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.platypus import KeepTogether
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import re


def generate_pdf(analysis, output_path: str):
    """
    Generate comprehensive PDF report for all tickers in analysis run.

    Structure:
    1. Cover page with run metadata
    2. Executive Summary (ranked candidates)
    3. Detailed Analysis per Ticker
    4. Board Comments Section
    5. Source References
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
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=HexColor('#1a1a1a'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    )

    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=HexColor('#2c3e50'),
        spaceAfter=10,
        spaceBefore=10,
        fontName='Helvetica-Bold',
    )

    subheading_style = ParagraphStyle(
        'CustomSubHeading',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=HexColor('#34495e'),
        spaceAfter=6,
        fontName='Helvetica-Bold',
    )

    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['BodyText'],
        fontSize=9,
        textColor=HexColor('#2c3e50'),
        spaceAfter=6,
        leading=11,
    )

    # ────────────────────────────────────────────────────────────────────
    # COVER PAGE
    # ────────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1.5*inch))
    story.append(Paragraph("SEC-Filing Research Analysis", title_style))
    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph(f"Earnings Event Analysis", heading_style))
    story.append(Spacer(1, 0.3*inch))

    # Metadata
    run_date = datetime.now().strftime("%B %d, %Y at %H:%M")
    story.append(Paragraph(f"<b>Report Date:</b> {run_date}", body_style))
    story.append(Paragraph(f"<b>Run ID:</b> {analysis.run_id}", body_style))
    story.append(Paragraph(f"<b>Tickers Analyzed:</b> {len(analysis.results)}", body_style))
    story.append(Spacer(1, 0.2*inch))

    # Methodology
    story.append(Paragraph("Methodology", subheading_style))
    story.append(Paragraph(
        "This analysis uses a 15-point SEC-filing-first framework, prioritizing "
        "10-Q/10-K MD&A disclosures as Tier 1 source material. Press releases, analyst "
        "reports, and news are cross-referenced to validate adoption signals.",
        body_style
    ))

    story.append(Spacer(1, 0.5*inch))
    story.append(PageBreak())

    # ────────────────────────────────────────────────────────────────────
    # EXECUTIVE SUMMARY (RANKINGS)
    # ────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Executive Summary: Candidate Rankings", title_style))
    story.append(Spacer(1, 0.2*inch))

    story.append(Paragraph(
        "Ranked by 15-point SEC-filing-first framework. Higher scores indicate stronger "
        "R&D adoption signals visible in 10-Q MD&A and footnotes.",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))

    # Build summary table
    summary_data = [['Rank', 'Ticker', 'Score', 'Earnings Date', 'Status']]

    for result in analysis.results:
        rank = result.get('rank', '?')
        ticker = result['ticker']
        score = result.get('score', 0)
        earnings = result.get('earnings_date', 'N/A')

        # Status badge
        if score >= 12:
            status = 'STRONG CANDIDATE'
        elif score >= 8:
            status = 'WATCH'
        elif score >= 5:
            status = 'CAUTION'
        else:
            status = 'AVOID'

        summary_data.append([
            str(rank),
            Paragraph(f"<b>{ticker}</b>", body_style),
            Paragraph(f"<b>{score}/15</b>", body_style),
            earnings,
            status,
        ])

    summary_table = Table(summary_data, colWidths=[0.8*inch, 1*inch, 1*inch, 1.5*inch, 1.5*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#34495e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#bdc3c7')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#ecf0f1')]),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))

    story.append(summary_table)
    story.append(Spacer(1, 0.3*inch))

    # ────────────────────────────────────────────────────────────────────
    # KEY FINDINGS BY SCORE TIER
    # ────────────────────────────────────────────────────────────────────
    strong = [r for r in analysis.results if r.get('score', 0) >= 12]
    watch = [r for r in analysis.results if 8 <= r.get('score', 0) < 12]
    caution = [r for r in analysis.results if 5 <= r.get('score', 0) < 8]
    avoid = [r for r in analysis.results if r.get('score', 0) < 5]

    if strong:
        story.append(Paragraph("🔥 Strong Candidates (Score ≥ 12/15)", subheading_style))
        for r in strong:
            text = f"<b>{r['ticker']}</b> ({r.get('score', 0)}/15) — {r.get('earnings_date', 'N/A')}"
            story.append(Paragraph(text, body_style))
        story.append(Spacer(1, 0.15*inch))

    if watch:
        story.append(Paragraph("👀 Watch (Score 8-11/15)", subheading_style))
        for r in watch:
            text = f"<b>{r['ticker']}</b> ({r.get('score', 0)}/15) — {r.get('earnings_date', 'N/A')}"
            story.append(Paragraph(text, body_style))
        story.append(Spacer(1, 0.15*inch))

    if caution:
        story.append(Paragraph("⚠️ Caution (Score 5-7/15)", subheading_style))
        for r in caution:
            text = f"<b>{r['ticker']}</b> ({r.get('score', 0)}/15) — {r.get('earnings_date', 'N/A')}"
            story.append(Paragraph(text, body_style))
        story.append(Spacer(1, 0.15*inch))

    if avoid:
        story.append(Paragraph("❌ Avoid (Score < 5/15)", subheading_style))
        for r in avoid:
            text = f"<b>{r['ticker']}</b> ({r.get('score', 0)}/15) — {r.get('earnings_date', 'N/A')}"
            story.append(Paragraph(text, body_style))

    story.append(PageBreak())

    # ────────────────────────────────────────────────────────────────────
    # DETAILED ANALYSIS PER TICKER
    # ────────────────────────────────────────────────────────────────────
    for i, result in enumerate(analysis.results, 1):
        ticker = result['ticker']
        score = result.get('score', 0)
        earnings_date = result.get('earnings_date', 'N/A')
        rank = result.get('rank', '?')

        story.append(Paragraph(
            f"Analysis #{rank}: {ticker} | Score: {score}/15 | Earnings: {earnings_date}",
            heading_style
        ))

        # Score breakdown
        breakdown = result.get('score_breakdown', {})
        if breakdown:
            story.append(Paragraph("Scoring Breakdown", subheading_style))

            breakdown_data = [['Criterion', 'Met?', 'Weight', 'Source']]
            for criterion, details in breakdown.get('breakdown', {}).items():
                met = '✓' if details.get('met') else '✗'
                weight = details.get('weight', 0)
                source = details.get('source', '—')
                breakdown_data.append([
                    criterion.replace('_', ' ').title(),
                    Paragraph(met, body_style),
                    Paragraph(str(weight), body_style),
                    Paragraph(source, body_style)
                ])

            breakdown_table = Table(breakdown_data, colWidths=[2*inch, 0.6*inch, 0.6*inch, 1.8*inch])
            breakdown_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), HexColor('#95a5a6')),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#bdc3c7')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')]),
            ]))
            story.append(breakdown_table)
            story.append(Spacer(1, 0.15*inch))

        # MD&A Summary
        if result.get('mda_summary'):
            story.append(Paragraph("MD&A Highlights (Item 2)", subheading_style))
            story.append(Paragraph(result['mda_summary'][:300], body_style))
            story.append(Spacer(1, 0.1*inch))

        # Risk Factors
        if result.get('risk_factors_summary'):
            story.append(Paragraph("Risk Factors (Item 1A)", subheading_style))
            story.append(Paragraph(result['risk_factors_summary'][:300], body_style))
            story.append(Spacer(1, 0.1*inch))

        # Sources
        sources = result.get('sources', {})
        if sources:
            story.append(Paragraph("Sources Found", subheading_style))
            story.append(Paragraph(f"• Press Releases: {sources.get('press_releases_count', 0)}", body_style))
            story.append(Paragraph(f"• Analyst Reports: {sources.get('analyst_reports_count', 0)}", body_style))
            story.append(Paragraph(f"• News Articles: {sources.get('news_count', 0)}", body_style))
            story.append(Paragraph(f"• SEC Filing: {sources.get('sec_filing', 'Not found')}", body_style))

        story.append(Spacer(1, 0.2*inch))

        # Page break between tickers (except last)
        if i < len(analysis.results):
            story.append(PageBreak())

    story.append(PageBreak())

    # ────────────────────────────────────────────────────────────────────
    # BOARD COMMENTS SECTION
    # ────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Board Comments & Notes", heading_style))
    story.append(Spacer(1, 0.2*inch))

    story.append(Paragraph("Observer Notes", subheading_style))
    story.append(Paragraph(
        "<b>Observation Period:</b> This analysis captures SEC filing disclosures "
        "as of the report date. Changes post-filing (earnings calls, guidance updates, "
        "competitor announcements) may materially affect adoption signals.<br/><br/>"
        "<b>Earnings Call Priority:</b> The scoring is based on 10-Q facts only. Listen to "
        "earnings calls for real-time management commentary on product revenue, customer wins, "
        "and strategic initiatives.<br/><br/>"
        "<b>Red Flag Monitoring:</b> Watch for revenue misses, auditor changes, or governance "
        "issues mentioned in risk factors—these often signal execution risk even with strong "
        "product adoption narratives.",
        body_style
    ))

    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph("Validation Checklist for Earnings Call", subheading_style))

    checklist = [
        "Does management specifically credit new product for revenue growth?",
        "Is customer concentration high (>50% from single customer)?",
        "Are gross margins expanding with new product mix?",
        "Does guidance mention product revenue contribution going forward?",
        "Are hiring plans/capex aligned with product scaling?",
    ]

    for i, item in enumerate(checklist, 1):
        story.append(Paragraph(f"<bullet>{i}.</bullet> {item}", body_style))

    story.append(Spacer(1, 0.3*inch))

    # ────────────────────────────────────────────────────────────────────
    # FOOTER / METHODOLOGY
    # ────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Methodology Reference: 15-Point SEC-Filing-First Framework", subheading_style))
    story.append(Paragraph(
        "<b>Tier 1 (Must Find in 10-Q):</b> Product named in MD&A, Revenue line item showing adoption, "
        "Guidance including product estimate, Risk factors mentioning product.<br/><br/>"
        "<b>Tier 2 (Verify in Press + Earnings):</b> Named customer wins, Deployment count/scale, "
        "CEO language escalation Q-over-Q.<br/><br/>"
        "<b>Tier 3 (Red Flags):</b> Revenue declining while product hyped, Governance/audit issues, "
        "Large gap between press and 10-Q disclosure.",
        body_style
    ))

    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph(
        f"Report generated {datetime.now().strftime('%B %d, %Y at %H:%M:%S')} | "
        f"Run ID: {analysis.run_id}",
        ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=grey,
            alignment=TA_CENTER,
        )
    ))

    # Build PDF
    doc.build(story)
    print(f"✓ PDF saved to {output_path}")


def generate_comprehensive_pdf(analysis, output_path: str):
    """
    Generate comprehensive PDF combining watchlist tier + SEC filing analysis.
    Shows which candidates from watchlist have 10-Q support.
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
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=HexColor('#1a1a1a'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    )

    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=HexColor('#2c3e50'),
        spaceAfter=10,
        spaceBefore=10,
        fontName='Helvetica-Bold',
    )

    subheading_style = ParagraphStyle(
        'CustomSubHeading',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=HexColor('#34495e'),
        spaceAfter=6,
        fontName='Helvetica-Bold',
    )

    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['BodyText'],
        fontSize=9,
        textColor=HexColor('#2c3e50'),
        spaceAfter=6,
        leading=11,
    )

    # ────────────────────────────────────────────────────────────────────
    # COVER PAGE
    # ────────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1.5*inch))
    story.append(Paragraph("Comprehensive R&D Adoption Research", title_style))
    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph("Watchlist Screening + SEC Filing Analysis", heading_style))
    story.append(Spacer(1, 0.3*inch))

    # Metadata
    run_date = datetime.now().strftime("%B %d, %Y at %H:%M")
    story.append(Paragraph(f"<b>Report Date:</b> {run_date}", body_style))
    story.append(Paragraph(f"<b>Run ID:</b> {analysis.sec_analysis.run_id}", body_style))
    story.append(Paragraph(f"<b>Tickers Analyzed:</b> {len(analysis.results)}", body_style))
    story.append(Spacer(1, 0.2*inch))

    # Methodology
    story.append(Paragraph("Methodology", subheading_style))
    story.append(Paragraph(
        "This analysis combines two layers: (1) Watchlist screening (market cap, sector, analyst activity) "
        "and (2) SEC filing analysis (10-Q MD&A, revenue attribution, risk factors). "
        "Combined score reflects both market signals and fundamental adoption proof.",
        body_style
    ))

    story.append(Spacer(1, 0.5*inch))
    story.append(PageBreak())

    # ────────────────────────────────────────────────────────────────────
    # EXECUTIVE SUMMARY (RANKINGS)
    # ────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Executive Summary: Ranked Candidates", title_style))
    story.append(Spacer(1, 0.2*inch))

    story.append(Paragraph(
        "Ranked by combined score (watchlist tier + SEC filing fundamentals). "
        "Watchlist tier (HIGH-PRIORITY/SECONDARY/etc.) indicates market signal strength. "
        "SEC score indicates 10-Q adoption proof. Combined score is highest when both align.",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))

    # Build summary table
    summary_data = [['Rank', 'Ticker', 'Watchlist Tier', 'SEC Score', 'Combined', 'Status']]

    for result in analysis.results:
        rank = result.get('overall_rank', '?')
        ticker = result['ticker']
        tier = result.get('watchlist_tier', 'UNRANKED')
        sec_score = result['score_breakdown']['sec_filing_score']
        combined = result['combined_score']

        # Status badge
        if combined >= 17:
            status = 'STRONG'
        elif combined >= 12:
            status = 'WATCH'
        elif combined >= 7:
            status = 'CAUTION'
        else:
            status = 'AVOID'

        summary_data.append([
            str(rank),
            Paragraph(f"<b>{ticker}</b>", body_style),
            tier,
            Paragraph(f"{sec_score}/15", body_style),
            Paragraph(f"<b>{combined}/20</b>", body_style),
            status,
        ])

    summary_table = Table(summary_data, colWidths=[0.8*inch, 0.8*inch, 1.3*inch, 0.9*inch, 0.9*inch, 0.9*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#34495e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#bdc3c7')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#ecf0f1')]),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
    ]))

    story.append(summary_table)
    story.append(Spacer(1, 0.3*inch))

    # Tier breakdown
    strong = [r for r in analysis.results if r.get('combined_score', 0) >= 17]
    watch = [r for r in analysis.results if 12 <= r.get('combined_score', 0) < 17]
    caution = [r for r in analysis.results if 7 <= r.get('combined_score', 0) < 12]
    avoid = [r for r in analysis.results if r.get('combined_score', 0) < 7]

    if strong:
        story.append(Paragraph("🔥 Strong Candidates (Score ≥ 17/20)", subheading_style))
        for r in strong:
            tier = r['watchlist_tier']
            combined = r['combined_score']
            sec = r['score_breakdown']['sec_filing_score']
            text = f"<b>{r['ticker']}</b> ({combined}/20) — Watchlist: {tier} | SEC: {sec}/15"
            story.append(Paragraph(text, body_style))
        story.append(Spacer(1, 0.15*inch))

    if watch:
        story.append(Paragraph("👀 Watch (Score 12-16/20)", subheading_style))
        for r in watch:
            tier = r['watchlist_tier']
            combined = r['combined_score']
            sec = r['score_breakdown']['sec_filing_score']
            text = f"<b>{r['ticker']}</b> ({combined}/20) — Watchlist: {tier} | SEC: {sec}/15"
            story.append(Paragraph(text, body_style))
        story.append(Spacer(1, 0.15*inch))

    story.append(PageBreak())

    # ────────────────────────────────────────────────────────────────────
    # DETAILED ANALYSIS PER TICKER
    # ────────────────────────────────────────────────────────────────────
    for i, result in enumerate(analysis.results, 1):
        ticker = result['ticker']
        combined = result['combined_score']
        tier = result['watchlist_tier']
        sec_score = result['score_breakdown']['sec_filing_score']
        rank = result['overall_rank']

        story.append(Paragraph(
            f"Analysis #{rank}: {ticker} | Combined Score: {combined}/20 | Tier: {tier}",
            heading_style
        ))

        # Watchlist Tier Info
        watchlist_data = result.get('watchlist_data', {})
        if watchlist_data:
            story.append(Paragraph(f"<b>Watchlist Position:</b> {tier}", subheading_style))
            raw_content = watchlist_data.get('raw_content', '')
            if raw_content:
                # Extract key points from watchlist markdown
                if 'What\'s Brewing' in raw_content or 'Why It Fits' in raw_content:
                    preview = raw_content.split('\n')[2:6]  # Get first few lines
                    story.append(Paragraph(
                        ' '.join([p for p in preview if p.strip() and not p.startswith('#')]),
                        body_style
                    ))
            story.append(Spacer(1, 0.1*inch))

        # SEC Scoring
        sec_data = result.get('sec_data', {})
        breakdown = sec_data.get('score_breakdown', {})
        if breakdown:
            story.append(Paragraph("SEC Filing Scoring", subheading_style))

            breakdown_data = [['Criterion', 'Met?', 'Wt', 'Source']]
            for criterion, details in breakdown.get('breakdown', {}).items():
                met = '✓' if details.get('met') else '✗'
                weight = details.get('weight', 0)
                source = details.get('source', '—')
                breakdown_data.append([
                    criterion.replace('_', ' ').title()[:20],
                    Paragraph(met, body_style),
                    Paragraph(str(weight), body_style),
                    Paragraph(source[:15], body_style)
                ])

            breakdown_table = Table(breakdown_data, colWidths=[1.8*inch, 0.5*inch, 0.5*inch, 1.5*inch])
            breakdown_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), HexColor('#95a5a6')),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#bdc3c7')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')]),
            ]))
            story.append(breakdown_table)
            story.append(Spacer(1, 0.1*inch))

        # Red Flags
        red_flags = result.get('red_flags', {})
        if red_flags and red_flags.get('disqualifiers'):
            story.append(Paragraph("🚩 RED FLAGS DETECTED", subheading_style))
            for flag in red_flags['disqualifiers']:
                story.append(Paragraph(f"❌ {flag}", body_style))
            story.append(Spacer(1, 0.08*inch))

        # Stock Performance
        perf = result.get('stock_performance')
        if perf:
            story.append(Paragraph("Stock Performance (90 Days)", subheading_style))
            pct = perf.get('change_pct', 0)
            direction = "📈" if pct > 0 else "📉"
            story.append(Paragraph(
                f"{direction} {pct:+.1f}% | Price: ${perf.get('end_price', 0):.2f} "
                f"| Range: ${perf.get('min_price', 0):.2f}-${perf.get('max_price', 0):.2f}",
                body_style
            ))
            story.append(Spacer(1, 0.08*inch))

        # Analyst Coverage
        analysts = result.get('analyst_coverage', [])
        if analysts:
            story.append(Paragraph("Analyst Coverage", subheading_style))
            for analyst_info in analysts:
                if analyst_info.get('type') == 'target_price':
                    story.append(Paragraph(
                        f"Target Price: ${analyst_info.get('value', 0):.2f} "
                        f"({analyst_info.get('num_analysts', 0)} analysts)",
                        body_style
                    ))
                elif analyst_info.get('type') == 'recommendation':
                    story.append(Paragraph(
                        f"Recommendation: {analyst_info.get('value', 'N/A')}",
                        body_style
                    ))
            story.append(Spacer(1, 0.08*inch))

        # RPO/Backlog
        rpo = result.get('rpo_backlog')
        if rpo:
            story.append(Paragraph("Backlog & Obligations", subheading_style))
            if rpo.get('rpo_total'):
                story.append(Paragraph(f"RPO: ${rpo['rpo_total']/1000:.1f}B", body_style))
            if rpo.get('backlog'):
                story.append(Paragraph(f"Backlog: ${rpo['backlog']/1000:.1f}B", body_style))
            story.append(Spacer(1, 0.08*inch))

        # Guidance
        guidance = result.get('guidance', [])
        if guidance:
            story.append(Paragraph("Forward Guidance", subheading_style))
            for guid in guidance[:2]:  # Show first 2
                story.append(Paragraph(f"• {guid.get('text', '')[:100]}", body_style))
            story.append(Spacer(1, 0.08*inch))

        # MD&A & Risk Factors
        if sec_data.get('mda_summary'):
            story.append(Paragraph("MD&A from 10-Q", subheading_style))
            story.append(Paragraph(sec_data['mda_summary'][:200], body_style))
            story.append(Spacer(1, 0.08*inch))

        if sec_data.get('risk_factors_summary'):
            story.append(Paragraph("Risk Factors from 10-Q", subheading_style))
            story.append(Paragraph(sec_data['risk_factors_summary'][:200], body_style))

        story.append(Spacer(1, 0.2*inch))

        # Page break between tickers (except last)
        if i < len(analysis.results):
            story.append(PageBreak())

    story.append(PageBreak())

    # ────────────────────────────────────────────────────────────────────
    # SCORING EXPLANATION
    # ────────────────────────────────────────────────────────────────────
    story.append(Paragraph("How Scores Work", heading_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("<b>SEC Filing Score (0-15):</b>", subheading_style))
    story.append(Paragraph(
        "Based on 10-Q analysis. Evaluates if product is named, revenue is quantified, "
        "growth is accelerating, and risk factors are updated.",
        body_style
    ))

    story.append(Paragraph("<b>Watchlist Tier Bonus/Penalty:</b>", subheading_style))
    story.append(Paragraph("• HIGH-PRIORITY: +3 (market cap, sector, analyst activity confirmed)", body_style))
    story.append(Paragraph("• SECONDARY: +1 (needs deeper research)", body_style))
    story.append(Paragraph("• CAUTION: -2 (red flags present)", body_style))
    story.append(Paragraph("• NON-FIT: -5 (doesn't match framework)", body_style))

    story.append(Paragraph("<b>Combined Score (0-20):</b>", subheading_style))
    story.append(Paragraph("SEC score + tier bonus. Shows alignment: high combined score means "
                          "watchlist tier AND 10-Q fundamentals both support adoption thesis.",
                          body_style))

    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("Combined Score Tiers:", subheading_style))
    story.append(Paragraph("• 17-20: STRONG (pursue aggressively)", body_style))
    story.append(Paragraph("• 12-16: WATCH (listen to earnings call)", body_style))
    story.append(Paragraph("• 7-11: CAUTION (execution risk)", body_style))
    story.append(Paragraph("• <7: AVOID (doesn't fit framework)", body_style))

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

    # Build PDF
    doc.build(story)
    print(f"✓ Comprehensive PDF saved to {output_path}")
