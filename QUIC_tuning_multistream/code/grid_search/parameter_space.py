"""
Parameter space definition for the Generation 1 grid search.

Enumerates every (application type, initial congestion window, max ACK delay,
loss reduction factor) combination that the sweep will measure, and provides
the `ParameterCombination` record describing a single point in that space.

The space is 4 x 4 x 4 across three application types, giving 64 combinations
per application and 192 runs in total. Values are declared as class attributes
rather than instance state because the space is fixed for the study; changing a
value here changes the experiment itself, and previously exported CSV files
would no longer correspond to the new grid.

Note that these values intentionally mirror those in `config.parameters`. This
module is the authority for what the sweep enumerates, while config.parameters
additionally supplies the hand-tuned comparison presets.

Connections:
    Imports from: standard library only (dataclasses, typing, itertools)
    Imported by:  grid_search/__init__.py, .scheduler, .executor, main.py
"""

from dataclasses import dataclass
from typing import List, Iterator
from itertools import product


@dataclass
class ParameterCombination:
    """A single combination of parameters for testing."""

    app_type: str
    initial_cw: int
    max_ack_delay: float
    loss_factor: float

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "app_type": self.app_type,
            "initial_cw": self.initial_cw,
            "max_ack_delay": self.max_ack_delay,
            "loss_factor": self.loss_factor,
        }

    def __str__(self) -> str:
        """String representation."""
        return (
            f"{self.app_type} "
            f"ICW={self.initial_cw} "
            f"ACK={self.max_ack_delay} "
            f"LF={self.loss_factor}"
        )


class ParameterSpace:
    """
    Defines the parameter space for grid search.

    Parameters with 4 values each:
    - Initial Congestion Window: 12000, 36000, 72000, 120000 bytes
    - Max ACK Delay: 0.002, 0.010, 0.025, 0.050 seconds
    - Loss Reduction Factor: 0.4, 0.5, 0.6, 0.7

    Application types:
    - video_streaming
    - file_transfer
    - conference_call

    Total combinations: 4 × 4 × 4 × 3 = 192
    """

    # Initial Congestion Window values (in bytes)
    # Corresponds to 10, 30, 60, 100 packets (at 1200 bytes/packet)
    INITIAL_CW_VALUES: List[int] = [12000, 36000, 72000, 120000]

    # Max ACK Delay values (in seconds)
    # 2ms, 10ms, 25ms (default), 50ms
    MAX_ACK_DELAY_VALUES: List[float] = [0.002, 0.010, 0.025, 0.050]

    # Loss Reduction Factor values
    # 0.4 (aggressive), 0.5 (default), 0.6, 0.7 (conservative)
    LOSS_FACTOR_VALUES: List[float] = [0.4, 0.5, 0.6, 0.7]

    # Application types to test
    APPLICATION_TYPES: List[str] = [
        "video_streaming",
        "file_transfer",
        "conference_call",
    ]

    @classmethod
    def get_total_combinations(cls) -> int:
        """Get total number of parameter combinations."""
        return (
            len(cls.APPLICATION_TYPES)
            * len(cls.INITIAL_CW_VALUES)
            * len(cls.MAX_ACK_DELAY_VALUES)
            * len(cls.LOSS_FACTOR_VALUES)
        )

    @classmethod
    def get_combinations_per_app_type(cls) -> int:
        """Get number of combinations per application type."""
        return (
            len(cls.INITIAL_CW_VALUES)
            * len(cls.MAX_ACK_DELAY_VALUES)
            * len(cls.LOSS_FACTOR_VALUES)
        )

    @classmethod
    def generate_all_combinations(cls) -> Iterator[ParameterCombination]:
        """
        Generate all parameter combinations.

        Yields:
            ParameterCombination objects for each combination.
        """
        for app_type in cls.APPLICATION_TYPES:
            for initial_cw in cls.INITIAL_CW_VALUES:
                for max_ack_delay in cls.MAX_ACK_DELAY_VALUES:
                    for loss_factor in cls.LOSS_FACTOR_VALUES:
                        yield ParameterCombination(
                            app_type=app_type,
                            initial_cw=initial_cw,
                            max_ack_delay=max_ack_delay,
                            loss_factor=loss_factor,
                        )

    @classmethod
    def generate_for_app_type(cls, app_type: str) -> Iterator[ParameterCombination]:
        """
        Generate combinations for a specific application type.

        Args:
            app_type: The application type to generate for.

        Yields:
            ParameterCombination objects for the specified app type.
        """
        for initial_cw in cls.INITIAL_CW_VALUES:
            for max_ack_delay in cls.MAX_ACK_DELAY_VALUES:
                for loss_factor in cls.LOSS_FACTOR_VALUES:
                    yield ParameterCombination(
                        app_type=app_type,
                        initial_cw=initial_cw,
                        max_ack_delay=max_ack_delay,
                        loss_factor=loss_factor,
                    )

    @classmethod
    def get_summary(cls) -> dict:
        """Get a summary of the parameter space."""
        return {
            "initial_cw_values": cls.INITIAL_CW_VALUES,
            "max_ack_delay_values": cls.MAX_ACK_DELAY_VALUES,
            "loss_factor_values": cls.LOSS_FACTOR_VALUES,
            "application_types": cls.APPLICATION_TYPES,
            "combinations_per_app": cls.get_combinations_per_app_type(),
            "total_combinations": cls.get_total_combinations(),
        }
