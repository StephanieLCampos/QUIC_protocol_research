"""
Metrics collector for real-time data collection during simulations.

Collects raw data during QUIC simulations and provides methods
to retrieve calculated metrics.

One collector lives inside each worker process, accumulating events for that
connection alone: packets sent, RTT and RTTVAR samples, congestion-window and
bytes-in-flight samples, and handshake timing.

Reading aioquic internals
-------------------------
aioquic publishes no API for RTT, congestion window or loss, so this collector
reads its private recovery object (`_loss`, and fields such as
`_rtt_smoothed`, `_rtt_latest`, `_rtt_variance`, `congestion_window`,
`bytes_in_flight`). Every access is guarded, so an aioquic version change
degrades the affected metric to zero rather than failing a run in progress.
This is the main point of coupling to a specific aioquic internal layout.

Delta throughput
----------------
`get_throughput_acked_delta` reports the rate over the window since it was last
called, rather than a cumulative average. This matters for the Q-learning
agents: a cumulative figure becomes steadily less sensitive as a run lengthens,
so a parameter change late in a long run would barely move it and the learning
signal would vanish. The delta figure stays responsive throughout.

Jitter is derived from aioquic's RTTVAR (RFC 6298) rather than computed from
consecutive smoothed-RTT samples, since smoothing deliberately suppresses
exactly the variation jitter is meant to capture.

Connections
-----------
Imports from : .calculator (MetricsCalculator, MetricsResult)
Imported by  : metrics/__init__.py, simulation.worker_process
Reads from   : aioquic connection internals (private recovery state)
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
    and then calculate the 6 performance metrics:
    - Throughput
    - RTT
    - Latency
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
    bytes_lost: int = 0  # Bytes lost (from CC if available)

    # Timestamps for jitter calculation
    send_timestamps: List[float] = field(default_factory=list)
    receive_timestamps: List[float] = field(default_factory=list)

    # RTT samples
    rtt_samples: List[float] = field(default_factory=list)

    # Direct RTTVAR samples from aioquic (for accurate jitter)
    rtt_variance_samples: List[float] = field(default_factory=list)

    # ACK-verified throughput tracking
    bytes_acked: int = 0
    cwnd_samples: List[int] = field(default_factory=list)
    bytes_in_flight_samples: List[int] = field(default_factory=list)

    # Internal state for epoch reset
    _epoch_bytes_offset: int = 0
    _epoch_packets_offset: int = 0

    # Delta tracking for per-epoch throughput (responsive to changes)
    _prev_bytes_acked: int = 0
    _prev_delta_time: Optional[float] = None
    _last_delta_throughput: float = 0.0

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

    def record_rtt_variance(self, rttvar: float):
        """
        Record RTTVAR measurement directly from aioquic.

        RTTVAR (RFC 6298) represents actual RTT variation, providing
        a direct measure of jitter without needing to calculate it
        from consecutive smoothed RTT samples.

        Args:
            rttvar: RTTVAR value in seconds.
        """
        if rttvar > 0:
            self.rtt_variance_samples.append(rttvar)

    def sample_connection_rtt(self):
        """
        Sample RTT from the QUIC connection if available.

        This accesses the internal RTT tracking in aioquic.
        """
        if self.connection is not None:
            try:
                # Access aioquic internal RTT metrics
                loss_handler = getattr(self.connection, "_loss", None)
                if loss_handler is not None:
                    rtt = getattr(loss_handler, "_rtt_smoothed", None)
                    if rtt is not None and rtt > 0:
                        self.rtt_samples.append(rtt)
            except (AttributeError, TypeError):
                pass  # Connection doesn't have RTT info

    def sample_network_metrics(self):
        """
        Sample network-level metrics from aioquic for ACK-verified throughput.

        This accesses:
        - congestion_window: Current cwnd
        - bytes_in_flight: Bytes sent but not yet ACKed

        bytes_acked = bytes_sent - bytes_in_flight
        """
        if self.connection is not None:
            try:
                loss_handler = getattr(self.connection, "_loss", None)
                if loss_handler is not None:
                    # Sample cwnd and bytes_in_flight
                    cwnd = getattr(loss_handler, "congestion_window", 0)
                    bytes_in_flight = getattr(loss_handler, "bytes_in_flight", 0)

                    if cwnd > 0:
                        self.cwnd_samples.append(cwnd)
                    if bytes_in_flight >= 0:
                        self.bytes_in_flight_samples.append(bytes_in_flight)

                    # Compute bytes acknowledged
                    # bytes_acked = bytes_sent - bytes_in_flight
                    current_acked = self.bytes_sent - bytes_in_flight
                    if current_acked > self.bytes_acked:
                        self.bytes_acked = current_acked
            except (AttributeError, TypeError):
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
        Calculate all 6 metrics from collected data.

        Returns:
            MetricsResult with all calculated metrics.
        """
        # Calculate packet loss rate using best available method:
        # 1. If packets_lost counter available from CC, use that
        # 2. If bytes_lost available, use that
        # 3. Estimate from cwnd reductions (indicates loss events)

        packet_loss_rate = 0.0

        if self.packets_lost > 0 and self.packets_sent > 0:
            # Method 1: Direct packet loss counter (most accurate if available)
            packet_loss_rate = self.packets_lost / self.packets_sent

        elif self.bytes_lost > 0 and self.bytes_sent > 0:
            # Method 2: Bytes lost ratio
            packet_loss_rate = self.bytes_lost / self.bytes_sent

        elif len(self.cwnd_samples) > 10 and self.duration > 1.0:
            # Method 3: Estimate from cwnd reductions
            # When loss occurs, CUBIC reduces cwnd. Count significant drops.
            # A drop of >15% from recent max indicates a loss event (more sensitive).
            loss_events = 0
            recent_max = self.cwnd_samples[0]
            min_samples_between_events = 5  # Avoid counting same event twice

            i = 0
            while i < len(self.cwnd_samples):
                cwnd = self.cwnd_samples[i]
                if cwnd > recent_max:
                    recent_max = cwnd
                elif cwnd < recent_max * 0.85:  # 15% drop indicates loss
                    loss_events += 1
                    recent_max = cwnd  # Reset after loss event
                    i += min_samples_between_events  # Skip ahead to avoid double-counting
                    continue
                i += 1

            # Estimate loss rate from loss events
            if self.packets_sent > 0 and loss_events > 0:
                avg_cwnd = sum(self.cwnd_samples) / len(self.cwnd_samples)
                # Estimate: each loss event loses ~2-3 packets
                estimated_total_lost = loss_events * 2.5
                packet_loss_rate = min(0.5, estimated_total_lost / self.packets_sent)

        # Method 4: Estimate from bytes_sent vs bytes_acked difference
        # If bytes_sent >> bytes_acked over time, some packets were lost
        if packet_loss_rate == 0.0 and self.bytes_sent > 0 and self.bytes_acked > 0 and self.duration > 5.0:
            # Expected: bytes_acked should be close to bytes_sent (minus in-flight)
            avg_in_flight = (sum(self.bytes_in_flight_samples) / len(self.bytes_in_flight_samples)
                            if self.bytes_in_flight_samples else 0)
            expected_acked = max(0, self.bytes_sent - avg_in_flight)
            if expected_acked > 0:
                ack_ratio = self.bytes_acked / expected_acked
                # If ack ratio is significantly less than 1, packets were lost
                if ack_ratio < 0.98:  # >2% difference suggests loss
                    packet_loss_rate = min(0.5, 1.0 - ack_ratio)

        # Calculate jitter: prefer direct RTTVAR from aioquic if available
        # RTTVAR is the actual RTT variation measured by QUIC, which is
        # more reliable than calculating from consecutive smoothed RTT samples
        direct_jitter = None
        if self.rtt_variance_samples:
            # Use mean of recent RTTVAR samples as jitter
            import statistics
            direct_jitter = statistics.mean(self.rtt_variance_samples[-20:])

        return MetricsCalculator.calculate_all(
            total_bytes=self.bytes_sent,
            duration_seconds=self.duration,
            rtt_samples=self.rtt_samples,
            packet_timestamps=self.receive_timestamps or self.send_timestamps,
            packets_sent=self.packets_sent,
            packets_received=self.packets_sent,  # Not used when loss_rate provided
            connection_time=self.connection_time,
            bytes_acked=self.bytes_acked,
            cwnd_samples=self.cwnd_samples,
            bytes_in_flight_samples=self.bytes_in_flight_samples,
            packet_loss_rate=packet_loss_rate,
            direct_jitter=direct_jitter,
        )

    def get_throughput_acked_delta(self) -> float:
        """
        Calculate throughput for the current measurement window only.

        Returns bytes/second for the period since last call, not cumulative average.
        This is useful for Q-learning under varying network conditions where
        responsiveness to changes matters more than long-term averaging.
        """
        now = time.time()

        # First call - initialize and return 0
        if self._prev_delta_time is None:
            self._prev_delta_time = now
            self._prev_bytes_acked = self.bytes_acked
            return 0.0

        elapsed = now - self._prev_delta_time

        # Avoid division by zero and too-frequent calls
        if elapsed < 0.05:  # Minimum 50ms between delta calculations
            return self._last_delta_throughput

        # Calculate delta
        delta_bytes = self.bytes_acked - self._prev_bytes_acked
        delta_throughput = delta_bytes / elapsed if elapsed > 0 else 0.0

        # Update tracking for next call
        self._prev_bytes_acked = self.bytes_acked
        self._prev_delta_time = now
        self._last_delta_throughput = delta_throughput

        return delta_throughput

    def reset_delta_tracking(self):
        """Reset delta tracking (call at epoch boundaries if needed)."""
        self._prev_bytes_acked = self.bytes_acked
        self._prev_delta_time = time.time()
        self._last_delta_throughput = 0.0

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
        self.bytes_lost = 0
        self.send_timestamps = []
        self.receive_timestamps = []
        self.rtt_samples = []
        self.rtt_variance_samples = []
        # ACK-verified throughput fields
        self.bytes_acked = 0
        self.cwnd_samples = []
        self.bytes_in_flight_samples = []
        # Delta tracking fields
        self._prev_bytes_acked = 0
        self._prev_delta_time = None
        self._last_delta_throughput = 0.0

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
            "bytes_acked": self.bytes_acked,
            "bytes_received": self.bytes_received,
            "packets_sent": self.packets_sent,
            "packets_received": self.packets_received,
            "packets_lost": self.packets_lost,
            "rtt_samples_count": len(self.rtt_samples),
            "cwnd_samples_count": len(self.cwnd_samples),
        }

    def get_current_metrics(self) -> dict:
        """
        Get current metrics as a raw dictionary for epoch sampling.

        Field names match what EpochManager._finalize_epoch() expects.

        Returns:
            Dictionary with current metric values.
        """
        metrics = self.calculate_metrics()

        # Calculate ACK-verified throughput
        throughput_acked = self.bytes_acked / self.duration if self.duration > 0 else 0.0

        # Calculate average cwnd and bytes_in_flight
        avg_cwnd = sum(self.cwnd_samples) / len(self.cwnd_samples) if self.cwnd_samples else 0.0
        avg_bytes_in_flight = (
            sum(self.bytes_in_flight_samples) / len(self.bytes_in_flight_samples)
            if self.bytes_in_flight_samples else 0.0
        )

        return {
            "throughput_bps": metrics.throughput,  # Offered throughput (bytes/sec)
            "throughput_acked_bps": throughput_acked,  # ACK-verified throughput (bytes/sec)
            "rtt": metrics.rtt,
            "latency": metrics.latency,
            "jitter": metrics.jitter,
            "packet_loss_rate": metrics.packet_loss_rate,
            "bytes_sent": self.bytes_sent,
            "bytes_acked": self.bytes_acked,
            "packets_sent": self.packets_sent,
            "avg_cwnd": avg_cwnd,
            "avg_bytes_in_flight": avg_bytes_in_flight,
        }

    def reset_for_new_epoch(self):
        """
        Soft reset for new epoch measurement.

        Unlike reset() which clears everything, this preserves the connection
        and timing info but resets counters for fresh epoch measurement.
        """
        # Store cumulative values before reset
        self._epoch_bytes_offset = self.bytes_sent
        self._epoch_packets_offset = self.packets_sent

        # Keep recent RTT samples for jitter calculation (need consecutive samples)
        # Jitter requires at least 2 samples, keep last 20 for smooth calculation
        self.rtt_samples = self.rtt_samples[-20:] if self.rtt_samples else []

        # Keep recent RTTVAR samples for direct jitter measurement
        self.rtt_variance_samples = self.rtt_variance_samples[-20:] if self.rtt_variance_samples else []

        # Keep send/receive timestamps for jitter calculation fresh
        self.send_timestamps = self.send_timestamps[-10:] if self.send_timestamps else []
        self.receive_timestamps = self.receive_timestamps[-10:] if self.receive_timestamps else []

        # Keep recent cwnd/bytes_in_flight samples for continuity
        self.cwnd_samples = self.cwnd_samples[-10:] if self.cwnd_samples else []
        self.bytes_in_flight_samples = self.bytes_in_flight_samples[-10:] if self.bytes_in_flight_samples else []

        # Reset delta tracking for fresh epoch measurement
        # Keep current bytes_acked as the baseline for next delta
        self._prev_bytes_acked = self.bytes_acked
        self._prev_delta_time = time.time()
        self._last_delta_throughput = 0.0
