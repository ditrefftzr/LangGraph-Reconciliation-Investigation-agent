"""
Impact calculation utility.

Used by each agent to compute the dollar impact of its findings
and classify them by direction (AR_HIGHER / GL_HIGHER) or systemic failure.
"""

from typing import Literal


def calculate_finding_impact(finding: dict, category: str) -> dict:
    """
    Compute the dollar impact and direction of a single finding.

    Returns:
        {
            "amount": float,
            "direction": "AR_HIGHER" | "GL_HIGHER" | None,
            "explains_discrepancy": bool,
            "is_systemic_failure": bool,
        }
    """
    missing_ar = finding["missing_in_ar"]
    missing_gl = finding["missing_in_gl"]

    # Both missing = systemic failure, no net discrepancy impact
    if missing_ar and missing_gl:
        return {
            "amount": _get_amount(finding, category),
            "direction": None,
            "explains_discrepancy": False,
            "is_systemic_failure": True,
        }

    # --- RESTRUCTURED PAYMENTS ---
    if category == "restructured":
        if finding["finding_type"] == "removed_from_period":
            # Original installment should have been removed (reversal applied) but wasn't on one side.
            # missing_in_ar=True  → AR did NOT apply reversal → AR still shows original → AR higher
            # missing_in_gl=True  → GL did NOT apply reversal → GL still shows original → GL higher
            if missing_ar and not missing_gl:
                # AR missing reversal (AR still has original), GL reversed → AR higher
                return _impact(finding["original_amount"], "AR_HIGHER")
            if not missing_ar and missing_gl:
                # GL missing reversal (GL still has original), AR reversed → GL higher
                return _impact(finding["original_amount"], "GL_HIGHER")

        elif finding["finding_type"] == "added_to_period":
            # Restructured installment should have been added but wasn't
            if missing_ar and not missing_gl:
                # GL posted, AR hasn't → GL higher
                return _impact(finding["restructured_amount"], "GL_HIGHER")
            if not missing_ar and missing_gl:
                # AR posted, GL hasn't → AR higher
                return _impact(finding["restructured_amount"], "AR_HIGHER")

    # --- DELINQUENCY FEES ---
    # Fees increase the receivable balance
    elif category == "delinquency":
        if missing_gl and not missing_ar:
            # Fee in AR but not GL → AR higher
            return _impact(finding["fee_amount"], "AR_HIGHER")
        if missing_ar and not missing_gl:
            # Fee in GL but not AR → GL higher
            return _impact(finding["fee_amount"], "GL_HIGHER")

    # --- REFUNDS ---
    # Refunds decrease the receivable balance
    elif category == "refund":
        if missing_ar and not missing_gl:
            # GL credited refund, AR not reduced → AR higher
            return _impact(finding["refund_amount"], "AR_HIGHER")
        if missing_gl and not missing_ar:
            # AR reduced, GL hasn't credited → GL higher
            return _impact(finding["refund_amount"], "GL_HIGHER")

    # --- CHARGE-OFFS ---
    # Charge-offs decrease the receivable balance
    elif category == "chargeoff":
        if missing_ar and not missing_gl:
            # GL wrote off, AR not cleared → AR higher
            return _impact(finding["charge_off_amount"], "AR_HIGHER")
        if missing_gl and not missing_ar:
            # AR cleared, GL entry missing → GL higher
            return _impact(finding["charge_off_amount"], "GL_HIGHER")

    # Fallback: no impact (neither or both flags set without matching category)
    return {
        "amount": 0.0,
        "direction": None,
        "explains_discrepancy": False,
        "is_systemic_failure": False,
    }


def _impact(amount: float, direction: Literal["AR_HIGHER", "GL_HIGHER"]) -> dict:
    return {
        "amount": amount,
        "direction": direction,
        "explains_discrepancy": True,
        "is_systemic_failure": False,
    }


def _get_amount(finding: dict, category: str) -> float:
    """Extract the relevant amount field based on category (for systemic failures)."""
    amount_fields = {
        "restructured": "original_amount",
        "delinquency": "fee_amount",
        "refund": "refund_amount",
        "chargeoff": "charge_off_amount",
    }
    return finding.get(amount_fields.get(category, ""), 0.0)


def build_agent_result(
    agent_name: str,
    findings: list[dict],
    category: str,
    discrepancy_direction: str,
) -> dict:
    """
    Called by each agent after tool execution.
    Processes all findings through impact calculation and builds AgentResult.

    Args:
        agent_name: "restructured", "delinquency", "refund", or "chargeoff"
        findings: list of Finding dicts from tools
        category: same as agent_name (used by calculate_finding_impact)
        discrepancy_direction: "AR_HIGHER" or "GL_HIGHER" from supervisor context

    Returns:
        AgentResult dict ready to write to state
    """
    explained_amount = 0.0
    opposite_amount = 0.0
    systemic_failures = []
    systemic_failures_amount = 0.0

    for finding in findings:
        impact = calculate_finding_impact(finding, category)

        if impact["is_systemic_failure"]:
            systemic_failures.append(finding)
            systemic_failures_amount += impact["amount"]
        elif impact["explains_discrepancy"]:
            if impact["direction"] == discrepancy_direction:
                explained_amount += impact["amount"]
            else:
                opposite_amount += impact["amount"]

    return {
        "agent_name": agent_name,
        "findings": findings,
        "explained_amount": explained_amount,
        "explained_direction": discrepancy_direction,
        "opposite_amount": opposite_amount,
        "systemic_failures": systemic_failures,
        "systemic_failures_amount": systemic_failures_amount,
    }
