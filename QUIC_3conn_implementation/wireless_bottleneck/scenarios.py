"""
Predefined wireless scenarios for testing.

These scenarios represent common wireless conditions that QUIC
connections may encounter.
"""

from dataclasses import dataclass
import math
from typing import Dict

from .config import BottleneckConfig, LossModel, QueueDiscipline


@dataclass
class WirelessScenario:
    """A named wireless scenario with description."""
    name: str
    description: str
    config: BottleneckConfig


def stable_high_capacity() -> WirelessScenario:
    """
    Stable high capacity link.
    
    Characteristics:
    - 100 Mbps capacity
    - 10ms RTT (5ms propagation)
    - 0.1% loss rate
    - Large queue (200 packets)
    - No variation
    """
    return WirelessScenario(
        name="stable_high_capacity",
        description="Stable 100 Mbps link with low latency and minimal loss",
        config=BottleneckConfig(
            capacity_bps=100_000_000,  # 100 Mbps
            propagation_delay=0.005,  # 5ms (10ms RTT)
            loss_rate=0.001,  # 0.1%
            loss_model=LossModel.RANDOM,
            queue_size_packets=200,
            queue_discipline=QueueDiscipline.FIFO,
            time_varying=False,
        )
    )


def congested_low_capacity() -> WirelessScenario:
    """
    Congested low capacity link.
    
    Characteristics:
    - 5 Mbps capacity (typical congested WiFi)
    - 30ms RTT (15ms propagation)
    - 2% loss rate
    - Small queue (50 packets, causes bufferbloat)
    - RED queueing to manage congestion
    """
    return WirelessScenario(
        name="congested_low_capacity",
        description="Congested 5 Mbps link with moderate latency and loss",
        config=BottleneckConfig(
            capacity_bps=5_000_000,  # 5 Mbps
            propagation_delay=0.015,  # 15ms (30ms RTT)
            loss_rate=0.02,  # 2%
            loss_model=LossModel.RANDOM,
            queue_size_packets=50,
            queue_discipline=QueueDiscipline.RED,
            red_min_threshold=15,
            red_max_threshold=45,
            red_max_probability=0.15,
            time_varying=False,
        )
    )


def rapidly_varying_capacity() -> WirelessScenario:
    """
    Varying capacity link (simulates mobility/slow fading).

    Characteristics:
    - 20 Mbps average capacity
    - Varies ±40% every 6 seconds (simulates slow fading)
    - 20ms RTT (10ms propagation)
    - 1% loss rate
    - Medium queue (100 packets)
    - CoDel queueing

    Note: 6-second variation period allows Q-learning agent (2s control interval)
    to make 3 decisions per network state, enabling proper cause-effect learning.
    """
    return WirelessScenario(
        name="rapidly_varying_capacity",
        description="20 Mbps link with ±40% capacity variation every 6s",
        config=BottleneckConfig(
            capacity_bps=20_000_000,  # 20 Mbps average
            propagation_delay=0.010,  # 10ms (20ms RTT)
            loss_rate=0.01,  # 1%
            loss_model=LossModel.RANDOM,
            queue_size_packets=100,
            queue_discipline=QueueDiscipline.CODEL,
            codel_target_delay=0.005,  # 5ms
            codel_interval=0.100,  # 100ms
            time_varying=True,
            variation_period=6.0,  # 6 second period (3 Q-learning decisions per state)
            variation_amplitude=0.4,  # ±40%
        )
    )


def loss_dominated_link() -> WirelessScenario:
    """
    Loss dominated link (poor wireless conditions).
    
    Characteristics:
    - 10 Mbps capacity
    - 40ms RTT (20ms propagation)
    - 5% loss rate with Gilbert-Elliott model (burst loss)
    - Medium queue (75 packets)
    - FIFO queueing
    """
    return WirelessScenario(
        name="loss_dominated_link",
        description="10 Mbps link with 5% burst loss (Gilbert-Elliott)",
        config=BottleneckConfig(
            capacity_bps=10_000_000,  # 10 Mbps
            propagation_delay=0.020,  # 20ms (40ms RTT)
            loss_rate=0.05,  # 5% average
            loss_model=LossModel.GILBERT_ELLIOTT,
            ge_good_to_bad=0.05,  # Stay in good state longer
            ge_bad_to_good=0.8,  # Quick recovery from bad
            ge_loss_in_bad=0.8,  # High loss in bad state
            queue_size_packets=75,
            queue_discipline=QueueDiscipline.FIFO,
            time_varying=False,
        )
    )


