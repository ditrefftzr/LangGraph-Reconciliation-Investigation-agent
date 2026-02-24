"""
Reconciliation Exception Investigation Agent — CLI entrypoint.

Usage:
    python main.py --period 2024-01-01
    python main.py --period 2024-01-01 --threshold 1.00
    python main.py --seed                     # seed database then run Jan 2024
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BNPL Reconciliation Exception Investigation Agent"
    )
    parser.add_argument(
        "--period",
        type=str,
        default=None,
        help="Reconciliation period as YYYY-MM-DD (first of month, e.g. 2024-01-01)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.01,
        help="Materiality threshold in currency units (default: 0.01)",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Seed the database with demo data before running",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Seed database if requested
    if args.seed:
        from src.database.seed import seed_database
        seed_database()

    # Resolve period
    if args.period:
        try:
            period = datetime.strptime(args.period, "%Y-%m-%d").date()
        except ValueError:
            print(f"Error: --period must be in YYYY-MM-DD format, got '{args.period}'")
            sys.exit(1)
    else:
        # Default to first day of current month
        today = date.today()
        period = date(today.year, today.month, 1)
        print(f"No --period provided. Using current month: {period}")

    # Ensure database is initialised
    from src.database.connection import initialize_database
    initialize_database()

    # Build initial state
    initial_state = {
        "reconciliation_period": period,
        "materiality_threshold": args.threshold,
        "ar_total": 0.0,
        "gl_total": 0.0,
        "discrepancy_amount": 0.0,
        "discrepancy_direction": "MATCH",
        "iteration_count": 0,
        "explanation_percentage": 0.0,
        "agent_results": [],
        "restructured_findings": [],
        "delinquency_findings": [],
        "refund_findings": [],
        "chargeoff_findings": [],
        "summary": None,
        "report_path": None,
    }

    print(f"\nStarting reconciliation investigation for period: {period}")
    print(f"Materiality threshold: ${args.threshold:,.2f}\n")

    from src.graph.graph import reconciliation_graph

    final_state = reconciliation_graph.invoke(initial_state)

    # Print summary to console
    summary = final_state.get("summary")
    if summary:
        print("\n" + "=" * 60)
        print("RECONCILIATION INVESTIGATION COMPLETE")
        print("=" * 60)
        print(f"Period:              {period}")
        print(f"Discrepancy:         ${final_state['discrepancy_amount']:,.2f} ({final_state['discrepancy_direction']})")
        print(f"Total Explained:     ${summary['total_explained_amount']:,.2f}")
        print(f"Explanation %:       {summary['explanation_percentage']:.1f}%")
        print(f"Journal Entries:     {len(summary['correcting_journal_entries'])}")
        print(f"Action Items:        {len(summary['action_items'])}")
        print(f"Systemic Failures:   {len(summary['systemic_posting_failures'])}")
        if final_state.get("report_path"):
            print(f"Report saved to:     {final_state['report_path']}")
        print("=" * 60)
    else:
        print("Investigation complete. No summary generated (discrepancy within threshold).")


if __name__ == "__main__":
    main()
