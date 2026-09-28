#!/usr/bin/env python3
#!/usr/bin/env python3
"""
Command-line entry point for the QUIC Multi-Stream Research Project (Generation 1).

Single front end for the whole Generation 1 workflow: running the parameter
sweep, inspecting its progress, and analysing the results it produced.

Commands
--------
    run       execute the grid search, resuming automatically from any
              previously completed combinations (--dry-run to preview)
    status    report sweep progress and the parameter space being searched
    analyze   print the optimal parameter set per application type
    report    render a full text report (--app-type for a single deep dive,
              -o to write it to a file)
    clear     delete all result CSVs for a fresh start (-f to skip the prompt)

Typical sequence:

    uv run main.py run          # hours; safe to interrupt and re-run
    uv run main.py status       # how far along
    uv run main.py report -o output/summary_report.txt

Note that the report is not produced automatically when the sweep finishes; it
must be generated explicitly with the `report` command after `run` completes.

Each command handler returns a process exit code, which `main()` passes to
sys.exit: 0 on success, 1 where results were required but not yet present.

Connections:
    Imports from: config.settings, grid_search (GridSearchExecutor,
                  ParameterSpace, ResumableScheduler), results (ResultsAnalyzer,
                  ReportGenerator)
    Imported by:  nothing; this is the top-level executable for this project
"""

import argparse
import asyncio
import sys
from pathlib import Path

from config.settings import DEFAULT_SETTINGS
from grid_search import GridSearchExecutor, ParameterSpace
from results import ResultsAnalyzer, ReportGenerator


def cmd_run(args):
    """
    Execute the parameter sweep, resuming from any prior progress.

    Resumption is automatic and requires no flag: the executor's scheduler
    treats existing result files as completed work, so re-invoking this command
    after an interruption continues rather than restarting.
    """
    print("QUIC Multi-Stream Research Project")
    print("=" * 40)

    executor = GridSearchExecutor(
        settings=DEFAULT_SETTINGS,
        output_dir=args.output_dir,
    )

    result = asyncio.run(executor.execute(dry_run=args.dry_run))

    if result["status"] == "complete":
        print("\nGrid search completed successfully!")
        if not args.dry_run:
            print(f"Results saved to: {args.output_dir}")
    elif result["status"] == "partial":
        print(f"\nPartial completion: {result['completed']}/{result['total']}")
        print(f"Failures: {result['failures']}")
    elif result["status"] == "dry_run":
        print(f"\nDry run complete. {result['pending']} simulations would run.")

    return 0


def cmd_status(args):
    """Show current status."""
    from grid_search import ResumableScheduler

    scheduler = ResumableScheduler(args.output_dir)
    completed, total = scheduler.get_progress()

    print("QUIC Grid Search Status")
    print("=" * 40)
    print(f"Progress: {scheduler.get_progress_string()}")
    print()

    if scheduler.is_all_complete():
        print("All simulations complete!")
    else:
        pending = scheduler.get_pending_combinations()
        print(f"Next pending: {pending[0] if pending else 'None'}")

    print()
    print("Parameter Space:")
    summary = ParameterSpace.get_summary()
    print(f"  Application types: {', '.join(summary['application_types'])}")
    print(f"  Initial CW values: {summary['initial_cw_values']}")
    print(f"  Max ACK Delay values: {summary['max_ack_delay_values']}")
    print(f"  Loss Factor values: {summary['loss_factor_values']}")
    print(f"  Total combinations: {summary['total_combinations']}")

    return 0


def cmd_analyze(args):
    """Analyze results."""
    analyzer = ResultsAnalyzer(args.output_dir)

    try:
        analyzer.load_data()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Run the grid search first to generate results.")
        return 1

    print("QUIC Grid Search Analysis")
    print("=" * 40)
    print(f"Total records: {len(analyzer.data)}")
    print()

    # Find optimal parameters for each app type
    print("Optimal Parameters by Application Type:")
    print("-" * 40)

    optimal = analyzer.find_all_optimal_parameters()

    for app_type, params in optimal.items():
        print(f"\n{app_type}:")
        print(f"  Target: {params.primary_metric} "
              f"({'min' if params.primary_metric in ['rtt', 'jitter'] else 'max'})")
        print(f"  Best {params.primary_metric}: {params.primary_metric_value:.4f}")
        print(f"  Configuration:")
        print(f"    - Initial CW: {params.initial_cw} bytes")
        print(f"    - Max ACK Delay: {params.max_ack_delay * 1000:.1f} ms")
        print(f"    - Loss Factor: {params.loss_factor}")

    return 0


def cmd_report(args):
    """Generate research report."""
    analyzer = ResultsAnalyzer(args.output_dir)
    generator = ReportGenerator(analyzer)

    try:
        if args.app_type:
            report = generator.generate_detailed_report(
                args.app_type,
                output_path=args.output_file,
            )
        else:
            report = generator.generate_summary_report(
                output_path=args.output_file,
            )

        if args.output_file:
            print(f"Report saved to: {args.output_file}")
        else:
            print(report)

    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Run the grid search first to generate results.")
        return 1
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    return 0


def cmd_clear(args):
    """
    Delete every result CSV, resetting the sweep to a fresh start.

    Destructive and not recoverable: because completion is tracked purely by
    the presence of result files, clearing them discards all record of work
    done and the next `run` will repeat the full sweep. Prompts for
    confirmation unless --force is given.
    """
    from grid_search import ResumableScheduler

    if not args.force:
        response = input("This will delete all result files. Continue? [y/N] ")
        if response.lower() != "y":
            print("Aborted.")
            return 0

    scheduler = ResumableScheduler(args.output_dir)
    scheduler.clear_results()
    print("All results cleared.")

    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="QUIC Multi-Stream Research Project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--output-dir",
        default="output/measurements",
        help="Directory for result files (default: output/measurements)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run the grid search")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be executed without running",
    )
    run_parser.set_defaults(func=cmd_run)

    # Status command
    status_parser = subparsers.add_parser("status", help="Show current status")
    status_parser.set_defaults(func=cmd_status)

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze results")
    analyze_parser.set_defaults(func=cmd_analyze)

    # Report command
    report_parser = subparsers.add_parser("report", help="Generate report")
    report_parser.add_argument(
        "--app-type",
        choices=["video_streaming", "file_transfer", "conference_call"],
        help="Generate detailed report for specific app type",
    )
    report_parser.add_argument(
        "-o", "--output-file",
        help="Save report to file",
    )
    report_parser.set_defaults(func=cmd_report)

    # Clear command
    clear_parser = subparsers.add_parser("clear", help="Clear all results")
    clear_parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Skip confirmation prompt",
    )
    clear_parser.set_defaults(func=cmd_clear)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
