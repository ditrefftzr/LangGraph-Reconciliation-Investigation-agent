"""
LangGraph graph wiring for the Reconciliation Exception Investigation Agent.

Flow:
  START
    → fetch_data
    → calculate_difference
    → supervisor (aggregation node)
        ↓ supervisor_route (conditional edge)
        ↓ returns [Send x4] on fan-out, or "summary" when done
    ┌── restructured_agent ──┐
    ├── delinquency_agent    ┤ all route back to supervisor
    ├── refunds_agent        ┤ (edges, not Send)
    └── chargeoffs_agent ───┘
        ↓ (supervisor_route returns "summary" when ≥90% or iterations ≥ 3)
    → summary
    → report
  END

Send API parallelism:
  supervisor_route returns a list of Send objects to fan out to all 4 agents.
  Each Send delivers an AgentInput payload directly to the agent node
  (bypassing main state). Agents write back via reducer-annotated state fields.
"""

from langgraph.graph import END, START, StateGraph

from src.graph.state import ReconciliationState
from src.nodes.agents.chargeoffs import chargeoffs_agent_node
from src.nodes.agents.delinquency import delinquency_agent_node
from src.nodes.agents.refunds import refunds_agent_node
from src.nodes.agents.restructured import restructured_agent_node
from src.nodes.calculate_difference import calculate_difference_node
from src.nodes.fetch_data import fetch_data_node
from src.nodes.report import report_node
from src.nodes.summary import summary_node
from src.nodes.supervisor import supervisor_node, supervisor_route


def build_graph() -> StateGraph:
    """
    Construct and compile the reconciliation investigation graph.
    """
    graph = StateGraph(ReconciliationState)

    # ── Nodes ─────────────────────────────────────────────────────────────────
    graph.add_node("fetch_data", fetch_data_node)
    graph.add_node("calculate_difference", calculate_difference_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("restructured_agent", restructured_agent_node)
    graph.add_node("delinquency_agent", delinquency_agent_node)
    graph.add_node("refunds_agent", refunds_agent_node)
    graph.add_node("chargeoffs_agent", chargeoffs_agent_node)
    graph.add_node("generate_summary", summary_node)
    graph.add_node("report", report_node)

    # ── Linear entry path ─────────────────────────────────────────────────────
    graph.add_edge(START, "fetch_data")
    graph.add_edge("fetch_data", "calculate_difference")
    graph.add_edge("calculate_difference", "supervisor")

    # ── Supervisor conditional edge ────────────────────────────────────────────
    # supervisor_route returns either a list[Send] (fan-out) or "generate_summary".
    # The mapping only covers the named-node return; Send returns are handled
    # automatically by LangGraph.
    graph.add_conditional_edges(
        "supervisor",
        supervisor_route,
        {"generate_summary": "generate_summary"},
    )

    # ── Agents route back to supervisor after completing ──────────────────────
    graph.add_edge("restructured_agent", "supervisor")
    graph.add_edge("delinquency_agent", "supervisor")
    graph.add_edge("refunds_agent", "supervisor")
    graph.add_edge("chargeoffs_agent", "supervisor")

    # ── Terminal path ──────────────────────────────────────────────────────────
    graph.add_edge("generate_summary", "report")
    graph.add_edge("report", END)

    return graph.compile()


# Module-level compiled graph instance
reconciliation_graph = build_graph()
