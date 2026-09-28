"""
Uniform configuration presets for comparative QUIC experiments.

These presets apply the SAME parameters to ALL 3 connections,
enabling fair comparison across application types.

Parameter values are from grid search results (243 combinations tested).
Jitter measured using RFC 3550 algorithm based on RTT variation.
See: grid_search_code/output/analysis/optimal_configs.json

Key findings from grid search (with corrected jitter measurement):
    - ft_friendly: Optimizes for throughput (326.88 Mbps achieved)
    - vc_friendly: Optimizes for jitter (0.06 ms achieved)
    - mm_friendly: Optimizes for latency (1.60 ms achieved)
    - Each app type now has DIFFERENT optimal parameters

The three presets are each the winner for one application type, applied
uniformly. Comparing an application's performance under its own preset against
its performance under the other two quantifies what a single shared
configuration costs, which is the experiment's purpose.

Note on the figures above: they were measured without a bottleneck applied, so
the throughput value reflects loopback capacity rather than a realistic link.
They are meaningful as relative comparisons between configurations, not as
absolute performance claims.

Connections
-----------
Imports from : standard library only (dataclasses, typing)
Imported by  : experiment_runner.py (by file path, see config/__init__.py)
Derived from : grid_search_code analysis output
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class UniformPreset:
    """A uniform configuration applied to all connections."""
    name: str
    description: str

    # Start-only parameters (fixed, same for all presets)
    initial_cw: int = 14720          # 14720 bytes (~12 packets) - RFC 9002 Section 7.2
    max_ack_delay: float = 0.025     # 25ms (RFC 9002 default)
    max_data: int = 1_048_576        # 1 MB connection flow control
    max_stream_data: int = 1_048_576 # 1 MB stream flow control

    # Dynamic parameters (these differ per preset)
    loss_reduction_factor: float = 0.7
    cubic_c: float = 0.4
    minimum_window: int = 2
    packet_threshold: int = 3
    time_threshold: float = 1.125
    cubic_max_idle_time: float = 2.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "initial_cw": self.initial_cw,
            "max_ack_delay": self.max_ack_delay,
            "max_data": self.max_data,
            "max_stream_data": self.max_stream_data,
            "loss_reduction_factor": self.loss_reduction_factor,
            "cubic_c": self.cubic_c,
            "minimum_window": self.minimum_window,
            "packet_threshold": self.packet_threshold,
            "time_threshold": self.time_threshold,
            "cubic_max_idle_time": self.cubic_max_idle_time,
        }


# =============================================================================
# PRESET CONFIGURATIONS
# =============================================================================
# Values from grid search results (243 combinations tested)
# Source: grid_search_code/output/analysis/optimal_configs.json

# Config A: File Transfer Friendly (Maximize Throughput)
# Grid search result: 326.88 Mbps optimal throughput
# Rationale:
#   - loss_reduction_factor=0.3: Aggressive reduction allows faster recovery
#   - cubic_c=0.2: Conservative growth maintains stability under high load
#   - minimum_window=4: Balanced floor for recovery after loss
#   - packet_threshold=3: RFC default for loss detection
#   - time_threshold=1.125: RFC 9002 default
#   - cubic_max_idle_time=2.0: Balanced idle tolerance
CONFIG_A_FT_FRIENDLY = UniformPreset(
    name="ft_friendly",
    description="File Transfer Friendly - Maximize Throughput",
    loss_reduction_factor=0.3,
    cubic_c=0.2,
    minimum_window=4,
    packet_threshold=3,
    time_threshold=1.125,
    cubic_max_idle_time=2.0,
)

# Config B: Video Call Friendly (Minimize Jitter)
# Grid search result: 0.06 ms optimal jitter (RFC 3550 measurement)
# Rationale:
#   - loss_reduction_factor=0.5: Balanced reduction for stable RTT
#   - cubic_c=0.2: Conservative growth minimizes RTT variation
#   - minimum_window=4: Higher floor provides consistent behavior
#   - packet_threshold=3: RFC default balances detection speed and stability
#   - time_threshold=1.125: RFC 9002 default
#   - cubic_max_idle_time=2.0: Balanced idle tolerance
CONFIG_B_VC_FRIENDLY = UniformPreset(
    name="vc_friendly",
    description="Video Call Friendly - Minimize Jitter",
    loss_reduction_factor=0.5,
    cubic_c=0.2,
    minimum_window=4,
    packet_threshold=3,
    time_threshold=1.125,
    cubic_max_idle_time=2.0,
)

# Config C: Multimedia Friendly (Minimize Latency)
# Grid search result: 1.60 ms optimal latency
# Rationale:
#   - loss_reduction_factor=0.7: Standard CUBIC reduction for smooth streaming
#   - cubic_c=0.4: Moderate growth balances throughput and latency
#   - minimum_window=2: Allow small windows for low queuing delay
#   - packet_threshold=4: Slower detection reduces false positives
#   - time_threshold=1.125: RFC 9002 default
#   - cubic_max_idle_time=2.0: Balanced idle tolerance
CONFIG_C_MM_FRIENDLY = UniformPreset(
    name="mm_friendly",
    description="Multimedia Friendly - Minimize Latency",
    loss_reduction_factor=0.7,
    cubic_c=0.4,
    minimum_window=2,
    packet_threshold=4,
    time_threshold=1.125,
    cubic_max_idle_time=2.0,
)


# Registry of all presets
UNIFORM_PRESETS = {
    "ft_friendly": CONFIG_A_FT_FRIENDLY,
    "vc_friendly": CONFIG_B_VC_FRIENDLY,
    "mm_friendly": CONFIG_C_MM_FRIENDLY,
}


def get_preset(name: str) -> UniformPreset:
    """Get a uniform preset by name."""
    if name not in UNIFORM_PRESETS:
        raise ValueError(f"Unknown preset: {name}. Available: {list(UNIFORM_PRESETS.keys())}")
    return UNIFORM_PRESETS[name]


def list_presets() -> list:
    """List available uniform preset names."""
    return list(UNIFORM_PRESETS.keys())


def print_preset_summary():
    """Print a summary of all presets."""
    print("\nAvailable Uniform Presets:")
    print("=" * 70)
    for name, preset in UNIFORM_PRESETS.items():
        print(f"\n{name}: {preset.description}")
        print(f"  loss_reduction_factor: {preset.loss_reduction_factor}")
        print(f"  cubic_c:               {preset.cubic_c}")
        print(f"  minimum_window:        {preset.minimum_window}")
        print(f"  packet_threshold:      {preset.packet_threshold}")
        print(f"  time_threshold:        {preset.time_threshold}")
        print(f"  cubic_max_idle_time:   {preset.cubic_max_idle_time}")
    print("\n" + "=" * 70)
