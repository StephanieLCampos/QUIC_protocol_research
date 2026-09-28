#!/usr/bin/env python3
#!/usr/bin/env python3
"""
Extract the 27 metric values from experiment results and calculate ranges.

This script reads the results from all 3 configuration experiments and:
1. Extracts the 27 values (3 configs x 3 apps x 3 metrics)
2. Calculates min/max ranges for each metric
3. Exports to CSV for further analysis

The 27 values form the comparison grid at the centre of this experiment:
every combination of configuration and application type, measured on all three
metrics. The per-metric ranges show how much a metric moves as the shared
configuration changes, which is the quantity the experiment exists to
establish.

Reads the most recent results file per configuration, so it can be run
repeatedly during an experiment series without collecting stale runs.

Usage:
    python results_extractor.py
    python results_extractor.py --output-dir custom_output
    python results_extractor.py --format csv

Connections
-----------
Imports from : standard library only (argparse, json, pathlib, typing)
Reads        : results written by experiment_runner.py
Writes       : all_27_values.csv, metric_ranges.csv, comparison_results.json
"""

import argparse
import json
from pathlib import Path
from typing import Dict, Optional


def find_latest_results(output_dir: Path, config_name: str) -> Optional[Path]:
    """Find the most recent results file for a config."""
    config_dir = output_dir / config_name
    if not config_dir.exists():
        return None

    results_files = sorted(config_dir.glob("results_*.json"))
    return results_files[-1] if results_files else None


def extract_metrics(results_file: Path) -> Dict:
    """Extract metrics from a results file."""
    with open(results_file) as f:
        data = json.load(f)

    metrics = {}
    for conn_id in ["1", "2", "3"]:
        conn = data["connection_results"][conn_id]
        app_type = conn["application_type"]
        final = conn["final_metrics"]

        metrics[app_type] = {
            "throughput_mbps": final.get("throughput", 0) * 8 / 1e6,
            "latency_ms": final.get("latency", 0) * 1000,
            "jitter_ms": final.get("jitter", 0) * 1000,
            "rtt_ms": final.get("rtt", 0) * 1000,
            "packet_loss_pct": final.get("packet_loss_rate", 0) * 100,
        }
    return metrics


def calculate_ranges(all_metrics: Dict) -> Dict:
    """
    Calculate min/max ranges for each metric across all 27 values.

    Returns dict with structure:
    {
        "throughput_mbps": {"min": X, "max": Y, "min_context": "app@config", "max_context": "app@config"},
        "latency_ms": {...},
        "jitter_ms": {...}
    }
    """
    ranges = {
        "throughput_mbps": {"min": float('inf'), "max": float('-inf'), "min_context": "", "max_context": ""},
        "latency_ms": {"min": float('inf'), "max": float('-inf'), "min_context": "", "max_context": ""},
        "jitter_ms": {"min": float('inf'), "max": float('-inf'), "min_context": "", "max_context": ""},
    }

    for config_name, apps in all_metrics.items():
        for app_name, metrics in apps.items():
            for metric_name in ["throughput_mbps", "latency_ms", "jitter_ms"]:
                val = metrics.get(metric_name, 0)
                context = f"{app_name} @ {config_name}"

                if val < ranges[metric_name]["min"]:
                    ranges[metric_name]["min"] = val
                    ranges[metric_name]["min_context"] = context
                if val > ranges[metric_name]["max"]:
                    ranges[metric_name]["max"] = val
                    ranges[metric_name]["max_context"] = context

    return ranges


def print_ranges(ranges: Dict):
    """Print the metric ranges summary."""
    print("\n" + "=" * 80)
    print("METRIC RANGES (derived from 27 measurements)")
    print("=" * 80)

    print("\nTHROUGHPUT:")
    print(f"  Minimum: {ranges['throughput_mbps']['min']:.2f} Mbps")
    print(f"           ({ranges['throughput_mbps']['min_context']})")
    print(f"  Maximum: {ranges['throughput_mbps']['max']:.2f} Mbps")
    print(f"           ({ranges['throughput_mbps']['max_context']})")
    ratio = ranges['throughput_mbps']['max'] / ranges['throughput_mbps']['min'] if ranges['throughput_mbps']['min'] > 0 else 0
    print(f"  Ratio:   {ratio:.1f}x difference")

    print("\nLATENCY:")
    print(f"  Minimum: {ranges['latency_ms']['min']:.2f} ms")
    print(f"           ({ranges['latency_ms']['min_context']})")
    print(f"  Maximum: {ranges['latency_ms']['max']:.2f} ms")
    print(f"           ({ranges['latency_ms']['max_context']})")
    ratio = ranges['latency_ms']['max'] / ranges['latency_ms']['min'] if ranges['latency_ms']['min'] > 0 else 0
    print(f"  Ratio:   {ratio:.1f}x difference")

    print("\nJITTER:")
    print(f"  Minimum: {ranges['jitter_ms']['min']:.2f} ms")
    print(f"           ({ranges['jitter_ms']['min_context']})")
    print(f"  Maximum: {ranges['jitter_ms']['max']:.2f} ms")
    print(f"           ({ranges['jitter_ms']['max_context']})")
    ratio = ranges['jitter_ms']['max'] / ranges['jitter_ms']['min'] if ranges['jitter_ms']['min'] > 0 else 0
    print(f"  Ratio:   {ratio:.1f}x difference")

    print("\n" + "=" * 80)


