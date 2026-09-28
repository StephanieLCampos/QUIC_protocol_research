"""
File transfer synthesizer.

Generates data patterns that mimic bulk file transfers,
sending data as fast as the congestion window allows.

This model imposes no pacing of its own, so the QUIC congestion window is the
only thing limiting it. That property makes this connection the throughput
workload in the three-connection experiment, and also makes it the most
aggressive competitor for the shared bottleneck.

Registers itself with SynthesizerFactory under "file_transfer" at import time
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


class FileTransferSynthesizer(BaseSynthesizer):
    """
    Synthesizer for file transfer data.

    Generates continuous data chunks that simulate bulk file transfers.
    This pattern sends data as fast as possible, limited only by the
    QUIC congestion window.

    Traffic Pattern:
    - Large chunks (64KB default)
    - No timing delays between chunks
    - Simulates FTP/SFTP/HTTP file downloads
    - Throughput-hungry, fills available bandwidth
    """

    CHUNK_SIZE = 65_536  # 64 KB chunks

    def __init__(
        self,
        duration_seconds: float = 10.0,
        chunk_size: int = 65_536,
    ):
        """
        Initialize file transfer synthesizer.

        Args:
            duration_seconds: Duration to keep transferring data.
            chunk_size: Size of each data chunk in bytes.
        """
        super().__init__(duration_seconds=duration_seconds)
        self.chunk_size = chunk_size

    async def generate(self) -> AsyncIterator[DataPacket]:
        """
        Generate file transfer packets.

        Yields large chunks continuously without delays, simulating
        bulk data transfer that utilizes full bandwidth. Continues
        for the entire simulation duration.
        """
        start_time = time.time()
        bytes_sent = 0
        chunk_number = 0

        # Continuously transfer data for the full duration
        while (time.time() - start_time) < self.duration_seconds:
            # Generate chunk data
            data = bytes(self.chunk_size)

            yield DataPacket(
                data=data,
                size=self.chunk_size,
                timestamp=time.time(),
                packet_type="file_chunk",
                sequence=self._next_sequence(),
                metadata={
                    "chunk_number": chunk_number,
                    "bytes_sent": bytes_sent,
                },
            )

            bytes_sent += self.chunk_size
            chunk_number += 1

            # Yield control to event loop without delay
            # This allows sending as fast as congestion window permits
            await asyncio.sleep(0)

    @property
    def application_type(self) -> str:
        return "file_transfer"


# Register with factory
SynthesizerFactory.register("file_transfer", FileTransferSynthesizer)
