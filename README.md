# BNPL Reconciliation Exception Investigation Agent

A LangGraph multi-agent workflow that investigates discrepancies between the AR Subledger and the GL Control Account in a Buy Now Pay Later (BNPL) portfolio. Built as an educational project to demonstrate Send API parallelism, supervisor routing, and state accumulation patterns.

## Architecture Overview

See [`docs/architecture.md`](docs/architecture.md) for the full spec: database schema, state schema, agent tool definitions, impact calculation logic, graph construction details, seed data scenarios, and report spec.

### Graph Flow

```
START → fetch_data → calculate_difference → supervisor
                                                ↓ (Send x4, parallel fan-out)
                            restructured_agent  delinquency_agent
                            refunds_agent       chargeoffs_agent
                                                ↓ (all route back)
                                            supervisor
                                                ↓ (≥90% explained or max iters)
                                            summary → report → END
```

### Agent Categories

| Agent | Exception Table | What it looks for |
|---|---|---|
| Restructured | `restructured_payments` | Installments removed from or added to the period |
| Delinquency | `delinquency_fees` | Late/penalty fees missing in AR or GL |
| Refunds | `refunds` | Refund credits not reflected in AR or GL |
| Charge-offs | `charge_offs` | Write-offs not cleared in AR or not posted to GL |

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd reconciliation-agent
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 3. Run

Seed the database with demo data and investigate January 2024:

```bash
python main.py --seed --period 2024-01-01
```

Run without seeding (if you have your own data):

```bash
python main.py --period 2024-01-01
```

Override the materiality threshold (default 0.01):

```bash
python main.py --period 2024-01-01 --threshold 5.00
```

The PDF report is saved to `output/reconciliation_YYYY-MM_<timestamp>.pdf`.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Gemini API key for Gemma 3 27B (free tier). Get one at [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| `DB_PATH` | No | Override SQLite database path (default: `./reconciliation.db`) |

## Running Tests

```bash
pytest tests/ -v
```

## Project Structure

```
reconciliation-agent/
├── main.py                  # CLI entrypoint
├── config.py                # Centralised config (model IDs, paths)
├── requirements.txt
├── .env.example
├── docs/
│   └── architecture.md      # Full technical spec
├── src/
│   ├── graph/
│   │   ├── state.py         # LangGraph state schema with reducer annotations
│   │   └── graph.py         # Graph wiring
│   ├── nodes/
│   │   ├── fetch_data.py    # Queries AR and GL totals
│   │   ├── calculate_difference.py
│   │   ├── supervisor.py    # Aggregation + routing (LLM for reasoning only)
│   │   ├── summary.py       # Journal entries, action items, LLM narrative
│   │   ├── report.py        # PDF generation (reportlab)
│   │   └── agents/
│   │       ├── restructured.py
│   │       ├── delinquency.py
│   │       ├── refunds.py
│   │       └── chargeoffs.py
│   ├── utils/
│   │   └── impact.py        # calculate_finding_impact + build_agent_result
│   └── database/
│       ├── schema.sql
│       ├── connection.py
│       └── seed.py
└── tests/
```
