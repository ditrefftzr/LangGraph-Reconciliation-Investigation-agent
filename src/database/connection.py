"""
SQLite connection helper.

Provides a single get_connection() function that returns a configured
sqlite3 connection. All queries use parameterized statements.
"""

import sqlite3
import os
from pathlib import Path


def get_connection() -> sqlite3.Connection:
    """
    Return a SQLite connection to the reconciliation database.

    The DB path is resolved from the DB_PATH environment variable,
    falling back to <project_root>/reconciliation.db.
    Row factory is set to sqlite3.Row for dict-like access.
    """
    db_path = os.getenv("DB_PATH")
    if not db_path:
        project_root = Path(__file__).resolve().parents[2]
        db_path = str(project_root / "reconciliation.db")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_database() -> None:
    """
    Create all tables from schema.sql if they do not exist.
    Safe to call multiple times (uses CREATE TABLE IF NOT EXISTS).
    """
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")

    conn = get_connection()
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()
