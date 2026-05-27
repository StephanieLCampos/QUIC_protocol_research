"""
Result data structures for simulation outputs.

Provides structured storage and export functionality for
simulation results including metrics, epochs, and parameter history.
"""

import json
import math
import statistics
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path


@dataclass
class ConnectionResult:
    """
    Result from a single QUIC connection.

    Includes final metrics, parameter history, and epoch-based metrics
    for analyzing performance across parameter changes.
    """

    connection_id: int
    application_type: str

    # Final aggregated metrics
    final_metrics: Dict[str, float] = field(default_factory=dict)

    # Parameter history: list of {timestamp, param_name, old_value, new_value}
    param_history: List[Dict[str, Any]] = field(default_factory=list)

    # Epoch history from EpochManager
    epoch_history: List[Dict[str, Any]] = field(default_factory=list)

    # Full metrics time series (100ms intervals)
    metrics_history: List[Dict[str, Any]] = field(default_factory=list)

    # Metadata
    start_time: float = 0.0
    end_time: float = 0.0
    success: bool = True
    error_message: Optional[str] = None

    # Network conditions this connection experienced
    network_scenario: str = ""
    network_config: Dict[str, Any] = field(default_factory=dict)

    def get_duration(self) -> float:
        """Get total connection duration in seconds."""
        return self.end_time - self.start_time

    def get_epoch_count(self) -> int:
        """Get number of completed epochs (parameter stable periods)."""
        return len(self.epoch_history)

    def get_final_epoch_metrics(self) -> Optional[Dict[str, Any]]:
        """Get metrics from the final (most recent) epoch."""
        if self.epoch_history:
            return self.epoch_history[-1]
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class MultiConnectionResult:
    """
    Combined result from all 3 QUIC connections.

    Provides methods to export results in various formats for analysis.
    """

    # Results per connection
    connection_results: Dict[int, ConnectionResult] = field(default_factory=dict)

    # Simulation metadata
    simulation_id: str = ""
    start_timestamp: str = ""
    end_timestamp: str = ""
    duration_seconds: float = 0.0

    # Network scenario used
    network_scenario: str = ""
    network_config: Dict[str, Any] = field(default_factory=dict)

    # Shared start-only parameters (constant for all connections)
    shared_params: Dict[str, Any] = field(default_factory=dict)

    # Aggregated fairness metrics
    fairness_index: float = 1.0
    total_throughput: float = 0.0

    def __post_init__(self):
        """Generate simulation ID if not provided."""
        if not self.simulation_id:
            self.simulation_id = datetime.now().strftime("%d-%m-%Y_%I-%M-%S%p")
        if not self.start_timestamp:
            self.start_timestamp = datetime.now().isoformat()

    def add_connection_result(self, result: ConnectionResult):
        """Add a connection result."""
        self.connection_results[result.connection_id] = result

    def compute_fairness_index(self) -> float:
        """Compute Jain's fairness index across all connections."""
        throughputs = [
            r.final_metrics.get("throughput", 0)
            for r in self.connection_results.values()
        ]
        if not throughputs or sum(throughputs) == 0:
            return 1.0

        n = len(throughputs)
        sum_x = sum(throughputs)
        sum_x_sq = sum(x ** 2 for x in throughputs)
        self.fairness_index = (sum_x ** 2) / (n * sum_x_sq) if sum_x_sq > 0 else 1.0
        return self.fairness_index

    def compute_total_throughput(self) -> float:
        """Compute total throughput across all connections."""
        self.total_throughput = sum(
            r.final_metrics.get("throughput", 0)
            for r in self.connection_results.values()
        )
        return self.total_throughput

    def finalize(self):
        """Finalize results: compute aggregates, set end timestamp."""
        self.end_timestamp = datetime.now().isoformat()
        self.compute_fairness_index()
        self.compute_total_throughput()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        offered_bps = self.total_throughput  # bytes per second
        offered_mbps = (offered_bps * 8) / 1_000_000
        bottleneck_summary = self.get_bottleneck_summary()
        robust_metrics_summary = self.get_robust_metrics_summary()

        return {
            "simulation_id": self.simulation_id,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "duration_seconds": self.duration_seconds,
            "network_scenario": self.network_scenario,
            "network_config": self.network_config,
            "shared_params": self.shared_params,
            "fairness_index": self.fairness_index,
            "total_offered_throughput_Bps": offered_bps,
            "total_offered_throughput_Mbps": offered_mbps,
            "total_throughput": offered_bps,
            "bottleneck_summary": bottleneck_summary,
            "robust_metrics_summary": robust_metrics_summary,
            "connections": {
                conn_id: result.to_dict()
                for conn_id, result in self.connection_results.items()
            },
        }

    def _compute_trimmed_median_summary(
        self,
        series: List[Dict[str, Any]],
        warmup_ratio: float = 0.2,
        cooldown_ratio: float = 0.1,
    ) -> Dict[str, Any]:
        """Compute warmup/cooldown-trimmed medians from a metrics time-series."""
        if not series:
            return {
                "samples_total": 0,
                "samples_used": 0,
                "warmup_ratio": warmup_ratio,
                "cooldown_ratio": cooldown_ratio,
            }

        n = len(series)
        start_idx = min(n - 1, max(0, int(math.floor(n * warmup_ratio))))
        end_idx = max(start_idx + 1, n - int(math.floor(n * cooldown_ratio)))
        trimmed = series[start_idx:end_idx]

        def median_of(key: str) -> float:
            values = [float(item.get(key, 0) or 0) for item in trimmed]
            return float(statistics.median(values)) if values else 0.0

        # Offered throughput (application send rate)
        offered_bps_med = median_of("throughput") * 8

        return {
            "samples_total": n,
            "samples_used": len(trimmed),
            "warmup_ratio": warmup_ratio,
            "cooldown_ratio": cooldown_ratio,
            "offered_throughput_median_bps": offered_bps_med,
            "offered_throughput_median_mbps": offered_bps_med / 1_000_000,
            "rtt_median_ms": median_of("rtt") * 1000,
            "latency_median_ms": median_of("latency") * 1000,
            "jitter_median_ms": median_of("jitter") * 1000,
            "packet_loss_rate_median": median_of("packet_loss_rate"),
        }

    def get_robust_metrics_summary(
        self,
        warmup_ratio: float = 0.2,
        cooldown_ratio: float = 0.1,
    ) -> Dict[str, Any]:
        """Build robust, trimmed-median summaries for each connection."""
        per_connection: Dict[str, Any] = {}
        for conn_id, result in self.connection_results.items():
            per_connection[str(conn_id)] = {
                "application_type": result.application_type,
                "trimmed_medians": self._compute_trimmed_median_summary(
                    result.metrics_history,
                    warmup_ratio=warmup_ratio,
                    cooldown_ratio=cooldown_ratio,
                ),
            }

        return {
            "method": "trimmed_median",
            "description": "Medians over metrics_history after dropping warmup and cooldown portions.",
            "warmup_ratio": warmup_ratio,
            "cooldown_ratio": cooldown_ratio,
            "per_connection": per_connection,
        }

    def _estimate_actual_throughput_per_connection(
        self, observed_link_bps: float
    ) -> Dict[str, Any]:
        """
        Estimate actual throughput per connection based on tc bottleneck.

        Logic:
        - Connections that offered less than their share of tc capacity
          likely got ALL their data through (actual ≈ offered)
        - Bottlenecked connections share the remaining tc capacity
          proportionally based on their offered load

        Returns dict with per-connection offered and actual throughput.
        """
        per_connection_throughput: Dict[str, Any] = {}

        # Calculate offered bytes per second for each connection
        per_conn_offered_bps: Dict[int, float] = {}
        for conn_id, result in self.connection_results.items():
            offered_Bps = result.final_metrics.get("throughput", 0)  # bytes/sec
            per_conn_offered_bps[conn_id] = offered_Bps * 8  # bits/sec

        total_offered_bps = sum(per_conn_offered_bps.values())

        # If no tc data or no offered throughput, return offered as actual
        if observed_link_bps <= 0 or total_offered_bps <= 0:
            for conn_id, result in self.connection_results.items():
                offered_bps = per_conn_offered_bps.get(conn_id, 0)
                receiver_mbps = result.final_metrics.get("receiver_throughput_mbps", 0)
                receiver_bytes = result.final_metrics.get("receiver_bytes", 0)
                bytes_sent = result.final_metrics.get("bytes_sent", 0)
                delivery_ratio = (receiver_bytes / bytes_sent * 100) if bytes_sent > 0 else 0

                # Get client-side ACK-verified throughput
                acked_throughput = result.final_metrics.get("throughput_acked", 0)
                acked_mbps = acked_throughput * 8 / 1_000_000  # Convert bytes/s to Mbps

                per_connection_throughput[str(conn_id)] = {
                    "application_type": result.application_type,
                    "client_offered_mbps": offered_bps / 1_000_000,
                    "client_acked_mbps": acked_mbps,
                    "server_received_mbps": receiver_mbps,
                    "delivery_ratio_percent": delivery_ratio,
                }
            return per_connection_throughput

        # If total offered <= observed (no bottleneck), actual ≈ offered
        if total_offered_bps <= observed_link_bps * 1.1:  # 10% tolerance
            for conn_id, result in self.connection_results.items():
                offered_bps = per_conn_offered_bps.get(conn_id, 0)
                receiver_mbps = result.final_metrics.get("receiver_throughput_mbps", 0)
                receiver_bytes = result.final_metrics.get("receiver_bytes", 0)
                bytes_sent = result.final_metrics.get("bytes_sent", 0)
                delivery_ratio = (receiver_bytes / bytes_sent * 100) if bytes_sent > 0 else 0

                # Get client-side ACK-verified throughput
                acked_throughput = result.final_metrics.get("throughput_acked", 0)
                acked_mbps = acked_throughput * 8 / 1_000_000  # Convert bytes/s to Mbps

                per_connection_throughput[str(conn_id)] = {
                    "application_type": result.application_type,
                    "client_offered_mbps": offered_bps / 1_000_000,
                    "client_acked_mbps": acked_mbps,
                    "server_received_mbps": receiver_mbps,
                    "delivery_ratio_percent": delivery_ratio,
                }
            return per_connection_throughput

        # Bottleneck is active - estimate per-connection actual throughput
        # Use PROPORTIONAL distribution based on offered load
        # This reflects real network behavior without fair queuing:
        # - Aggressive senders (file transfer) dominate the bottleneck
        # - Smaller flows get starved proportionally
        # The Q-learning's job is to optimize parameters to improve fairness

        actual_bps: Dict[int, float] = {}

        for conn_id, offered_bps in per_conn_offered_bps.items():
            # Each connection gets a share of tc capacity proportional to its offered load
            proportion = offered_bps / total_offered_bps if total_offered_bps > 0 else 0
            actual_bps[conn_id] = observed_link_bps * proportion

        # Build result
        for conn_id, result in self.connection_results.items():
            offered_bps = per_conn_offered_bps.get(conn_id, 0)
            conn_actual_bps = actual_bps.get(conn_id, offered_bps)

            # Ensure actual doesn't exceed offered
            conn_actual_bps = min(conn_actual_bps, offered_bps)

            # Check for receiver-side throughput (actual measurement from server)
            receiver_mbps = result.final_metrics.get("receiver_throughput_mbps", 0)
            receiver_bytes = result.final_metrics.get("receiver_bytes", 0)
            bytes_sent = result.final_metrics.get("bytes_sent", 0)

            # Calculate delivery ratio if we have both values
            delivery_ratio = 0.0
            if bytes_sent > 0 and receiver_bytes > 0:
                delivery_ratio = (receiver_bytes / bytes_sent) * 100

            # Get client-side ACK-verified throughput
            acked_throughput = result.final_metrics.get("throughput_acked", 0)
            acked_mbps = acked_throughput * 8 / 1_000_000  # Convert bytes/s to Mbps

            per_connection_throughput[str(conn_id)] = {
                "application_type": result.application_type,
                "client_offered_mbps": offered_bps / 1_000_000,
                "client_acked_mbps": acked_mbps,
                "server_received_mbps": receiver_mbps,
                "delivery_ratio_percent": delivery_ratio,
            }

        return per_connection_throughput

    def get_bottleneck_summary(self) -> Dict[str, Any]:
        """Build a bottleneck-focused summary that is easy to interpret."""
        offered_bps = self.total_throughput * 8
        offered_mbps = offered_bps / 1_000_000

        configured_capacity_bps = 0.0
        observed_link_bps = 0.0

        if isinstance(self.network_config, dict):
            configured_capacity_bps = float(self.network_config.get("capacity_bps", 0) or 0)
            observed_link_bps = float(self.network_config.get("tc_observed_throughput_bps", 0) or 0)

        configured_capacity_mbps = configured_capacity_bps / 1_000_000 if configured_capacity_bps > 0 else 0.0
        observed_link_mbps = observed_link_bps / 1_000_000 if observed_link_bps > 0 else 0.0

        cap_utilization_pct = (
            (observed_link_bps / configured_capacity_bps) * 100
            if configured_capacity_bps > 0 and observed_link_bps > 0
            else 0.0
        )

        offered_vs_observed_ratio = (
            (offered_bps / observed_link_bps)
            if observed_link_bps > 0
            else 0.0
        )

        bottleneck_applied = observed_link_bps > 0
        bottleneck_limiting = offered_bps > 0 and observed_link_bps > 0 and offered_bps > (observed_link_bps * 1.2)
        near_configured_cap = (
            configured_capacity_bps > 0
            and observed_link_bps > 0
            and observed_link_bps <= (configured_capacity_bps * 1.15)
        )

        network_probe = {}
        if isinstance(self.network_config, dict):
            probe = self.network_config.get("network_rtt_probe", {})
            if isinstance(probe, dict):
                network_probe = probe

        # Calculate per-connection throughput (offered vs actual through bottleneck)
        per_connection_throughput = self._estimate_actual_throughput_per_connection(
            observed_link_bps
        )

        return {
            "bottleneck_applied": bottleneck_applied,
            "bottleneck_limiting_traffic": bottleneck_limiting,
            "observed_rate_near_configured_cap": near_configured_cap,
            "configured_capacity_bps": configured_capacity_bps,
            "configured_capacity_mbps": configured_capacity_mbps,
            "observed_link_throughput_bps": observed_link_bps,
            "observed_link_throughput_mbps": observed_link_mbps,
            "total_offered_throughput_bps": offered_bps,
            "total_offered_throughput_mbps": offered_mbps,
            "cap_utilization_percent": cap_utilization_pct,
            "offered_to_observed_ratio": offered_vs_observed_ratio,
            "network_only_rtt_probe": network_probe,
            "per_connection_throughput": per_connection_throughput,
        }

    def export_json(self, output_dir: str = "output") -> str:
        """
        Export complete results to JSON file.

        Returns the path to the exported file.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        filename = f"results_{self.simulation_id}.json"
        filepath = output_path / filename

        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

        return str(filepath)

    def export_metrics_history(self, output_dir: str = "output") -> str:
        """
        Export full metrics time series for all connections.

        Returns the path to the exported file.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        filename = f"metrics_history_{self.simulation_id}.json"
        filepath = output_path / filename

        history_data = {
            "simulation_id": self.simulation_id,
            "network_scenario": self.network_scenario,
            "connections": {
                conn_id: {
                    "application_type": result.application_type,
                    "metrics_history": result.metrics_history,
                }
                for conn_id, result in self.connection_results.items()
            },
        }

        with open(filepath, "w") as f:
            json.dump(history_data, f, indent=2)

        return str(filepath)

    def export_epoch_histories(self, output_dir: str = "output") -> str:
        """
        Export epoch-based metrics for all connections.

        Returns the path to the exported file.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        filename = f"epoch_history_{self.simulation_id}.json"
        filepath = output_path / filename

        epoch_data = {
            "simulation_id": self.simulation_id,
            "network_scenario": self.network_scenario,
            "network_config": self.network_config,
            "shared_params": self.shared_params,
            "connections": {},
        }

        for conn_id, result in self.connection_results.items():
            epoch_data["connections"][conn_id] = {
                "application_type": result.application_type,
                "epoch_count": result.get_epoch_count(),
                "epochs": result.epoch_history,
            }

        with open(filepath, "w") as f:
            json.dump(epoch_data, f, indent=2)

        return str(filepath)

    def export_bottleneck_summary(self, output_dir: str = "output") -> str:
        """
        Export a compact bottleneck-specific summary for quick verification.

        Returns the path to the exported file.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        filename = f"bottleneck_summary_{self.simulation_id}.json"
        filepath = output_path / filename

        data = {
            "simulation_id": self.simulation_id,
            "network_scenario": self.network_scenario,
            "bottleneck_summary": self.get_bottleneck_summary(),
            "robust_metrics_summary": self.get_robust_metrics_summary(),
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        return str(filepath)

    def export_median_metrics_summary(self, output_dir: str = "output") -> str:
        """
        Export only trimmed-median metrics for quick comparison.

        Returns the path to the exported file.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        filename = f"median_metrics_summary_{self.simulation_id}.json"
        filepath = output_path / filename

        robust = self.get_robust_metrics_summary()
        per_connection = robust.get("per_connection", {})

        # Get tc-based actual throughput from bottleneck summary
        bottleneck_summary = self.get_bottleneck_summary()
        per_conn_throughput = bottleneck_summary.get("per_connection_throughput", {})

        compact_connections: Dict[str, Any] = {}
        for conn_id, conn_data in per_connection.items():
            med = conn_data.get("trimmed_medians", {})
            # Get throughput data from bottleneck summary
            throughput_data = per_conn_throughput.get(str(conn_id), {})
            client_acked_mbps = throughput_data.get("client_acked_mbps", 0.0)
            server_received_mbps = throughput_data.get("server_received_mbps", 0.0)
            delivery_ratio = throughput_data.get("delivery_ratio_percent", 0.0)

            compact_connections[str(conn_id)] = {
                "application_type": conn_data.get("application_type", ""),
                "client_offered_median_mbps": med.get("offered_throughput_median_mbps", 0.0),
                "client_acked_mbps": client_acked_mbps,
                "server_received_mbps": server_received_mbps,
                "delivery_ratio_percent": delivery_ratio,
                "rtt_median_ms": med.get("rtt_median_ms", 0.0),
                "latency_median_ms": med.get("latency_median_ms", 0.0),
                "jitter_median_ms": med.get("jitter_median_ms", 0.0),
                "packet_loss_rate_median": med.get("packet_loss_rate_median", 0.0),
                "samples_used": med.get("samples_used", 0),
                "samples_total": med.get("samples_total", 0),
            }

        data = {
            "simulation_id": self.simulation_id,
            "network_scenario": self.network_scenario,
            "method": robust.get("method", "trimmed_median"),
            "warmup_ratio": robust.get("warmup_ratio", 0.2),
            "cooldown_ratio": robust.get("cooldown_ratio", 0.1),
            "network_only_rtt_probe": bottleneck_summary.get("network_only_rtt_probe", {}),
            "connections": compact_connections,
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        return str(filepath)

    def get_epoch_comparison_summary(self) -> Dict[str, Any]:
        """
        Generate summary comparing metrics across epochs for each connection.

        Useful for seeing how parameter changes affected performance.
        """
        summary = {}

        for conn_id, result in self.connection_results.items():
            if not result.epoch_history:
                continue

            epochs = result.epoch_history
            summary[conn_id] = {
                "application_type": result.application_type,
                "total_epochs": len(epochs),
                "epoch_summaries": [],
            }

            for i, epoch in enumerate(epochs):
                epoch_summary = {
                    "epoch_number": epoch.get("epoch_number", i + 1),
                    "parameters": epoch.get("parameters", {}),
                    "duration_seconds": epoch.get("duration_seconds", 0),
                    "metrics": epoch.get("metrics", {}),
                }
                summary[conn_id]["epoch_summaries"].append(epoch_summary)

        return summary
