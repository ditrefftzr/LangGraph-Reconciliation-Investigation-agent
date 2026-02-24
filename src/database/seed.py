"""
Seed data for the reconciliation investigation agent.

Scenarios for period 2024-01-01:

1. RESTRUCTURE — AR_HIGHER (removed_from_period)
   RST-001: original installment removed from period.
   AR still shows the original; GL correctly reversed it.
   → AR higher by 1,200.00

2. RESTRUCTURE — GL_HIGHER (added_to_period)
   RST-002: restructured installment added to period.
   GL posted the new amount; AR hasn't picked it up.
   → GL higher by 950.00

3. DELINQUENCY FEE — AR_HIGHER
   FEE-001: late fee posted in AR but missing in GL.
   → AR higher by 75.00

4. REFUND — AR_HIGHER
   REF-001: refund credited in GL but AR balance not reduced.
   → AR higher by 300.00

5. CHARGE-OFF — GL_HIGHER
   CHG-001: charge-off written off in GL; AR balance not cleared.
   → AR higher by 5,000.00

6. SYSTEMIC FAILURE (both missing)
   FEE-002: fee missing in BOTH AR and GL.
   → No net discrepancy impact; process failure indicator.

7. RESTRUCTURE — added_to_period, small amount (triggers re-delegation scenario)
   RST-003: restructured installment added; AR posted, GL missing.
   → AR higher by 200.00

Net discrepancy for period 2024-01-01:
  AR_HIGHER contributions: 1,200 + 75 + 300 + 5,000 + 200 = 6,775.00
  GL_HIGHER contributions: 950.00
  Net: AR higher by 5,825.00

Seed for period 2024-02-01 (re-delegation scenario):
  Only small findings (< 90% explained on first pass with partial seed).
"""

import sqlite3
from datetime import date

from src.database.connection import get_connection, initialize_database


# ── helpers ────────────────────────────────────────────────────────────────

def _insert(conn: sqlite3.Connection, table: str, row: dict) -> None:
    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" * len(row))
    conn.execute(
        f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})",
        list(row.values()),
    )


# ── period constants ────────────────────────────────────────────────────────

PERIOD_JAN = "2024-01-01"
PERIOD_FEB = "2024-02-01"


# ── exception records ───────────────────────────────────────────────────────

RESTRUCTURED_PAYMENTS = [
    # RST-001: original in 2024-01, restructured to 2024-03 → should be removed from Jan
    {
        "restructure_id": "RST-001",
        "loan_id": "LOAN-A001",
        "original_due_date": "2024-01-15",
        "restructured_due_date": "2024-03-15",
        "period": PERIOD_JAN,
        "original_amount": 1200.00,
        "restructured_amount": 1100.00,
        "status": "COMPLETED",
    },
    # RST-002: original in 2023-12, restructured to 2024-01 → should be added to Jan
    {
        "restructure_id": "RST-002",
        "loan_id": "LOAN-A002",
        "original_due_date": "2023-12-20",
        "restructured_due_date": "2024-01-20",
        "period": PERIOD_JAN,
        "original_amount": 900.00,
        "restructured_amount": 950.00,
        "status": "COMPLETED",
    },
    # RST-003: original in 2023-12, restructured to 2024-01 → AR posted, GL missing
    {
        "restructure_id": "RST-003",
        "loan_id": "LOAN-A003",
        "original_due_date": "2023-12-05",
        "restructured_due_date": "2024-01-05",
        "period": PERIOD_JAN,
        "original_amount": 180.00,
        "restructured_amount": 200.00,
        "status": "COMPLETED",
    },
]

DELINQUENCY_FEES = [
    # FEE-001: posted in AR, missing in GL
    {
        "fee_id": "FEE-001",
        "loan_id": "LOAN-B001",
        "fee_date": "2024-01-10",
        "period": PERIOD_JAN,
        "fee_amount": 75.00,
        "fee_type": "LATE_FEE",
        "days_past_due": 30,
    },
    # FEE-002: missing in BOTH AR and GL → systemic failure
    {
        "fee_id": "FEE-002",
        "loan_id": "LOAN-B002",
        "fee_date": "2024-01-22",
        "period": PERIOD_JAN,
        "fee_amount": 50.00,
        "fee_type": "PENALTY_FEE",
        "days_past_due": 45,
    },
]

REFUNDS = [
    # REF-001: GL credited refund, AR balance not reduced
    {
        "refund_id": "REF-001",
        "loan_id": "LOAN-C001",
        "refund_date": "2024-01-18",
        "period": PERIOD_JAN,
        "refund_amount": 300.00,
        "refund_reason": "OVERPAYMENT",
    },
]

