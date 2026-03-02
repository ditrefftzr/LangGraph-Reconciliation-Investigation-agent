"""
Charge-offs Agent.

Tool:
  - find_chargeoffs_missing_in_ar_or_gl

Node function: chargeoffs_agent_node
  Receives AgentInput via Send API, calls tool, deduplicates,
  builds AgentResult, and returns state updates.
"""

import sqlite3
from datetime import date
from typing import List

from src.database.connection import get_connection
from src.graph.state import AgentInput, ChargeOffFinding
from src.utils.impact import build_agent_result


# ── Tool ──────────────────────────────────────────────────────────────────────

def find_chargeoffs_missing_in_ar_or_gl(
    period: date,
    conn: sqlite3.Connection,
) -> List[ChargeOffFinding]:
    """
    Find confirmed charge-offs (days_past_due >= 90, status = 'CONFIRMED')
    for the period where the AR balance wasn't cleared, the GL write-off
    entry is missing, or both.

    Source: charge_offs
    Cross-references: ar_subledger (CHARGE_OFF_CLEARANCE) and
    gl_journal_entries (CHARGE_OFF_WRITE_OFF) via reference_id
    WHERE reference_type = 'CHARGE_OFF'.
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
            co.charge_off_id,
            co.loan_id,
            co.charge_off_date,
            co.charge_off_amount,
            co.days_past_due,
            co.status,
            CASE WHEN ar.reference_id IS NOT NULL THEN 1 ELSE 0 END AS ar_exists,
            CASE WHEN gl.reference_id IS NOT NULL THEN 1 ELSE 0 END AS gl_exists
        FROM charge_offs co
        LEFT JOIN ar_subledger ar
            ON ar.reference_id = co.charge_off_id
           AND ar.reference_type = 'CHARGE_OFF'
           AND ar.transaction_type = 'CHARGE_OFF_CLEARANCE'
        LEFT JOIN gl_journal_entries gl
            ON gl.reference_id = co.charge_off_id
           AND gl.reference_type = 'CHARGE_OFF'
           AND gl.entry_type = 'CHARGE_OFF_WRITE_OFF'
        WHERE co.charge_off_date >= ?
          AND co.charge_off_date < ?
          AND co.days_past_due >= 90
          AND co.status = 'CONFIRMED'
          AND NOT (ar.reference_id IS NOT NULL AND gl.reference_id IS NOT NULL)
        """,
        (period_start, next_month),
    ).fetchall()

    findings: List[ChargeOffFinding] = []
    for row in rows:
        findings.append(
            ChargeOffFinding(
                charge_off_id=row["charge_off_id"],
                loan_id=row["loan_id"],
                charge_off_date=row["charge_off_date"],
                charge_off_amount=float(row["charge_off_amount"]),
                days_past_due=int(row["days_past_due"]),
                status=row["status"],
                missing_in_ar=not row["ar_exists"],
                missing_in_gl=not row["gl_exists"],
            )
        )
    return findings


# ── Node function ─────────────────────────────────────────────────────────────

def chargeoffs_agent_node(agent_input: AgentInput) -> dict:
    """
    LangGraph node for the Charge-offs agent.

    Receives AgentInput via Send API payload (not from main state).
    Returns state updates for agent_results and chargeoff_findings.
    """
    period = agent_input["reconciliation_period"]
    discrepancy_direction = agent_input["discrepancy_direction"]
    previously_found_ids = set(agent_input.get("previously_found_ids", []))

    conn = get_connection()
    try:
        all_findings = find_chargeoffs_missing_in_ar_or_gl(period, conn)
    finally:
        conn.close()

    new_findings = [
        f for f in all_findings
        if f["charge_off_id"] not in previously_found_ids
    ]

    result = build_agent_result(
        agent_name="chargeoff",
        findings=new_findings,
        category="chargeoff",
        discrepancy_direction=discrepancy_direction,
    )

    return {
        "agent_results": [result],
        "chargeoff_findings": new_findings,
    }
