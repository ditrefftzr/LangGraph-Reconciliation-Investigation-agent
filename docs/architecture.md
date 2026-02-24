1. Database Schema
(Unchanged from v1)
Reference Type Enum (shared across ledger tables)
RESTRUCTURE | FEE | REFUND | CHARGE_OFF
GL Entry Type Enum
RESTRUCTURE_REVERSAL     -- reversing original installment from GL
RESTRUCTURE_ADDITION     -- posting restructured installment to GL
FEE_POSTING              -- posting delinquency fee to GL
REFUND_CREDIT            -- posting refund credit to GL
CHARGE_OFF_WRITE_OFF     -- writing off receivable in GL
AR Transaction Type Enum
RESTRUCTURE_REVERSAL     -- removing original installment from AR
RESTRUCTURE_ADDITION     -- adding restructured installment to AR
FEE_CHARGE               -- charging delinquency fee in AR
REFUND_APPLIED           -- applying refund to reduce AR balance
CHARGE_OFF_CLEARANCE     -- clearing charged-off balance from AR

gl_journal_entries
ColumnTypeNotesentry_idPKtransaction_dateDATEperiodDATEReconciliation period (first of month)account_codeVARCHARdebit_amountDECIMALcredit_amountDECIMALreference_idVARCHARFK to exception table PKreference_typeVARCHARDiscriminator: RESTRUCTURE, FEE, REFUND, CHARGE_OFFentry_typeVARCHARSee GL Entry Type Enum above
ar_subledger
ColumnTypeNotesrecord_idPKloan_idVARCHARtransaction_dateDATEperiodDATEReconciliation period (first of month)transaction_typeVARCHARSee AR Transaction Type Enum aboveamountDECIMALreference_idVARCHARFK to exception table PK (renamed from gl_reference_id)reference_typeVARCHARDiscriminator: RESTRUCTURE, FEE, REFUND, CHARGE_OFF
restructured_payments
ColumnTypeNotesrestructure_idPKloan_idVARCHARoriginal_due_dateDATErestructured_due_dateDATEperiodDATEoriginal_amountDECIMALrestructured_amountDECIMALstatusVARCHAR
delinquency_fees
ColumnTypeNotesfee_idPKloan_idVARCHARfee_dateDATEperiodDATEfee_amountDECIMALfee_typeVARCHARdays_past_dueINTEGER
refunds
ColumnTypeNotesrefund_idPKloan_idVARCHARrefund_dateDATEperiodDATErefund_amountDECIMALrefund_reasonVARCHAR
charge_offs
ColumnTypeNotescharge_off_idPKloan_idVARCHARcharge_off_dateDATEperiodDATEdays_past_dueINTEGERcharge_off_amountDECIMALstatusVARCHAR

2. Agent Tool Definitions
(Unchanged from v1 — tools return raw findings. The agent node wraps tool results with impact calculation before returning.)
Restructured Payments Agent — 2 tools
find_restructures_removed_from_period

Source: restructured_payments
Condition: original_due_date within reconciliation period AND restructured_due_date outside period
Cross-references: ar_subledger and gl_journal_entries via reference_id WHERE reference_type = 'RESTRUCTURE'
Returns: Records where AR or GL still reflects the original cash flow that should have been removed
Output fields: restructure_id, loan_id, original_due_date, restructured_due_date, original_amount, restructured_amount, missing_in_ar, missing_in_gl

find_restructures_added_to_period

Source: restructured_payments
Condition: restructured_due_date within reconciliation period AND original_due_date outside period
Cross-references: ar_subledger and gl_journal_entries via reference_id WHERE reference_type = 'RESTRUCTURE'
Returns: Records where AR or GL hasn't picked up the new cash flow that should have been added
Output fields: restructure_id, loan_id, original_due_date, restructured_due_date, original_amount, restructured_amount, missing_in_ar, missing_in_gl

Delinquency Fees Agent — 1 tool
find_fees_missing_in_ar_or_gl

Source: delinquency_fees
Condition: fee_date within reconciliation period
Cross-references: ar_subledger and gl_journal_entries via reference_id WHERE reference_type = 'FEE'
Returns: Fee records not reflected in AR, GL, or both
Output fields: fee_id, loan_id, fee_date, fee_amount, fee_type, days_past_due, missing_in_ar, missing_in_gl

