"""
Epoch-based metrics collection for parameter change handling.

Provides data structures and management for collecting metrics during
stable parameter periods (epochs), with settling time support.
"""

import time
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ParameterSnapshot:
    """Snapshot of all parameters at a point in time."""
    loss_reduction_factor: float
    cubic_c: float
    minimum_window: int
    packet_threshold: int
    time_threshold: float
    cubic_max_idle_time: float

    # Start-only parameters (for reference)
    initial_cw: int
    max_ack_delay: float
    max_data: int
    max_stream_data: int

    def to_dict(self) -> dict:
        return {
            "dynamic": {
                "loss_reduction_factor": self.loss_reduction_factor,
                "cubic_c": self.cubic_c,
                "minimum_window": self.minimum_window,
                "packet_threshold": self.packet_threshold,
                "time_threshold": self.time_threshold,
                "cubic_max_idle_time": self.cubic_max_idle_time,
            },
            "start_only": {
                "initial_cw": self.initial_cw,
                "max_ack_delay": self.max_ack_delay,
                "max_data": self.max_data,
                "max_stream_data": self.max_stream_data,
            },
        }


@dataclass
class EpochMetrics:
    """Metrics collected during a stable parameter epoch."""
    throughput_bps: float
    avg_rtt_seconds: float
    min_rtt_seconds: float
    max_rtt_seconds: float
    jitter_seconds: float
    packet_loss_rate: float
    bytes_sent: int
    bytes_received: int
    packets_sent: int
    packets_lost: int

    def to_dict(self) -> dict:
        return {
            "throughput_bps": self.throughput_bps,
            "throughput_mbps": self.throughput_bps / 1_000_000,
            "avg_rtt_ms": self.avg_rtt_seconds * 1000,
            "min_rtt_ms": self.min_rtt_seconds * 1000,
            "max_rtt_ms": self.max_rtt_seconds * 1000,
            "jitter_ms": self.jitter_seconds * 1000,
            "packet_loss_rate": self.packet_loss_rate,
            "packet_loss_percent": self.packet_loss_rate * 100,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "packets_sent": self.packets_sent,
            "packets_lost": self.packets_lost,
        }


@dataclass
class Epoch:
    """
    A single epoch representing a stable period with fixed parameters.

    An epoch starts when:
    - Connection begins (epoch 0)
    - Parameters change (epoch N, after settling)

    An epoch ends when:
    - Parameters change again
    - Connection ends
    """
    epoch_id: int
    connection_id: int
    application_type: str

    # Timing
    start_time: float  # Epoch start (after settling if not first)
    end_time: Optional[float] = None
    settling_start: Optional[float] = None  # When param change occurred
    settling_duration: float = 0.0  # How long we waited

    # Parameters for this epoch
    parameters: Optional[ParameterSnapshot] = None

    # Network conditions
    network_scenario: str = ""
    network_config: Dict = field(default_factory=dict)

    # Metrics (calculated after epoch ends)
    metrics: Optional[EpochMetrics] = None

    # Raw samples collected during this epoch (for detailed analysis)
    raw_samples: List[Dict] = field(default_factory=list)

    @property
    def duration(self) -> float:
        """Duration of this epoch (excluding settling time)."""
        if self.end_time is None:
            return time.time() - self.start_time
        return self.end_time - self.start_time

    @property
    def is_valid(self) -> bool:
        """Epoch is valid if it has enough measurement time."""
        MIN_MEASUREMENT_TIME = 2.0  # At least 2 seconds of data
        return self.duration >= MIN_MEASUREMENT_TIME

    def to_dict(self) -> dict:
        return {
            "epoch_id": self.epoch_id,
            "connection_id": self.connection_id,
            "application_type": self.application_type,
            "timing": {
                "start_time": self.start_time,
                "end_time": self.end_time,
                "duration_seconds": self.duration,
                "settling_start": self.settling_start,
                "settling_duration_seconds": self.settling_duration,
            },
            "parameters": self.parameters.to_dict() if self.parameters else None,
            "network": {
                "scenario": self.network_scenario,
                "config": self.network_config,
            },
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "is_valid": self.is_valid,
            "sample_count": len(self.raw_samples),
        }


