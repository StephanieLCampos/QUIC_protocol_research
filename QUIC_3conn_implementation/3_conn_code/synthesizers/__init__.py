"""
Synthesizers package.

Provides data generators for different application types:
- Video streaming: I-frames and P-frames at 30fps
- File transfer: Bulk data as fast as congestion allows
- Conference call: Small packets every 20ms

Each synthesizer reproduces the size and timing profile of a real application
without carrying real media content, which is sufficient because QUIC's
congestion control responds only to packet sizes and arrival timing.

Registration side effect
------------------------
Unlike the Generation 1 factory, which held a hard-coded mapping, this package
uses a registry: each synthesizer module calls
`SynthesizerFactory.register(...)` at import time. Importing this package is
therefore what populates the factory. Importing `synthesizers.base` alone would
yield an empty registry and every `create()` call would raise ValueError.

Connections
-----------
Imports from : .base, .video_streaming, .file_transfer, .conference_call
Imported by  : simulation.worker_process
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
