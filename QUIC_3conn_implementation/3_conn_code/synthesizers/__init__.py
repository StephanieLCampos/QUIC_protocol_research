"""
Synthesizers package.

Provides data generators for different application types:
- Video streaming: I-frames and P-frames at 30fps
- File transfer: Bulk data as fast as congestion allows
- Conference call: Small packets every 20ms
"""

from .base import BaseSynthesizer, DataPacket, SynthesizerFactory
from .video_streaming import VideoStreamingSynthesizer
from .file_transfer import FileTransferSynthesizer
from .conference_call import ConferenceCallSynthesizer

__all__ = [
    "BaseSynthesizer",
    "DataPacket",
    "SynthesizerFactory",
    "VideoStreamingSynthesizer",
    "FileTransferSynthesizer",
    "ConferenceCallSynthesizer",
]
