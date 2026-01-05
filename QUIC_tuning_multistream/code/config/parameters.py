"""
Parameter definitions for QUIC tuning research.

This module defines the parameter values used in grid search
and preset configurations for different application types.
"""

from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class GridSearchParams:
    """Parameter values for grid search."""

    # Initial Congestion Window values (in bytes)
    # 10, 30, 60, 100 packets * 1200 bytes/packet
    initial_cw_values: List[int] = None

    # Max ACK Delay values (in seconds)
    max_ack_delay_values: List[float] = None

    # Loss Reduction Factor values
    loss_factor_values: List[float] = None

    def __post_init__(self):
        """Set default values if not provided."""
        if self.initial_cw_values is None:
            self.initial_cw_values = [12000, 36000, 72000, 120000]
        if self.max_ack_delay_values is None:
            self.max_ack_delay_values = [0.002, 0.010, 0.025, 0.050]
        if self.loss_factor_values is None:
            self.loss_factor_values = [0.4, 0.5, 0.6, 0.7]

    @property
    def total_combinations(self) -> int:
        """Total number of parameter combinations."""
        return (
            len(self.initial_cw_values)
            * len(self.max_ack_delay_values)
            * len(self.loss_factor_values)
        )


# Default grid search parameters
GRID_SEARCH_PARAMS = GridSearchParams()


@dataclass
class ParameterSet:
    """A single set of QUIC parameters."""

    initial_cw: int  # Initial Congestion Window in bytes
    max_ack_delay: float  # Max ACK Delay in seconds
    loss_reduction_factor: float  # Loss Reduction Factor (0.0 - 1.0)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "initial_congestion_window": self.initial_cw,
            "max_ack_delay": self.max_ack_delay,
            "loss_reduction_factor": self.loss_reduction_factor,
        }


class ParameterPresets:
    """Pre-configured parameter sets for different application types."""

    # Baseline (default aioquic values)
    BASELINE = ParameterSet(
        initial_cw=12000,
        max_ack_delay=0.025,
        loss_reduction_factor=0.5,
    )

    # Optimized for file transfer (high throughput)
    FILE_TRANSFER = ParameterSet(
        initial_cw=120000,  # Large initial window for fast ramp-up
        max_ack_delay=0.025,  # Standard ACK delay acceptable
        loss_reduction_factor=0.7,  # Quick recovery from loss
    )

    # Optimized for video streaming (low latency)
    VIDEO_STREAMING = ParameterSet(
        initial_cw=72000,  # Moderate initial window
        max_ack_delay=0.002,  # Low latency critical
        loss_reduction_factor=0.5,  # Standard recovery
    )

    # Optimized for conference calls (low jitter)
    CONFERENCE_CALL = ParameterSet(
        initial_cw=12000,  # Standard startup (small packets)
        max_ack_delay=0.002,  # Minimal delay for low jitter
        loss_reduction_factor=0.5,  # Standard recovery
    )

    @classmethod
    def get_preset(cls, application_type: str) -> ParameterSet:
        """Get preset for a specific application type."""
        presets = {
            "baseline": cls.BASELINE,
            "file_transfer": cls.FILE_TRANSFER,
            "video_streaming": cls.VIDEO_STREAMING,
            "conference_call": cls.CONFERENCE_CALL,
        }
        return presets.get(application_type, cls.BASELINE)

    @classmethod
    def list_presets(cls) -> List[str]:
        """List available preset names."""
        return ["baseline", "file_transfer", "video_streaming", "conference_call"]
