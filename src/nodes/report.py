"""
Report node.

Converts SummaryOutput into a formatted PDF report using reportlab.
Writes the output path to state.report_path.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.graph.state import (
    ActionItem,
    CorrectingJournalEntry,
    ReconciliationState,
    SummaryOutput,
    SystemicPostingFailure,
)


# ── Style constants ───────────────────────────────────────────────────────────

PRIORITY_COLORS = {
    "HIGH": colors.HexColor("#FF4C4C"),
    "MEDIUM": colors.HexColor("#FFA500"),
    "LOW": colors.HexColor("#4CAF50"),
}

HEADER_COLOR = colors.HexColor("#1A3A5C")
ALT_ROW_COLOR = colors.HexColor("#F2F6FA")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_amount(amount: float) -> str:
    return f"${amount:,.2f}"


def _build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle",
        fontSize=20,
        textColor=HEADER_COLOR,
        spaceAfter=6,
        fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        name="SectionHeading",
        fontSize=13,
        textColor=HEADER_COLOR,
        spaceBefore=14,
        spaceAfter=6,
        fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        name="SubHeading",
        fontSize=11,
        textColor=colors.HexColor("#2C5282"),
        spaceBefore=8,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        name="BodyText2",
        fontSize=9,
        spaceAfter=4,
        leading=14,
    ))
    styles.add(ParagraphStyle(
        name="NarrativeText",
        fontSize=10,
        spaceAfter=6,
        leading=16,
    ))
    return styles


def _table_style(header_color=HEADER_COLOR, alt_color=ALT_ROW_COLOR) -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, alt_color]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ])


# ── Section builders ──────────────────────────────────────────────────────────

def _section_summary_metrics(
    summary: SummaryOutput,
    discrepancy_amount: float,
    discrepancy_direction: str,
    styles,
) -> list:
    elements = [Paragraph("Discrepancy Summary", styles["SectionHeading"])]
    data = [
        ["Metric", "Value"],
        ["Discrepancy Amount", _fmt_amount(discrepancy_amount)],
        ["Direction", discrepancy_direction.replace("_", " ")],
        ["Total Explained", _fmt_amount(summary["total_explained_amount"])],
        ["Explanation %", f"{summary['explanation_percentage']:.1f}%"],
        ["Correcting Entries", str(len(summary["correcting_journal_entries"]))],
        ["Action Items", str(len(summary["action_items"]))],
        ["Systemic Failures", str(len(summary["systemic_posting_failures"]))],
    ]
    t = Table(data, colWidths=[8 * cm, 8 * cm])
    t.setStyle(_table_style())
    elements.append(t)
    return elements


def _section_narrative(summary: SummaryOutput, styles) -> list:
    elements = [Paragraph("Investigation Narrative", styles["SectionHeading"])]
    for para in summary["narrative"].split("\n\n"):
        if para.strip():
            elements.append(Paragraph(para.strip(), styles["NarrativeText"]))
            elements.append(Spacer(1, 0.2 * cm))
    return elements


def _section_journal_entries(entries: List[CorrectingJournalEntry], styles) -> list:
    elements = [Paragraph("Correcting Journal Entries", styles["SectionHeading"])]
    if not entries:
        elements.append(Paragraph("No correcting entries required.", styles["BodyText2"]))
        return elements

    data = [["Reference ID", "Type", "Account", "Debit", "Credit", "Description"]]
    for e in entries:
        data.append([
            e["reference_id"],
            e["entry_type"],
            e["account_code"],
            _fmt_amount(e["debit_amount"]) if e["debit_amount"] else "-",
            _fmt_amount(e["credit_amount"]) if e["credit_amount"] else "-",
            Paragraph(e["description"], ParagraphStyle("tiny", fontSize=7, leading=9)),
        ])
    col_widths = [2.5 * cm, 3.5 * cm, 2.5 * cm, 2 * cm, 2 * cm, 5.5 * cm]
    t = Table(data, colWidths=col_widths)
    t.setStyle(_table_style())
    elements.append(t)
    return elements


def _section_action_items(items: List[ActionItem], styles) -> list:
    elements = [Paragraph("Action Items", styles["SectionHeading"])]
    if not items:
        elements.append(Paragraph("No action items.", styles["BodyText2"]))
        return elements

    data = [["Priority", "Category", "Amount", "Description"]]
    style = _table_style()
    row_styles = []
    for i, item in enumerate(items, start=1):
        color = PRIORITY_COLORS.get(item["priority"], colors.black)
        data.append([
            item["priority"],
            item["category"],
            _fmt_amount(item["amount"]),
            Paragraph(item["description"], ParagraphStyle("tiny", fontSize=7, leading=9)),
        ])
        row_styles.append(("TEXTCOLOR", (0, i), (0, i), color))
        row_styles.append(("FONTNAME", (0, i), (0, i), "Helvetica-Bold"))

    col_widths = [2 * cm, 4 * cm, 2.5 * cm, 9.5 * cm]
    t = Table(data, colWidths=col_widths)
    combined = _table_style()
    for cmd in row_styles:
        combined.add(*cmd)
    t.setStyle(combined)
    elements.append(t)
    return elements


def _section_systemic_failures(failures: List[SystemicPostingFailure], styles) -> list:
    elements = [Paragraph("Systemic Posting Failures", styles["SectionHeading"])]
    if not failures:
        elements.append(Paragraph("No systemic failures detected.", styles["BodyText2"]))
        return elements

    data = [["Reference ID", "Type", "Category", "Amount", "Description"]]
    for f in failures:
        data.append([
            f["reference_id"],
            f["reference_type"],
            f["category"],
            _fmt_amount(f["amount"]),
            Paragraph(f["description"], ParagraphStyle("tiny", fontSize=7, leading=9)),
        ])
    col_widths = [2.5 * cm, 2.5 * cm, 3 * cm, 2.5 * cm, 7.5 * cm]
    t = Table(data, colWidths=col_widths)
    t.setStyle(_table_style(header_color=colors.HexColor("#8B0000")))
    elements.append(t)
    return elements


# ── Node function ─────────────────────────────────────────────────────────────

def report_node(state: ReconciliationState) -> dict:
    """
    Generate a PDF reconciliation report from the summary in state.
    Returns report_path written to output/.
    """
    summary: SummaryOutput = state["summary"]
    period = state["reconciliation_period"]
    period_str = str(period)[:7]  # YYYY-MM

    output_dir = Path(__file__).resolve().parents[2] / "output"
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = str(output_dir / f"reconciliation_{period_str}_{timestamp}.pdf")

    styles = _build_styles()
    doc = SimpleDocTemplate(
        report_path,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    elements = []

    # ── Header ────────────────────────────────────────────────────────────────
    elements.append(Paragraph(
        f"BNPL Reconciliation Investigation Report",
        styles["ReportTitle"],
    ))
    elements.append(Paragraph(
        f"Period: {period_str}  |  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        styles["BodyText2"],
    ))
    elements.append(HRFlowable(width="100%", thickness=1, color=HEADER_COLOR))
    elements.append(Spacer(1, 0.3 * cm))

    # ── Sections ──────────────────────────────────────────────────────────────
    elements += _section_summary_metrics(
        summary,
        state["discrepancy_amount"],
        state["discrepancy_direction"],
        styles,
    )
    elements += _section_narrative(summary, styles)
    elements += _section_journal_entries(summary["correcting_journal_entries"], styles)
    elements += _section_action_items(summary["action_items"], styles)
    elements += _section_systemic_failures(summary["systemic_posting_failures"], styles)

    doc.build(elements)
    print(f"[Report] PDF saved to {report_path}")
    return {"report_path": report_path}
