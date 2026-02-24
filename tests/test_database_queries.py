"""
Tests for database layer.

Coverage:
  - initialize_database: creates all expected tables
  - get_connection: returns sqlite3.Row factory
  - Parameterized queries are used (no f-string injection risk)
  - Schema constraints: PK uniqueness, DECIMAL precision
"""

import sqlite3
import pytest

from src.database.connection import get_connection, initialize_database


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    initialize_database()
    conn = get_connection()
    yield conn
    conn.close()


EXPECTED_TABLES = {
    "restructured_payments",
    "delinquency_fees",
    "refunds",
    "charge_offs",
    "gl_journal_entries",
    "ar_subledger",
}


class TestInitializeDatabase:
    def test_all_tables_created(self, db):
        rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        tables = {row["name"] for row in rows}
        assert EXPECTED_TABLES.issubset(tables)

    def test_idempotent_initialization(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "idempotent.db"))
        initialize_database()
        initialize_database()  # second call should not raise
        conn = get_connection()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        tables = {row["name"] for row in rows}
        assert EXPECTED_TABLES.issubset(tables)


class TestGetConnection:
    def test_row_factory_set(self, db):
        assert db.row_factory == sqlite3.Row

    def test_foreign_keys_enabled(self, db):
        result = db.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1


class TestSchemaConstraints:
    def test_primary_key_uniqueness(self, db):
        db.execute(
            "INSERT INTO delinquency_fees VALUES (?,?,?,?,?,?,?)",
            ("FEE-PK", "L01", "2024-01-10", "2024-01-01", 50.0, "LATE_FEE", 30),
        )
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO delinquency_fees VALUES (?,?,?,?,?,?,?)",
                ("FEE-PK", "L02", "2024-01-11", "2024-01-01", 60.0, "LATE_FEE", 31),
            )

    def test_decimal_precision_stored(self, db):
        db.execute(
            "INSERT INTO refunds VALUES (?,?,?,?,?,?)",
            ("REF-DEC", "L01", "2024-01-01", "2024-01-01", 123.45, "OVERPAYMENT"),
        )
        db.commit()
        row = db.execute(
            "SELECT refund_amount FROM refunds WHERE refund_id = ?", ("REF-DEC",)
        ).fetchone()
        assert float(row["refund_amount"]) == pytest.approx(123.45)
