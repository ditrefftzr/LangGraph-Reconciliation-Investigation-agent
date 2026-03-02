"""
Delinquency Fees Agent.

Tool:
  - find_fees_missing_in_ar_or_gl

Node function: delinquency_agent_node
  Receives AgentInput via Send API, calls tool, deduplicates,
  builds AgentResult, and returns state updates.
"""

import sqlite3
from datetime import date
from typing import List

from src.database.connection import get_connection
from src.graph.state import AgentInput, DelinquencyFinding
from src.utils.impact import build_agent_result


# ── Tool ──────────────────────────────────────────────────────────────────────

def find_fees_missing_in_ar_or_gl(
    period: date,
    conn: sqlite3.Connection,
) -> List[DelinquencyFinding]:
    """
    Find delinquency fees for the period that are missing in AR, GL, or both.

    Source: delinquency_fees
    Cross-references: ar_subledger (FEE_CHARGE) and gl_journal_entries (FEE_POSTING)
    via reference_id WHERE reference_type = 'FEE'.
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
            df.fee_id,
            df.loan_id,
            df.fee_date,
            df.fee_amount,
            df.fee_type,
            df.days_past_due,
            CASE WHEN ar.reference_id IS NOT NULL THEN 1 ELSE 0 END AS ar_exists,
            CASE WHEN gl.reference_id IS NOT NULL THEN 1 ELSE 0 END AS gl_exists
        FROM delinquency_fees df
        LEFT JOIN ar_subledger ar
            ON ar.reference_id = df.fee_id
           AND ar.reference_type = 'FEE'
           AND ar.transaction_type = 'FEE_CHARGE'
        LEFT JOIN gl_journal_entries gl
            ON gl.reference_id = df.fee_id
           AND gl.reference_type = 'FEE'
           AND gl.entry_type = 'FEE_POSTING'
        WHERE df.fee_date >= ?
          AND df.fee_date < ?
          AND NOT (ar.reference_id IS NOT NULL AND gl.reference_id IS NOT NULL)
        """,
        (period_start, next_month),
    ).fetchall()

    findings: List[DelinquencyFinding] = []
    for row in rows:
        findings.append(
            DelinquencyFinding(
                fee_id=row["fee_id"],
                loan_id=row["loan_id"],
                fee_date=row["fee_date"],
                fee_amount=float(row["fee_amount"]),
                fee_type=row["fee_type"],
                days_past_due=int(row["days_past_due"]),
                missing_in_ar=not row["ar_exists"],
                missing_in_gl=not row["gl_exists"],
            )
        )
    return findings


# ── Node function ─────────────────────────────────────────────────────────────

def delinquency_agent_node(agent_input: AgentInput) -> dict:
    """
    LangGraph node for the Delinquency Fees agent.

    Receives AgentInput via Send API payload (not from main state).
    Returns state updates for agent_results and delinquency_findings.
    """
    period = agent_input["reconciliation_period"]
    discrepancy_direction = agent_input["discrepancy_direction"]
    previously_found_ids = set(agent_input.get("previously_found_ids", []))

    conn = get_connection()
    try:
        all_findings = find_fees_missing_in_ar_or_gl(period, conn)
    finally:
        conn.close()

    new_findings = [
        f for f in all_findings
        if f["fee_id"] not in previously_found_ids
    ]

    result = build_agent_result(
        agent_name="delinquency",
        findings=new_findings,
        category="delinquency",
        discrepancy_direction=discrepancy_direction,
    )

    return {
        "agent_results": [result],
        "delinquency_findings": new_findings,
    }
