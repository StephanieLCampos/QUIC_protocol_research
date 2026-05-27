#!/usr/bin/env python3
"""
Grid Search CLI Entry Point

Find optimal QUIC congestion control parameters for each application type.

Searches only the 6 DYNAMIC parameters. Start-only parameters
(initial_cw, max_ack_delay) are fixed at their default values.

Usage:
    # Run reduced grid search (243 combinations, ~2 hours)
    python main.py run

    # Dry run (show what would be executed)
    python main.py run --dry-run

    # Run for single app type only (81 combinations)
    python main.py run --app-type file_transfer

    # Run full grid search (2,187 combinations, ~18 hours)
    python main.py run --full

    # Analyze results and find optimal configs
    python main.py analyze

    # Show status of current search progress
    python main.py status
"""

import argparse
import sys
from pathlib import Path

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent))

from config.parameter_space import ParameterSpace
from runner.executor import GridSearchExecutor
from analysis.results_analyzer import ResultsAnalyzer
from scheduler.resumable_scheduler import ResumableScheduler


def cmd_run(args):
    """Run the grid search."""
    # Show parameter space summary
    print("\nParameter Space Configuration:")
    summary = ParameterSpace.get_summary(reduced=not args.full)
    print(f"  Search mode: {summary['mode'].upper()}")
    print(f"  Parameters being searched: {', '.join(summary['searched_parameters'])}")

    if 'fixed_dynamic_parameters' in summary:
        print(f"  Fixed dynamic parameters: {summary['fixed_dynamic_parameters']}")

    print(f"  Fixed start-only parameters: {summary['fixed_start_only_parameters']}")
    print(f"  Combinations per app: {summary['combinations_per_app']}")
    print(f"  Total combinations: {summary['total_combinations']}")

    # Calculate time estimate based on parallelism
    num_workers = 1 if args.no_parallel else args.workers
    if args.app_type:
        total_combos = summary['combinations_per_app']
    else:
        total_combos = summary['total_combinations']

    estimated_minutes = (total_combos / num_workers) * (args.duration + 5) / 60
    print(f"  Parallel workers: {num_workers}")
    print(f"  Estimated time: ~{estimated_minutes:.0f} minutes ({estimated_minutes/60:.1f} hours)")
    print()

    if args.app_type:
        print(f"  Filtering to app type: {args.app_type}")
        print()

    # Create executor
    executor = GridSearchExecutor(
        output_dir=args.output_dir,
        duration=args.duration,
        reduced_search=not args.full,
        num_workers=args.workers,
    )

    # Run
    result = executor.execute(
        dry_run=args.dry_run,
        app_type=args.app_type,
        parallel=not args.no_parallel,
    )

    return 0 if result.get("status") in ("complete", "dry_run") else 1


def cmd_analyze(args):
    """Analyze results and find optimal configurations."""
    analyzer = ResultsAnalyzer(measurements_dir=args.measurements_dir)
    count = analyzer.load_results()

    if count == 0:
        print("\nNo results found. Run the grid search first:")
        print("  python main.py run")
        return 1

    # Print summary
    analyzer.print_summary()

    # Print statistics if requested
    if args.stats:
        analyzer.print_statistics()

    # Export results
    analyzer.export_optimal_configs(output_path=args.output)
    analyzer.export_optimal_configs_json(
        output_path=args.output.replace(".csv", ".json")
    )

    if args.export_all:
        analyzer.export_all_results(
            output_path=str(Path(args.output).parent / "all_results.csv")
        )

    return 0


