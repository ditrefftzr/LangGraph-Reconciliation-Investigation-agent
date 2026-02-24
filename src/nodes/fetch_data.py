"""
Fetch Data node.

Queries AR subledger and GL journal entries to compute period totals.
Writes ar_total and gl_total to state.
"""

from datetime import date

from src.database.connection import get_connection
from src.graph.state import ReconciliationState


def fetch_data_node(state: ReconciliationState) -> dict:
    """
    Query AR subledger and GL journal entries for the reconciliation period
    and return the net totals for each ledger.

    AR total  = SUM(amount) from ar_subledger for the period
    GL total  = SUM(debit_amount) - SUM(credit_amount) from gl_journal_entries
                for the period (net debit position = AR control balance)
    """
    period = state["reconciliation_period"]
    period_str = period.isoformat() if isinstance(period, date) else str(period)

    conn = get_connection()
    try:
        ar_row = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM ar_subledger
            WHERE period = ?
            """,
            (period_str,),
        ).fetchone()

        gl_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(debit_amount), 0) - COALESCE(SUM(credit_amount), 0) AS total
            FROM gl_journal_entries
            WHERE period = ?
            """,
            (period_str,),
        ).fetchone()
    finally:
        conn.close()

    return {
        "ar_total": float(ar_row["total"]),
        "gl_total": float(gl_row["total"]),
    }
