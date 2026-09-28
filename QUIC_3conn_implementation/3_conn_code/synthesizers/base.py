"""
Base synthesizer module.

Provides abstract base class for all data synthesizers and a factory
for creating synthesizers by application type.

Defines `DataPacket` (the unit yielded by every synthesizer), `BaseSynthesizer`
(the interface each application model implements), and `SynthesizerFactory`.

Registry-based factory
----------------------
The factory holds a class-level `_synthesizers` mapping that starts empty and
is filled by `register()` calls made at the bottom of each synthesizer module.
Consequently the factory only knows about a type once that module has been
imported, which the package `__init__` guarantees. This indirection exists so
new application types can be added without editing the factory itself.

Connections
-----------
Imports from : standard library only (abc, dataclasses, typing)
Imported by  : .video_streaming, .file_transfer, .conference_call (each of
               which registers itself here), synthesizers/__init__.py
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional, Dict, Any


@dataclass
class DataPacket:
    """
    Represents a packet of synthesized data.

    Attributes:
        data: The raw bytes to transmit.
        size: Size of the data in bytes.
        timestamp: When the packet was generated.
        packet_type: Type identifier (e.g., "I-frame", "P-frame", "audio").
        sequence: Sequence number for ordering.
        metadata: Additional application-specific data.
    """

    data: bytes
    size: int
    timestamp: float
    packet_type: str = "data"
    sequence: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseSynthesizer(ABC):
    """
    Abstract base class for data synthesizers.

    Synthesizers generate realistic data patterns for different
    application types (video streaming, file transfer, conference calls).
    """

    def __init__(
        self,
        duration_seconds: float = 10.0,
        target_bitrate: Optional[int] = None,
    ):
        """
        Initialize the synthesizer.

        Args:
            duration_seconds: How long to generate data for.
            target_bitrate: Target bitrate in bits per second (optional).
        """
        self.duration_seconds = duration_seconds
        self.target_bitrate = target_bitrate
        self._sequence = 0

    @abstractmethod
    async def generate(self) -> AsyncIterator[DataPacket]:
        """
        Generate data packets.

        Yields:
            DataPacket objects at appropriate intervals.
        """
        pass

    def _next_sequence(self) -> int:
        """Get the next sequence number."""
        seq = self._sequence
        self._sequence += 1
        return seq

    @property
    @abstractmethod
    def application_type(self) -> str:
        """Return the application type identifier."""
        pass


class SynthesizerFactory:
    """Factory for creating synthesizers by application type."""

    # Populated at import time by register() calls in each synthesizer module,
    # rather than declared here. Keeping the mapping empty by default means the
    # factory has no compile-time knowledge of its implementations, so a new
    # application type is added purely by writing and importing its module.
    _synthesizers: Dict[str, type] = {}

    @classmethod
    def register(cls, name: str, synthesizer_class: type):
        """Register a synthesizer class."""
        cls._synthesizers[name] = synthesizer_class

    @classmethod
    def create(
        cls,
        application_type: str,
        duration_seconds: float = 10.0,
        **kwargs,
    ) -> BaseSynthesizer:
        """
        Create a synthesizer instance.

        Args:
            application_type: Type of application (video_streaming, file_transfer, conference_call).
            duration_seconds: Duration to generate data for.
            **kwargs: Additional arguments for the synthesizer.

        Returns:
            A synthesizer instance.

        Raises:
            ValueError: If application_type is not registered.
        """
        if application_type not in cls._synthesizers:
            raise ValueError(
                f"Unknown application type: {application_type}. "
                f"Available: {list(cls._synthesizers.keys())}"
            )

        return cls._synthesizers[application_type](
            duration_seconds=duration_seconds, **kwargs
        )

    @classmethod
    def available_types(cls) -> list:
        """Return list of available application types."""
        return list(cls._synthesizers.keys())
