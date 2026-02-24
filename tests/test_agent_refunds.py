"""
Tests for the Refunds agent.

Coverage:
  - find_refunds_missing_in_ar_or_gl: both directions
  - Both-missing systemic failure
  - Deduplication
  - Clean records not returned
"""

import pytest
from datetime import date

from src.database.connection import get_connection, initialize_database
from src.nodes.agents.refunds import (
    find_refunds_missing_in_ar_or_gl,
    refunds_agent_node,
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


class TestFindRefundsMissingInArOrGl:
    def test_gl_credited_ar_not_reduced(self, db):
        _insert(db, "refunds", {
            "refund_id": "REF-T01",
            "loan_id": "L01",
            "refund_date": "2024-01-18",
            "period": "2024-01-01",
            "refund_amount": 300.0,
            "refund_reason": "OVERPAYMENT",
        })
        _insert(db, "gl_journal_entries", {
            "entry_id": "GL-REF-T01",
            "transaction_date": "2024-01-18",
            "period": "2024-01-01",
            "account_code": "REFUND_PAYABLE",
            "debit_amount": 300.0,
            "credit_amount": 0.0,
            "reference_id": "REF-T01",
            "reference_type": "REFUND",
            "entry_type": "REFUND_CREDIT",
        })
        findings = find_refunds_missing_in_ar_or_gl(date(2024, 1, 1), db)
        assert len(findings) == 1
        f = findings[0]
        assert f["missing_in_ar"] is True
        assert f["missing_in_gl"] is False

    def test_ar_reduced_gl_missing(self, db):
        _insert(db, "refunds", {
            "refund_id": "REF-T02",
            "loan_id": "L02",
            "refund_date": "2024-01-20",
            "period": "2024-01-01",
            "refund_amount": 150.0,
            "refund_reason": "CANCELLED_LOAN",
        })
        _insert(db, "ar_subledger", {
            "record_id": "AR-REF-T02",
            "loan_id": "L02",
            "transaction_date": "2024-01-20",
            "period": "2024-01-01",
            "transaction_type": "REFUND_APPLIED",
            "amount": 150.0,
            "reference_id": "REF-T02",
            "reference_type": "REFUND",
        })
        findings = find_refunds_missing_in_ar_or_gl(date(2024, 1, 1), db)
        assert len(findings) == 1
        assert findings[0]["missing_in_ar"] is False
        assert findings[0]["missing_in_gl"] is True

    def test_both_missing_systemic(self, db):
        _insert(db, "refunds", {
            "refund_id": "REF-BOTH",
            "loan_id": "L03",
            "refund_date": "2024-01-25",
            "period": "2024-01-01",
            "refund_amount": 200.0,
            "refund_reason": "DISPUTE",
        })
        findings = find_refunds_missing_in_ar_or_gl(date(2024, 1, 1), db)
        assert len(findings) == 1
        assert findings[0]["missing_in_ar"] is True
        assert findings[0]["missing_in_gl"] is True

    def test_clean_refund_not_returned(self, db):
        _insert(db, "refunds", {
            "refund_id": "REF-CLEAN",
            "loan_id": "L04",
            "refund_date": "2024-01-12",
            "period": "2024-01-01",
            "refund_amount": 100.0,
            "refund_reason": "OVERPAYMENT",
        })
        _insert(db, "ar_subledger", {
            "record_id": "AR-REF-CLEAN",
            "loan_id": "L04",
            "transaction_date": "2024-01-12",
            "period": "2024-01-01",
            "transaction_type": "REFUND_APPLIED",
            "amount": 100.0,
            "reference_id": "REF-CLEAN",
            "reference_type": "REFUND",
        })
        _insert(db, "gl_journal_entries", {
            "entry_id": "GL-REF-CLEAN",
            "transaction_date": "2024-01-12",
            "period": "2024-01-01",
            "account_code": "REFUND_PAYABLE",
            "debit_amount": 100.0,
            "credit_amount": 0.0,
            "reference_id": "REF-CLEAN",
            "reference_type": "REFUND",
            "entry_type": "REFUND_CREDIT",
        })
        findings = find_refunds_missing_in_ar_or_gl(date(2024, 1, 1), db)
        assert findings == []


class TestRefundsAgentDeduplication:
    def test_deduplication(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "dedup.db"))
        initialize_database()
        conn = get_connection()
        _insert(conn, "refunds", {
            "refund_id": "REF-DEDUP",
            "loan_id": "L99",
            "refund_date": "2024-01-18",
            "period": "2024-01-01",
            "refund_amount": 300.0,
            "refund_reason": "OVERPAYMENT",
        })
        conn.close()

        agent_input = {
            "reconciliation_period": date(2024, 1, 1),
            "discrepancy_amount": 300.0,
            "discrepancy_direction": "AR_HIGHER",
            "previously_found_ids": ["REF-DEDUP"],
        }
        result = refunds_agent_node(agent_input)
        assert result["refund_findings"] == []
        assert result["agent_results"][0]["explained_amount"] == 0.0