@dataclass
class ConnectionEpochHistory:
    """Complete epoch history for a single connection."""
    connection_id: int
    application_type: str
    epochs: List[Epoch] = field(default_factory=list)

    def add_epoch(self, epoch: Epoch):
        self.epochs.append(epoch)

    def get_valid_epochs(self) -> List[Epoch]:
        """Return only epochs with sufficient measurement time."""
        return [e for e in self.epochs if e.is_valid]

    def to_dict(self) -> dict:
        return {
            "connection_id": self.connection_id,
            "application_type": self.application_type,
            "total_epochs": len(self.epochs),
            "valid_epochs": len(self.get_valid_epochs()),
            "epochs": [e.to_dict() for e in self.epochs],
        }

    def export_json(self, path: str):
        """Export to JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


@dataclass
class EpochConfig:
    """Configuration for epoch management."""
    settling_time: float = 2.0  # Seconds to wait after param change
    min_epoch_duration: float = 2.0  # Minimum measurement time
    sample_interval: float = 0.1  # How often to collect samples


class EpochManager:
    """
    Manages epoch-based metrics collection for a connection.

    Handles:
    - Detecting parameter changes
    - Waiting for settling time
    - Collecting metrics during stable periods
    - Finalizing epochs when parameters change or connection ends
    """

    def __init__(
        self,
        connection_id: int,
        application_type: str,
        network_scenario: str,
        network_config: dict,
        initial_params: ParameterSnapshot,
        config: EpochConfig = None,
    ):
        self.connection_id = connection_id
        self.application_type = application_type
        self.network_scenario = network_scenario
        self.network_config = network_config
        self.config = config or EpochConfig()

        self.history = ConnectionEpochHistory(
            connection_id=connection_id,
            application_type=application_type,
        )

        self._current_epoch: Optional[Epoch] = None
        self._current_params = initial_params
        self._metrics_collector = None
        self._settling = False
        self._settling_end_time: float = 0

    def set_metrics_collector(self, collector):
        """Set the metrics collector to sample from."""
        self._metrics_collector = collector

    def start(self):
        """Start the first epoch."""
        self._current_epoch = Epoch(
            epoch_id=0,
            connection_id=self.connection_id,
            application_type=self.application_type,
            start_time=time.time(),
            parameters=self._current_params,
            network_scenario=self.network_scenario,
            network_config=self.network_config,
        )

    def on_parameter_change(self, new_params: ParameterSnapshot):
        """
        Called when parameters change.

        1. Finalize current epoch (calculate metrics from samples)
        2. Enter settling period
        3. Start new epoch after settling
        """
        now = time.time()

        # Finalize current epoch
        if self._current_epoch:
            self._current_epoch.end_time = now
            self._finalize_epoch(self._current_epoch)
            self.history.add_epoch(self._current_epoch)

        # Enter settling period
        self._settling = True
        self._settling_end_time = now + self.config.settling_time
        self._current_params = new_params

        # Prepare next epoch (will start after settling)
        next_epoch_id = len(self.history.epochs)
        self._current_epoch = Epoch(
            epoch_id=next_epoch_id,
            connection_id=self.connection_id,
            application_type=self.application_type,
            settling_start=now,
            settling_duration=self.config.settling_time,
            start_time=self._settling_end_time,  # Will start after settling
            parameters=new_params,
            network_scenario=self.network_scenario,
            network_config=self.network_config,
        )

    def collect_sample(self):
        """
        Collect a metric sample if not in settling period.
        Called periodically (e.g., every 100ms).
        """
        now = time.time()

        # Check if settling period ended
        if self._settling and now >= self._settling_end_time:
            self._settling = False
            # Reset metrics collector for fresh epoch data
            if self._metrics_collector:
                self._metrics_collector.reset_for_new_epoch()

        # Don't collect during settling
        if self._settling:
            return

        # Collect sample
        if self._current_epoch and self._metrics_collector:
            metrics = self._metrics_collector.get_current_metrics()
            self._current_epoch.raw_samples.append({
                "timestamp": now,
                "elapsed": now - self._current_epoch.start_time,
                **metrics,
            })

    def is_settling(self) -> bool:
        """Return True if currently in settling period."""
        return self._settling

    def finalize(self):
        """Finalize the current epoch when connection ends."""
        if self._current_epoch:
            self._current_epoch.end_time = time.time()
            self._finalize_epoch(self._current_epoch)
            self.history.add_epoch(self._current_epoch)
            self._current_epoch = None

    def _finalize_epoch(self, epoch: Epoch):
        """Calculate final metrics for an epoch from its samples."""
        if not epoch.raw_samples:
            return

        # Calculate aggregated metrics from samples
        samples = epoch.raw_samples

        throughputs = [s.get("throughput_bps", 0) for s in samples]
        rtts = [s.get("rtt", 0) for s in samples if s.get("rtt", 0) > 0]
        jitters = [s.get("jitter", 0) for s in samples]

        # Use last sample for cumulative values
        last_sample = samples[-1]
        first_sample = samples[0]

        epoch.metrics = EpochMetrics(
            throughput_bps=sum(throughputs) / len(throughputs) if throughputs else 0,
            avg_rtt_seconds=sum(rtts) / len(rtts) if rtts else 0,
            min_rtt_seconds=min(rtts) if rtts else 0,
            max_rtt_seconds=max(rtts) if rtts else 0,
            jitter_seconds=sum(jitters) / len(jitters) if jitters else 0,
            packet_loss_rate=last_sample.get("packet_loss_rate", 0),
            bytes_sent=last_sample.get("bytes_sent", 0) - first_sample.get("bytes_sent", 0),
            bytes_received=last_sample.get("bytes_received", 0) - first_sample.get("bytes_received", 0),
            packets_sent=last_sample.get("packets_sent", 0) - first_sample.get("packets_sent", 0),
            packets_lost=last_sample.get("packets_lost", 0) - first_sample.get("packets_lost", 0),
        )

    def get_history(self) -> ConnectionEpochHistory:
        """Get the complete epoch history."""
        return self.history
