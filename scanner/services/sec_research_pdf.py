"""
PDF Report Generator for SEC Research Analysis
Generates comprehensive PDF with executive summary, detailed ticker analysis, board comments.
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
            f"<b>{ticker}</b>",
            f"<b>{score}/15</b>",
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
                breakdown_data.append([criterion.replace('_', ' ').title(), met, str(weight), source])

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
            sources_text = f"""
            <bullet>•</bullet> Press Releases: {sources.get('press_releases_count', 0)}<br/>
            <bullet>•</bullet> Analyst Reports: {sources.get('analyst_reports_count', 0)}<br/>
            <bullet>•</bullet> News Articles: {sources.get('news_count', 0)}<br/>
            """
            story.append(Paragraph(sources_text, body_style))

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
