"""
LangGraph state schema for the Reconciliation Exception Investigation Agent.

All list fields that are written by parallel Send API agent nodes carry
Annotated[List[...], operator.add] reducer annotations so that results
accumulate rather than overwrite.
"""

import operator
from datetime import date
from typing import Annotated, List, Literal, Optional, TypedDict


# ── Agent Input (passed via Send API payload, NOT stored on main state) ──────

class AgentInput(TypedDict):
    reconciliation_period: date
    discrepancy_amount: float
    discrepancy_direction: Literal["AR_HIGHER", "GL_HIGHER", "MATCH"]
    previously_found_ids: List[str]


# ── Finding TypedDicts (tool output shapes) ──────────────────────────────────

class RestructuredFinding(TypedDict):
    restructure_id: str
    loan_id: str
    original_due_date: date
    restructured_due_date: date
    original_amount: float
    restructured_amount: float
    missing_in_ar: bool
    missing_in_gl: bool
    finding_type: Literal["removed_from_period", "added_to_period"]


class DelinquencyFinding(TypedDict):
    fee_id: str
    loan_id: str
    fee_date: date
    fee_amount: float
    fee_type: str
    days_past_due: int
    missing_in_ar: bool
    missing_in_gl: bool


class RefundFinding(TypedDict):
    refund_id: str
    loan_id: str
    refund_date: date
    refund_amount: float
    refund_reason: str
    missing_in_ar: bool
    missing_in_gl: bool


class ChargeOffFinding(TypedDict):
    charge_off_id: str
    loan_id: str
    charge_off_date: date
    charge_off_amount: float
    days_past_due: int
    status: str
    missing_in_ar: bool
    missing_in_gl: bool


# ── Agent Result (what each agent returns to the supervisor via Send API) ─────

class AgentResult(TypedDict):
    agent_name: Literal["restructured", "delinquency", "refund", "chargeoff"]
    findings: List[dict]          # category-specific Finding dicts
    explained_amount: float       # sum of impacts matching discrepancy direction
    explained_direction: Literal["AR_HIGHER", "GL_HIGHER"]
    opposite_amount: float        # findings that widen the gap (opposite direction)
    systemic_failures: List[dict] # findings missing in both AR and GL
    systemic_failures_amount: float


# ── Summary Output ────────────────────────────────────────────────────────────

class CorrectingJournalEntry(TypedDict):
    account_code: str
    debit_amount: float
    credit_amount: float
    reference_id: str
    reference_type: str   # RESTRUCTURE | FEE | REFUND | CHARGE_OFF
    entry_type: str
    description: str


class ActionItem(TypedDict):
    priority: Literal["HIGH", "MEDIUM", "LOW"]
    category: str
    description: str
    amount: float


class SystemicPostingFailure(TypedDict):
    """Records missing in BOTH AR and GL — no discrepancy impact but process failure."""
    reference_id: str
    reference_type: str
    category: str
    amount: float
    description: str


class SummaryOutput(TypedDict):
    total_explained_amount: float
    explanation_percentage: float
    correcting_journal_entries: List[CorrectingJournalEntry]
    action_items: List[ActionItem]
    systemic_posting_failures: List[SystemicPostingFailure]
    narrative: str


# ── Main Graph State ──────────────────────────────────────────────────────────

class ReconciliationState(TypedDict):
    # Reconciliation context
    reconciliation_period: date
    materiality_threshold: float

    # Fetched totals
    ar_total: float
    gl_total: float

    # Computed discrepancy
    discrepancy_amount: float
    discrepancy_direction: Literal["AR_HIGHER", "GL_HIGHER", "MATCH"]

    # Supervisor tracking
    iteration_count: int
    explanation_percentage: float

    # Agent results — reducer annotation required for Send API accumulation
    agent_results: Annotated[List[AgentResult], operator.add]

    # Agent findings — reducer annotation required for Send API accumulation
    restructured_findings: Annotated[List[RestructuredFinding], operator.add]
    delinquency_findings: Annotated[List[DelinquencyFinding], operator.add]
    refund_findings: Annotated[List[RefundFinding], operator.add]
    chargeoff_findings: Annotated[List[ChargeOffFinding], operator.add]

    # Summary and report
    summary: Optional[SummaryOutput]
    report_path: Optional[str]
