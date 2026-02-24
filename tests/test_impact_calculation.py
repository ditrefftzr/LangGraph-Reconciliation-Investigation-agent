"""
Tests for src/utils/impact.py

Coverage:
  - calculate_finding_impact: all 4 categories × both directions
  - Both-missing (systemic failure) exclusion from explained_amount
  - build_agent_result aggregation
"""

import pytest
from src.utils.impact import build_agent_result, calculate_finding_impact


# ── Restructured — removed_from_period ───────────────────────────────────────

class TestRestructuredRemovedFromPeriod:
    BASE = {
        "restructure_id": "RST-001",
        "loan_id": "LOAN-001",
        "original_due_date": "2024-01-15",
        "restructured_due_date": "2024-03-15",
        "original_amount": 1000.0,
        "restructured_amount": 900.0,
        "finding_type": "removed_from_period",
    }

    def test_ar_still_has_it_gl_removed(self):
        f = {**self.BASE, "missing_in_ar": False, "missing_in_gl": True}
        result = calculate_finding_impact(f, "restructured")
        assert result["direction"] == "AR_HIGHER"
        assert result["amount"] == 1000.0
        assert result["explains_discrepancy"] is True
        assert result["is_systemic_failure"] is False

    def test_gl_still_has_it_ar_removed(self):
        f = {**self.BASE, "missing_in_ar": True, "missing_in_gl": False}
        result = calculate_finding_impact(f, "restructured")
        assert result["direction"] == "GL_HIGHER"
        assert result["amount"] == 1000.0

    def test_both_missing_is_systemic(self):
        f = {**self.BASE, "missing_in_ar": True, "missing_in_gl": True}
        result = calculate_finding_impact(f, "restructured")
        assert result["is_systemic_failure"] is True
        assert result["explains_discrepancy"] is False
        assert result["direction"] is None
        assert result["amount"] == 1000.0  # original_amount for restructured


# ── Restructured — added_to_period ────────────────────────────────────────────

class TestRestructuredAddedToPeriod:
    BASE = {
        "restructure_id": "RST-002",
        "loan_id": "LOAN-002",
        "original_due_date": "2023-12-20",
        "restructured_due_date": "2024-01-20",
        "original_amount": 900.0,
        "restructured_amount": 950.0,
        "finding_type": "added_to_period",
    }

    def test_gl_posted_ar_missing(self):
        f = {**self.BASE, "missing_in_ar": True, "missing_in_gl": False}
        result = calculate_finding_impact(f, "restructured")
        assert result["direction"] == "GL_HIGHER"
        assert result["amount"] == 950.0

    def test_ar_posted_gl_missing(self):
        f = {**self.BASE, "missing_in_ar": False, "missing_in_gl": True}
        result = calculate_finding_impact(f, "restructured")
        assert result["direction"] == "AR_HIGHER"
        assert result["amount"] == 950.0


# ── Delinquency Fees ──────────────────────────────────────────────────────────

class TestDelinquencyFees:
    BASE = {
        "fee_id": "FEE-001",
        "loan_id": "LOAN-B001",
        "fee_date": "2024-01-10",
        "fee_amount": 75.0,
        "fee_type": "LATE_FEE",
        "days_past_due": 30,
    }

    def test_in_ar_missing_in_gl(self):
        f = {**self.BASE, "missing_in_ar": False, "missing_in_gl": True}
        result = calculate_finding_impact(f, "delinquency")
        assert result["direction"] == "AR_HIGHER"
        assert result["amount"] == 75.0

    def test_in_gl_missing_in_ar(self):
        f = {**self.BASE, "missing_in_ar": True, "missing_in_gl": False}
        result = calculate_finding_impact(f, "delinquency")
        assert result["direction"] == "GL_HIGHER"
        assert result["amount"] == 75.0

    def test_both_missing_systemic(self):
        f = {**self.BASE, "missing_in_ar": True, "missing_in_gl": True}
        result = calculate_finding_impact(f, "delinquency")
        assert result["is_systemic_failure"] is True
        assert result["explains_discrepancy"] is False


# ── Refunds ───────────────────────────────────────────────────────────────────

