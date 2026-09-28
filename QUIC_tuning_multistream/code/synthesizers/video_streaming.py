"""
Video streaming traffic synthesizer.

Reproduces an H.264-like frame pattern: large I-frames (keyframes) emitted at a
fixed interval, with small P-frames (predicted frames) in between, paced to a
target frame rate.

The resulting traffic is bursty and latency-sensitive, which makes this the
workload used to evaluate the latency dimension of a parameter set. Pacing is
computed against the run's absolute start time rather than by sleeping a fixed
interval per frame, so scheduling jitter does not accumulate over a long run.

Connections:
    Imports from: .base (BaseSynthesizer, DataPacket)
    Imported by:  synthesizers/__init__.py, SynthesizerFactory
"""

import asyncio
import time
from typing import AsyncIterator

from .base import BaseSynthesizer, DataPacket


class VideoStreamingSynthesizer(BaseSynthesizer):
    """
    Generates H.264-like video frame patterns.

    Characteristics:
    - 30 fps (33.33ms intervals)
    - I-frames every 60 frames (~50KB each) - keyframes for random access
    - P-frames between I-frames (~5KB each) - predicted frames

    The actual content of the frames is irrelevant to QUIC behavior.
    Only the size and timing patterns matter for protocol performance.
    """

    def __init__(
        self,
        duration_seconds: float = 10.0,
        fps: int = 30,
        i_frame_size: int = 50000,
        p_frame_size: int = 5000,
        i_frame_interval: int = 60,
    ):
        """
        Initialize the video streaming synthesizer.

        Args:
            duration_seconds: Duration of video stream to generate.
            fps: Frames per second (default: 30).
            i_frame_size: Size of I-frames in bytes (default: 50000 = ~50KB).
            p_frame_size: Size of P-frames in bytes (default: 5000 = ~5KB).
            i_frame_interval: Number of frames between I-frames (default: 60).
        """
        super().__init__(duration_seconds)
        self.fps = fps
        self.i_frame_size = i_frame_size
        self.p_frame_size = p_frame_size
        self.i_frame_interval = i_frame_interval
        self.frame_interval = 1.0 / fps  # Time between frames in seconds

    @property
    def application_type(self) -> str:
        """Return the application type identifier."""
        return "video_streaming"

    async def generate(self) -> AsyncIterator[DataPacket]:
        """
        Generate video frames asynchronously.

        Yields frames at the configured FPS rate, alternating between
        I-frames (keyframes) and P-frames (predicted frames).

        Yields:
            DataPacket objects representing video frames.
        """
        self.reset()
        start_time = time.time()
        frame_number = 0
        total_frames = int(self.duration_seconds * self.fps)

        while frame_number < total_frames:
            current_time = time.time()

            # Determine frame type and size
            if frame_number % self.i_frame_interval == 0:
                frame_type = "I-frame"
                frame_size = self.i_frame_size
            else:
                frame_type = "P-frame"
                frame_size = self.p_frame_size

            # Create and yield the packet
            packet = self._create_packet(
                size=frame_size,
                timestamp=current_time,
                packet_type=frame_type,
                metadata={
                    "frame_number": frame_number,
                    "fps": self.fps,
                    "is_keyframe": frame_type == "I-frame",
                },
            )
            yield packet

            frame_number += 1

            # Pace to the next frame boundary. The target is computed from the
            # absolute start time rather than by sleeping a fixed interval each
            # iteration, so per-frame scheduling overhead does not accumulate
            # into growing drift over a long run.
            elapsed = time.time() - start_time
            expected_time = frame_number * self.frame_interval
            sleep_time = expected_time - elapsed

            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    def get_stats(self) -> dict:
        """
        Get statistics about the synthesizer configuration.

        Returns:
            Dictionary with configuration statistics.
        """
        total_frames = int(self.duration_seconds * self.fps)
        num_i_frames = (total_frames // self.i_frame_interval) + 1
        num_p_frames = total_frames - num_i_frames

        total_bytes = (num_i_frames * self.i_frame_size) + (num_p_frames * self.p_frame_size)
        avg_bitrate = (total_bytes * 8) / self.duration_seconds / 1_000_000  # Mbps

        return {
            "total_frames": total_frames,
            "i_frames": num_i_frames,
            "p_frames": num_p_frames,
            "total_bytes": total_bytes,
            "average_bitrate_mbps": avg_bitrate,
            "duration_seconds": self.duration_seconds,
        }
