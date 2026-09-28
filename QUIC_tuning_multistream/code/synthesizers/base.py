"""
Abstract base class and factory for traffic synthesizers.

Defines the `DataPacket` record yielded by every synthesizer, the
`BaseSynthesizer` interface that each application model implements, and the
`SynthesizerFactory` used to construct one by application-type name.

Design note: generated payloads are zero-filled rather than random. Packet
*content* has no effect on QUIC congestion control, so only the size and the
emission timing are modelled; zero-filling avoids the CPU cost of generating
megabytes of random bytes during a timing-sensitive run.

Subclasses must implement `application_type` and the async `generate()`
iterator; the factory maps the three type names onto their implementations and
raises ValueError for anything else.

Connections:
    Imports from: standard library only (abc, typing, dataclasses)
    Imported by:  .video_streaming, .file_transfer, .conference_call,
                  synthesizers/__init__.py, simulation.client
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Any, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from .video_streaming import VideoStreamingSynthesizer
    from .file_transfer import FileTransferSynthesizer
    from .conference_call import ConferenceCallSynthesizer


@dataclass
class DataPacket:
    """Represents a single data packet from a synthesizer."""

    data: bytes  # The actual bytes to send
    size: int  # Size in bytes
    timestamp: float  # When the packet was generated
    packet_type: str  # Type identifier (e.g., "I-frame", "P-frame", "audio", "chunk")
    sequence: int  # Sequence number
    metadata: Dict[str, Any] = None  # Optional additional metadata

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class BaseSynthesizer(ABC):
    """
    Abstract base class for all data synthesizers.

    Synthesizers generate traffic patterns that mimic real application
    behavior without using actual media content. QUIC doesn't care about
    the content of the data - only the size and timing patterns matter.
    """

    def __init__(self, duration_seconds: float = 10.0):
        """
        Initialize the synthesizer.

        Args:
            duration_seconds: How long to generate data for.
        """
        self.duration_seconds = duration_seconds
        self._packet_count = 0

    @property
    @abstractmethod
    def application_type(self) -> str:
        """Return the application type identifier."""
        pass

    @abstractmethod
    async def generate(self) -> AsyncIterator[DataPacket]:
        """
        Generate data packets asynchronously.

        Yields:
            DataPacket objects with synthesized data.
        """
        pass

    def reset(self):
        """Reset the synthesizer state for a new run."""
        self._packet_count = 0

    def _create_packet(
        self,
        size: int,
        timestamp: float,
        packet_type: str,
        metadata: Dict[str, Any] = None,
    ) -> DataPacket:
        """
        Create a data packet with synthesized bytes.

        Args:
            size: Size of the packet in bytes.
            timestamp: When the packet was generated.
            packet_type: Type of packet (for logging/analysis).
            metadata: Optional additional metadata.

        Returns:
            A DataPacket with random bytes of the specified size.
        """
        self._packet_count += 1
        return DataPacket(
            # Zero-filled rather than random: QUIC's congestion control reacts
            # only to packet size and timing, and generating random bytes would
            # add CPU cost inside a timing-sensitive generation loop.
            data=bytes(size),
            size=size,
            timestamp=timestamp,
            packet_type=packet_type,
            sequence=self._packet_count,
            metadata=metadata,
        )


class SynthesizerFactory:
    """Factory for creating synthesizers based on application type."""

    @staticmethod
    def create(
        application_type: str,
        duration_seconds: float = 10.0,
        **kwargs,
    ) -> BaseSynthesizer:
        """
        Create a synthesizer for the specified application type.

        Args:
            application_type: One of "video_streaming", "file_transfer", "conference_call".
            duration_seconds: Duration for data generation.
            **kwargs: Additional arguments passed to the synthesizer.

        Returns:
            An instance of the appropriate synthesizer.

        Raises:
            ValueError: If the application type is not recognized.
        """
        # Imported inside the function rather than at module scope: each
        # synthesizer module imports BaseSynthesizer from this file, so a
        # top-level import here would form an import cycle.
        from .video_streaming import VideoStreamingSynthesizer
        from .file_transfer import FileTransferSynthesizer
        from .conference_call import ConferenceCallSynthesizer

        synthesizers = {
            "video_streaming": VideoStreamingSynthesizer,
            "file_transfer": FileTransferSynthesizer,
            "conference_call": ConferenceCallSynthesizer,
        }

        if application_type not in synthesizers:
            raise ValueError(
                f"Unknown application type: {application_type}. "
                f"Valid types are: {list(synthesizers.keys())}"
            )

        return synthesizers[application_type](duration_seconds=duration_seconds, **kwargs)
