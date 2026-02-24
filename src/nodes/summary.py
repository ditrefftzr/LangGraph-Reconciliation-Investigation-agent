"""
Summary node.

Aggregates all agent findings into correcting journal entries, action items,
and systemic failure records. Generates a narrative via LLM.
Writes SummaryOutput to state.
"""

import os
from typing import List

from langchain_google_genai import ChatGoogleGenerativeAI

from src.graph.state import (
    ActionItem,
    AgentResult,
    ChargeOffFinding,
    CorrectingJournalEntry,
    DelinquencyFinding,
    ReconciliationState,
    RefundFinding,
    RestructuredFinding,
    SummaryOutput,
    SystemicPostingFailure,
)
from src.utils.impact import calculate_finding_impact


# ── LLM setup ────────────────────────────────────────────────────────────────

def _get_llm() -> ChatGoogleGenerativeAI:
    from config import LLM_MODEL
    return ChatGoogleGenerativeAI(
        model=LLM_MODEL,
        google_api_key=os.environ["GEMINI_API_KEY"],
        temperature=0.2,
    )


# ── Journal entry builders ────────────────────────────────────────────────────

def _journal_for_restructured(finding: RestructuredFinding) -> List[CorrectingJournalEntry]:
    entries = []
    if finding["finding_type"] == "removed_from_period":
        amount = finding["original_amount"]
        if finding["missing_in_ar"] and not finding["missing_in_gl"]:
            entries.append(CorrectingJournalEntry(
                account_code="AR_CONTROL",
                debit_amount=0.0,
                credit_amount=amount,
                reference_id=finding["restructure_id"],
                reference_type="RESTRUCTURE",
                entry_type="RESTRUCTURE_REVERSAL",
                description=f"Reverse original installment from period for {finding['loan_id']}",
            ))
        elif finding["missing_in_gl"] and not finding["missing_in_ar"]:
            entries.append(CorrectingJournalEntry(
                account_code="AR_CONTROL",
                debit_amount=0.0,
                credit_amount=amount,
                reference_id=finding["restructure_id"],
                reference_type="RESTRUCTURE",
                entry_type="RESTRUCTURE_REVERSAL",
                description=f"Post GL reversal for restructured installment {finding['loan_id']}",
            ))
    elif finding["finding_type"] == "added_to_period":
        amount = finding["restructured_amount"]
        if finding["missing_in_ar"] and not finding["missing_in_gl"]:
            entries.append(CorrectingJournalEntry(
                account_code="AR_CONTROL",
                debit_amount=amount,
                credit_amount=0.0,
                reference_id=finding["restructure_id"],
                reference_type="RESTRUCTURE",
                entry_type="RESTRUCTURE_ADDITION",
                description=f"Add restructured installment to AR for {finding['loan_id']}",
            ))
        elif finding["missing_in_gl"] and not finding["missing_in_ar"]:
            entries.append(CorrectingJournalEntry(
                account_code="AR_CONTROL",
                debit_amount=amount,
                credit_amount=0.0,
                reference_id=finding["restructure_id"],
                reference_type="RESTRUCTURE",
                entry_type="RESTRUCTURE_ADDITION",
                description=f"Post GL addition for restructured installment {finding['loan_id']}",
            ))
    return entries


def _journal_for_delinquency(finding: DelinquencyFinding) -> List[CorrectingJournalEntry]:
    if finding["missing_in_ar"] and finding["missing_in_gl"]:
        return []  # systemic failure — no correcting entry
    amount = finding["fee_amount"]
    if finding["missing_in_gl"]:
        return [CorrectingJournalEntry(
            account_code="FEE_INCOME",
            debit_amount=amount,
            credit_amount=0.0,
            reference_id=finding["fee_id"],
            reference_type="FEE",
            entry_type="FEE_POSTING",
            description=f"Post delinquency fee to GL for {finding['loan_id']} ({finding['fee_type']})",
        )]
    if finding["missing_in_ar"]:
        return [CorrectingJournalEntry(
            account_code="AR_CONTROL",
            debit_amount=amount,
            credit_amount=0.0,
            reference_id=finding["fee_id"],
            reference_type="FEE",
            entry_type="FEE_POSTING",
            description=f"Post delinquency fee to AR for {finding['loan_id']} ({finding['fee_type']})",
        )]
    return []


