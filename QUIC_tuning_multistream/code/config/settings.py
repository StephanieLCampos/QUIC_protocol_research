"""
Global settings for the QUIC Multi-Stream Research Project.

This module contains all configurable settings including paths,
default values, and simulation parameters.
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import List


@dataclass
class Settings:
    """Global settings for the research project."""

    # Base paths
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent)

    # Certificate paths
    cert_file: Path = field(default_factory=lambda: Path(__file__).parent.parent / "certs" / "cert.pem")
    key_file: Path = field(default_factory=lambda: Path(__file__).parent.parent / "certs" / "key.pem")

    # Output paths
    measurements_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "output" / "measurements")
    reports_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "output" / "reports")

    # Server settings
    server_host: str = "localhost"
    server_port: int = 4433

    # Simulation settings
    simulation_duration: float = 10.0  # seconds per simulation
    num_streams: int = 3  # Number of streams to open per connection

    # Application types
    application_types: List[str] = field(
        default_factory=lambda: ["video_streaming", "file_transfer", "conference_call"]
    )

    # Video streaming settings
    video_fps: int = 30
    video_i_frame_size: int = 50000  # ~50KB
    video_p_frame_size: int = 5000   # ~5KB
    video_i_frame_interval: int = 60  # I-frame every 60 frames (2 seconds at 30fps)

    # File transfer settings
    file_chunk_size: int = 65536  # 64KB chunks
    file_total_size: int = 10_000_000  # 10MB default file size

    # Conference call settings
    conference_packet_interval_ms: int = 20  # 20ms intervals
    conference_bitrate_kbps: int = 128  # 128kbps audio

    def __post_init__(self):
        """Ensure output directories exist."""
        self.measurements_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_instance(cls) -> "Settings":
        """Get singleton instance of settings."""
        if not hasattr(cls, "_instance"):
            cls._instance = cls()
        return cls._instance


# Default settings instance
DEFAULT_SETTINGS = Settings()
