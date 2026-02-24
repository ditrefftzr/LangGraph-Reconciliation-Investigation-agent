"""
Restructured Payments Agent.

Tools:
  - find_restructures_removed_from_period
  - find_restructures_added_to_period

Node function: restructured_agent_node
  Receives AgentInput via Send API, calls both tools, deduplicates,
  builds AgentResult, and returns state updates.
"""

import sqlite3
from datetime import date
from typing import List

from src.database.connection import get_connection
from src.graph.state import AgentInput, RestructuredFinding
from src.utils.impact import build_agent_result


# ── Tool 1 ────────────────────────────────────────────────────────────────────

def find_restructures_removed_from_period(
    period: date,
    conn: sqlite3.Connection,
) -> List[RestructuredFinding]:
    """
    Find restructures where the original installment should have been removed
    from this period (original_due_date in period, restructured_due_date outside).

    Cross-references AR and GL to detect which side is still showing the
    original cash flow that should no longer be in this period.
    """
    period_str = period.isoformat() if isinstance(period, date) else str(period)
    period_start = period_str[:7] + "-01"
    # Last day of the month computed via next-month trick
    year, month = int(period_str[:4]), int(period_str[5:7])
    if month == 12:
        next_month = f"{year + 1}-01-01"
    else:
        next_month = f"{year}-{month + 1:02d}-01"

    rows = conn.execute(
        """
        SELECT
            rp.restructure_id,
            rp.loan_id,
            rp.original_due_date,
            rp.restructured_due_date,
            rp.original_amount,
            rp.restructured_amount
        FROM restructured_payments rp
        WHERE rp.original_due_date >= ?
          AND rp.original_due_date < ?
          AND (rp.restructured_due_date < ? OR rp.restructured_due_date >= ?)
        """,
        (period_start, next_month, period_start, next_month),
    ).fetchall()

    findings: List[RestructuredFinding] = []
    for row in rows:
        rid = row["restructure_id"]

        ar_exists = conn.execute(
            """
            SELECT 1 FROM ar_subledger
            WHERE reference_id = ?
              AND reference_type = 'RESTRUCTURE'
              AND transaction_type = 'RESTRUCTURE_REVERSAL'
            LIMIT 1
            """,
            (rid,),
        ).fetchone() is not None

        gl_exists = conn.execute(
            """
            SELECT 1 FROM gl_journal_entries
            WHERE reference_id = ?
              AND reference_type = 'RESTRUCTURE'
              AND entry_type = 'RESTRUCTURE_REVERSAL'
            LIMIT 1
            """,
            (rid,),
        ).fetchone() is not None

        # Only report if at least one side is discrepant
        # (both present = clean; both absent = systemic failure — still reported)
        if ar_exists and gl_exists:
            continue  # fully reconciled

        findings.append(
            RestructuredFinding(
                restructure_id=rid,
                loan_id=row["loan_id"],
                original_due_date=row["original_due_date"],
                restructured_due_date=row["restructured_due_date"],
                original_amount=float(row["original_amount"]),
                restructured_amount=float(row["restructured_amount"]),
                missing_in_ar=not ar_exists,
                missing_in_gl=not gl_exists,
                finding_type="removed_from_period",
            )
        )
    return findings


# ── Tool 2 ────────────────────────────────────────────────────────────────────

def find_restructures_added_to_period(
    period: date,
    conn: sqlite3.Connection,
) -> List[RestructuredFinding]:
    """
    Find restructures where the new installment should have been added to this
    period (restructured_due_date in period, original_due_date outside).

    Cross-references AR and GL to detect which side hasn't posted the new
    cash flow.
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
            rp.restructure_id,
            rp.loan_id,
            rp.original_due_date,
            rp.restructured_due_date,
            rp.original_amount,
            rp.restructured_amount
        FROM restructured_payments rp
        WHERE rp.restructured_due_date >= ?
          AND rp.restructured_due_date < ?
          AND rp.original_due_date < ?
        """,
        (period_start, next_month, period_start),
    ).fetchall()

    findings: List[RestructuredFinding] = []
    for row in rows:
        rid = row["restructure_id"]

        ar_exists = conn.execute(
            """
            SELECT 1 FROM ar_subledger
            WHERE reference_id = ?
              AND reference_type = 'RESTRUCTURE'
              AND transaction_type = 'RESTRUCTURE_ADDITION'
            LIMIT 1
            """,
            (rid,),
        ).fetchone() is not None

        gl_exists = conn.execute(
            """
            SELECT 1 FROM gl_journal_entries
            WHERE reference_id = ?
              AND reference_type = 'RESTRUCTURE'
              AND entry_type = 'RESTRUCTURE_ADDITION'
            LIMIT 1
            """,
            (rid,),
        ).fetchone() is not None

        if ar_exists and gl_exists:
            continue  # fully reconciled

        findings.append(
            RestructuredFinding(
                restructure_id=rid,
                loan_id=row["loan_id"],
                original_due_date=row["original_due_date"],
                restructured_due_date=row["restructured_due_date"],
                original_amount=float(row["original_amount"]),
                restructured_amount=float(row["restructured_amount"]),
                missing_in_ar=not ar_exists,
                missing_in_gl=not gl_exists,
                finding_type="added_to_period",
            )
        )
    return findings


# ── Node function ─────────────────────────────────────────────────────────────

def restructured_agent_node(agent_input: AgentInput) -> dict:
    """
    LangGraph node for the Restructured Payments agent.

    Receives AgentInput via Send API payload (not from main state).
    Returns state updates for agent_results and restructured_findings.
    """
    period = agent_input["reconciliation_period"]
    discrepancy_direction = agent_input["discrepancy_direction"]
    previously_found_ids = set(agent_input.get("previously_found_ids", []))

    conn = get_connection()
    try:
        removed = find_restructures_removed_from_period(period, conn)
        added = find_restructures_added_to_period(period, conn)
    finally:
        conn.close()

    all_findings = removed + added

    # Deduplicate: skip findings already discovered in prior iterations
    new_findings = [
        f for f in all_findings
        if f["restructure_id"] not in previously_found_ids
    ]

    result = build_agent_result(
        agent_name="restructured",
        findings=new_findings,
        category="restructured",
        discrepancy_direction=discrepancy_direction,
    )

    return {
        "agent_results": [result],
        "restructured_findings": new_findings,
    }
