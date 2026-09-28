"""
Configuration model for the wireless bottleneck.

Defines `BottleneckConfig`, the single description of an emulated link, plus
the `LossModel` and `QueueDiscipline` enumerations it draws on.

A link is characterised along four axes:
    capacity      link rate in bits per second, optionally asymmetric
    delay         one-way propagation delay (RTT is twice this)
    loss          rate plus a model: uniform random, or Gilbert-Elliott bursts
    queueing      buffer depth and discipline (FIFO, RED, CoDel, PIE)

Time-varying links are supported for mobility and fading studies: when
`time_varying` is set, capacity follows a sinusoid of the configured period and
amplitude, or a caller-supplied function if one is given.

This class is a pure description and performs no enforcement; it is consumed by
WirelessBottleneck, which translates it into Linux tc commands. Note that not
every field declared here is expressed in the tc configuration that the current
bottleneck implementation emits (the PIE and RED tuning fields in particular
belong to a qdisc path that is no longer invoked); see bottleneck.py.

Connections:
    Imports from: standard library only (dataclasses, typing, enum)
    Imported by:  .bottleneck, .scenarios, wireless_bottleneck/__init__.py
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
        
        # Sinusoidal variation is the default model for fading and mobility:
        # capacity oscillates smoothly about its nominal value by
        # +/- variation_amplitude over variation_period seconds. A caller
        # needing a different profile supplies capacity_variation_function.
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
