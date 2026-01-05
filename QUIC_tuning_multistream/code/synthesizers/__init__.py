"""
Data synthesizers for QUIC Multi-Stream Research Project.

This module provides synthesizers that generate traffic patterns
for different application types (video streaming, file transfer,
conference calls).
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
