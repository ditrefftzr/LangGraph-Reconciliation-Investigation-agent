"""
Tests for the Delinquency Fees agent.

Coverage:
  - find_fees_missing_in_ar_or_gl: detects AR/GL discrepancy
  - Both-missing (systemic failure) returned but not in explained_amount
  - Deduplication
  - Clean records not returned
"""

import pytest
from datetime import date

from src.database.connection import get_connection, initialize_database
from src.nodes.agents.delinquency import (
    delinquency_agent_node,
    find_fees_missing_in_ar_or_gl,
)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    initialize_database()
    conn = get_connection()
    yield conn
    conn.close()


def _insert(conn, table, row):
    cols = ", ".join(row.keys())
    ph = ", ".join("?" * len(row))
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({ph})", list(row.values()))
    conn.commit()


class TestFindFeesMissingInArOrGl:
    def test_fee_in_ar_missing_in_gl(self, db):
        _insert(db, "delinquency_fees", {
            "fee_id": "FEE-T01",
            "loan_id": "L01",
            "fee_date": "2024-01-10",
            "period": "2024-01-01",
            "fee_amount": 75.0,
            "fee_type": "LATE_FEE",
            "days_past_due": 30,
        })
        _insert(db, "ar_subledger", {
            "record_id": "AR-FEE-T01",
            "loan_id": "L01",
            "transaction_date": "2024-01-10",
            "period": "2024-01-01",
            "transaction_type": "FEE_CHARGE",
            "amount": 75.0,
            "reference_id": "FEE-T01",
            "reference_type": "FEE",
        })
        findings = find_fees_missing_in_ar_or_gl(date(2024, 1, 1), db)
        assert len(findings) == 1
        assert findings[0]["missing_in_ar"] is False
        assert findings[0]["missing_in_gl"] is True

    def test_both_missing_is_returned_as_systemic(self, db):
        _insert(db, "delinquency_fees", {
            "fee_id": "FEE-BOTH",
            "loan_id": "L02",
            "fee_date": "2024-01-22",
            "period": "2024-01-01",
            "fee_amount": 50.0,
            "fee_type": "PENALTY_FEE",
            "days_past_due": 45,
        })
        findings = find_fees_missing_in_ar_or_gl(date(2024, 1, 1), db)
        assert len(findings) == 1
        assert findings[0]["missing_in_ar"] is True
        assert findings[0]["missing_in_gl"] is True

    def test_clean_fee_not_returned(self, db):
        _insert(db, "delinquency_fees", {
            "fee_id": "FEE-CLEAN",
            "loan_id": "L03",
            "fee_date": "2024-01-05",
            "period": "2024-01-01",
            "fee_amount": 25.0,
            "fee_type": "ADMIN_FEE",
            "days_past_due": 15,
        })
        _insert(db, "ar_subledger", {
            "record_id": "AR-FEE-CLEAN",
            "loan_id": "L03",
            "transaction_date": "2024-01-05",
            "period": "2024-01-01",
            "transaction_type": "FEE_CHARGE",
            "amount": 25.0,
            "reference_id": "FEE-CLEAN",
            "reference_type": "FEE",
        })
        _insert(db, "gl_journal_entries", {
            "entry_id": "GL-FEE-CLEAN",
            "transaction_date": "2024-01-05",
            "period": "2024-01-01",
            "account_code": "FEE_INCOME",
            "debit_amount": 25.0,
            "credit_amount": 0.0,
            "reference_id": "FEE-CLEAN",
            "reference_type": "FEE",
            "entry_type": "FEE_POSTING",
        })
        findings = find_fees_missing_in_ar_or_gl(date(2024, 1, 1), db)
        assert findings == []

    def test_out_of_period_fee_not_returned(self, db):
        _insert(db, "delinquency_fees", {
            "fee_id": "FEE-OLD",
            "loan_id": "L04",
            "fee_date": "2023-12-15",  # previous period
            "period": "2023-12-01",
            "fee_amount": 40.0,
            "fee_type": "LATE_FEE",
            "days_past_due": 20,
        })
        findings = find_fees_missing_in_ar_or_gl(date(2024, 1, 1), db)
        assert findings == []


class TestDelinquencyAgentDeduplication:
    def test_deduplication(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "dedup.db"))
        initialize_database()
        conn = get_connection()
        _insert(conn, "delinquency_fees", {
            "fee_id": "FEE-DEDUP",
            "loan_id": "L99",
            "fee_date": "2024-01-10",
            "period": "2024-01-01",
            "fee_amount": 75.0,
            "fee_type": "LATE_FEE",
            "days_past_due": 30,
        })
        conn.close()

        agent_input = {
            "reconciliation_period": date(2024, 1, 1),
            "discrepancy_amount": 75.0,
            "discrepancy_direction": "AR_HIGHER",
            "previously_found_ids": ["FEE-DEDUP"],
        }
        result = delinquency_agent_node(agent_input)
        assert result["delinquency_findings"] == []
        assert result["agent_results"][0]["explained_amount"] == 0.0
