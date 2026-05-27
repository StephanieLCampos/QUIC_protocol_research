"""
Parameter space definitions for QUIC congestion control grid search.

Defines the search space for finding optimal parameters per application type.
Only the 6 DYNAMIC parameters are searched. Start-only parameters
(initial_cw, max_ack_delay) are fixed at their defaults.
"""

from dataclasses import dataclass
from typing import List, Iterator, Dict, Any


@dataclass
class ParameterCombination:
    """A single combination of parameters to test."""

    app_type: str

    # Dynamic parameters (CUBIC CC) - THESE ARE SEARCHED
    loss_reduction_factor: float
    cubic_c: float
    minimum_window: int
    packet_threshold: int
    time_threshold: float
    cubic_max_idle_time: float

    # Start-only parameters (QUIC protocol) - FIXED AT DEFAULTS
    initial_cw: int = 14720        # Fixed, not searched - RFC 9002 Section 7.2
    max_ack_delay: float = 0.025   # Fixed, not searched

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "app_type": self.app_type,
            "loss_reduction_factor": self.loss_reduction_factor,
            "cubic_c": self.cubic_c,
            "minimum_window": self.minimum_window,
            "packet_threshold": self.packet_threshold,
            "time_threshold": self.time_threshold,
            "cubic_max_idle_time": self.cubic_max_idle_time,
            "initial_cw": self.initial_cw,
            "max_ack_delay": self.max_ack_delay,
        }

    def get_filename(self) -> str:
        """Generate unique filename for this combination."""
        return (
            f"{self.app_type}_"
            f"lrf{self.loss_reduction_factor}_"
            f"cc{self.cubic_c}_"
            f"mw{self.minimum_window}_"
            f"pt{self.packet_threshold}_"
            f"tt{self.time_threshold}_"
            f"mit{self.cubic_max_idle_time}.csv"
        )

    def __str__(self) -> str:
        """Human-readable representation."""
        return (
            f"{self.app_type}: "
            f"lrf={self.loss_reduction_factor}, "
            f"cubic_c={self.cubic_c}, "
            f"min_win={self.minimum_window}, "
            f"pkt_thresh={self.packet_threshold}"
        )


