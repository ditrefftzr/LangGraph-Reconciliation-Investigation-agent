"""
Tests for supervisor routing logic.

Coverage:
  - explanation_percentage >= 90% → route to "summary" (string)
  - explanation_percentage < 90% + iteration_count < 3 → re-delegate (list[Send])
  - iteration_count >= 3 → force summary (string)
"""

import pytest
from unittest.mock import patch
from langgraph.types import Send

from src.nodes.supervisor import supervisor_route


def _state(explanation_percentage: float, iteration_count: int) -> dict:
    """Minimal ReconciliationState-like dict for routing tests."""
    return {
        "reconciliation_period": "2024-01-01",
        "materiality_threshold": 0.01,
        "ar_total": 10000.0,
        "gl_total": 5000.0,
        "discrepancy_amount": 5000.0,
        "discrepancy_direction": "AR_HIGHER",
        "iteration_count": iteration_count,
        "explanation_percentage": explanation_percentage,
        "agent_results": [],
        "restructured_findings": [],
        "delinquency_findings": [],
        "refund_findings": [],
        "chargeoff_findings": [],
        "summary": None,
        "report_path": None,
    }


# Suppress LLM calls in all routing tests
@pytest.fixture(autouse=True)
def mock_llm_reasoning():
    with patch("src.nodes.supervisor._llm_routing_reasoning", return_value="mocked reason"):
        yield


class TestSupervisorRouting:
    def test_routes_to_summary_at_90_percent(self):
        state = _state(explanation_percentage=90.0, iteration_count=1)
        assert supervisor_route(state) == "generate_summary"

    def test_routes_to_summary_above_90_percent(self):
        state = _state(explanation_percentage=95.5, iteration_count=1)
        assert supervisor_route(state) == "generate_summary"

    def test_routes_to_summary_at_100_percent(self):
        state = _state(explanation_percentage=100.0, iteration_count=1)
        assert supervisor_route(state) == "generate_summary"

    def test_redelegates_below_90_iteration_1(self):
        state = _state(explanation_percentage=80.0, iteration_count=1)
        result = supervisor_route(state)
        assert isinstance(result, list)
        assert len(result) == 4
        assert all(isinstance(s, Send) for s in result)

    def test_redelegates_below_90_iteration_2(self):
        state = _state(explanation_percentage=50.0, iteration_count=2)
        result = supervisor_route(state)
        assert isinstance(result, list)
        assert len(result) == 4

    def test_force_summary_at_iteration_3(self):
        state = _state(explanation_percentage=40.0, iteration_count=3)
        assert supervisor_route(state) == "generate_summary"

    def test_force_summary_above_iteration_3(self):
        state = _state(explanation_percentage=10.0, iteration_count=5)
        assert supervisor_route(state) == "generate_summary"

    def test_boundary_just_below_90(self):
        state = _state(explanation_percentage=89.99, iteration_count=1)
        result = supervisor_route(state)
        assert isinstance(result, list)

    def test_zero_explanation_routes_to_redelegate(self):
        state = _state(explanation_percentage=0.0, iteration_count=1)
        result = supervisor_route(state)
        assert isinstance(result, list)
        assert len(result) == 4

    def test_redelegate_sends_target_all_four_agents(self):
        state = _state(explanation_percentage=50.0, iteration_count=1)
        result = supervisor_route(state)
        node_names = {s.node for s in result}
        assert node_names == {
            "restructured_agent",
            "delinquency_agent",
            "refunds_agent",
            "chargeoffs_agent",
        }

    def test_redelegate_passes_previously_found_ids(self):
        state = _state(explanation_percentage=50.0, iteration_count=1)
        state["restructured_findings"] = [
            {"restructure_id": "RST-001", "loan_id": "L01",
             "original_due_date": "2024-01-15", "restructured_due_date": "2024-03-15",
             "original_amount": 1000.0, "restructured_amount": 900.0,
             "missing_in_ar": False, "missing_in_gl": True, "finding_type": "removed_from_period"}
        ]
        result = supervisor_route(state)
        for send in result:
            assert "RST-001" in send.arg["previously_found_ids"]
