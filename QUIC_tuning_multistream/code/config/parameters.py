"""
QUIC parameter definitions for the Generation 1 tuning research.

Declares the parameter space swept by the grid search and the hand-tuned
presets used as comparison baselines.

Three congestion-control parameters are swept here:
    - initial_cw            Initial congestion window, in bytes
    - max_ack_delay         Maximum ACK delay, in seconds
    - loss_reduction_factor Multiplier applied to cwnd on loss

Four values each yields 4 x 4 x 4 = 64 combinations per application type, and
192 runs across all three types. The `ParameterPresets` class additionally
holds per-application configurations expressing the expected trade-offs
(throughput for file transfer, latency for video, jitter for conference calls);
these serve as the baselines that grid-search results are compared against.

Connections:
    Imports from: standard library only (dataclasses, typing)
    Imported by:  config/__init__.py, grid_search.parameter_space,
                  examples.wireless_experiment
"""

from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class GridSearchParams:
    """Parameter values for grid search."""

    # These three fields default to None rather than to a list literal because
    # mutable defaults are shared across all dataclass instances in Python. The
    # real defaults are assigned per-instance in __post_init__ below.

    # Initial Congestion Window values (in bytes).
    # Chosen as 10, 30, 60 and 100 packets at the 1200-byte QUIC datagram size,
    # spanning the RFC 9002 default up to an aggressive fast-start window.
    initial_cw_values: List[int] = None

    # Max ACK Delay values (in seconds), from near-immediate (2ms) to the
    # 25ms RFC default and beyond, trading ACK overhead against feedback latency.
    max_ack_delay_values: List[float] = None

    # Loss Reduction Factor values: the multiplier applied to the congestion
    # window on a loss event. Lower is more conservative, higher recovers faster.
    loss_factor_values: List[float] = None

    def __post_init__(self):
        """Assign per-instance default parameter grids when none were supplied."""
        if self.initial_cw_values is None:
            self.initial_cw_values = [12000, 36000, 72000, 120000]
        if self.max_ack_delay_values is None:
            self.max_ack_delay_values = [0.002, 0.010, 0.025, 0.050]
        if self.loss_factor_values is None:
            self.loss_factor_values = [0.4, 0.5, 0.6, 0.7]

    @property
    def total_combinations(self) -> int:
        """
        Number of parameter combinations in the sweep, per application type.

        This is the Cartesian product of the three value lists (4 x 4 x 4 = 64
        by default). The full run multiplies this by the three application
        types, giving the 192 simulations the scheduler enumerates.
        """
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
        """
        Return the preset parameter set for an application type.

        Args:
            application_type: One of "baseline", "file_transfer",
                "video_streaming" or "conference_call".

        Returns:
            The matching ParameterSet, or BASELINE if the name is unrecognised.
            Falling back rather than raising keeps a mistyped application name
            from aborting a long grid-search run.
        """
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