def asymmetric_link() -> WirelessScenario:
    """
    Asymmetric uplink/downlink (typical mobile network).
    
    Characteristics:
    - Downlink: 50 Mbps
    - Uplink: 10 Mbps
    - 25ms RTT (12.5ms propagation)
    - 0.5% loss rate
    - Large queue (150 packets)
    - FIFO queueing
    """
    return WirelessScenario(
        name="asymmetric_link",
        description="Asymmetric 50 Mbps down / 10 Mbps up (mobile-like)",
        config=BottleneckConfig(
            capacity_bps=50_000_000,  # Default to downlink
            downlink_capacity_bps=50_000_000,  # 50 Mbps
            uplink_capacity_bps=10_000_000,  # 10 Mbps
            propagation_delay=0.0125,  # 12.5ms (25ms RTT)
            loss_rate=0.005,  # 0.5%
            loss_model=LossModel.RANDOM,
            queue_size_packets=150,
            queue_discipline=QueueDiscipline.FIFO,
            time_varying=False,
        )
    )


def per_ideal() -> WirelessScenario:
    """
    Ideal channel — zero packet error rate.

    Characteristics:
    - 50 Mbps capacity (mid-range baseline)
    - 20ms RTT (10ms propagation)
    - 0% loss rate  (perfect channel)
    - 100-packet FIFO queue
    - No time variation

    Use as the reference point for the PER ladder.
    """
    return WirelessScenario(
        name="per_ideal",
        description="Ideal 50 Mbps channel — 0% packet error rate",
        config=BottleneckConfig(
            capacity_bps=50_000_000,   # 50 Mbps
            propagation_delay=0.010,   # 10ms one-way (20ms RTT)
            loss_rate=0.00,            # 0% PER
            loss_model=LossModel.RANDOM,
            queue_size_packets=100,
            queue_discipline=QueueDiscipline.FIFO,
            time_varying=False,
        )
    )


def per_1pct() -> WirelessScenario:
    """
    Near-ideal channel — 1% packet error rate.

    Characteristics:
    - 50 Mbps capacity
    - 20ms RTT (10ms propagation)
    - 1% loss rate  (light channel noise / minor interference)
    - 100-packet FIFO queue
    - No time variation
    """
    return WirelessScenario(
        name="per_1pct",
        description="50 Mbps channel — 1% packet error rate (light noise)",
        config=BottleneckConfig(
            capacity_bps=50_000_000,
            propagation_delay=0.010,
            loss_rate=0.01,            # 1% PER
            loss_model=LossModel.RANDOM,
            queue_size_packets=100,
            queue_discipline=QueueDiscipline.FIFO,
            time_varying=False,
        )
    )


def per_5pct() -> WirelessScenario:
    """
    Degraded channel — 5% packet error rate.

    Characteristics:
    - 50 Mbps capacity
    - 20ms RTT (10ms propagation)
    - 5% loss rate  (moderate congestion / interference)
    - 100-packet FIFO queue
    - No time variation
    """
    return WirelessScenario(
        name="per_5pct",
        description="50 Mbps channel — 5% packet error rate (moderate degradation)",
        config=BottleneckConfig(
            capacity_bps=50_000_000,
            propagation_delay=0.010,
            loss_rate=0.05,            # 5% PER
            loss_model=LossModel.RANDOM,
            queue_size_packets=100,
            queue_discipline=QueueDiscipline.FIFO,
            time_varying=False,
        )
    )


def per_10pct() -> WirelessScenario:
    """
    Heavily degraded channel — 10% packet error rate.

    Characteristics:
    - 50 Mbps capacity
    - 20ms RTT (10ms propagation)
    - 10% loss rate  (heavy congestion / poor signal)
    - 100-packet FIFO queue
    - No time variation
    """
    return WirelessScenario(
        name="per_10pct",
        description="50 Mbps channel — 10% packet error rate (heavy degradation)",
        config=BottleneckConfig(
            capacity_bps=50_000_000,
            propagation_delay=0.010,
            loss_rate=0.10,            # 10% PER
            loss_model=LossModel.RANDOM,
            queue_size_packets=100,
            queue_discipline=QueueDiscipline.FIFO,
            time_varying=False,
        )
    )


def per_20pct() -> WirelessScenario:
    """
    Severely degraded channel — 20% packet error rate.

    Characteristics:
    - 50 Mbps capacity
    - 20ms RTT (10ms propagation)
    - 20% loss rate  (extreme congestion / near-failure channel)
    - 100-packet FIFO queue
    - No time variation
    """
    return WirelessScenario(
        name="per_20pct",
        description="50 Mbps channel — 20% packet error rate (severe degradation)",
        config=BottleneckConfig(
            capacity_bps=50_000_000,
            propagation_delay=0.010,
            loss_rate=0.20,            # 20% PER
            loss_model=LossModel.RANDOM,
            queue_size_packets=100,
            queue_discipline=QueueDiscipline.FIFO,
            time_varying=False,
        )
    )


