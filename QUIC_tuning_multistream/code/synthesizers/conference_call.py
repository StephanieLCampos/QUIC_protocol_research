"""
Conference call traffic synthesizer.

Generates constant-bitrate VoIP-like audio traffic: small packets emitted at a
strict, regular interval for the duration of the run.

Packet size is derived from the target bitrate and the interval rather than
hard-coded, so changing either keeps the stream at the requested bitrate.
Because the emission interval is fixed and short, deviation in delivery timing
is the metric that matters here, which makes this the workload used to evaluate
the jitter dimension of a parameter set. As with the video synthesizer, pacing
is computed against absolute elapsed time to prevent drift.

Connections:
    Imports from: .base (BaseSynthesizer, DataPacket)
    Imported by:  synthesizers/__init__.py, SynthesizerFactory
"""

import asyncio
import time
from typing import AsyncIterator

from .base import BaseSynthesizer, DataPacket


class ConferenceCallSynthesizer(BaseSynthesizer):
    """
    Generates bidirectional audio-like packets.

    Characteristics:
    - 20ms packet intervals (50 packets/second)
    - ~320 bytes per packet (128kbps audio)
    - Designed for bidirectional communication (low jitter critical)

    This synthesizer mimics VoIP audio patterns where small packets
    are sent at very regular intervals. Jitter (variation in packet
    timing) is the most critical metric for this application type.
    """

    def __init__(
        self,
        duration_seconds: float = 10.0,
        packet_interval_ms: int = 20,
        bitrate_kbps: int = 128,
    ):
        """
        Initialize the conference call synthesizer.

        Args:
            duration_seconds: Duration of audio stream to generate.
            packet_interval_ms: Interval between packets in milliseconds (default: 20).
            bitrate_kbps: Audio bitrate in kilobits per second (default: 128).
        """
        super().__init__(duration_seconds)
        self.packet_interval_ms = packet_interval_ms
        self.packet_interval = packet_interval_ms / 1000.0  # Convert to seconds
        self.bitrate_kbps = bitrate_kbps

        # Derive packet size from bitrate and interval so that changing either
        # keeps the stream at the requested constant bitrate.
        #   bits_per_second * interval_seconds / 8 = bytes_per_packet
        #   128 kbps at 20ms -> 128000 * 0.020 / 8 = 320 bytes
        self.packet_size = int(bitrate_kbps * 1000 * self.packet_interval / 8)

    @property
    def application_type(self) -> str:
        """Return the application type identifier."""
        return "conference_call"

    async def generate(self) -> AsyncIterator[DataPacket]:
        """
        Generate audio packets asynchronously.

        Yields packets at the configured interval (default: every 20ms),
        simulating a constant bitrate audio stream.

        Yields:
            DataPacket objects representing audio packets.
        """
        self.reset()
        start_time = time.time()
        packet_number = 0
        total_packets = int(self.duration_seconds / self.packet_interval)

        while packet_number < total_packets:
            current_time = time.time()

            # Create and yield the packet
            packet = self._create_packet(
                size=self.packet_size,
                timestamp=current_time,
                packet_type="audio",
                metadata={
                    "packet_number": packet_number,
                    "interval_ms": self.packet_interval_ms,
                    "bitrate_kbps": self.bitrate_kbps,
                },
            )
            yield packet

            packet_number += 1

            # Pace to the next packet boundary against absolute elapsed time.
            # Regularity is the whole point of this workload, since jitter is
            # the metric it exists to measure, so drift must not accumulate.
            elapsed = time.time() - start_time
            expected_time = packet_number * self.packet_interval
            sleep_time = expected_time - elapsed

            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    def get_stats(self) -> dict:
        """
        Get statistics about the synthesizer configuration.

        Returns:
            Dictionary with configuration statistics.
        """
        total_packets = int(self.duration_seconds / self.packet_interval)
        packets_per_second = 1000 / self.packet_interval_ms
        total_bytes = total_packets * self.packet_size

        return {
            "packet_interval_ms": self.packet_interval_ms,
            "packet_size_bytes": self.packet_size,
            "packets_per_second": packets_per_second,
            "total_packets": total_packets,
            "total_bytes": total_bytes,
            "bitrate_kbps": self.bitrate_kbps,
            "duration_seconds": self.duration_seconds,
        }