class ParameterSpace:
    """
    Defines the parameter space for grid search.

    Only the 6 DYNAMIC parameters are searched. Start-only parameters
    (initial_cw, max_ack_delay) are fixed at their defaults.
    """

    # =========================================================================
    # DYNAMIC PARAMETERS (CUBIC Congestion Control) - THESE ARE SEARCHED
    # =========================================================================

    # How much to reduce cwnd on packet loss (lower = more aggressive)
    # RFC 9438: CUBIC uses 0.7 (standard), RFC 9002: NewReno uses 0.5
    # Range includes aggressive (0.3), standards (0.5, 0.7), and conservative (0.9)
    LOSS_REDUCTION_FACTOR_VALUES: List[float] = [0.3, 0.5, 0.7, 0.9]

    # CUBIC aggressiveness (higher = faster cwnd growth)
    # RFC 9438, RFC 8312: Standard value is 0.4
    CUBIC_C_VALUES: List[float] = [0.2, 0.4, 0.6]

    # Minimum congestion window in packets (floor)
    # RFC 9002: Recommended value is 2 packets
    # Range includes below (1), at (2), and above (4) standard
    MINIMUM_WINDOW_VALUES: List[int] = [1, 2, 4]

    # Duplicate ACKs before fast retransmit
    # RFC 9002, RFC 5681: Standard value is 3
    PACKET_THRESHOLD_VALUES: List[int] = [2, 3, 4]

    # RTT multiplier for time-based loss detection
    # RFC 9002: Standard value is 9/8 = 1.125
    TIME_THRESHOLD_VALUES: List[float] = [1.0, 1.125, 1.25]

    # Idle timeout before cwnd reset
    # Implementation-specific, range covers responsive (0.5s) to tolerant (4.0s)
    CUBIC_MAX_IDLE_TIME_VALUES: List[float] = [0.5, 1.0, 2.0, 4.0]

    # =========================================================================
    # START-ONLY PARAMETERS (QUIC Protocol) - FIXED, NOT SEARCHED
    # These cannot be changed mid-connection, so we keep them at defaults
    # =========================================================================

    # Initial congestion window (bytes) - FIXED at default
    FIXED_INITIAL_CW: int = 14720  # RFC 9002 Section 7.2

    # Max ACK delay (seconds) - FIXED at default
    FIXED_MAX_ACK_DELAY: float = 0.025

    # =========================================================================
    # APPLICATION TYPES
    # =========================================================================

    APPLICATION_TYPES: List[str] = [
        "file_transfer",      # Optimize for: highest throughput
        "video_streaming",    # Optimize for: lowest latency
        "conference_call",    # Optimize for: lowest jitter
    ]

    # =========================================================================
    # SEARCH MODES
    # =========================================================================

    @classmethod
    def get_full_combinations_count(cls) -> int:
        """
        Total combinations searching all 6 DYNAMIC parameters.

        Note: initial_cw and max_ack_delay are START-ONLY parameters
        and are NOT searched - they remain fixed at defaults.
        """
        return (
            len(cls.APPLICATION_TYPES)
            * len(cls.LOSS_REDUCTION_FACTOR_VALUES)
            * len(cls.CUBIC_C_VALUES)
            * len(cls.MINIMUM_WINDOW_VALUES)
            * len(cls.PACKET_THRESHOLD_VALUES)
            * len(cls.TIME_THRESHOLD_VALUES)
            * len(cls.CUBIC_MAX_IDLE_TIME_VALUES)
        )  # 3 apps x 4x3x3x3x3x4 = 3,888 combinations

    @classmethod
    def get_reduced_combinations_count(cls) -> int:
        """
        Combinations for reduced search (4 most impactful dynamic params).

        Searches: loss_reduction_factor, cubic_c, minimum_window, packet_threshold
        Fixes: time_threshold=1.125, cubic_max_idle_time=2.0

        Note: initial_cw and max_ack_delay are always fixed (start-only).
        """
        return (
            len(cls.APPLICATION_TYPES)
            * len(cls.LOSS_REDUCTION_FACTOR_VALUES)
            * len(cls.CUBIC_C_VALUES)
            * len(cls.MINIMUM_WINDOW_VALUES)
            * len(cls.PACKET_THRESHOLD_VALUES)
        )  # 3 apps x 4x3x3x3 = 324 combinations

    @classmethod
    def generate_reduced_combinations(cls) -> Iterator[ParameterCombination]:
        """
        Generate combinations for REDUCED search (recommended for initial run).

        Searches 4 most impactful DYNAMIC parameters:
        - loss_reduction_factor (4 values: 0.3, 0.5, 0.7, 0.9)
        - cubic_c (3 values: 0.2, 0.4, 0.6)
        - minimum_window (3 values: 1, 2, 4)
        - packet_threshold (3 values: 2, 3, 4)

        Fixed dynamic parameters:
        - time_threshold = 1.125 (default)
        - cubic_max_idle_time = 2.0 (default)

        Fixed start-only parameters (NOT searched):
        - initial_cw = 14720 (RFC 9002 Section 7.2)
        - max_ack_delay = 0.025 (default)

        Total: 4x3x3x3 x 3 apps = 324 combinations
        """
        for app_type in cls.APPLICATION_TYPES:
            for lrf in cls.LOSS_REDUCTION_FACTOR_VALUES:
                for cubic_c in cls.CUBIC_C_VALUES:
                    for min_win in cls.MINIMUM_WINDOW_VALUES:
                        for pkt_thresh in cls.PACKET_THRESHOLD_VALUES:
                            yield ParameterCombination(
                                app_type=app_type,
                                loss_reduction_factor=lrf,
                                cubic_c=cubic_c,
                                minimum_window=min_win,
                                packet_threshold=pkt_thresh,
                                time_threshold=1.125,        # Fixed
                                cubic_max_idle_time=2.0,     # Fixed
                                initial_cw=cls.FIXED_INITIAL_CW,      # Start-only, fixed
                                max_ack_delay=cls.FIXED_MAX_ACK_DELAY, # Start-only, fixed
                            )

    @classmethod
    def generate_full_combinations(cls) -> Iterator[ParameterCombination]:
        """
        Generate ALL dynamic parameter combinations.

        Searches all 6 DYNAMIC parameters:
        - loss_reduction_factor (4 values: 0.3, 0.5, 0.7, 0.9)
        - cubic_c (3 values: 0.2, 0.4, 0.6)
        - minimum_window (3 values: 1, 2, 4)
        - packet_threshold (3 values: 2, 3, 4)
        - time_threshold (3 values: 1.0, 1.125, 1.25)
        - cubic_max_idle_time (4 values: 0.5, 1.0, 2.0, 4.0)

        Fixed start-only parameters (NOT searched):
        - initial_cw = 14720 (RFC 9002 Section 7.2)
        - max_ack_delay = 0.025 (default)

        Total: 4x3x3x3x3x4 x 3 apps = 3,888 combinations
        At 30s per run with 4 workers = ~8-9 hours
        """
        for app_type in cls.APPLICATION_TYPES:
            for lrf in cls.LOSS_REDUCTION_FACTOR_VALUES:
                for cubic_c in cls.CUBIC_C_VALUES:
                    for min_win in cls.MINIMUM_WINDOW_VALUES:
                        for pkt_thresh in cls.PACKET_THRESHOLD_VALUES:
                            for time_thresh in cls.TIME_THRESHOLD_VALUES:
                                for idle_time in cls.CUBIC_MAX_IDLE_TIME_VALUES:
                                    yield ParameterCombination(
                                        app_type=app_type,
                                        loss_reduction_factor=lrf,
                                        cubic_c=cubic_c,
                                        minimum_window=min_win,
                                        packet_threshold=pkt_thresh,
                                        time_threshold=time_thresh,
                                        cubic_max_idle_time=idle_time,
                                        initial_cw=cls.FIXED_INITIAL_CW,      # Start-only, fixed
                                        max_ack_delay=cls.FIXED_MAX_ACK_DELAY, # Start-only, fixed
                                    )

    @classmethod
    def generate_for_app_type(
        cls,
        app_type: str,
        reduced: bool = True
    ) -> Iterator[ParameterCombination]:
        """Generate combinations for a specific application type."""
        if reduced:
            for combo in cls.generate_reduced_combinations():
                if combo.app_type == app_type:
                    yield combo
        else:
            for combo in cls.generate_full_combinations():
                if combo.app_type == app_type:
                    yield combo

    @classmethod
    def get_summary(cls, reduced: bool = True) -> Dict[str, Any]:
        """Get summary of the parameter space configuration."""
        if reduced:
            return {
                "mode": "reduced",
                "searched_parameters": [
                    "loss_reduction_factor",
                    "cubic_c",
                    "minimum_window",
                    "packet_threshold",
                ],
                "fixed_dynamic_parameters": {
                    "time_threshold": 1.125,
                    "cubic_max_idle_time": 2.0,
                },
                "fixed_start_only_parameters": {
                    "initial_cw": cls.FIXED_INITIAL_CW,
                    "max_ack_delay": cls.FIXED_MAX_ACK_DELAY,
                },
                "values": {
                    "loss_reduction_factor": cls.LOSS_REDUCTION_FACTOR_VALUES,
                    "cubic_c": cls.CUBIC_C_VALUES,
                    "minimum_window": cls.MINIMUM_WINDOW_VALUES,
                    "packet_threshold": cls.PACKET_THRESHOLD_VALUES,
                },
                "combinations_per_app": 4 * 3 * 3 * 3,  # 108
                "total_combinations": cls.get_reduced_combinations_count(),  # 324
                "application_types": cls.APPLICATION_TYPES,
            }
        else:
            return {
                "mode": "full",
                "searched_parameters": [
                    "loss_reduction_factor",
                    "cubic_c",
                    "minimum_window",
                    "packet_threshold",
                    "time_threshold",
                    "cubic_max_idle_time",
                ],
                "fixed_start_only_parameters": {
                    "initial_cw": cls.FIXED_INITIAL_CW,
                    "max_ack_delay": cls.FIXED_MAX_ACK_DELAY,
                },
                "values": {
                    "loss_reduction_factor": cls.LOSS_REDUCTION_FACTOR_VALUES,
                    "cubic_c": cls.CUBIC_C_VALUES,
                    "minimum_window": cls.MINIMUM_WINDOW_VALUES,
                    "packet_threshold": cls.PACKET_THRESHOLD_VALUES,
                    "time_threshold": cls.TIME_THRESHOLD_VALUES,
                    "cubic_max_idle_time": cls.CUBIC_MAX_IDLE_TIME_VALUES,
                },
                "combinations_per_app": 4 * 3 * 3 * 3 * 3 * 4,  # 1296
                "total_combinations": cls.get_full_combinations_count(),  # 3888
                "application_types": cls.APPLICATION_TYPES,
            }