def _journal_for_refund(finding: RefundFinding) -> List[CorrectingJournalEntry]:
    if finding["missing_in_ar"] and finding["missing_in_gl"]:
        return []
    amount = finding["refund_amount"]
    if finding["missing_in_ar"]:
        return [CorrectingJournalEntry(
            account_code="AR_CONTROL",
            debit_amount=0.0,
            credit_amount=amount,
            reference_id=finding["refund_id"],
            reference_type="REFUND",
            entry_type="REFUND_APPLIED",
            description=f"Apply refund to AR balance for {finding['loan_id']} ({finding['refund_reason']})",
        )]
    if finding["missing_in_gl"]:
        return [CorrectingJournalEntry(
            account_code="REFUND_PAYABLE",
            debit_amount=amount,
            credit_amount=0.0,
            reference_id=finding["refund_id"],
            reference_type="REFUND",
            entry_type="REFUND_CREDIT",
            description=f"Post refund credit to GL for {finding['loan_id']} ({finding['refund_reason']})",
        )]
    return []


def _journal_for_chargeoff(finding: ChargeOffFinding) -> List[CorrectingJournalEntry]:
    if finding["missing_in_ar"] and finding["missing_in_gl"]:
        return []
    amount = finding["charge_off_amount"]
    if finding["missing_in_ar"]:
        return [CorrectingJournalEntry(
            account_code="AR_CONTROL",
            debit_amount=0.0,
            credit_amount=amount,
            reference_id=finding["charge_off_id"],
            reference_type="CHARGE_OFF",
            entry_type="CHARGE_OFF_CLEARANCE",
            description=f"Clear charged-off balance from AR for {finding['loan_id']}",
        )]
    if finding["missing_in_gl"]:
        return [CorrectingJournalEntry(
            account_code="CREDIT_LOSS",
            debit_amount=amount,
            credit_amount=0.0,
            reference_id=finding["charge_off_id"],
            reference_type="CHARGE_OFF",
            entry_type="CHARGE_OFF_WRITE_OFF",
            description=f"Post charge-off write-off to GL for {finding['loan_id']}",
        )]
    return []


# ── Action item builders ──────────────────────────────────────────────────────

def _action_priority(amount: float, is_opposite: bool, is_systemic: bool) -> str:
    if is_opposite or is_systemic:
        return "HIGH"
    if amount >= 1000:
        return "MEDIUM"
    return "LOW"


# ── Narrative generation ──────────────────────────────────────────────────────

