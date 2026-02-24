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
            refund_id,
            loan_id,
            refund_date,
            refund_amount,
            refund_reason
        FROM refunds
        WHERE refund_date >= ?
          AND refund_date < ?
        """,
        (period_start, next_month),
    ).fetchall()

    findings: List[RefundFinding] = []
    for row in rows:
        rid = row["refund_id"]

        ar_exists = conn.execute(
            """
            SELECT 1 FROM ar_subledger
            WHERE reference_id = ?
              AND reference_type = 'REFUND'
              AND transaction_type = 'REFUND_APPLIED'
            LIMIT 1
            """,
            (rid,),
        ).fetchone() is not None

        gl_exists = conn.execute(
            """
            SELECT 1 FROM gl_journal_entries
            WHERE reference_id = ?
              AND reference_type = 'REFUND'
              AND entry_type = 'REFUND_CREDIT'
            LIMIT 1
            """,
            (rid,),
        ).fetchone() is not None

        if ar_exists and gl_exists:
            continue  # fully reconciled

        findings.append(
            RefundFinding(
                refund_id=rid,
                loan_id=row["loan_id"],
                refund_date=row["refund_date"],
                refund_amount=float(row["refund_amount"]),
                refund_reason=row["refund_reason"],
                missing_in_ar=not ar_exists,
                missing_in_gl=not gl_exists,
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
