"""
Real-time metrics collection during a QUIC simulation.

`MetricsCollector` is attached to a live connection and records events as they
happen (packets sent and received, RTT samples, handshake completion), then
hands the accumulated data to MetricsCalculator when the run ends.

Important implementation note: aioquic exposes no public API for loss and RTT
statistics, so this collector reads the connection's private recovery state
(`_loss`, and its `_rtt_smoothed`, `_packets_lost` and `_packets_sent` fields).
Every such access is wrapped in getattr with a default and guarded by
try/except, so that an aioquic version change degrades the affected metric to
zero rather than crashing a sweep in progress. This is the main place the
project is coupled to a specific aioquic internal layout.

Connections:
    Imports from: .calculator (MetricsCalculator, MetricsResult)
    Imported by:  metrics/__init__.py, simulation.client, simulation.runner
    Reads from:   aioquic connection internals (private recovery state)
"""

import time
from typing import List, Optional, Any
from dataclasses import dataclass, field

from .calculator import MetricsCalculator, MetricsResult


@dataclass
class MetricsCollector:
    """
    Collects metrics during simulation execution.

    This class is used to record events during a QUIC simulation
    and then calculate the 5 performance metrics:
    - Throughput
    - RTT
    - Jitter
    - Packet Loss Rate
    - Connection Establishment Time
    """

    # Connection reference (for accessing internal metrics)
    connection: Any = None

    # Timing
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    connection_ready_time: Optional[float] = None

    # Byte counters
    bytes_sent: int = 0
    bytes_received: int = 0

    # Packet counters
    packets_sent: int = 0
    packets_received: int = 0
    packets_lost: int = 0

    # Timestamps for jitter calculation
    send_timestamps: List[float] = field(default_factory=list)
    receive_timestamps: List[float] = field(default_factory=list)

    # RTT samples
    rtt_samples: List[float] = field(default_factory=list)

    def start(self):
        """Mark the start of the simulation."""
        self.start_time = time.time()

    def stop(self):
        """Mark the end of the simulation."""
        self.end_time = time.time()

    def record_connection_ready(self):
        """Record when the connection is ready (handshake complete)."""
        self.connection_ready_time = time.time()

    def record_packet_sent(self, size: int):
        """
        Record a sent packet.

        Args:
            size: Size of the packet in bytes.
        """
        self.packets_sent += 1
        self.bytes_sent += size
        self.send_timestamps.append(time.time())

    def record_packet_received(self, size: int = 0):
        """
        Record a received packet (acknowledgment).

        Args:
            size: Size of the packet in bytes (optional).
        """
        self.packets_received += 1
        self.bytes_received += size
        self.receive_timestamps.append(time.time())

    def record_packet_lost(self):
        """Record a lost packet."""
        self.packets_lost += 1

    def record_rtt_sample(self, rtt: float):
        """
        Record an RTT measurement.

        Args:
            rtt: RTT value in seconds.
        """
        self.rtt_samples.append(rtt)

    def sample_connection_rtt(self):
        """
        Sample RTT from the QUIC connection if available.

        This accesses the internal RTT tracking in aioquic.
        """
        if self.connection is not None:
            try:
                # aioquic keeps smoothed RTT on its private recovery object and
                # offers no public accessor, so this reaches into _loss directly.
                # Guarded throughout: a version change degrades RTT to zero
                # rather than raising mid-run.
                loss_handler = getattr(self.connection, "_loss", None)
                if loss_handler is not None:
                    rtt = getattr(loss_handler, "_rtt_smoothed", None)
                    if rtt is not None and rtt > 0:
                        self.rtt_samples.append(rtt)
            except (AttributeError, TypeError):
                # No usable RTT state on this connection; leave the sample list
                # untouched so the run still reports its other metrics.
                pass

    @property
    def duration(self) -> float:
        """Get the simulation duration in seconds."""
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time else time.time()
        return end - self.start_time

    @property
    def connection_time(self) -> float:
        """Get the connection establishment time in seconds."""
        if self.start_time is None or self.connection_ready_time is None:
            return 0.0
        return self.connection_ready_time - self.start_time

    def calculate_metrics(self) -> MetricsResult:
        """
        Calculate all 5 metrics from collected data.

        Returns:
            MetricsResult with all calculated metrics.
        """
        # Prefer aioquic's own sent/lost counters over the locally incremented
        # ones. The local counters track application-level writes, whereas
        # aioquic counts actual QUIC packets after coalescing and
        # retransmission, which is the figure a loss rate should be based on.
        actual_packets_sent = self.packets_sent
        actual_packets_lost = 0

        if self.connection is not None:
            try:
                loss_handler = getattr(self.connection, "_loss", None)
                if loss_handler is not None:
                    # Get packets lost from aioquic's internal tracking
                    actual_packets_lost = getattr(loss_handler, "_packets_lost", 0)
                    # Use aioquic's sent count if available
                    sent_count = getattr(loss_handler, "_packets_sent", 0)
                    if sent_count > 0:
                        actual_packets_sent = sent_count
            except (AttributeError, TypeError):
                pass

        # Received is inferred rather than observed: the sender never sees a
        # receive count directly, so anything sent and not reported lost is
        # treated as delivered.
        actual_packets_received = max(0, actual_packets_sent - actual_packets_lost)

        return MetricsCalculator.calculate_all(
            total_bytes=self.bytes_sent,
            duration_seconds=self.duration,
            rtt_samples=self.rtt_samples,
            # Prefer receive timestamps for jitter; fall back to send
            # timestamps for send-only workloads (such as file transfer, where
            # nothing is echoed back) so jitter is still reported.
            packet_timestamps=self.receive_timestamps or self.send_timestamps,
            packets_sent=actual_packets_sent,
            packets_received=actual_packets_received,
            connection_time=self.connection_time,
        )

    def reset(self):
        """Reset all collected data for a new simulation."""
        self.start_time = None
        self.end_time = None
        self.connection_ready_time = None
        self.bytes_sent = 0
        self.bytes_received = 0
        self.packets_sent = 0
        self.packets_received = 0
        self.packets_lost = 0
        self.send_timestamps = []
        self.receive_timestamps = []
        self.rtt_samples = []

    def get_summary(self) -> dict:
        """
        Get a summary of collected data.

        Returns:
            Dictionary with collection summary.
        """
        return {
            "duration_seconds": self.duration,
            "connection_time_seconds": self.connection_time,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "packets_sent": self.packets_sent,
            "packets_received": self.packets_received,
            "packets_lost": self.packets_lost,
            "rtt_samples_count": len(self.rtt_samples),
        }