def cmd_status(args):
    """Show current search progress."""
    scheduler = ResumableScheduler(output_dir=args.measurements_dir)

    print("\nGrid Search Status")
    print("=" * 50)

    # Show reduced search progress
    progress = scheduler.get_progress(reduced=True)
    print(f"\nReduced Search (4 parameters, 243 combinations):")
    print(f"  Completed: {progress['completed']}/{progress['total']}")
    print(f"  Pending:   {progress['pending']}")
    print(f"  Progress:  {progress['percent_complete']:.1f}%")

    # Show full search progress
    progress = scheduler.get_progress(reduced=False)
    print(f"\nFull Search (6 parameters, 2187 combinations):")
    print(f"  Completed: {progress['completed']}/{progress['total']}")
    print(f"  Pending:   {progress['pending']}")
    print(f"  Progress:  {progress['percent_complete']:.1f}%")

    # Show breakdown by app type
    print("\nBy Application Type:")
    for app_type in ParameterSpace.APPLICATION_TYPES:
        pending = scheduler.get_pending_combinations(reduced=True, app_type=app_type)
        completed = 81 - len(pending)  # 81 combinations per app in reduced mode
        print(f"  {app_type}: {completed}/81 ({completed/81*100:.0f}%)")

    print()
    return 0


def cmd_clear(args):
    """Clear all results (with confirmation)."""
    scheduler = ResumableScheduler(output_dir=args.measurements_dir)
    progress = scheduler.get_progress(reduced=True)

    if progress['completed'] == 0:
        print("No results to clear.")
        return 0

    print(f"\nThis will delete {progress['completed']} result files.")

    if not args.yes:
        response = input("Are you sure? (y/N): ")
        if response.lower() != 'y':
            print("Cancelled.")
            return 0

    scheduler.clear_results()
    print("Results cleared.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="QUIC Parameter Grid Search - Find optimal configurations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py run                   # Run reduced grid search
  python main.py run --dry-run         # Preview without running
  python main.py run --app-type file_transfer  # Single app type
  python main.py run --full            # Run full search (slow!)
  python main.py analyze               # Find optimal parameters
  python main.py status                # Check progress
        """
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Run command
    run_parser = subparsers.add_parser(
        "run",
        help="Run grid search"
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be executed without running"
    )
    run_parser.add_argument(
        "--full",
        action="store_true",
        help="Run full grid search with all 6 parameters (WARNING: ~18 hours!)"
    )
    run_parser.add_argument(
        "--app-type",
        choices=["file_transfer", "video_streaming", "conference_call"],
        help="Only run for specific app type"
    )
    run_parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Duration per simulation in seconds (default: 30)"
    )
    run_parser.add_argument(
        "--output-dir",
        default="output/measurements",
        help="Output directory for results (default: output/measurements)"
    )
    run_parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)"
    )
    run_parser.add_argument(
        "--no-parallel",
        action="store_true",
        help="Run sequentially instead of in parallel"
    )
    run_parser.set_defaults(func=cmd_run)

    # Analyze command
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze results and find optimal configurations"
    )
    analyze_parser.add_argument(
        "--measurements-dir",
        default="output/measurements",
        help="Directory containing measurement CSVs (default: output/measurements)"
    )
    analyze_parser.add_argument(
        "--output",
        default="output/analysis/optimal_configs.csv",
        help="Output file for optimal configs (default: output/analysis/optimal_configs.csv)"
    )
    analyze_parser.add_argument(
        "--stats",
        action="store_true",
        help="Show detailed statistics"
    )
    analyze_parser.add_argument(
        "--export-all",
        action="store_true",
        help="Export all results to a single CSV"
    )
    analyze_parser.set_defaults(func=cmd_analyze)

    # Status command
    status_parser = subparsers.add_parser(
        "status",
        help="Show current search progress"
    )
    status_parser.add_argument(
        "--measurements-dir",
        default="output/measurements",
        help="Directory containing measurement CSVs"
    )
    status_parser.set_defaults(func=cmd_status)

    # Clear command
    clear_parser = subparsers.add_parser(
        "clear",
        help="Clear all results"
    )
    clear_parser.add_argument(
        "--measurements-dir",
        default="output/measurements",
        help="Directory containing measurement CSVs"
    )
    clear_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation"
    )
    clear_parser.set_defaults(func=cmd_clear)

    # Parse args
    args = parser.parse_args()

    if hasattr(args, "func"):
        return args.func(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
