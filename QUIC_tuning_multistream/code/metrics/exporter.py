"""
Metrics exporter for saving results to CSV files.

Exports simulation metrics to CSV files with standardized naming
convention for easy analysis.
"""

import csv
from pathlib import Path
from typing import Dict, Any, Optional

from .calculator import MetricsResult


class MetricsExporter:
    """
    Exports metrics to CSV files.

    File naming convention:
    <application_type>_<Initial_CW>_<Max_ACK_Delay>_<Loss_Factor>.csv

    Examples:
    - video_streaming_12000_0.025_0.5.csv
    - file_transfer_60000_0.010_0.7.csv
    - conference_call_120000_0.002_0.6.csv
    """

    # CSV column headers
    HEADERS = [
        "initial_congestion_window",
        "max_ack_delay",
        "loss_reduction_factor",
        "throughput",
        "rtt",
        "latency",
        "jitter",
        "packet_loss_rate",
        "connection_establishment_time",
    ]

    def __init__(self, output_dir: str = "output/measurements"):
        """
        Initialize the metrics exporter.

        Args:
            output_dir: Directory where CSV files will be saved.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_filename(
        self,
        application_type: str,
        initial_cw: int,
        max_ack_delay: float,
        loss_factor: float,
    ) -> str:
        """
        Generate the standardized filename for a simulation result.

        Args:
            application_type: Type of application (video_streaming, file_transfer, conference_call).
            initial_cw: Initial congestion window value.
            max_ack_delay: Max ACK delay value.
            loss_factor: Loss reduction factor value.

        Returns:
            Filename string.
        """
        return f"{application_type}_{initial_cw}_{max_ack_delay}_{loss_factor}.csv"

    def get_filepath(
        self,
        application_type: str,
        initial_cw: int,
        max_ack_delay: float,
        loss_factor: float,
    ) -> Path:
        """
        Get the full file path for a simulation result.

        Args:
            application_type: Type of application.
            initial_cw: Initial congestion window value.
            max_ack_delay: Max ACK delay value.
            loss_factor: Loss reduction factor value.

        Returns:
            Full Path object to the CSV file.
        """
        filename = self.get_filename(application_type, initial_cw, max_ack_delay, loss_factor)
        return self.output_dir / filename

    def export(
        self,
        application_type: str,
        initial_cw: int,
        max_ack_delay: float,
        loss_factor: float,
        metrics: MetricsResult,
    ) -> Path:
        """
        Export metrics to a CSV file.

        Args:
            application_type: Type of application.
            initial_cw: Initial congestion window value.
            max_ack_delay: Max ACK delay value.
            loss_factor: Loss reduction factor value.
            metrics: The calculated metrics to export.

        Returns:
            Path to the created CSV file.
        """
        filepath = self.get_filepath(application_type, initial_cw, max_ack_delay, loss_factor)

        # Prepare row data
        row = {
            "initial_congestion_window": initial_cw,
            "max_ack_delay": max_ack_delay,
            "loss_reduction_factor": loss_factor,
            "throughput": metrics.throughput,
            "rtt": metrics.rtt,
            "latency": metrics.latency,
            "jitter": metrics.jitter,
            "packet_loss_rate": metrics.packet_loss_rate,
            "connection_establishment_time": metrics.connection_establishment_time,
        }

        # Write to CSV
        with open(filepath, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=self.HEADERS)
            writer.writeheader()
            writer.writerow(row)

        return filepath

    def export_dict(
        self,
        application_type: str,
        initial_cw: int,
        max_ack_delay: float,
        loss_factor: float,
        metrics_dict: Dict[str, Any],
    ) -> Path:
        """
        Export metrics from a dictionary to a CSV file.

        Args:
            application_type: Type of application.
            initial_cw: Initial congestion window value.
            max_ack_delay: Max ACK delay value.
            loss_factor: Loss reduction factor value.
            metrics_dict: Dictionary with metric values.

        Returns:
            Path to the created CSV file.
        """
        filepath = self.get_filepath(application_type, initial_cw, max_ack_delay, loss_factor)

        # Prepare row data
        row = {
            "initial_congestion_window": initial_cw,
            "max_ack_delay": max_ack_delay,
            "loss_reduction_factor": loss_factor,
            "throughput": metrics_dict.get("throughput", 0),
            "rtt": metrics_dict.get("rtt", 0),
            "latency": metrics_dict.get("latency", 0),
            "jitter": metrics_dict.get("jitter", 0),
            "packet_loss_rate": metrics_dict.get("packet_loss_rate", 0),
            "connection_establishment_time": metrics_dict.get("connection_establishment_time", 0),
        }

        # Write to CSV
        with open(filepath, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=self.HEADERS)
            writer.writeheader()
            writer.writerow(row)

        return filepath

    def file_exists(
        self,
        application_type: str,
        initial_cw: int,
        max_ack_delay: float,
        loss_factor: float,
    ) -> bool:
        """
        Check if a result file already exists.

        Used by the scheduler for resumability.

        Args:
            application_type: Type of application.
            initial_cw: Initial congestion window value.
            max_ack_delay: Max ACK delay value.
            loss_factor: Loss reduction factor value.

        Returns:
            True if the file exists, False otherwise.
        """
        filepath = self.get_filepath(application_type, initial_cw, max_ack_delay, loss_factor)
        return filepath.exists()
