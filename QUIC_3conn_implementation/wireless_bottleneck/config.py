"""
Configuration model for the wireless bottleneck (Generation 2).

Defines `BottleneckConfig`, the single description of an emulated link, plus
the `LossModel` and `QueueDiscipline` enumerations it draws on.

A link is characterised along four axes:
    capacity      link rate in bits per second, optionally asymmetric
    delay         one-way propagation delay (RTT is twice this)
    loss          rate plus a model: uniform random, or Gilbert-Elliott bursts
    queueing      buffer depth and discipline

Two forms of time variation are supported. The simple form varies capacity
alone along a sinusoid. The channel-quality form (`channel_quality_variation`)
derives all four parameters from one Ornstein-Uhlenbeck quality proxy, with the
`cqv_*` fields defining the value each parameter takes at q=0 and q=1; see
bottleneck.py for the mappings and the rationale.

This class is a pure description and performs no enforcement. Note that not
every declared field reaches the tc configuration actually emitted: the RED,
CoDel and PIE tuning fields belong to a qdisc path that is no longer invoked.

Connections
-----------
Imports from : standard library only (dataclasses, typing, enum)
Imported by  : .bottleneck, .scenarios, wireless_bottleneck/__init__.py
"""

from dataclasses import dataclass, field
from typing import Optional, List, Callable
from enum import Enum


class LossModel(Enum):
    """Packet loss models."""
    RANDOM = "random"  # Uniform random loss
    GILBERT_ELLIOTT = "gilbert_elliott"  # Burst loss model
    MARKOV = "markov"  # Multi-state Markov model


class QueueDiscipline(Enum):
    """Queueing disciplines."""
    FIFO = "fifo"  # First-In-First-Out
    RED = "red"  # Random Early Detection
    CODEL = "codel"  # Controlled Delay
    PIE = "pie"  # Proportional Integral Controller Enhanced


@dataclass
class BottleneckConfig:
    """
    Configuration for a wireless bottleneck.
    
    This models a shared wireless link that all QUIC connections
    must traverse, with configurable capacity, delay, loss, and
    queueing behavior.
    """
    
    # Link capacity (bits per second)
    capacity_bps: int = 10_000_000  # 10 Mbps default
    
    # Propagation delay (seconds, one-way)
    propagation_delay: float = 0.020  # 20ms default
    
    # Transmission delay (calculated from capacity and packet size)
    # For 1500 byte packet at 10 Mbps: 1.2ms
    
    # Packet loss rate (0.0 to 1.0)
    loss_rate: float = 0.01  # 1% default
    
    # Loss model
    loss_model: LossModel = LossModel.RANDOM
    
    # Gilbert-Elliott model parameters (for burst loss)
    ge_good_to_bad: float = 0.1  # Transition probability
    ge_bad_to_good: float = 0.9  # Transition probability
    ge_loss_in_bad: float = 0.5  # Loss rate in bad state
    
    # Queue/buffer size (in packets)
    queue_size_packets: int = 100
    
    # Queue/buffer size (in bytes, alternative to packets)
    queue_size_bytes: Optional[int] = None
    
    # Queueing discipline
    queue_discipline: QueueDiscipline = QueueDiscipline.FIFO
    
    # RED parameters (if using RED)
    red_min_threshold: int = 30  # packets
    red_max_threshold: int = 90  # packets
    red_max_probability: float = 0.1
    
    # CoDel parameters (if using CoDel)
    codel_target_delay: float = 0.005  # 5ms
    codel_interval: float = 0.100  # 100ms
    
    # Asymmetric uplink/downlink
    uplink_capacity_bps: Optional[int] = None  # If None, use capacity_bps
    downlink_capacity_bps: Optional[int] = None  # If None, use capacity_bps
    
    # Time-varying behavior
    time_varying: bool = False
    capacity_variation_function: Optional[Callable[[float], int]] = None
    
    # Variation period for fading/mobility simulation
    variation_period: float = 1.0  # seconds
    variation_amplitude: float = 0.3  # fraction (0.3 = ±30%)

    # -----------------------------------------------------------------------
    # Channel-quality-driven random walk (realistic multi-parameter variation)
    # -----------------------------------------------------------------------
    # When channel_quality_variation=True a single SNR proxy q ∈ [0, 1] is
    # evolved as an Ornstein-Uhlenbeck (mean-reverting random walk) each tick.
    # All four link parameters (bandwidth, delay, jitter, loss) are derived
    # from q via nonlinear mappings calibrated against published LTE/802.11
    # field measurements. Requires time_varying=True.
    channel_quality_variation: bool = False
    channel_quality_initial: float = 0.7      # starting quality [0=poor, 1=excellent]
    channel_quality_step: float = 0.04        # Gaussian σ of OU diffusion per 500 ms tick
    channel_quality_seed: Optional[int] = None  # RNG seed — None = non-deterministic

    # Bounds used when channel_quality_variation=True
    cqv_max_capacity_bps: int = 50_000_000    # bandwidth at q=1.0  (50 Mbps)
    cqv_min_capacity_bps: int = 1_000_000     # bandwidth at q=0.0  ( 1 Mbps)
    cqv_max_delay_ms: float = 80.0            # one-way delay at q=0.0 (ms)
    cqv_min_delay_ms: float = 5.0             # one-way delay at q=1.0 (ms)
    cqv_max_jitter_ms: float = 25.0           # jitter (netem σ) at q=0.0 (ms)
    cqv_min_jitter_ms: float = 1.0            # jitter (netem σ) at q=1.0 (ms)
    cqv_max_loss_rate: float = 0.15           # loss rate at q=0.0  (15 %)
    cqv_min_loss_rate: float = 0.001          # loss rate at q=1.0  ( 0.1 %)

    def get_capacity_at_time(self, elapsed_time: float) -> int:
        """
        Get link capacity at a given time (for time-varying links).
        
        Args:
            elapsed_time: Time elapsed since simulation start (seconds)
            
        Returns:
            Capacity in bits per second
        """
        if not self.time_varying:
            return self.capacity_bps
        
        if self.capacity_variation_function:
            return self.capacity_variation_function(elapsed_time)
        
        # Default: sinusoidal variation
        import math
        phase = (elapsed_time / self.variation_period) * 2 * math.pi
        variation = 1.0 + self.variation_amplitude * math.sin(phase)
        return int(self.capacity_bps * variation)
    
    def get_transmission_delay(self, packet_size_bytes: int) -> float:
        """
        Calculate transmission delay for a packet.
        
        Args:
            packet_size_bytes: Size of packet in bytes
            
        Returns:
            Transmission delay in seconds
        """
        bits = packet_size_bytes * 8
        return bits / self.capacity_bps
    
    def get_total_delay(self, packet_size_bytes: int = 1500) -> float:
        """
        Get total one-way delay (propagation + transmission).
        
        Args:
            packet_size_bytes: Size of packet in bytes
            
        Returns:
            Total delay in seconds
        """
        return self.propagation_delay + self.get_transmission_delay(packet_size_bytes)
