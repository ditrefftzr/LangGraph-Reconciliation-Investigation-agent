"""
Tests for fetch_data and calculate_difference nodes.

Coverage:
  - AR_HIGHER direction
  - GL_HIGHER direction
  - MATCH (within materiality threshold)
  - Exact discrepancy amounts from seed data
"""

import sqlite3
import pytest

from src.nodes.calculate_difference import calculate_difference_node


def _state(ar_total: float, gl_total: float, threshold: float = 0.01) -> dict:
    return {
        "reconciliation_period": "2024-01-01",
        "materiality_threshold": threshold,
        "ar_total": ar_total,
        "gl_total": gl_total,
        "discrepancy_amount": 0.0,
        "discrepancy_direction": "MATCH",
        "iteration_count": 0,
        "explanation_percentage": 0.0,
        "agent_results": [],
        "restructured_findings": [],
        "delinquency_findings": [],
        "refund_findings": [],
        "chargeoff_findings": [],
        "summary": None,
        "report_path": None,
    }


class TestCalculateDifference:
    def test_ar_higher(self):
        result = calculate_difference_node(_state(ar_total=10000.0, gl_total=7000.0))
        assert result["discrepancy_amount"] == pytest.approx(3000.0)
        assert result["discrepancy_direction"] == "AR_HIGHER"

    def test_gl_higher(self):
        result = calculate_difference_node(_state(ar_total=7000.0, gl_total=10000.0))
        assert result["discrepancy_amount"] == pytest.approx(3000.0)
        assert result["discrepancy_direction"] == "GL_HIGHER"

    def test_exact_match(self):
        result = calculate_difference_node(_state(ar_total=5000.0, gl_total=5000.0))
        assert result["discrepancy_amount"] == pytest.approx(0.0)
        assert result["discrepancy_direction"] == "MATCH"

    def test_within_materiality_threshold(self):
        result = calculate_difference_node(
            _state(ar_total=5000.00, gl_total=5000.005, threshold=0.01)
        )
        assert result["discrepancy_direction"] == "MATCH"

    def test_outside_materiality_threshold(self):
        result = calculate_difference_node(
            _state(ar_total=5000.00, gl_total=5000.02, threshold=0.01)
        )
        assert result["discrepancy_direction"] == "GL_HIGHER"
        assert result["discrepancy_amount"] == pytest.approx(0.02)


class TestSeedDataDiscrepancy:
    """
    Validate that seed data produces the expected discrepancy totals.

    Seed AR entries:   RST-001 (1200) + RST-003 (200) + FEE-001 (75) = 1475.00
    Seed GL entries (net debit):
      GL-RST-001-REV: credit 1200 → net -1200
      GL-RST-002-ADD: debit 950  → net +950
      GL-REF-001:     debit 300  → net +300
      GL-CHG-001:     debit 5000 → net +5000
      Net GL = -1200 + 950 + 300 + 5000 = 5050.00

    Expected: AR=1475, GL=5050 → GL higher by 3575.00
    """

    @pytest.fixture(autouse=True)
    def seed_db(self, tmp_path, monkeypatch):
        """Create a fresh in-memory SQLite DB seeded with test data."""
        import os
        db_file = str(tmp_path / "test.db")
        monkeypatch.setenv("DB_PATH", db_file)

        from src.database.connection import initialize_database
        from src.database.seed import seed_database
        initialize_database()
        seed_database()

    def test_ar_total_matches_seed(self):
        from src.nodes.fetch_data import fetch_data_node
        state = _state(ar_total=0.0, gl_total=0.0)
        state["reconciliation_period"] = "2024-01-01"
        result = fetch_data_node(state)
        assert result["ar_total"] == pytest.approx(1475.0)

    def test_gl_total_matches_seed(self):
        from src.nodes.fetch_data import fetch_data_node
        state = _state(ar_total=0.0, gl_total=0.0)
        state["reconciliation_period"] = "2024-01-01"
        result = fetch_data_node(state)
        assert result["gl_total"] == pytest.approx(5050.0)

    def test_discrepancy_direction_and_amount(self):
        from src.nodes.fetch_data import fetch_data_node
        state = _state(ar_total=0.0, gl_total=0.0)
        state["reconciliation_period"] = "2024-01-01"
        fetched = fetch_data_node(state)
        state.update(fetched)
        diff = calculate_difference_node(state)
        assert diff["discrepancy_direction"] == "GL_HIGHER"
        assert diff["discrepancy_amount"] == pytest.approx(3575.0)