CHARGE_OFFS = [
    # CHG-001: GL wrote off, AR not cleared
    {
        "charge_off_id": "CHG-001",
        "loan_id": "LOAN-D001",
        "charge_off_date": "2024-01-25",
        "period": PERIOD_JAN,
        "days_past_due": 120,
        "charge_off_amount": 5000.00,
        "status": "CONFIRMED",
    },
]

# ── GL journal entries ──────────────────────────────────────────────────────
# Only entries that EXIST (missing ones intentionally absent)

GL_ENTRIES = [
    # RST-001 removed_from_period: GL correctly reversed original → entry present
    {
        "entry_id": "GL-RST-001-REV",
        "transaction_date": "2024-01-31",
        "period": PERIOD_JAN,
        "account_code": "AR_CONTROL",
        "debit_amount": 0.00,
        "credit_amount": 1200.00,
        "reference_id": "RST-001",
        "reference_type": "RESTRUCTURE",
        "entry_type": "RESTRUCTURE_REVERSAL",
    },
    # RST-002 added_to_period: GL posted new amount → entry present
    {
        "entry_id": "GL-RST-002-ADD",
        "transaction_date": "2024-01-20",
        "period": PERIOD_JAN,
        "account_code": "AR_CONTROL",
        "debit_amount": 950.00,
        "credit_amount": 0.00,
        "reference_id": "RST-002",
        "reference_type": "RESTRUCTURE",
        "entry_type": "RESTRUCTURE_ADDITION",
    },
    # RST-003 added_to_period: GL missing (no entry here)

    # FEE-001: GL entry MISSING (intentionally absent)
    # FEE-002: GL entry MISSING (systemic — also absent in AR)

    # REF-001: GL credited refund → CREDIT to AR_CONTROL (reduces receivable balance in GL)
    {
        "entry_id": "GL-REF-001",
        "transaction_date": "2024-01-18",
        "period": PERIOD_JAN,
        "account_code": "AR_CONTROL",
        "debit_amount": 0.00,
        "credit_amount": 300.00,
        "reference_id": "REF-001",
        "reference_type": "REFUND",
        "entry_type": "REFUND_CREDIT",
    },
    # CHG-001: GL wrote off → CREDIT to AR_CONTROL (clears charged-off receivable in GL)
    {
        "entry_id": "GL-CHG-001",
        "transaction_date": "2024-01-25",
        "period": PERIOD_JAN,
        "account_code": "AR_CONTROL",
        "debit_amount": 0.00,
        "credit_amount": 5000.00,
        "reference_id": "CHG-001",
        "reference_type": "CHARGE_OFF",
        "entry_type": "CHARGE_OFF_WRITE_OFF",
    },
]

# ── AR subledger entries ────────────────────────────────────────────────────
# Only entries that EXIST (missing ones intentionally absent)

AR_ENTRIES = [
    # RST-001 removed_from_period: AR has NOT applied the reversal → entry intentionally ABSENT
    # (missing RESTRUCTURE_REVERSAL in AR means AR still shows the original → AR_HIGHER by 1,200)

    # RST-002 added_to_period: AR hasn't picked up new amount → entry MISSING

    # RST-003 added_to_period: AR posted new amount → entry present
    {
        "record_id": "AR-RST-003",
        "loan_id": "LOAN-A003",
        "transaction_date": "2024-01-05",
        "period": PERIOD_JAN,
        "transaction_type": "RESTRUCTURE_ADDITION",
        "amount": 200.00,
        "reference_id": "RST-003",
        "reference_type": "RESTRUCTURE",
    },
    # FEE-001: AR has the fee → entry present
    {
        "record_id": "AR-FEE-001",
        "loan_id": "LOAN-B001",
        "transaction_date": "2024-01-10",
        "period": PERIOD_JAN,
        "transaction_type": "FEE_CHARGE",
        "amount": 75.00,
        "reference_id": "FEE-001",
        "reference_type": "FEE",
    },
    # FEE-002: AR entry MISSING (systemic — also absent in GL)

    # REF-001: AR balance NOT reduced → entry MISSING

    # CHG-001: AR balance NOT cleared → entry MISSING
]


def seed_database() -> None:
    """
    Insert all seed records into the database.
    Uses INSERT OR IGNORE so it is safe to call multiple times.
    """
    initialize_database()
    conn = get_connection()
    try:
        for row in RESTRUCTURED_PAYMENTS:
            _insert(conn, "restructured_payments", row)
        for row in DELINQUENCY_FEES:
            _insert(conn, "delinquency_fees", row)
        for row in REFUNDS:
            _insert(conn, "refunds", row)
        for row in CHARGE_OFFS:
            _insert(conn, "charge_offs", row)
        for row in GL_ENTRIES:
            _insert(conn, "gl_journal_entries", row)
        for row in AR_ENTRIES:
            _insert(conn, "ar_subledger", row)
        conn.commit()
        print("Seed data inserted successfully.")
    finally:
        conn.close()


if __name__ == "__main__":
    seed_database()