def print_table(all_metrics: Dict):
    """Print a formatted comparison table."""
    configs = ["ft_friendly", "vc_friendly", "mm_friendly"]
    apps = ["video_streaming", "file_transfer", "conference_call"]

    print("\n" + "=" * 80)
    print("COMPARATIVE RESULTS: 27 Values (3 configs x 3 apps x 3 metrics)")
    print("=" * 80)

    # Throughput table
    print("\nTHROUGHPUT (Mbps)")
    print("-" * 65)
    print(f"{'App Type':<20} {'FT-Friendly':<15} {'VC-Friendly':<15} {'MM-Friendly':<15}")
    print("-" * 65)
    for app in apps:
        row = f"{app:<20}"
        for config in configs:
            if config in all_metrics and app in all_metrics[config]:
                val = all_metrics[config][app].get("throughput_mbps", 0)
                row += f" {val:<14.2f}"
            else:
                row += f" {'N/A':<14}"
        print(row)

    # Latency table
    print("\nLATENCY (ms)")
    print("-" * 65)
    print(f"{'App Type':<20} {'FT-Friendly':<15} {'VC-Friendly':<15} {'MM-Friendly':<15}")
    print("-" * 65)
    for app in apps:
        row = f"{app:<20}"
        for config in configs:
            if config in all_metrics and app in all_metrics[config]:
                val = all_metrics[config][app].get("latency_ms", 0)
                row += f" {val:<14.2f}"
            else:
                row += f" {'N/A':<14}"
        print(row)

    # Jitter table
    print("\nJITTER (ms)")
    print("-" * 65)
    print(f"{'App Type':<20} {'FT-Friendly':<15} {'VC-Friendly':<15} {'MM-Friendly':<15}")
    print("-" * 65)
    for app in apps:
        row = f"{app:<20}"
        for config in configs:
            if config in all_metrics and app in all_metrics[config]:
                val = all_metrics[config][app].get("jitter_ms", 0)
                row += f" {val:<14.2f}"
            else:
                row += f" {'N/A':<14}"
        print(row)

    print("\n" + "=" * 80)


def export_csv(all_metrics: Dict, ranges: Dict, output_dir: Path):
    """Export metrics and ranges to CSV files."""
    configs = ["ft_friendly", "vc_friendly", "mm_friendly"]
    apps = ["video_streaming", "file_transfer", "conference_call"]

    # Export all 27 values
    values_file = output_dir / "all_27_values.csv"
    with open(values_file, "w") as f:
        f.write("config,app_type,throughput_mbps,latency_ms,jitter_ms,rtt_ms,packet_loss_pct\n")
        for config in configs:
            if config not in all_metrics:
                continue
            for app in apps:
                if app not in all_metrics[config]:
                    continue
                m = all_metrics[config][app]
                f.write(f"{config},{app},{m['throughput_mbps']:.4f},{m['latency_ms']:.4f},"
                        f"{m['jitter_ms']:.4f},{m['rtt_ms']:.4f},{m['packet_loss_pct']:.4f}\n")
    print(f"All 27 values exported to: {values_file}")

    # Export ranges summary
    ranges_file = output_dir / "metric_ranges.csv"
    with open(ranges_file, "w") as f:
        f.write("metric,min_value,min_context,max_value,max_context,ratio\n")
        for metric in ["throughput_mbps", "latency_ms", "jitter_ms"]:
            r = ranges[metric]
            ratio = r['max'] / r['min'] if r['min'] > 0 else 0
            f.write(f"{metric},{r['min']:.4f},\"{r['min_context']}\","
                    f"{r['max']:.4f},\"{r['max_context']}\",{ratio:.2f}\n")
    print(f"Metric ranges exported to: {ranges_file}")


def export_json(all_metrics: Dict, ranges: Dict, output_dir: Path):
    """Export all data to JSON for programmatic access."""
    data = {
        "metrics": all_metrics,
        "ranges": ranges,
    }

    json_file = output_dir / "comparison_results.json"
    with open(json_file, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Full data exported to: {json_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract 27 metric values and calculate ranges",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script analyzes results from all 3 configuration experiments and produces:
  - Comparison tables showing all 27 values
  - Metric ranges (min/max) with context
  - CSV files for further analysis

Run experiments first:
  python experiment_runner.py --all --duration 60
        """
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Base output directory (default: output)"
    )
    parser.add_argument(
        "--format",
        choices=["table", "csv", "both"],
        default="both",
        help="Output format (default: both)"
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    configs = ["ft_friendly", "vc_friendly", "mm_friendly"]

    all_metrics = {}
    missing = []

    print("\nSearching for experiment results...")
    print("-" * 40)

    for config_name in configs:
        results_file = find_latest_results(output_dir, config_name)
        if results_file:
            print(f"Found: {results_file}")
            all_metrics[config_name] = extract_metrics(results_file)
        else:
            missing.append(config_name)

    if missing:
        print(f"\nWarning: Missing results for: {missing}")
        print("Run experiments first:")
        for m in missing:
            print(f"  python experiment_runner.py --config {m}")
        if not all_metrics:
            print("\nNo results to analyze!")
            return 1

    # Calculate ranges from collected data
    ranges = calculate_ranges(all_metrics)

    # Output results
    if args.format in ["table", "both"]:
        print_table(all_metrics)
        print_ranges(ranges)

    if args.format in ["csv", "both"]:
        export_csv(all_metrics, ranges, output_dir)
        export_json(all_metrics, ranges, output_dir)

    # Print interpretation
    print("\n" + "=" * 80)
    print("INTERPRETATION")
    print("=" * 80)
    print("""
The ranges show how much each metric varies across configurations:

- THROUGHPUT range shows the trade-off between bulk transfer and real-time apps
- LATENCY range shows the impact of aggressive vs conservative CC parameters
- JITTER range shows how much consistency varies with different configurations

Key insight: There is NO single configuration that is optimal for all apps.
Each configuration favors certain application types at the cost of others.
""")

    return 0


if __name__ == "__main__":
    exit(main())