def _generate_narrative(
    state: ReconciliationState,
    net_explained: float,
    explanation_percentage: float,
    journal_entries: List[CorrectingJournalEntry],
    action_items: List[ActionItem],
    systemic_failures: List[SystemicPostingFailure],
) -> str:
    try:
        llm = _get_llm()
        high_actions = [a for a in action_items if a["priority"] == "HIGH"]

        # Build findings text with context labels so the LLM understands the nature of each item
        findings_lines = []
        for a in action_items:
            desc = a["description"]
            if "added_to_period" in desc:
                context = " [valid transaction — present in one ledger, pending alignment in the other]"
            elif "removed_from_period" in desc:
                context = " [valid reversal — present in one ledger, pending alignment in the other]"
            else:
                context = ""
            findings_lines.append(
                f"  - [{a['priority']}] {a['category']}: {desc} (${a['amount']:,.2f}){context}"
            )
        for sf in systemic_failures:
            findings_lines.append(
                f"  - [SYSTEMIC PROCESS GAP — no correcting journal entry required] "
                f"{sf['category']}: {sf['description']} (${sf['amount']:,.2f})"
            )
        findings_text = "\n".join(findings_lines) if findings_lines else "  (none)"

        prompt = (
            f"Reconciliation Investigation Report — {state['reconciliation_period']}\n\n"
            f"Discrepancy: ${state['discrepancy_amount']:,.2f} ({state['discrepancy_direction'].replace('_', ' ')})\n"
            f"Net Explained: ${net_explained:,.2f} ({explanation_percentage:.1f}%)\n"
            f"Correcting journal entries required: {len(journal_entries)}\n"
            f"High-priority action items: {len(high_actions)}\n"
            f"Systemic posting failures detected: {len(systemic_failures)}\n\n"
            f"Findings discovered during investigation:\n{findings_text}\n\n"
            "Important context for writing the narrative:\n"
            "1. The Net Explained figure accounts for both same-direction findings AND offsetting "
            "findings (entries valid in one ledger but not the other that partially narrow the gap).\n"
            "2. Restructured payment findings marked 'added/removed to period' are valid transactions "
            "requiring ledger alignment — they are NOT posting errors to be reversed.\n"
            "3. Systemic process failures are absent from BOTH ledgers. They require process "
            "investigation, NOT a correcting journal entry.\n\n"
            "Using ONLY the findings listed above (do not invent any other issues), "
            "write a professional 3-paragraph reconciliation narrative for a finance team.\n"
            "Paragraph 1: state the discrepancy amount, direction, and that "
            f"${net_explained:,.2f} ({explanation_percentage:.1f}%) of it has been explained.\n"
            "Paragraph 2: describe root causes by referencing the actual finding IDs, categories, "
            "and amounts — distinguish between unposted entries (ledger alignment) and "
            "process failures.\n"
            "Paragraph 3: recommend immediate actions — address systemic failures first (process fix, "
            "no journal entry), then process the correcting journal entries for the remaining items."
        )
        response = llm.invoke(prompt)
        return response.content.strip()
    except Exception as exc:
        return (
            f"Reconciliation investigation complete for period {state['reconciliation_period']}. "
            f"Discrepancy of ${state['discrepancy_amount']:,.2f} is {explanation_percentage:.1f}% explained. "
            f"(Narrative generation failed: {exc})"
        )


# ── Node function ─────────────────────────────────────────────────────────────

