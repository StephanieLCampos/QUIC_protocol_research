"""
File transfer data synthesizer.

Generates bulk file transfer data with fixed-size chunks,
sent as fast as possible without timing delays.
"""

import time
from typing import AsyncIterator

from .base import BaseSynthesizer, DataPacket


class FileTransferSynthesizer(BaseSynthesizer):
    """
    Generates bulk file transfer data.

    Characteristics:
    - 64KB chunks (configurable)
    - No timing delay (send as fast as possible)
    - Configurable total size

    Unlike video streaming, file transfer has no timing constraints.
    Data is generated and sent as quickly as the congestion window allows.
    """

    def __init__(
        self,
        duration_seconds: float = 10.0,
        chunk_size: int = 65536,
        total_size: int = 10_000_000,
    ):
        """
        Initialize the file transfer synthesizer.

        Args:
            duration_seconds: Not used for file transfer (included for interface compatibility).
            chunk_size: Size of each chunk in bytes (default: 65536 = 64KB).
            total_size: Total file size in bytes (default: 10_000_000 = 10MB).
        """
        super().__init__(duration_seconds)
        self.chunk_size = chunk_size
        self.total_size = total_size

    @property
    def application_type(self) -> str:
        """Return the application type identifier."""
        return "file_transfer"

    async def generate(self) -> AsyncIterator[DataPacket]:
        """
        Generate file chunks asynchronously.

        Generates chunks as fast as possible until the total file size
        is reached. No timing delays are introduced - the speed is
        limited only by the QUIC congestion window.

        Yields:
            DataPacket objects representing file chunks.
        """
        self.reset()
        bytes_sent = 0
        chunk_number = 0
        start_time = time.time()

        while bytes_sent < self.total_size:
            # Calculate chunk size (last chunk may be smaller)
            remaining = self.total_size - bytes_sent
            current_chunk_size = min(self.chunk_size, remaining)

            # Create and yield the packet
            packet = self._create_packet(
                size=current_chunk_size,
                timestamp=time.time(),
                packet_type="chunk",
                metadata={
                    "chunk_number": chunk_number,
                    "offset": bytes_sent,
                    "total_size": self.total_size,
                    "is_last_chunk": bytes_sent + current_chunk_size >= self.total_size,
                },
            )
            yield packet

            bytes_sent += current_chunk_size
            chunk_number += 1

            # No delay - yield control but continue immediately
            # This allows other async tasks to run but doesn't slow down transfer
            # In practice, the QUIC congestion window will be the limiting factor

    def get_stats(self) -> dict:
        """
        Get statistics about the synthesizer configuration.

        Returns:
            Dictionary with configuration statistics.
        """
        num_chunks = (self.total_size + self.chunk_size - 1) // self.chunk_size

        return {
            "total_size_bytes": self.total_size,
            "total_size_mb": self.total_size / 1_000_000,
            "chunk_size_bytes": self.chunk_size,
            "chunk_size_kb": self.chunk_size / 1024,
            "num_chunks": num_chunks,
        }
