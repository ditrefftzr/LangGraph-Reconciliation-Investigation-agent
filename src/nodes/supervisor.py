"""
Supervisor node.

Responsibilities:
  - supervisor_node: aggregates agent results and computes explanation_percentage.
    On the very first call (no agent_results yet), returns immediately so the
    conditional edge can fan out.
  - supervisor_route (conditional edge): decides whether to fan out to agents
    (first pass or re-delegation) or route to the summary node.

LLM call: used for routing reasoning text (logged to console).
Routing decision is pure Python conditional logic — NOT LLM-driven.
"""

import os
from datetime import date
from typing import Union

from langgraph.types import Send

from src.graph.state import AgentInput, ReconciliationState


# ── LLM setup ─────────────────────────────────────────────────────────────────

def _get_llm():
    from langchain_google_genai import ChatGoogleGenerativeAI
    from config import LLM_MODEL
    return ChatGoogleGenerativeAI(
        model=LLM_MODEL,
        google_api_key=os.environ["GEMINI_API_KEY"],
        temperature=0,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _collect_previously_found_ids(state: ReconciliationState) -> list[str]:
    """Gather all finding PKs accumulated so far (for dedup on re-delegation)."""
    ids: list[str] = []
    for f in state.get("restructured_findings", []):
        ids.append(f["restructure_id"])
    for f in state.get("delinquency_findings", []):
        ids.append(f["fee_id"])
    for f in state.get("refund_findings", []):
        ids.append(f["refund_id"])
    for f in state.get("chargeoff_findings", []):
        ids.append(f["charge_off_id"])
    return ids


def _llm_routing_reasoning(
    state: ReconciliationState,
    explanation_percentage: float,
    decision: str,
) -> str:
    """Ask the LLM to articulate the routing rationale (audit log only)."""
    try:
        llm = _get_llm()
        prompt = (
            f"Reconciliation period: {state['reconciliation_period']}\n"
            f"Discrepancy: ${state['discrepancy_amount']:,.2f} ({state['discrepancy_direction']})\n"
            f"Explanation: {explanation_percentage:.1f}% after iteration "
            f"{state.get('iteration_count', 0)}\n"
            f"Decision: {decision}\n\n"
            "In 2-3 sentences, explain why this routing decision is appropriate."
        )
        response = llm.invoke(prompt)
        return response.content.strip()
    except Exception:
        return f"Routing to {decision} ({explanation_percentage:.1f}% explained)."


# ── Node function ─────────────────────────────────────────────────────────────

def supervisor_node(state: ReconciliationState) -> dict:
    """
    Aggregation node. Computes explanation_percentage from accumulated
    agent_results and sets iteration_count based on rounds completed.

    On the first call (agent_results is empty), returns an empty dict
    so that supervisor_route immediately fans out to agents.
    """
    agent_results = state.get("agent_results", [])

    if not agent_results:
        # First call — nothing to aggregate yet.
        return {}

    discrepancy_amount = state["discrepancy_amount"]
    total_explained = sum(r["explained_amount"] for r in agent_results)
    total_opposite = sum(r["opposite_amount"] for r in agent_results)
    net_explained = total_explained - total_opposite
    explanation_percentage = (
        (net_explained / discrepancy_amount * 100) if discrepancy_amount > 0 else 100.0
    )

    # Each round produces exactly 4 AgentResult entries (one per agent).
    rounds_completed = len(agent_results) // 4

    return {
        "explanation_percentage": explanation_percentage,
        "iteration_count": rounds_completed,
    }


# ── Conditional edge ──────────────────────────────────────────────────────────

def supervisor_route(state: ReconciliationState) -> Union[str, list[Send]]:
    """
    Conditional edge called after supervisor_node.

    Returns a list of Send objects to fan out to all 4 agents, or the
    string "summary" to advance to the summary node.

    Routing rules (pure Python — LLM used for reasoning text only):
      - explanation_percentage >= 90% → summary
      - iteration_count >= 3          → force summary
      - otherwise                     → re-delegate (Send x4)
    """
    explanation_percentage = state.get("explanation_percentage", 0.0)
    iteration_count = state.get("iteration_count", 0)
    discrepancy_direction = state["discrepancy_direction"]
    discrepancy_amount = state["discrepancy_amount"]
    period = state["reconciliation_period"]

    if explanation_percentage >= 90.0:
        reasoning = _llm_routing_reasoning(state, explanation_percentage, "summary")
        print(f"[Supervisor] Routing to summary ({explanation_percentage:.1f}% explained). {reasoning}")
        return "generate_summary"

    if iteration_count >= 3:
        reasoning = _llm_routing_reasoning(state, explanation_percentage, "force_summary")
        print(f"[Supervisor] Forcing summary (max iterations reached). {reasoning}")
        return "generate_summary"

    # Fan out to all 4 agents
    previously_found_ids = _collect_previously_found_ids(state)
    reasoning = _llm_routing_reasoning(state, explanation_percentage, "re_delegate")
    print(
        f"[Supervisor] Re-delegating (iteration {iteration_count + 1}, "
        f"{explanation_percentage:.1f}% explained). {reasoning}"
    )

    agent_input = AgentInput(
        reconciliation_period=period,
        discrepancy_amount=discrepancy_amount,
        discrepancy_direction=discrepancy_direction,
        previously_found_ids=previously_found_ids,
    )

    return [
        Send("restructured_agent", agent_input),
        Send("delinquency_agent", agent_input),
        Send("refunds_agent", agent_input),
        Send("chargeoffs_agent", agent_input),
    ]