Refunds Agent — 1 tool
find_refunds_missing_in_ar_or_gl

Source: refunds
Condition: refund_date within reconciliation period
Cross-references: ar_subledger and gl_journal_entries via reference_id WHERE reference_type = 'REFUND'
Returns: Refund records where AR not reduced, GL credit missing, or both
Output fields: refund_id, loan_id, refund_date, refund_amount, refund_reason, missing_in_ar, missing_in_gl

Charge-offs Agent — 1 tool
find_chargeoffs_missing_in_ar_or_gl

Source: charge_offs
Condition: days_past_due >= 90 AND status = 'CONFIRMED' within reconciliation period
Cross-references: ar_subledger and gl_journal_entries via reference_id WHERE reference_type = 'CHARGE_OFF'
Returns: Charge-off records where AR balance not cleared, GL entry missing, or both
Output fields: charge_off_id, loan_id, charge_off_date, charge_off_amount, days_past_due, status, missing_in_ar, missing_in_gl


3. State Schema
pythonimport operator
from typing import TypedDict, Literal, Optional, List, Annotated
from datetime import date


# --- Agent Input (passed via Send API payload, NOT stored on main state) ---

class AgentInput(TypedDict):
    reconciliation_period: date
    discrepancy_amount: float
    discrepancy_direction: Literal["AR_HIGHER", "GL_HIGHER", "MATCH"]
    previously_found_ids: List[str]


# --- Finding TypedDicts (tool output shapes) ---

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


# --- Agent Result (what each agent returns to the supervisor via Send API) ---

class AgentResult(TypedDict):
    agent_name: Literal["restructured", "delinquency", "refund", "chargeoff"]
    findings: List[dict]  # category-specific Finding dicts
    explained_amount: float  # sum of impacts matching discrepancy direction
    explained_direction: Literal["AR_HIGHER", "GL_HIGHER"]  # direction of explained findings
    opposite_amount: float  # findings that widen the gap (opposite direction)
    systemic_failures: List[dict]  # findings missing in both AR and GL
    systemic_failures_amount: float


# --- Summary Output ---

class CorrectingJournalEntry(TypedDict):
    account_code: str
    debit_amount: float
    credit_amount: float
    reference_id: str
    reference_type: str  # RESTRUCTURE, FEE, REFUND, CHARGE_OFF
    entry_type: str
    description: str


class ActionItem(TypedDict):
    priority: Literal["HIGH", "MEDIUM", "LOW"]
    category: str
    description: str
    amount: float


class SystemicPostingFailure(TypedDict):
    """Records missing in BOTH AR and GL — no discrepancy impact but indicates process failure."""
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


# --- Main Graph State ---

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

    # Agent results — reducer annotation for Send API accumulation
    # Each agent appends its AgentResult; supervisor reads all to aggregate
    agent_results: Annotated[List[AgentResult], operator.add]

    # Agent findings — reducer annotation for Send API accumulation
    # Raw findings preserved for summary node to generate journal entries
    restructured_findings: Annotated[List[RestructuredFinding], operator.add]
    delinquency_findings: Annotated[List[DelinquencyFinding], operator.add]
    refund_findings: Annotated[List[RefundFinding], operator.add]
    chargeoff_findings: Annotated[List[ChargeOffFinding], operator.add]

    # Summary and report
    summary: Optional[SummaryOutput]
    report_path: Optional[str]

