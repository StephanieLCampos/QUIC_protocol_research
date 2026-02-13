"""
Additional export utilities for metrics data.

Complements the JSON exports in result.py with CSV and other formats
for integration with analysis tools like pandas, Excel, etc.
"""

import csv
from pathlib import Path
from typing import Dict, List, Any


class MetricsExporter:
    """
    Additional export utilities for metrics data.

    Complements the JSON exports in result.py with CSV and other formats
    for integration with analysis tools like pandas, Excel, etc.
    """

    @staticmethod
    def export_metrics_to_csv(
        metrics_history: List[Dict[str, Any]],
        output_path: str,
        connection_id: int,
    ) -> str:
        """
        Export metrics time series to CSV format.

        Args:
            metrics_history: List of metric snapshots
            output_path: Directory for output file
            connection_id: Connection identifier

        Returns:
            Path to the exported CSV file.
        """
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"metrics_conn_{connection_id}.csv"
        filepath = output_dir / filename

        if not metrics_history:
            return str(filepath)

        # Get all metric keys from first entry
        fieldnames = ["timestamp"]
        sample = metrics_history[0]
        for key in sample.keys():
            if key != "timestamp":
                fieldnames.append(key)

        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(metrics_history)

        return str(filepath)

    @staticmethod
    def export_epochs_to_csv(
        epoch_history: List[Dict[str, Any]],
        output_path: str,
        connection_id: int,
    ) -> str:
        """
        Export epoch-based metrics to CSV format.

        Flattens the epoch structure for easy analysis in spreadsheets.

        Args:
            epoch_history: List of epoch records
            output_path: Directory for output file
            connection_id: Connection identifier

        Returns:
            Path to the exported CSV file.
        """
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"epochs_conn_{connection_id}.csv"
        filepath = output_dir / filename

        if not epoch_history:
            return str(filepath)

        # Build flattened rows
        rows = []
        for epoch in epoch_history:
            row = {
                "epoch_number": epoch.get("epoch_number", 0),
                "start_time": epoch.get("start_time", 0),
                "end_time": epoch.get("end_time", 0),
                "duration_seconds": epoch.get("duration_seconds", 0),
                "settling_time": epoch.get("settling_time", 0),
            }

            # Flatten parameters
            params = epoch.get("parameters", {})
            for param_name, value in params.items():
                row[f"param_{param_name}"] = value

            # Flatten metrics
            metrics = epoch.get("metrics", {})
            for metric_name, value in metrics.items():
                row[f"metric_{metric_name}"] = value

            rows.append(row)

        if rows:
            fieldnames = list(rows[0].keys())
            with open(filepath, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

        return str(filepath)

    @staticmethod
    def export_comparison_csv(
        all_results: Dict[int, Dict[str, Any]],
        output_path: str,
        simulation_id: str,
    ) -> str:
        """
        Export a comparison CSV with all connections side-by-side.

        Creates a single CSV where each row is a timestamp and columns
        show metrics for each connection.

        Args:
            all_results: Dict mapping connection_id to result data
            output_path: Directory for output file
            simulation_id: Simulation identifier

        Returns:
            Path to the exported CSV file.
        """
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"comparison_{simulation_id}.csv"
        filepath = output_dir / filename

        # Build header with metrics for each connection
        metric_names = ["throughput", "rtt", "latency", "jitter", "packet_loss_rate"]
        fieldnames = ["timestamp"]
        for conn_id in sorted(all_results.keys()):
            app_type = all_results[conn_id].get("application_type", f"conn_{conn_id}")
            for metric in metric_names:
                fieldnames.append(f"{app_type}_{metric}")

        # Merge metrics histories by timestamp
        merged_data: Dict[float, Dict[str, Any]] = {}

        for conn_id, result in all_results.items():
            app_type = result.get("application_type", f"conn_{conn_id}")
            for entry in result.get("metrics_history", []):
                ts = entry.get("timestamp", 0)
                if ts not in merged_data:
                    merged_data[ts] = {"timestamp": ts}
                for metric in metric_names:
                    merged_data[ts][f"{app_type}_{metric}"] = entry.get(metric, "")

        # Sort by timestamp and write
        rows = [merged_data[ts] for ts in sorted(merged_data.keys())]

        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        return str(filepath)

    @staticmethod
    def export_summary_csv(
        results: Dict[str, Any],
        output_path: str,
    ) -> str:
        """
        Export a one-row summary CSV for batch analysis.

        Useful when running many simulations and wanting to compare
        final results across different configurations.

        Args:
            results: Full simulation result dictionary
            output_path: Directory for output file

        Returns:
            Path to the exported CSV file.
        """
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        simulation_id = results.get("simulation_id", "unknown")
        filename = f"summary_{simulation_id}.csv"
        filepath = output_dir / filename

        # Build summary row
        row = {
            "simulation_id": simulation_id,
            "network_scenario": results.get("network_scenario", ""),
            "duration_seconds": results.get("duration_seconds", 0),
            "fairness_index": results.get("fairness_index", 0),
            "total_throughput": results.get("total_throughput", 0),
        }

        # Add per-connection final metrics
        connections = results.get("connections", {})
        for conn_id, conn_result in connections.items():
            app_type = conn_result.get("application_type", f"conn_{conn_id}")
            final_metrics = conn_result.get("final_metrics", {})
            for metric_name, value in final_metrics.items():
                row[f"{app_type}_{metric_name}"] = value

        fieldnames = list(row.keys())
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(row)

        return str(filepath)
