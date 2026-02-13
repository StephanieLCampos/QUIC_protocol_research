"""
Result data structures for simulation outputs.

Provides structured storage and export functionality for
simulation results including metrics, epochs, and parameter history.
"""

import json
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
            self.simulation_id = datetime.now().strftime("%Y%m%d_%H%M%S")
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
        return {
            "simulation_id": self.simulation_id,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "duration_seconds": self.duration_seconds,
            "network_scenario": self.network_scenario,
            "network_config": self.network_config,
            "shared_params": self.shared_params,
            "fairness_index": self.fairness_index,
            "total_throughput": self.total_throughput,
            "connections": {
                conn_id: result.to_dict()
                for conn_id, result in self.connection_results.items()
            },
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
