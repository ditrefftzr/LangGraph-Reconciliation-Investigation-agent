"""
Tests for the Restructured Payments agent.

Coverage:
  - find_restructures_removed_from_period: detects AR/GL discrepancy
  - find_restructures_added_to_period: detects AR/GL discrepancy
  - Deduplication: previously_found_ids skips already-found records
  - Both-missing detection
  - Clean records (both present) are not returned
"""

import pytest
from datetime import date

from src.database.connection import get_connection, initialize_database
from src.nodes.agents.restructured import (
    find_restructures_added_to_period,
    find_restructures_removed_from_period,
    restructured_agent_node,
)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Isolated SQLite DB for each test."""
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


class TestFindRestructuresRemovedFromPeriod:
    def test_finds_ar_still_has_original(self, db):
        # RST: original in Jan, restructured in Mar → should be removed from Jan
        _insert(db, "restructured_payments", {
            "restructure_id": "RST-R01",
            "loan_id": "L01",
            "original_due_date": "2024-01-15",
            "restructured_due_date": "2024-03-15",
            "period": "2024-01-01",
            "original_amount": 1000.0,
            "restructured_amount": 900.0,
            "status": "COMPLETED",
        })
        # GL has reversal, AR does NOT → AR still has original (discrepancy)
        _insert(db, "gl_journal_entries", {
            "entry_id": "GL-R01",
            "transaction_date": "2024-01-31",
            "period": "2024-01-01",
            "account_code": "AR_CONTROL",
            "debit_amount": 0.0,
            "credit_amount": 1000.0,
            "reference_id": "RST-R01",
            "reference_type": "RESTRUCTURE",
            "entry_type": "RESTRUCTURE_REVERSAL",
        })
        findings = find_restructures_removed_from_period(date(2024, 1, 1), db)
        assert len(findings) == 1
        f = findings[0]
        assert f["restructure_id"] == "RST-R01"
        assert f["missing_in_ar"] is True
        assert f["missing_in_gl"] is False
        assert f["finding_type"] == "removed_from_period"

    def test_clean_record_not_returned(self, db):
        _insert(db, "restructured_payments", {
            "restructure_id": "RST-CLEAN",
            "loan_id": "L02",
            "original_due_date": "2024-01-10",
            "restructured_due_date": "2024-04-10",
            "period": "2024-01-01",
            "original_amount": 500.0,
            "restructured_amount": 480.0,
            "status": "COMPLETED",
        })
        _insert(db, "gl_journal_entries", {
            "entry_id": "GL-CLEAN",
            "transaction_date": "2024-01-31",
            "period": "2024-01-01",
            "account_code": "AR_CONTROL",
            "debit_amount": 0.0,
            "credit_amount": 500.0,
            "reference_id": "RST-CLEAN",
            "reference_type": "RESTRUCTURE",
            "entry_type": "RESTRUCTURE_REVERSAL",
        })
        _insert(db, "ar_subledger", {
            "record_id": "AR-CLEAN",
            "loan_id": "L02",
            "transaction_date": "2024-01-31",
            "period": "2024-01-01",
            "transaction_type": "RESTRUCTURE_REVERSAL",
            "amount": 500.0,
            "reference_id": "RST-CLEAN",
            "reference_type": "RESTRUCTURE",
        })
        findings = find_restructures_removed_from_period(date(2024, 1, 1), db)
        assert findings == []

    def test_both_missing_systemic_failure(self, db):
        _insert(db, "restructured_payments", {
            "restructure_id": "RST-BOTH",
            "loan_id": "L03",
            "original_due_date": "2024-01-20",
            "restructured_due_date": "2024-05-20",
            "period": "2024-01-01",
            "original_amount": 800.0,
            "restructured_amount": 750.0,
            "status": "COMPLETED",
        })
        findings = find_restructures_removed_from_period(date(2024, 1, 1), db)
        assert len(findings) == 1
        assert findings[0]["missing_in_ar"] is True
        assert findings[0]["missing_in_gl"] is True


class TestFindRestructuresAddedToPeriod:
    def test_finds_ar_missing_new_amount(self, db):
        _insert(db, "restructured_payments", {
            "restructure_id": "RST-A01",
            "loan_id": "L10",
            "original_due_date": "2023-12-20",
            "restructured_due_date": "2024-01-20",
            "period": "2024-01-01",
            "original_amount": 900.0,
            "restructured_amount": 950.0,
            "status": "COMPLETED",
        })
        # GL posted addition, AR did not
        _insert(db, "gl_journal_entries", {
            "entry_id": "GL-A01",
            "transaction_date": "2024-01-20",
            "period": "2024-01-01",
            "account_code": "AR_CONTROL",
            "debit_amount": 950.0,
            "credit_amount": 0.0,
            "reference_id": "RST-A01",
            "reference_type": "RESTRUCTURE",
            "entry_type": "RESTRUCTURE_ADDITION",
        })
        findings = find_restructures_added_to_period(date(2024, 1, 1), db)
        assert len(findings) == 1
        f = findings[0]
        assert f["missing_in_ar"] is True
        assert f["missing_in_gl"] is False
        assert f["finding_type"] == "added_to_period"


class TestRestructuredAgentDeduplication:
    def test_previously_found_ids_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "dedup.db"))
        initialize_database()
        conn = get_connection()
        _insert(conn, "restructured_payments", {
            "restructure_id": "RST-D01",
            "loan_id": "L20",
            "original_due_date": "2024-01-15",
            "restructured_due_date": "2024-03-15",
            "period": "2024-01-01",
            "original_amount": 600.0,
            "restructured_amount": 550.0,
            "status": "COMPLETED",
        })
        conn.close()

        agent_input = {
            "reconciliation_period": date(2024, 1, 1),
            "discrepancy_amount": 600.0,
            "discrepancy_direction": "AR_HIGHER",
            "previously_found_ids": ["RST-D01"],  # already found
        }
        result = restructured_agent_node(agent_input)
        assert result["restructured_findings"] == []
        assert result["agent_results"][0]["explained_amount"] == 0.0
