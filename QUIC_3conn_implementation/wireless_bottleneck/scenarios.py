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
    Rapidly varying capacity link (simulates mobility/fading).
    
    Characteristics:
    - 20 Mbps average capacity
    - Varies ±40% every 2 seconds (simulates fading)
    - 20ms RTT (10ms propagation)
    - 1% loss rate
    - Medium queue (100 packets)
    - CoDel queueing
    """
    return WirelessScenario(
        name="rapidly_varying_capacity",
        description="20 Mbps link with ±40% capacity variation every 2s",
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
            variation_period=2.0,  # 2 second period
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


# Predefined scenarios dictionary
PREDEFINED_SCENARIOS: Dict[str, WirelessScenario] = {
    "stable_high": stable_high_capacity(),
    "congested_low": congested_low_capacity(),
    "varying": rapidly_varying_capacity(),
    "lossy": loss_dominated_link(),
    "asymmetric": asymmetric_link(),
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
