"""
Analyze grid search results to find optimal parameters.

Finds the best parameter combinations for each application type
based on their optimization targets:
- File Transfer: Maximize throughput
- Video Streaming: Minimize latency
- Conference Call: Minimize jitter
"""

import csv
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional
import statistics


@dataclass
class MeasurementResult:
    """Single measurement from grid search."""
    app_type: str
    loss_reduction_factor: float
    cubic_c: float
    minimum_window: int
    packet_threshold: int
    time_threshold: float
    cubic_max_idle_time: float
    initial_cw: int
    max_ack_delay: float
    throughput: float
    latency: float
    jitter: float
    rtt: float
    packet_loss_rate: float
    bytes_sent: int = 0


class ResultsAnalyzer:
    """
    Analyzes grid search results to find best parameters per app type.

    Optimization targets:
    - file_transfer: MAXIMIZE throughput
    - video_streaming: MINIMIZE latency
    - conference_call: MINIMIZE jitter
    """

    def __init__(self, measurements_dir: str = "output/measurements"):
        self.measurements_dir = Path(measurements_dir)
        self.results: List[MeasurementResult] = []

    def load_results(self) -> int:
        """
        Load all CSV measurement files.

        Returns:
            Number of results loaded
        """
        self.results = []

        if not self.measurements_dir.exists():
            print(f"Warning: Directory {self.measurements_dir} does not exist")
            return 0

        csv_files = list(self.measurements_dir.glob("*.csv"))

        for csv_file in csv_files:
            # Skip internal files
            if csv_file.name.startswith("_"):
                continue

            try:
                with open(csv_file, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        self.results.append(MeasurementResult(
                            app_type=row["app_type"],
                            loss_reduction_factor=float(row["loss_reduction_factor"]),
                            cubic_c=float(row["cubic_c"]),
                            minimum_window=int(row["minimum_window"]),
                            packet_threshold=int(row["packet_threshold"]),
                            time_threshold=float(row["time_threshold"]),
                            cubic_max_idle_time=float(row["cubic_max_idle_time"]),
                            initial_cw=int(row["initial_cw"]),
                            max_ack_delay=float(row["max_ack_delay"]),
                            throughput=float(row["throughput"]),
                            latency=float(row["latency"]),
                            jitter=float(row["jitter"]),
                            rtt=float(row["rtt"]),
                            packet_loss_rate=float(row["packet_loss_rate"]),
                            bytes_sent=int(row.get("bytes_sent", 0)),
                        ))
            except Exception as e:
                print(f"Warning: Could not load {csv_file}: {e}")

        print(f"Loaded {len(self.results)} measurements from {len(csv_files)} files")
        return len(self.results)

    def get_results_by_app(self, app_type: str) -> List[MeasurementResult]:
        """Get all results for a specific app type."""
        return [r for r in self.results if r.app_type == app_type]

    def find_best_for_file_transfer(self) -> Optional[MeasurementResult]:
        """
        Find parameters with HIGHEST throughput for file transfer.

        File transfer optimization target: MAXIMIZE throughput
        """
        ft_results = self.get_results_by_app("file_transfer")
        if not ft_results:
            return None
        return max(ft_results, key=lambda r: r.throughput)

    def find_best_for_video_streaming(self) -> Optional[MeasurementResult]:
        """
        Find parameters with LOWEST latency for video streaming.

        Video streaming optimization target: MINIMIZE latency
        """
        vs_results = self.get_results_by_app("video_streaming")
        if not vs_results:
            return None
        # Filter out zero latency results (likely errors)
        valid_results = [r for r in vs_results if r.latency > 0]
        if not valid_results:
            return min(vs_results, key=lambda r: r.latency)
        return min(valid_results, key=lambda r: r.latency)

    def find_best_for_conference_call(self) -> Optional[MeasurementResult]:
        """
        Find parameters with LOWEST jitter for conference call.

        Conference call optimization target: MINIMIZE jitter
        """
        cc_results = self.get_results_by_app("conference_call")
        if not cc_results:
            return None
        # Filter out zero jitter results (likely errors)
        valid_results = [r for r in cc_results if r.jitter > 0]
        if not valid_results:
            return min(cc_results, key=lambda r: r.jitter)
        return min(valid_results, key=lambda r: r.jitter)

    def get_optimal_configs(self) -> Dict[str, Optional[MeasurementResult]]:
        """Get optimal configurations for all app types."""
        return {
            "file_transfer": self.find_best_for_file_transfer(),
            "video_streaming": self.find_best_for_video_streaming(),
            "conference_call": self.find_best_for_conference_call(),
        }

    def get_statistics_by_app(self, app_type: str) -> Dict:
        """
        Get statistics for a specific app type.

        Returns min, max, mean, stdev for each metric.
        """
        results = self.get_results_by_app(app_type)
        if not results:
            return {}

        throughputs = [r.throughput for r in results]
        latencies = [r.latency for r in results if r.latency > 0]
        jitters = [r.jitter for r in results if r.jitter > 0]
        rtts = [r.rtt for r in results if r.rtt > 0]
        loss_rates = [r.packet_loss_rate for r in results]

        def calc_stats(values):
            if not values:
                return {"min": 0, "max": 0, "mean": 0, "stdev": 0}
            return {
                "min": min(values),
                "max": max(values),
                "mean": statistics.mean(values),
                "stdev": statistics.stdev(values) if len(values) > 1 else 0,
            }

        return {
            "throughput": calc_stats(throughputs),
            "latency": calc_stats(latencies),
            "jitter": calc_stats(jitters),
            "rtt": calc_stats(rtts),
            "packet_loss_rate": calc_stats(loss_rates),
            "count": len(results),
        }

    def print_summary(self):
        """Print summary of optimal configurations."""
        optimal = self.get_optimal_configs()

        print("\n" + "=" * 70)
        print("OPTIMAL CONFIGURATIONS FOUND")
        print("(Only 6 dynamic parameters were searched)")
        print("=" * 70)

        for app_type, result in optimal.items():
            print(f"\n{app_type.upper().replace('_', ' ')}")
            print("-" * 50)

            if result:
                # Determine which metric was optimized
                metric_info = {
                    "file_transfer": ("Throughput", f"{result.throughput:.0f} bytes/sec ({result.throughput * 8 / 1_000_000:.2f} Mbps)"),
                    "video_streaming": ("Latency", f"{result.latency * 1000:.2f} ms"),
                    "conference_call": ("Jitter", f"{result.jitter * 1000:.2f} ms"),
                }[app_type]

                print(f"  Optimization target: {metric_info[0]} = {metric_info[1]}")
                print()
                print(f"  Dynamic parameters (searched):")
                print(f"    loss_reduction_factor: {result.loss_reduction_factor}")
                print(f"    cubic_c:               {result.cubic_c}")
                print(f"    minimum_window:        {result.minimum_window}")
                print(f"    packet_threshold:      {result.packet_threshold}")
                print(f"    time_threshold:        {result.time_threshold}")
                print(f"    cubic_max_idle_time:   {result.cubic_max_idle_time}")
                print()
                print(f"  Start-only parameters (fixed, not searched):")
                print(f"    initial_cw:            {result.initial_cw}")
                print(f"    max_ack_delay:         {result.max_ack_delay}")
                print()
                print(f"  Other metrics:")
                print(f"    RTT:         {result.rtt * 1000:.2f} ms")
                print(f"    Packet Loss: {result.packet_loss_rate * 100:.2f}%")
            else:
                print("  No results found!")

        print("\n" + "=" * 70)

    def print_statistics(self):
        """Print statistics for all app types."""
        print("\n" + "=" * 70)
        print("STATISTICS BY APPLICATION TYPE")
        print("=" * 70)

        for app_type in ["file_transfer", "video_streaming", "conference_call"]:
            stats = self.get_statistics_by_app(app_type)
            if not stats:
                continue

            print(f"\n{app_type.upper().replace('_', ' ')} ({stats['count']} measurements)")
            print("-" * 50)

            print(f"  Throughput (bytes/sec):")
            t = stats["throughput"]
            print(f"    Min: {t['min']:.0f}  Max: {t['max']:.0f}  Mean: {t['mean']:.0f}  StdDev: {t['stdev']:.0f}")

            print(f"  Latency (ms):")
            l = stats["latency"]
            print(f"    Min: {l['min']*1000:.2f}  Max: {l['max']*1000:.2f}  Mean: {l['mean']*1000:.2f}  StdDev: {l['stdev']*1000:.2f}")

            print(f"  Jitter (ms):")
            j = stats["jitter"]
            print(f"    Min: {j['min']*1000:.2f}  Max: {j['max']*1000:.2f}  Mean: {j['mean']*1000:.2f}  StdDev: {j['stdev']*1000:.2f}")

        print("\n" + "=" * 70)

    def export_optimal_configs(
        self,
        output_path: str = "output/analysis/optimal_configs.csv"
    ):
        """Export optimal configurations to CSV."""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        optimal = self.get_optimal_configs()

        with open(output_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "app_type",
                "optimization_metric",
                "metric_value",
                "loss_reduction_factor",
                "cubic_c",
                "minimum_window",
                "packet_threshold",
                "time_threshold",
                "cubic_max_idle_time",
                "initial_cw",
                "max_ack_delay",
                "throughput",
                "latency",
                "jitter",
                "rtt",
                "packet_loss_rate",
            ])

            for app_type, result in optimal.items():
                if result:
                    metric_name = {
                        "file_transfer": "throughput",
                        "video_streaming": "latency",
                        "conference_call": "jitter",
                    }[app_type]
                    metric_value = {
                        "file_transfer": result.throughput,
                        "video_streaming": result.latency,
                        "conference_call": result.jitter,
                    }[app_type]

                    writer.writerow([
                        app_type,
                        metric_name,
                        metric_value,
                        result.loss_reduction_factor,
                        result.cubic_c,
                        result.minimum_window,
                        result.packet_threshold,
                        result.time_threshold,
                        result.cubic_max_idle_time,
                        result.initial_cw,
                        result.max_ack_delay,
                        result.throughput,
                        result.latency,
                        result.jitter,
                        result.rtt,
                        result.packet_loss_rate,
                    ])

        print(f"Optimal configs exported to: {output_file}")

    def export_optimal_configs_json(
        self,
        output_path: str = "output/analysis/optimal_configs.json"
    ):
        """Export optimal configurations to JSON for easy loading."""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        optimal = self.get_optimal_configs()

        export_data = {}
        for app_type, result in optimal.items():
            if result:
                export_data[app_type] = {
                    "parameters": {
                        "loss_reduction_factor": result.loss_reduction_factor,
                        "cubic_c": result.cubic_c,
                        "minimum_window": result.minimum_window,
                        "packet_threshold": result.packet_threshold,
                        "time_threshold": result.time_threshold,
                        "cubic_max_idle_time": result.cubic_max_idle_time,
                        "initial_cw": result.initial_cw,
                        "max_ack_delay": result.max_ack_delay,
                    },
                    "metrics": {
                        "throughput": result.throughput,
                        "latency": result.latency,
                        "jitter": result.jitter,
                        "rtt": result.rtt,
                        "packet_loss_rate": result.packet_loss_rate,
                    },
                }

        with open(output_file, "w") as f:
            json.dump(export_data, f, indent=2)

        print(f"Optimal configs exported to: {output_file}")

    def export_all_results(
        self,
        output_path: str = "output/analysis/all_results.csv"
    ):
        """Export all results to a single CSV for external analysis."""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "app_type",
                "loss_reduction_factor",
                "cubic_c",
                "minimum_window",
                "packet_threshold",
                "time_threshold",
                "cubic_max_idle_time",
                "initial_cw",
                "max_ack_delay",
                "throughput",
                "latency",
                "jitter",
                "rtt",
                "packet_loss_rate",
                "bytes_sent",
            ])

            for result in self.results:
                writer.writerow([
                    result.app_type,
                    result.loss_reduction_factor,
                    result.cubic_c,
                    result.minimum_window,
                    result.packet_threshold,
                    result.time_threshold,
                    result.cubic_max_idle_time,
                    result.initial_cw,
                    result.max_ack_delay,
                    result.throughput,
                    result.latency,
                    result.jitter,
                    result.rtt,
                    result.packet_loss_rate,
                    result.bytes_sent,
                ])

        print(f"All results exported to: {output_file}")


if __name__ == "__main__":
    # Quick test
    analyzer = ResultsAnalyzer()
    count = analyzer.load_results()
    if count > 0:
        analyzer.print_summary()
        analyzer.print_statistics()
    else:
        print("No results to analyze. Run the grid search first.")