def summary_node(state: ReconciliationState) -> dict:
    """
    Build the full SummaryOutput from accumulated agent findings.
    Generates narrative via LLM.
    """
    discrepancy_direction = state["discrepancy_direction"]
    discrepancy_amount = state["discrepancy_amount"]
    agent_results: List[AgentResult] = state.get("agent_results", [])

    total_explained = sum(r["explained_amount"] for r in agent_results)
    total_opposite = sum(r["opposite_amount"] for r in agent_results)
    net_explained = total_explained - total_opposite
    explanation_percentage = (
        (net_explained / discrepancy_amount * 100) if discrepancy_amount > 0 else 100.0
    )

    journal_entries: List[CorrectingJournalEntry] = []
    action_items: List[ActionItem] = []
    systemic_failures_output: List[SystemicPostingFailure] = []

    # ── Restructured findings ─────────────────────────────────────────────────
    for f in state.get("restructured_findings", []):
        impact = calculate_finding_impact(f, "restructured")
        if impact["is_systemic_failure"]:
            systemic_failures_output.append(SystemicPostingFailure(
                reference_id=f["restructure_id"],
                reference_type="RESTRUCTURE",
                category="Restructured Payments",
                amount=impact["amount"],
                description=f"Restructure {f['restructure_id']} missing in both AR and GL for {f['loan_id']}",
            ))
            action_items.append(ActionItem(
                priority="HIGH",
                category="Restructured Payments",
                description=f"Systemic failure: restructure {f['restructure_id']} absent from both ledgers",
                amount=impact["amount"],
            ))
        else:
            journal_entries.extend(_journal_for_restructured(f))
            is_opposite = impact.get("direction") != discrepancy_direction
            action_items.append(ActionItem(
                priority=_action_priority(impact["amount"], is_opposite, False),
                category="Restructured Payments",
                description=f"Restructure {f['restructure_id']} ({f['finding_type']}) for {f['loan_id']}",
                amount=impact["amount"],
            ))

    # ── Delinquency findings ──────────────────────────────────────────────────
    for f in state.get("delinquency_findings", []):
        impact = calculate_finding_impact(f, "delinquency")
        if impact["is_systemic_failure"]:
            systemic_failures_output.append(SystemicPostingFailure(
                reference_id=f["fee_id"],
                reference_type="FEE",
                category="Delinquency Fees",
                amount=impact["amount"],
                description=f"Fee {f['fee_id']} missing in both AR and GL for {f['loan_id']}",
            ))
            action_items.append(ActionItem(
                priority="HIGH",
                category="Delinquency Fees",
                description=f"Systemic failure: fee {f['fee_id']} absent from both ledgers",
                amount=impact["amount"],
            ))
        else:
            journal_entries.extend(_journal_for_delinquency(f))
            is_opposite = impact.get("direction") != discrepancy_direction
            action_items.append(ActionItem(
                priority=_action_priority(impact["amount"], is_opposite, False),
                category="Delinquency Fees",
                description=f"Fee {f['fee_id']} ({f['fee_type']}) for {f['loan_id']}",
                amount=impact["amount"],
            ))

    # ── Refund findings ───────────────────────────────────────────────────────
    for f in state.get("refund_findings", []):
        impact = calculate_finding_impact(f, "refund")
        if impact["is_systemic_failure"]:
            systemic_failures_output.append(SystemicPostingFailure(
                reference_id=f["refund_id"],
                reference_type="REFUND",
                category="Refunds",
                amount=impact["amount"],
                description=f"Refund {f['refund_id']} missing in both AR and GL for {f['loan_id']}",
            ))
            action_items.append(ActionItem(
                priority="HIGH",
                category="Refunds",
                description=f"Systemic failure: refund {f['refund_id']} absent from both ledgers",
                amount=impact["amount"],
            ))
        else:
            journal_entries.extend(_journal_for_refund(f))
            is_opposite = impact.get("direction") != discrepancy_direction
            action_items.append(ActionItem(
                priority=_action_priority(impact["amount"], is_opposite, False),
                category="Refunds",
                description=f"Refund {f['refund_id']} ({f['refund_reason']}) for {f['loan_id']}",
                amount=impact["amount"],
            ))

    # ── Charge-off findings ───────────────────────────────────────────────────
    for f in state.get("chargeoff_findings", []):
        impact = calculate_finding_impact(f, "chargeoff")
        if impact["is_systemic_failure"]:
            systemic_failures_output.append(SystemicPostingFailure(
                reference_id=f["charge_off_id"],
                reference_type="CHARGE_OFF",
                category="Charge-offs",
                amount=impact["amount"],
                description=f"Charge-off {f['charge_off_id']} missing in both AR and GL for {f['loan_id']}",
            ))
            action_items.append(ActionItem(
                priority="HIGH",
                category="Charge-offs",
                description=f"Systemic failure: charge-off {f['charge_off_id']} absent from both ledgers",
                amount=impact["amount"],
            ))
        else:
            journal_entries.extend(_journal_for_chargeoff(f))
            is_opposite = impact.get("direction") != discrepancy_direction
            action_items.append(ActionItem(
                priority=_action_priority(impact["amount"], is_opposite, False),
                category="Charge-offs",
                description=f"Charge-off {f['charge_off_id']} for {f['loan_id']} (${f['charge_off_amount']:,.2f})",
                amount=impact["amount"],
            ))

    # Sort action items: HIGH first, then by amount descending
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    action_items.sort(key=lambda a: (priority_order[a["priority"]], -a["amount"]))

    narrative = _generate_narrative(
        state,
        net_explained,
        explanation_percentage,
        journal_entries,
        action_items,
        systemic_failures_output,
    )

    summary = SummaryOutput(
        total_explained_amount=net_explained,
        explanation_percentage=explanation_percentage,
        correcting_journal_entries=journal_entries,
        action_items=action_items,
        systemic_posting_failures=systemic_failures_output,
        narrative=narrative,
    )

    return {"summary": summary, "explanation_percentage": explanation_percentage}
