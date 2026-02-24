# Reconciliation Exception Investigation Agent

## Project Overview
BNPL (Buy Now Pay Later) reconciliation system that investigates discrepancies between AR Subledger and GL Control Account using a LangGraph multi-agent workflow. Educational project focused on learning Send API parallelism, supervisor routing, and state accumulation patterns.

## Reference Architecture
Read docs/architecture.md before implementing any new feature or modifying existing nodes. It contains the database schema, state schema, agent tool definitions, impact calculation logic, graph construction details, seed data scenarios, and report spec.

## Architecture Invariants (non-negotiable)
- Agents are deterministic nodes — they call SQL tool functions directly, run build_agent_result, and return. NO LLM calls in agents, NO ReAct loops.
- Supervisor aggregates and routes — it does NOT investigate. It sums explained_amounts from AgentResult, computes explanation_percentage, and decides: summary, re-delegate, or force summary.
- Send API for parallel fan-out — supervisor returns Send objects to 4 agent nodes. Agents write to isolated state keys via reducer annotations.
- Reducer annotations (Annotated[List[...], operator.add]) are REQUIRED on: agent_results, restructured_findings, delinquency_findings, refund_findings, chargeoff_findings. Without these, Send API overwrites instead of accumulates.
- Exception tables are source of truth — tools originate from exception tables and cross-reference AR/GL. There are no orphan ledger entries without corresponding exception records.
- Deduplication via previously_found_ids — agents receive IDs of already-discovered records and skip them on re-delegation iterations.
- Impact calculation lives inside each agent — agents compute their own explained_amount before returning AgentResult to supervisor.
- Both-missing findings (missing_in_ar AND missing_in_gl) are systemic failures — they do NOT contribute to explained_amount.

## Coding Conventions
- Python 3.11+
- Type hints everywhere — use TypedDict for all structured data, not dataclass
- Imports: group stdlib, third-party, local with blank lines between
- All SQL queries use parameterized queries, never f-strings
- File organization follows src/ structure defined in docs/architecture.md
- Keep agent modules self-contained — each agent file contains its tool functions, build_agent_result call, and the node function

## Testing Requirements
- Test impact calculation logic for all 4 categories × both directions
- Test supervisor routing: ≥90% → summary, <90% + iterations<3 → re-delegate, iterations≥3 → force summary
- Test deduplication: agent receiving previously_found_ids should not return those records
- Test both-missing exclusion from explained_amount
- Test seed data produces expected discrepancy amounts
- Report formatting does NOT need tests

## Common Pitfalls
- Forgetting reducer annotations on list fields — Send API will silently overwrite
- Adding LLM calls inside agent nodes — agents are pure Python, only supervisor and summary use LLM
- Using the wrong reference_type filter in SQL queries — always filter by reference_type alongside reference_id
- Double-counting findings across iterations — deduplication handles this, don't add manual clearing
- Putting impact calculation in summary node — it belongs in the agents



## LLM Configuration
- All LLM calls use Gemma 3 27B (free tier) 
- Two LLM call points only: supervisor (routing reasoning) and summary node (narrative generation)
- API key stored in .env as GEMINI_API_KEY, loaded via python-dotenv
- Never hardcode API keys or model strings — use config.py to centralize

## Repository & Security
- Project must be deployable via GitHub
- Include README.md with: project description, setup instructions, .env configuration, how to run, architecture overview pointing to docs/architecture.md
- .gitignore must exclude: .env, __pycache__/, output/*.pdf, .mypy_cache/, *.pyc, node_modules/ + other documents you consider relevant to hide.
- .env.example file with placeholder values so contributors know what's needed
- Never commit API keys, database credentials, or output files
- requirements.txt with all dependencies pinned

## Development Process
- Follow an iterative build-then-review cycle:
  1. Implement a module or feature
  2. Critically review the code written — check for: architectural violations (see Invariants above), type mismatches, missing reducer annotations, incorrect SQL filters, LLM calls where they shouldn't be
  3. Fix issues found in review before moving to next module
- Build order: database/schema → database/seed → state schema → agent tools → agent nodes → supervisor → summary → report → graph wiring → tests
- Do not skip the review step — catching errors early prevents cascading bugs in the graph

- This cycle should be iterated over three times to ensure good code quality, functionality and security in the app. 