class TestRefunds:
    BASE = {
        "refund_id": "REF-001",
        "loan_id": "LOAN-C001",
        "refund_date": "2024-01-18",
        "refund_amount": 300.0,
        "refund_reason": "OVERPAYMENT",
    }

    def test_gl_credited_ar_not_reduced(self):
        f = {**self.BASE, "missing_in_ar": True, "missing_in_gl": False}
        result = calculate_finding_impact(f, "refund")
        assert result["direction"] == "AR_HIGHER"
        assert result["amount"] == 300.0

    def test_ar_reduced_gl_missing(self):
        f = {**self.BASE, "missing_in_ar": False, "missing_in_gl": True}
        result = calculate_finding_impact(f, "refund")
        assert result["direction"] == "GL_HIGHER"
        assert result["amount"] == 300.0

    def test_both_missing_systemic(self):
        f = {**self.BASE, "missing_in_ar": True, "missing_in_gl": True}
        result = calculate_finding_impact(f, "refund")
        assert result["is_systemic_failure"] is True


# ── Charge-offs ───────────────────────────────────────────────────────────────

class TestChargeOffs:
    BASE = {
        "charge_off_id": "CHG-001",
        "loan_id": "LOAN-D001",
        "charge_off_date": "2024-01-25",
        "charge_off_amount": 5000.0,
        "days_past_due": 120,
        "status": "CONFIRMED",
    }

    def test_gl_wrote_off_ar_not_cleared(self):
        f = {**self.BASE, "missing_in_ar": True, "missing_in_gl": False}
        result = calculate_finding_impact(f, "chargeoff")
        assert result["direction"] == "AR_HIGHER"
        assert result["amount"] == 5000.0

    def test_ar_cleared_gl_missing(self):
        f = {**self.BASE, "missing_in_ar": False, "missing_in_gl": True}
        result = calculate_finding_impact(f, "chargeoff")
        assert result["direction"] == "GL_HIGHER"
        assert result["amount"] == 5000.0

    def test_both_missing_systemic(self):
        f = {**self.BASE, "missing_in_ar": True, "missing_in_gl": True}
        result = calculate_finding_impact(f, "chargeoff")
        assert result["is_systemic_failure"] is True


# ── build_agent_result ────────────────────────────────────────────────────────

class TestBuildAgentResult:
    def test_explained_amount_sums_matching_direction(self):
        findings = [
            {
                "fee_id": "FEE-A",
                "loan_id": "L1",
                "fee_date": "2024-01-01",
                "fee_amount": 100.0,
                "fee_type": "LATE_FEE",
                "days_past_due": 30,
                "missing_in_ar": False,
                "missing_in_gl": True,   # AR_HIGHER
            },
            {
                "fee_id": "FEE-B",
                "loan_id": "L2",
                "fee_date": "2024-01-02",
                "fee_amount": 50.0,
                "fee_type": "LATE_FEE",
                "days_past_due": 35,
                "missing_in_ar": False,
                "missing_in_gl": True,   # AR_HIGHER
            },
        ]
        result = build_agent_result("delinquency", findings, "delinquency", "AR_HIGHER")
        assert result["explained_amount"] == 150.0
        assert result["opposite_amount"] == 0.0
        assert result["systemic_failures"] == []

    def test_opposite_direction_not_in_explained(self):
        findings = [
            {
                "fee_id": "FEE-A",
                "loan_id": "L1",
                "fee_date": "2024-01-01",
                "fee_amount": 100.0,
                "fee_type": "LATE_FEE",
                "days_past_due": 30,
                "missing_in_ar": True,
                "missing_in_gl": False,  # GL_HIGHER
            },
        ]
        result = build_agent_result("delinquency", findings, "delinquency", "AR_HIGHER")
        assert result["explained_amount"] == 0.0
        assert result["opposite_amount"] == 100.0

    def test_systemic_failure_excluded_from_explained(self):
        findings = [
            {
                "fee_id": "FEE-SYS",
                "loan_id": "L1",
                "fee_date": "2024-01-01",
                "fee_amount": 75.0,
                "fee_type": "PENALTY_FEE",
                "days_past_due": 45,
                "missing_in_ar": True,
                "missing_in_gl": True,
            },
        ]
        result = build_agent_result("delinquency", findings, "delinquency", "AR_HIGHER")
        assert result["explained_amount"] == 0.0
        assert result["opposite_amount"] == 0.0
        assert len(result["systemic_failures"]) == 1
        assert result["systemic_failures_amount"] == 75.0
