"""
Metrics calculation utilities.

Provides functions for calculating the 6 key performance metrics
from raw measurement data.

Stateless calculation layer: every method is pure arithmetic over values the
collector gathered, and `MetricsResult` is the container carried through IPC,
aggregation and export.

Throughput is reported twice, and the distinction matters when reading results:

    throughput        bytes the application offered to the transport
    throughput_acked  bytes the peer actually acknowledged

Under a bottleneck these diverge sharply, because offered data can sit in
buffers or be dropped. The acknowledged figure is the one that reflects real
delivery; the offered figure is retained because comparing the two reveals how
much data the link absorbed or discarded.

As in Generation 1, latency is derived as RTT/2 and so assumes a symmetric
path, and every calculation returns 0.0 for its degenerate case rather than
raising.

Connections
-----------
Imports from : standard library only (statistics, typing, dataclasses)
Imported by  : metrics/__init__.py, metrics.collector,
               simulation.worker_process
"""

import statistics
from typing import List
from dataclasses import dataclass


@dataclass
class MetricsResult:
    """Container for calculated metrics."""

    throughput: float  # bytes per second (offered/sent)
    rtt: float  # round-trip time in seconds
    latency: float  # one-way latency in seconds (estimated as RTT / 2)
    jitter: float  # jitter in seconds
    packet_loss_rate: float  # percentage (0.0 to 1.0)
    connection_establishment_time: float  # seconds

    # ACK-verified throughput metrics
    throughput_acked: float = 0.0  # bytes per second (ACK-verified delivery)
    bytes_sent: int = 0  # total bytes sent (for receiver-side matching)
    bytes_acked: int = 0  # total bytes acknowledged
    avg_cwnd: float = 0.0  # average congestion window
    avg_bytes_in_flight: float = 0.0  # average bytes in flight

    def to_dict(self) -> dict:
        """Convert to dictionary for export."""
        return {
            "throughput": self.throughput,
            "throughput_acked": self.throughput_acked,
            "rtt": self.rtt,
            "latency": self.latency,
            "jitter": self.jitter,
            "packet_loss_rate": self.packet_loss_rate,
            "connection_establishment_time": self.connection_establishment_time,
            "bytes_sent": self.bytes_sent,
            "bytes_acked": self.bytes_acked,
            "avg_cwnd": self.avg_cwnd,
            "avg_bytes_in_flight": self.avg_bytes_in_flight,
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
        expected_interval: float = None,
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

        # Calculate inter-packet delays
        delays = []
        for i in range(1, len(packet_timestamps)):
            delay = packet_timestamps[i] - packet_timestamps[i - 1]
            delays.append(delay)

        if len(delays) < 2:
            return 0.0

        # Jitter is the standard deviation of delays
        try:
            return statistics.stdev(delays)
        except statistics.StatisticsError:
            return 0.0

    @staticmethod
    def calculate_jitter_rfc3550(rtt_samples: List[float]) -> float:
        """
        Calculate RTT jitter using RFC 3550 EWMA algorithm.

        Uses the RFC 3550 exponentially-weighted moving average formula
        to smooth RTT variation. The 1/16 gain factor provides good noise
        reduction while maintaining reasonable convergence rate.

        Formula: J = J + (|D(i)| - J) / 16
        Where D(i) = RTT(i) - RTT(i-1) is the change in RTT between samples.

        Note: This measures RTT jitter (not one-way jitter) since QUIC
        uses RTT for congestion control. The EWMA smoothing factor is
        independent of one-way vs RTT measurement.

        Args:
            rtt_samples: List of RTT measurements in seconds.

        Returns:
            RTT jitter in seconds (EWMA smoothed).
        """
        if len(rtt_samples) < 2:
            return 0.0

        jitter = 0.0
        for i in range(1, len(rtt_samples)):
            # D(i) is the difference between consecutive RTT measurements
            d = abs(rtt_samples[i] - rtt_samples[i - 1])
            # RFC 3550 EWMA smoothing: J = J + (|D| - J) / 16
            jitter = jitter + (d - jitter) / 16.0

        return jitter

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

        packets_lost = packets_sent - packets_received
        if packets_lost < 0:
            packets_lost = 0

        return packets_lost / packets_sent

    @staticmethod
    def calculate_latency(rtt: float) -> float:
        """
        Calculate estimated one-way latency from RTT.

        Latency is estimated as RTT / 2, assuming a symmetric network path.

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
        bytes_acked: int = 0,
        cwnd_samples: List[int] = None,
        bytes_in_flight_samples: List[int] = None,
        packet_loss_rate: float = None,
        direct_jitter: float = None,
    ) -> MetricsResult:
        """
        Calculate all metrics.

        Args:
            total_bytes: Total bytes transferred (offered).
            duration_seconds: Duration of the transfer.
            rtt_samples: List of RTT measurements.
            packet_timestamps: List of packet receive timestamps.
            packets_sent: Number of packets sent.
            packets_received: Number of packets received.
            connection_time: Time to establish connection.
            bytes_acked: Total bytes acknowledged (for ACK-verified throughput).
            cwnd_samples: List of congestion window samples.
            bytes_in_flight_samples: List of bytes in flight samples.
            packet_loss_rate: Pre-computed packet loss rate (0.0-1.0). If provided,
                this is used instead of calculating from packets_sent/received.
                This allows for more accurate byte-based loss calculation.
            direct_jitter: Pre-computed jitter from RTTVAR (seconds). If provided,
                this is used instead of calculating from RTT samples. RTTVAR from
                aioquic provides more accurate jitter than derived calculation.

        Returns:
            MetricsResult with all calculated metrics.
        """
        if cwnd_samples is None:
            cwnd_samples = []
        if bytes_in_flight_samples is None:
            bytes_in_flight_samples = []

        # Calculate offered throughput
        throughput = MetricsCalculator.calculate_throughput(
            total_bytes, duration_seconds
        )

        # Calculate ACK-verified throughput
        throughput_acked = MetricsCalculator.calculate_throughput(
            bytes_acked, duration_seconds
        )

        # Calculate average RTT
        if rtt_samples:
            rtt = statistics.mean(rtt_samples)
        else:
            rtt = 0.0

        # Calculate latency (estimated as RTT / 2)
        latency = MetricsCalculator.calculate_latency(rtt)

        # Calculate jitter: use direct RTTVAR if available, else RFC 3550
        # Direct RTTVAR from aioquic provides actual RTT variation
        # RFC 3550 calculation from smoothed RTT samples is less accurate
        if direct_jitter is not None and direct_jitter > 0:
            jitter = direct_jitter
        else:
            jitter = MetricsCalculator.calculate_jitter_rfc3550(rtt_samples)

        # Use pre-computed packet loss rate if provided, otherwise calculate from packets
        if packet_loss_rate is None:
            packet_loss_rate = MetricsCalculator.calculate_packet_loss_rate(
                packets_sent, packets_received
            )

        # Calculate averages for cwnd and bytes_in_flight
        avg_cwnd = sum(cwnd_samples) / len(cwnd_samples) if cwnd_samples else 0.0
        avg_bytes_in_flight = (
            sum(bytes_in_flight_samples) / len(bytes_in_flight_samples)
            if bytes_in_flight_samples else 0.0
        )

        return MetricsResult(
            throughput=throughput,
            throughput_acked=throughput_acked,
            rtt=rtt,
            latency=latency,
            jitter=jitter,
            packet_loss_rate=packet_loss_rate,
            connection_establishment_time=connection_time,
            bytes_sent=total_bytes,
            bytes_acked=bytes_acked,
            avg_cwnd=avg_cwnd,
            avg_bytes_in_flight=avg_bytes_in_flight,
        )
