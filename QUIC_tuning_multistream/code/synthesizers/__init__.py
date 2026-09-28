"""
Traffic synthesizer package for the QUIC Multi-Stream Research Project.

Provides the three application traffic models used as simulation workloads,
plus the abstract base class and factory that select between them.

Each synthesizer reproduces the *size and timing* profile of a real
application without carrying real media content, which is sufficient because
QUIC's congestion control responds only to packet sizes and arrival timing.

Connections:
    Imports from: .base, .video_streaming, .file_transfer, .conference_call
    Imported by:  simulation.runner, simulation.client
"""

from .base import BaseSynthesizer, SynthesizerFactory
from .video_streaming import VideoStreamingSynthesizer
from .file_transfer import FileTransferSynthesizer
from .conference_call import ConferenceCallSynthesizer

__all__ = [
    "BaseSynthesizer",
    "SynthesizerFactory",
    "VideoStreamingSynthesizer",
    "FileTransferSynthesizer",
    "ConferenceCallSynthesizer",
]
