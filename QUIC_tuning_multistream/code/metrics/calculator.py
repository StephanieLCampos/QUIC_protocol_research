"""
Metric calculations for QUIC simulation runs.

Reduces the raw event data gathered by MetricsCollector into the six reported
performance metrics, and defines the `MetricsResult` container that carries
them through export and analysis.

The six metrics:
    1. throughput                       bytes per second
    2. rtt                              mean round-trip time, seconds
    3. latency                          one-way latency, estimated as RTT / 2
    4. jitter                           stdev of inter-packet delay, seconds
    5. packet_loss_rate                 fraction lost, 0.0 to 1.0
    6. connection_establishment_time    handshake duration, seconds

Two measurement caveats worth noting when reading results. Latency is derived
from RTT rather than measured directly, which assumes a symmetric path; on the
deliberately asymmetric bottleneck scenarios that assumption does not hold.
Jitter is the standard deviation of inter-arrival gaps, so it reflects
irregularity of delivery rather than deviation from any nominal interval.

Every calculation guards its degenerate case (zero duration, fewer than two
samples, zero packets sent) by returning 0.0 rather than raising, so that a
failed or empty run still produces a well-formed row instead of aborting a
long sweep.

Connections:
    Imports from: standard library only (statistics, typing, dataclasses)
    Imported by:  metrics.collector, metrics.exporter, simulation.runner
"""

import statistics
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class MetricsResult:
    """Container for calculated metrics."""

    throughput: float  # bytes per second
    rtt: float  # round-trip time in seconds
    latency: float  # one-way latency in seconds (estimated as RTT / 2)
    jitter: float  # jitter in seconds
    packet_loss_rate: float  # percentage (0.0 to 1.0)
    connection_establishment_time: float  # seconds

    def to_dict(self) -> dict:
        """Convert to dictionary for export."""
        return {
            "throughput": self.throughput,
            "rtt": self.rtt,
            "latency": self.latency,
            "jitter": self.jitter,
            "packet_loss_rate": self.packet_loss_rate,
            "connection_establishment_time": self.connection_establishment_time,
        }


class MetricsCalculator:
    """
    Calculates performance metrics from raw data.

    The 6 metrics are:
    1. Throughput: Data transfer rate (bytes/second)
    2. RTT: Round-trip time (seconds)
    3. Latency: One-way latency estimated as RTT/2 (seconds)
    4. Jitter: Variation in packet delay (seconds)
    5. Packet Loss Rate: Percentage of lost packets
    6. Connection Establishment Time: Time for initial handshake
    """

    @staticmethod
    def calculate_throughput(
        total_bytes: int,
        duration_seconds: float,
    ) -> float:
        """
        Calculate throughput in bytes per second.

        Args:
            total_bytes: Total bytes transferred.
            duration_seconds: Duration of the transfer.

        Returns:
            Throughput in bytes per second.
        """
        if duration_seconds <= 0:
            return 0.0
        return total_bytes / duration_seconds

    @staticmethod
    def calculate_jitter(
        packet_timestamps: List[float],
        expected_interval: Optional[float] = None,
    ) -> float:
        """
        Calculate jitter (variation in inter-packet delay).

        Jitter is calculated as the standard deviation of the
        inter-packet delays. For applications like conference calls,
        low jitter is critical for quality.

        Args:
            packet_timestamps: List of packet receive timestamps.
            expected_interval: Optional expected interval between packets.

        Returns:
            Jitter in seconds (standard deviation of delays).
        """
        if len(packet_timestamps) < 2:
            return 0.0

        # Jitter here is the spread of the gaps between consecutive packets,
        # not deviation from a nominal interval. A stream that is uniformly
        # late but perfectly regular therefore scores near-zero jitter, which
        # is the intended behaviour: steady pacing is what the conference-call
        # workload cares about.
        delays = []
        for i in range(1, len(packet_timestamps)):
            delay = packet_timestamps[i] - packet_timestamps[i - 1]
            delays.append(delay)

        if len(delays) < 2:
            return 0.0

        # stdev needs at least two data points; the guard above covers that,
        # but StatisticsError is still caught so that a degenerate sample set
        # yields 0.0 instead of aborting an in-progress sweep.
        try:
            return statistics.stdev(delays)
        except statistics.StatisticsError:
            return 0.0

    @staticmethod
    def calculate_packet_loss_rate(
        packets_sent: int,
        packets_received: int,
    ) -> float:
        """
        Calculate packet loss rate.

        Args:
            packets_sent: Number of packets sent.
            packets_received: Number of packets received (acknowledged).

        Returns:
            Packet loss rate as a fraction (0.0 to 1.0).
        """
        if packets_sent <= 0:
            return 0.0

        # Clamp at zero: the sent and received counts come from different
        # sources (local counter vs. aioquic's recovery state) and can briefly
        # disagree, which would otherwise yield a negative loss rate.
        packets_lost = packets_sent - packets_received
        if packets_lost < 0:
            packets_lost = 0

        return packets_lost / packets_sent

    @staticmethod
    def calculate_latency(rtt: float) -> float:
        """
        Calculate estimated one-way latency from RTT.

        Latency is estimated as RTT / 2, assuming a symmetric network path.
        This is a reasonable approximation for localhost testing and symmetric
        networks. For asymmetric networks, actual one-way latency may differ.

        Note: This measures pure network/QUIC latency. Real-world application
        latency would include processing overhead (encoding, decoding, etc.)
        which is negligible with synthetic data but significant (~5-20ms) with
        real data.

        Args:
            rtt: Round-trip time in seconds.

        Returns:
            Estimated one-way latency in seconds.
        """
        if rtt <= 0:
            return 0.0
        return rtt / 2

    @staticmethod
    def calculate_all(
        total_bytes: int,
        duration_seconds: float,
        rtt_samples: List[float],
        packet_timestamps: List[float],
        packets_sent: int,
        packets_received: int,
        connection_time: float,
    ) -> MetricsResult:
        """
        Calculate all 6 metrics.

        Args:
            total_bytes: Total bytes transferred.
            duration_seconds: Duration of the transfer.
            rtt_samples: List of RTT measurements.
            packet_timestamps: List of packet receive timestamps.
            packets_sent: Number of packets sent.
            packets_received: Number of packets received.
            connection_time: Time to establish connection.

        Returns:
            MetricsResult with all calculated metrics.
        """
        # Calculate throughput
        throughput = MetricsCalculator.calculate_throughput(
            total_bytes, duration_seconds
        )

        # Calculate average RTT
        if rtt_samples:
            rtt = statistics.mean(rtt_samples)
        else:
            rtt = 0.0

        # Calculate latency (estimated as RTT / 2)
        latency = MetricsCalculator.calculate_latency(rtt)

        # Calculate jitter
        jitter = MetricsCalculator.calculate_jitter(packet_timestamps)

        # Calculate packet loss rate
        packet_loss_rate = MetricsCalculator.calculate_packet_loss_rate(
            packets_sent, packets_received
        )

        return MetricsResult(
            throughput=throughput,
            rtt=rtt,
            latency=latency,
            jitter=jitter,
            packet_loss_rate=packet_loss_rate,
            connection_establishment_time=connection_time,
        )
