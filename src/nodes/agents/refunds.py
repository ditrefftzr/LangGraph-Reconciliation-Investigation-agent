"""
Refunds Agent.

Tool:
  - find_refunds_missing_in_ar_or_gl

Node function: refunds_agent_node
  Receives AgentInput via Send API, calls tool, deduplicates,
  builds AgentResult, and returns state updates.
"""

import sqlite3
from datetime import date
from typing import List

from src.database.connection import get_connection
from src.graph.state import AgentInput, RefundFinding
from src.utils.impact import build_agent_result


# ── Tool ──────────────────────────────────────────────────────────────────────

def find_refunds_missing_in_ar_or_gl(
    period: date,
    conn: sqlite3.Connection,
) -> List[RefundFinding]:
    """
    Find refunds for the period where the AR balance wasn't reduced,
    the GL credit is missing, or both are missing.

    Source: refunds
    Cross-references: ar_subledger (REFUND_APPLIED) and gl_journal_entries (REFUND_CREDIT)
    via reference_id WHERE reference_type = 'REFUND'.
    """
    period_str = period.isoformat() if isinstance(period, date) else str(period)
    period_start = period_str[:7] + "-01"
    year, month = int(period_str[:4]), int(period_str[5:7])
    if month == 12:
        next_month = f"{year + 1}-01-01"
    else:
        next_month = f"{year}-{month + 1:02d}-01"

    rows = conn.execute(
        """
        SELECT
            r.refund_id,
            r.loan_id,
            r.refund_date,
            r.refund_amount,
            r.refund_reason,
            CASE WHEN ar.reference_id IS NOT NULL THEN 1 ELSE 0 END AS ar_exists,
            CASE WHEN gl.reference_id IS NOT NULL THEN 1 ELSE 0 END AS gl_exists
        FROM refunds r
        LEFT JOIN ar_subledger ar
            ON ar.reference_id = r.refund_id
           AND ar.reference_type = 'REFUND'
           AND ar.transaction_type = 'REFUND_APPLIED'
        LEFT JOIN gl_journal_entries gl
            ON gl.reference_id = r.refund_id
           AND gl.reference_type = 'REFUND'
           AND gl.entry_type = 'REFUND_CREDIT'
        WHERE r.refund_date >= ?
          AND r.refund_date < ?
          AND NOT (ar.reference_id IS NOT NULL AND gl.reference_id IS NOT NULL)
        """,
        (period_start, next_month),
    ).fetchall()

    findings: List[RefundFinding] = []
    for row in rows:
        findings.append(
            RefundFinding(
                refund_id=row["refund_id"],
                loan_id=row["loan_id"],
                refund_date=row["refund_date"],
                refund_amount=float(row["refund_amount"]),
                refund_reason=row["refund_reason"],
                missing_in_ar=not row["ar_exists"],
                missing_in_gl=not row["gl_exists"],
            )
        )
    return findings


# ── Node function ─────────────────────────────────────────────────────────────

def refunds_agent_node(agent_input: AgentInput) -> dict:
    """
    LangGraph node for the Refunds agent.

    Receives AgentInput via Send API payload (not from main state).
    Returns state updates for agent_results and refund_findings.
    """
    period = agent_input["reconciliation_period"]
    discrepancy_direction = agent_input["discrepancy_direction"]
    previously_found_ids = set(agent_input.get("previously_found_ids", []))

    conn = get_connection()
    try:
        all_findings = find_refunds_missing_in_ar_or_gl(period, conn)
    finally:
        conn.close()

    new_findings = [
        f for f in all_findings
        if f["refund_id"] not in previously_found_ids
    ]

    result = build_agent_result(
        agent_name="refund",
        findings=new_findings,
        category="refund",
        discrepancy_direction=discrepancy_direction,
    )

    return {
        "agent_results": [result],
        "refund_findings": new_findings,
    }
