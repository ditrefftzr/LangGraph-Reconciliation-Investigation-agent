"""
Tests for the Charge-offs agent.

Coverage:
  - find_chargeoffs_missing_in_ar_or_gl: both directions
  - Only CONFIRMED + days_past_due >= 90 are included
  - Both-missing systemic failure
  - Deduplication
  - Clean records not returned
"""

import pytest
from datetime import date

from src.database.connection import get_connection, initialize_database
from src.nodes.agents.chargeoffs import (
    chargeoffs_agent_node,
    find_chargeoffs_missing_in_ar_or_gl,
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


class TestFindChargeoffsMissingInArOrGl:
    def test_gl_wrote_off_ar_not_cleared(self, db):
        _insert(db, "charge_offs", {
            "charge_off_id": "CHG-T01",
            "loan_id": "L01",
            "charge_off_date": "2024-01-25",
            "period": "2024-01-01",
            "days_past_due": 120,
            "charge_off_amount": 5000.0,
            "status": "CONFIRMED",
        })
        _insert(db, "gl_journal_entries", {
            "entry_id": "GL-CHG-T01",
            "transaction_date": "2024-01-25",
            "period": "2024-01-01",
            "account_code": "CREDIT_LOSS",
            "debit_amount": 5000.0,
            "credit_amount": 0.0,
            "reference_id": "CHG-T01",
            "reference_type": "CHARGE_OFF",
            "entry_type": "CHARGE_OFF_WRITE_OFF",
        })
        findings = find_chargeoffs_missing_in_ar_or_gl(date(2024, 1, 1), db)
        assert len(findings) == 1
        assert findings[0]["missing_in_ar"] is True
        assert findings[0]["missing_in_gl"] is False

    def test_ar_cleared_gl_missing(self, db):
        _insert(db, "charge_offs", {
            "charge_off_id": "CHG-T02",
            "loan_id": "L02",
            "charge_off_date": "2024-01-10",
            "period": "2024-01-01",
            "days_past_due": 95,
            "charge_off_amount": 2000.0,
            "status": "CONFIRMED",
        })
        _insert(db, "ar_subledger", {
            "record_id": "AR-CHG-T02",
            "loan_id": "L02",
            "transaction_date": "2024-01-10",
            "period": "2024-01-01",
            "transaction_type": "CHARGE_OFF_CLEARANCE",
            "amount": 2000.0,
            "reference_id": "CHG-T02",
            "reference_type": "CHARGE_OFF",
        })
        findings = find_chargeoffs_missing_in_ar_or_gl(date(2024, 1, 1), db)
        assert len(findings) == 1
        assert findings[0]["missing_in_ar"] is False
        assert findings[0]["missing_in_gl"] is True

    def test_pending_status_excluded(self, db):
        _insert(db, "charge_offs", {
            "charge_off_id": "CHG-PEND",
            "loan_id": "L03",
            "charge_off_date": "2024-01-20",
            "period": "2024-01-01",
            "days_past_due": 100,
            "charge_off_amount": 1000.0,
            "status": "PENDING",  # should be excluded
        })
        findings = find_chargeoffs_missing_in_ar_or_gl(date(2024, 1, 1), db)
        assert findings == []

    def test_below_90_days_excluded(self, db):
        _insert(db, "charge_offs", {
            "charge_off_id": "CHG-YOUNG",
            "loan_id": "L04",
            "charge_off_date": "2024-01-15",
            "period": "2024-01-01",
            "days_past_due": 89,  # just under threshold
            "charge_off_amount": 800.0,
            "status": "CONFIRMED",
        })
        findings = find_chargeoffs_missing_in_ar_or_gl(date(2024, 1, 1), db)
        assert findings == []

    def test_clean_chargeoff_not_returned(self, db):
        _insert(db, "charge_offs", {
            "charge_off_id": "CHG-CLEAN",
            "loan_id": "L05",
            "charge_off_date": "2024-01-08",
            "period": "2024-01-01",
            "days_past_due": 90,
            "charge_off_amount": 3000.0,
            "status": "CONFIRMED",
        })
        _insert(db, "ar_subledger", {
            "record_id": "AR-CHG-CLEAN",
            "loan_id": "L05",
            "transaction_date": "2024-01-08",
            "period": "2024-01-01",
            "transaction_type": "CHARGE_OFF_CLEARANCE",
            "amount": 3000.0,
            "reference_id": "CHG-CLEAN",
            "reference_type": "CHARGE_OFF",
        })
        _insert(db, "gl_journal_entries", {
            "entry_id": "GL-CHG-CLEAN",
            "transaction_date": "2024-01-08",
            "period": "2024-01-01",
            "account_code": "CREDIT_LOSS",
            "debit_amount": 3000.0,
            "credit_amount": 0.0,
            "reference_id": "CHG-CLEAN",
            "reference_type": "CHARGE_OFF",
            "entry_type": "CHARGE_OFF_WRITE_OFF",
        })
        findings = find_chargeoffs_missing_in_ar_or_gl(date(2024, 1, 1), db)
        assert findings == []

    def test_both_missing_systemic(self, db):
        _insert(db, "charge_offs", {
            "charge_off_id": "CHG-BOTH",
            "loan_id": "L06",
            "charge_off_date": "2024-01-28",
            "period": "2024-01-01",
            "days_past_due": 180,
            "charge_off_amount": 4500.0,
            "status": "CONFIRMED",
        })
        findings = find_chargeoffs_missing_in_ar_or_gl(date(2024, 1, 1), db)
        assert len(findings) == 1
        assert findings[0]["missing_in_ar"] is True
        assert findings[0]["missing_in_gl"] is True


class TestChargeoffsAgentDeduplication:
    def test_deduplication(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "dedup.db"))
        initialize_database()
        conn = get_connection()
        _insert(conn, "charge_offs", {
            "charge_off_id": "CHG-DEDUP",
            "loan_id": "L99",
            "charge_off_date": "2024-01-25",
            "period": "2024-01-01",
            "days_past_due": 120,
            "charge_off_amount": 5000.0,
            "status": "CONFIRMED",
        })
        conn.close()

        agent_input = {
            "reconciliation_period": date(2024, 1, 1),
            "discrepancy_amount": 5000.0,
            "discrepancy_direction": "AR_HIGHER",
            "previously_found_ids": ["CHG-DEDUP"],
        }
        result = chargeoffs_agent_node(agent_input)
        assert result["chargeoff_findings"] == []
        assert result["agent_results"][0]["explained_amount"] == 0.0
