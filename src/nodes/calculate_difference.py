"""
Calculate Difference node.

Computes discrepancy_amount and discrepancy_direction from ar_total and gl_total.
Writes both values to state.
"""

from src.graph.state import ReconciliationState


def calculate_difference_node(state: ReconciliationState) -> dict:
    """
    Derive discrepancy amount and direction from fetched totals.

    discrepancy_amount   = abs(ar_total - gl_total)
    discrepancy_direction:
      AR_HIGHER — AR subledger balance exceeds GL control account
      GL_HIGHER — GL control account exceeds AR subledger
      MATCH     — no discrepancy (within materiality threshold)
    """
    ar_total = state["ar_total"]
    gl_total = state["gl_total"]
    materiality_threshold = state.get("materiality_threshold", 0.01)

    diff = ar_total - gl_total
    discrepancy_amount = abs(diff)

    if discrepancy_amount <= materiality_threshold:
        direction = "MATCH"
    elif diff > 0:
        direction = "AR_HIGHER"
    else:
        direction = "GL_HIGHER"

    return {
        "discrepancy_amount": discrepancy_amount,
        "discrepancy_direction": direction,
    }
