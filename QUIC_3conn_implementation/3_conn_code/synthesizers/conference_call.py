"""
Conference call synthesizer.

Generates data patterns that mimic real-time audio/video conferencing
with strict timing requirements.

Small packets are emitted at a strict, regular interval. Because the cadence is
fixed and short, irregularity in delivery is what degrades this workload, which
is why this connection is tuned for low jitter in the three-connection
experiment.

Registers itself with SynthesizerFactory under "conference_call" at import time
(see the call at the end of this module).

Connections
-----------
Imports from : .base (BaseSynthesizer, DataPacket, SynthesizerFactory)
Imported by  : synthesizers/__init__.py; constructed via SynthesizerFactory
               in simulation.worker_process
"""

import asyncio
import time
from typing import AsyncIterator

from .base import BaseSynthesizer, DataPacket, SynthesizerFactory


class ConferenceCallSynthesizer(BaseSynthesizer):
    """
    Synthesizer for conference call data.

    Generates small, frequent packets that simulate real-time
    communication (WebRTC, Zoom, Teams). This traffic is sensitive
    to latency and jitter.

    Traffic Pattern:
    - Small packets (~320 bytes for 128kbps audio)
    - Strict timing: 20ms intervals (50 packets/sec)
    - Bidirectional (requires echo from server)
    - Low latency requirements
    - Jitter-sensitive

    Audio Codec Simulation:
    - 128 kbps audio = 16,000 bytes/sec
    - 50 packets/sec = 320 bytes/packet
    """

    # Audio packet parameters
    PACKET_SIZE = 320  # bytes (128kbps / 50pps)
    PACKET_INTERVAL = 0.020  # 20ms between packets

    def __init__(
        self,
        duration_seconds: float = 10.0,
        packet_size: int = 320,
        packet_interval: float = 0.020,
    ):
        """
        Initialize conference call synthesizer.

        Args:
            duration_seconds: Duration of the call.
            packet_size: Size of each audio packet in bytes.
            packet_interval: Time between packets in seconds.
        """
        super().__init__(duration_seconds=duration_seconds)
        self.packet_size = packet_size
        self.packet_interval = packet_interval

    async def generate(self) -> AsyncIterator[DataPacket]:
        """
        Generate conference call packets.

        Yields small audio packets at precise intervals,
        simulating real-time voice communication.
        """
        start_time = time.time()
        packet_count = 0

        while (time.time() - start_time) < self.duration_seconds:
            packet_start = time.time()

            # Generate audio packet
            data = bytes(self.packet_size)

            yield DataPacket(
                data=data,
                size=self.packet_size,
                timestamp=time.time(),
                packet_type="audio",
                sequence=self._next_sequence(),
                metadata={
                    "packet_number": packet_count,
                    "codec": "opus_128kbps",
                    "realtime": True,
                },
            )

            packet_count += 1

            # Precise timing is critical for conference calls
            # Calculate exact sleep time to maintain interval
            elapsed = time.time() - packet_start
            sleep_time = max(0, self.packet_interval - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    @property
    def application_type(self) -> str:
        return "conference_call"


# Register with factory
SynthesizerFactory.register("conference_call", ConferenceCallSynthesizer)