4. Impact Calculation Logic (shared utility, used by agents)
Lives in src/utils/impact.py. Each agent imports this and calls it on its findings before constructing AgentResult.
python"""
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
            # Original installment should have been removed but wasn't
            if not missing_ar and missing_gl:
                # AR still has it, GL removed it → AR higher
                return _impact(finding["original_amount"], "AR_HIGHER")
            if missing_ar and not missing_gl:
                # GL still has it, AR removed it → GL higher
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

    # Fallback
    return {"amount": 0, "direction": None, "explains_discrepancy": False, "is_systemic_failure": False}


def _impact(amount: float, direction: Literal["AR_HIGHER", "GL_HIGHER"]) -> dict:
    return {"amount": amount, "direction": direction, "explains_discrepancy": True, "is_systemic_failure": False}


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

5. Node Responsibilities (updated)
Supervisor Node
Inputs from state: discrepancy_amount, discrepancy_direction, iteration_count, agent_results
Logic:
1. If first iteration (iteration_count == 0):
   - Construct AgentInput for each agent
   - Fan out to 4 agents via Send API
   - Increment iteration_count

2. If returning from agents (agent_results populated):
   - Aggregate: total_explained = sum(r.explained_amount for r in agent_results)
   - Compute: explanation_percentage = total_explained / discrepancy_amount * 100
   - Collect previously_found_ids from all agent findings (for dedup on re-delegation)

   - If explanation_percentage >= 90%:
       → Route to Summary node
   - If explanation_percentage < 90% AND iteration_count < 3:
       → Re-delegate: construct new AgentInput with previously_found_ids
       → Fan out to 4 agents again via Send API
       → Increment iteration_count
   - If iteration_count >= 3:
       → Force route to Summary node (with whatever was found)
Writes to state: iteration_count, explanation_percentage
Note: The supervisor does NOT use an LLM call for routing — this is pure conditional logic. The LLM is only involved in the agent nodes (tool selection) and summary node (narrative generation).
Agent Nodes (all 4 follow same pattern)
Inputs via Send API payload: AgentInput
Logic:
1. Receive AgentInput (period, discrepancy context, previously_found_ids)
2. Call tool(s) to discover findings
3. Filter out any findings whose PK is in previously_found_ids (dedup)
4. Call build_agent_result() to compute explained amounts
5. Return: AgentResult → state.agent_results (via reducer)
         + category-specific findings → state.{category}_findings (via reducer)
Writes to state: agent_results (appended), {category}_findings (appended)
Summary Node
Inputs from state: agent_results, all 4 findings lists, discrepancy_amount, discrepancy_direction, explanation_percentage
Logic:
1. Receives pre-computed totals from supervisor (via explanation_percentage on state)
2. Reads agent_results for:
   - total_explained_amount (already summed by supervisor, but also on each AgentResult)
   - systemic_failures across all agents
   - opposite_direction amounts (gap-widening findings)
3. Iterates through all findings lists to generate:
   - Correcting journal entries (one per finding that explains discrepancy)
   - Action items ranked by priority:
     * HIGH: opposite-direction findings (they widen the gap)
     * HIGH: systemic failures (process breakdown)
     * MEDIUM: large explained findings needing journal correction
     * LOW: small explained findings
4. Generates narrative via LLM call (structured prompt with all data)
5. Constructs SummaryOutput
Writes to state: summary
Report Node
Inputs from state: summary
Logic: Converts SummaryOutput JSON into formatted report (PDF or document). Pure formatting — no business logic.
Writes to state: report_path

6. Updated File Structure
One addition — the shared utility module:
reconciliation-agent/
├── ...
├── src/
│   ├── __init__.py
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── graph.py
│   │   └── state.py
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── fetch_data.py
│   │   ├── calculate_difference.py
│   │   ├── supervisor.py
│   │   ├── summary.py
│   │   ├── report.py
│   │   └── agents/
│   │       ├── __init__.py
│   │       ├── restructured.py
│   │       ├── delinquency.py
│   │       ├── refunds.py
│   │       └── chargeoffs.py
│   ├── utils/                  # NEW
│   │   ├── __init__.py
│   │   └── impact.py           # calculate_finding_impact + build_agent_result
│   └── database/
│       ├── __init__.py
│       ├── schema.sql
│       ├── seed.py
│       └── connection.py
├── output/
│   └── .gitkeep
└── tests/
    ├── __init__.py
    ├── test_discrepancy.py
    ├── test_supervisor_routing.py
    ├── test_agent_restructured.py
    ├── test_agent_delinquency.py
    ├── test_agent_refunds.py
    ├── test_agent_chargeoffs.py
    ├── test_impact_calculation.py  # NEW
    └── test_database_queries.py