"""
Video streaming synthesizer.

Generates data patterns that mimic video streaming traffic with
I-frames and P-frames at realistic intervals.
"""

import asyncio
import time
from typing import AsyncIterator

from .base import BaseSynthesizer, DataPacket, SynthesizerFactory


class VideoStreamingSynthesizer(BaseSynthesizer):
    """
    Synthesizer for video streaming data.

    Generates I-frames (keyframes) and P-frames (delta frames) at
    realistic video streaming rates. Default configuration mimics
    720p video at 30fps with periodic keyframes.

    Traffic Pattern:
    - 30 fps (frames per second)
    - I-frames (keyframes): ~50KB every 60 frames (2 seconds)
    - P-frames (delta): ~5KB between I-frames
    - Total bitrate: approximately 5-6 Mbps
    """

    # Frame sizes in bytes
    I_FRAME_SIZE = 50_000  # ~50 KB for keyframes
    P_FRAME_SIZE = 5_000  # ~5 KB for delta frames

    # Timing
    FPS = 30
    FRAME_INTERVAL = 1.0 / FPS  # ~33ms between frames
    KEYFRAME_INTERVAL = 60  # I-frame every 60 frames (2 seconds)

    def __init__(
        self,
        duration_seconds: float = 10.0,
        fps: int = 30,
        i_frame_size: int = 50_000,
        p_frame_size: int = 5_000,
        keyframe_interval: int = 60,
    ):
        """
        Initialize video streaming synthesizer.

        Args:
            duration_seconds: Duration of the video stream.
            fps: Frames per second.
            i_frame_size: Size of I-frames (keyframes) in bytes.
            p_frame_size: Size of P-frames (delta frames) in bytes.
            keyframe_interval: Number of frames between keyframes.
        """
        super().__init__(duration_seconds=duration_seconds)
        self.fps = fps
        self.i_frame_size = i_frame_size
        self.p_frame_size = p_frame_size
        self.keyframe_interval = keyframe_interval
        self.frame_interval = 1.0 / fps

    async def generate(self) -> AsyncIterator[DataPacket]:
        """
        Generate video streaming packets.

        Yields I-frames at keyframe intervals and P-frames in between,
        maintaining consistent frame timing.
        """
        start_time = time.time()
        frame_count = 0

        while (time.time() - start_time) < self.duration_seconds:
            frame_start = time.time()

            # Determine frame type
            is_keyframe = (frame_count % self.keyframe_interval) == 0

            if is_keyframe:
                # I-frame (keyframe)
                frame_type = "I-frame"
                frame_size = self.i_frame_size
            else:
                # P-frame (delta)
                frame_type = "P-frame"
                frame_size = self.p_frame_size

            # Generate frame data
            data = bytes(frame_size)

            yield DataPacket(
                data=data,
                size=frame_size,
                timestamp=time.time(),
                packet_type=frame_type,
                sequence=self._next_sequence(),
                metadata={
                    "frame_number": frame_count,
                    "is_keyframe": is_keyframe,
                },
            )

            frame_count += 1

            # Wait for next frame timing
            elapsed = time.time() - frame_start
            sleep_time = max(0, self.frame_interval - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    @property
    def application_type(self) -> str:
        return "video_streaming"


# Register with factory
SynthesizerFactory.register("video_streaming", VideoStreamingSynthesizer)