def realistic_mobile_channel() -> WirelessScenario:
    """
    Realistic mobile wireless channel with correlated multi-parameter variation.

    All four link parameters (bandwidth, one-way delay, jitter, loss rate) are
    derived from a single channel-quality proxy q ∈ [0, 1] that evolves as an
    Ornstein-Uhlenbeck (mean-reverting random walk) process, updated every 500 ms.

    This ensures physical realism: parameters cannot contradict each other the
    way independent random draws would (e.g. high throughput AND high loss cannot
    co-occur, matching real radio behaviour where both degrade together as SNR falls).

    Parameter bounds (calibrated against published LTE / 802.11ac field measurements):
      q = 1.0  →  50 Mbps,  5 ms delay,  1 ms jitter,   0.1% loss  (excellent signal)
      q = 0.65 →  ~25 Mbps, 32 ms delay, 11 ms jitter,  ~1% loss   (typical urban LTE)
      q = 0.0  →   1 Mbps,  80 ms delay, 25 ms jitter,  15% loss   (cell edge / deep fade)

    Ornstein-Uhlenbeck parameters:
      θ = 0.08   (mean-reversion strength → ~6 s half-life)
      μ = 0.65   (long-run mean quality → typical urban mobile environment)
      σ = 0.04   (diffusion per 500 ms tick → visible fluctuation every ~2–3 s)
    """
    return WirelessScenario(
        name="realistic_mobile_channel",
        description=(
            "Correlated multi-parameter variation driven by a single SNR proxy "
            "(Ornstein-Uhlenbeck random walk). Bandwidth 1–50 Mbps, delay 5–80 ms, "
            "jitter 1–25 ms, loss 0.1–15 %. Calibrated against LTE / 802.11ac measurements."
        ),
        config=BottleneckConfig(
            # Initial / fallback static values (used during setup before first tick)
            capacity_bps=25_000_000,     # 25 Mbps — mid-range starting point
            propagation_delay=0.032,     # 32 ms one-way (64 ms RTT) — typical urban LTE
            loss_rate=0.01,              # 1% — typical urban starting point
            loss_model=LossModel.RANDOM,
            queue_size_packets=150,
            queue_discipline=QueueDiscipline.CODEL,  # AQM for buferbloat control
            codel_target_delay=0.005,    # 5 ms target queue delay
            codel_interval=0.100,        # 100 ms CoDel interval
            # Enable channel-quality random walk
            time_varying=True,
            channel_quality_variation=True,
            channel_quality_initial=0.65,    # start at typical urban quality
            channel_quality_step=0.04,       # σ per 500 ms tick
            channel_quality_seed=None,       # non-deterministic by default
            # Parameter bounds
            cqv_max_capacity_bps=50_000_000, # 50 Mbps at q=1
            cqv_min_capacity_bps=1_000_000,  #  1 Mbps at q=0
            cqv_max_delay_ms=80.0,           # 80 ms one-way at q=0
            cqv_min_delay_ms=5.0,            #  5 ms one-way at q=1
            cqv_max_jitter_ms=25.0,          # 25 ms jitter at q=0
            cqv_min_jitter_ms=1.0,           #  1 ms jitter at q=1
            cqv_max_loss_rate=0.15,          # 15% loss at q=0
            cqv_min_loss_rate=0.001,         #  0.1% loss at q=1
        )
    )


# Predefined scenarios dictionary
PREDEFINED_SCENARIOS: Dict[str, WirelessScenario] = {
    # Original heterogeneous scenarios
    "stable_high": stable_high_capacity(),
    "congested_low": congested_low_capacity(),
    "varying": rapidly_varying_capacity(),
    "lossy": loss_dominated_link(),
    "asymmetric": asymmetric_link(),
    # Packet Error Rate (PER) ladder — only loss_rate varies, all else fixed
    "per_ideal": per_ideal(),
    "per_1":     per_1pct(),
    "per_5":     per_5pct(),
    "per_10":    per_10pct(),
    "per_20":    per_20pct(),
    # Realistic correlated multi-parameter variation
    "realistic_scenario": realistic_mobile_channel(),
}


def get_scenario(name: str) -> WirelessScenario:
    """
    Get a predefined scenario by name.
    
    Args:
        name: Scenario name (stable_high, congested_low, varying, lossy, asymmetric)
        
    Returns:
        WirelessScenario object
        
    Raises:
        KeyError: If scenario name not found
    """
    return PREDEFINED_SCENARIOS[name]


def list_scenarios() -> list[str]:
    """List all available scenario names."""
    return list(PREDEFINED_SCENARIOS.keys())
