"""
Bottleneck monitoring and instrumentation.

Records queue occupancy, packet drops, per-flow statistics,
and other metrics from the wireless bottleneck.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from collections import defaultdict
import statistics


@dataclass
class BottleneckMetrics:
    """Metrics collected from the wireless bottleneck."""
    
    # Time series data
    timestamps: List[float] = field(default_factory=list)
    queue_occupancy: List[int] = field(default_factory=list)  # packets in queue
    queue_occupancy_bytes: List[int] = field(default_factory=list)  # bytes in queue
    instantaneous_capacity: List[int] = field(default_factory=list)  # bps
    
    # Packet statistics
    total_packets_arrived: int = 0
    total_packets_dropped: int = 0
    total_packets_transmitted: int = 0
    total_bytes_arrived: int = 0
    total_bytes_dropped: int = 0
    total_bytes_transmitted: int = 0
    
    # Per-flow statistics
    flow_packets_transmitted: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    flow_bytes_transmitted: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    flow_packets_dropped: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    # Queue delay statistics
    queue_delays: List[float] = field(default_factory=list)  # seconds
    
    # Drop statistics by cause
    drops_by_overflow: int = 0
    drops_by_red: int = 0
    drops_by_codel: int = 0
    drops_by_loss_model: int = 0
    
    def record_queue_state(self, timestamp: float, occupancy: int, occupancy_bytes: int, capacity: int):
        """Record queue occupancy at a point in time."""
        self.timestamps.append(timestamp)
        self.queue_occupancy.append(occupancy)
        self.queue_occupancy_bytes.append(occupancy_bytes)
        self.instantaneous_capacity.append(capacity)
    
    def record_packet_arrival(self, flow_id: str, packet_size: int):
        """Record a packet arriving at the bottleneck."""
        self.total_packets_arrived += 1
        self.total_bytes_arrived += packet_size
    
    def record_packet_drop(self, flow_id: str, packet_size: int, reason: str = "overflow"):
        """Record a packet being dropped."""
        self.total_packets_dropped += 1
        self.total_bytes_dropped += packet_size
        self.flow_packets_dropped[flow_id] += 1
        
        if reason == "overflow":
            self.drops_by_overflow += 1
        elif reason == "red":
            self.drops_by_red += 1
        elif reason == "codel":
            self.drops_by_codel += 1
        elif reason == "loss_model":
            self.drops_by_loss_model += 1
    
    def record_packet_transmission(self, flow_id: str, packet_size: int, queue_delay: float):
        """Record a packet being transmitted."""
        self.total_packets_transmitted += 1
        self.total_bytes_transmitted += packet_size
        self.flow_packets_transmitted[flow_id] += 1
        self.flow_bytes_transmitted[flow_id] += packet_size
        self.queue_delays.append(queue_delay)
    
    def get_packet_loss_rate(self) -> float:
        """Calculate overall packet loss rate."""
        if self.total_packets_arrived == 0:
            return 0.0
        return self.total_packets_dropped / self.total_packets_arrived
    
    def get_byte_loss_rate(self) -> float:
        """Calculate overall byte loss rate."""
        if self.total_bytes_arrived == 0:
            return 0.0
        return self.total_bytes_dropped / self.total_bytes_arrived
    
    def get_flow_share(self, flow_id: str) -> float:
        """
        Get a flow's share of transmitted bytes.
        
        Returns:
            Fraction of total transmitted bytes (0.0 to 1.0)
        """
        if self.total_bytes_transmitted == 0:
            return 0.0
        return self.flow_bytes_transmitted[flow_id] / self.total_bytes_transmitted
    
    def get_average_queue_occupancy(self) -> float:
        """Get average queue occupancy in packets."""
        if not self.queue_occupancy:
            return 0.0
        return statistics.mean(self.queue_occupancy)
    
    def get_max_queue_occupancy(self) -> int:
        """Get maximum queue occupancy in packets."""
        if not self.queue_occupancy:
            return 0
        return max(self.queue_occupancy)
    
    def get_average_queue_delay(self) -> float:
        """Get average queueing delay in seconds."""
        if not self.queue_delays:
            return 0.0
        return statistics.mean(self.queue_delays)
    
    def get_max_queue_delay(self) -> float:
        """Get maximum queueing delay in seconds."""
        if not self.queue_delays:
            return 0.0
        return max(self.queue_delays)
    
    def get_flow_fairness_index(self) -> float:
        """
        Calculate Jain's fairness index across flows.
        
        Returns:
            Fairness index (1.0 = perfectly fair, 0.0 = completely unfair)
        """
        if not self.flow_bytes_transmitted:
            return 1.0
        
        shares = list(self.flow_bytes_transmitted.values())
        n = len(shares)
        
        if n == 0:
            return 1.0
        
        sum_shares = sum(shares)
        sum_squares = sum(x * x for x in shares)
        
        if sum_squares == 0:
            return 1.0
        
        return (sum_shares ** 2) / (n * sum_squares)
    
    def summary(self) -> Dict[str, any]:
        """Generate summary statistics."""
        return {
            "total_packets": {
                "arrived": self.total_packets_arrived,
                "transmitted": self.total_packets_transmitted,
                "dropped": self.total_packets_dropped,
                "loss_rate": self.get_packet_loss_rate(),
            },
            "total_bytes": {
                "arrived": self.total_bytes_arrived,
                "transmitted": self.total_bytes_transmitted,
                "dropped": self.total_bytes_dropped,
                "loss_rate": self.get_byte_loss_rate(),
            },
            "queue": {
                "avg_occupancy_packets": self.get_average_queue_occupancy(),
                "max_occupancy_packets": self.get_max_queue_occupancy(),
                "avg_delay_ms": self.get_average_queue_delay() * 1000,
                "max_delay_ms": self.get_max_queue_delay() * 1000,
            },
            "drops": {
                "overflow": self.drops_by_overflow,
                "red": self.drops_by_red,
                "codel": self.drops_by_codel,
                "loss_model": self.drops_by_loss_model,
            },
            "flows": {
                flow_id: {
                    "packets_transmitted": self.flow_packets_transmitted[flow_id],
                    "bytes_transmitted": self.flow_bytes_transmitted[flow_id],
                    "packets_dropped": self.flow_packets_dropped[flow_id],
                    "share": self.get_flow_share(flow_id),
                }
                for flow_id in self.flow_bytes_transmitted.keys()
            },
            "fairness_index": self.get_flow_fairness_index(),
        }


class BottleneckMonitor:
    """
    Real-time monitor for the wireless bottleneck.
    
    Periodically samples queue state and records events.
    """
    
    def __init__(self, sampling_interval: float = 0.1):
        """
        Initialize the monitor.
        
        Args:
            sampling_interval: How often to sample queue state (seconds)
        """
        self.sampling_interval = sampling_interval
        self.metrics = BottleneckMetrics()
        self.start_time: Optional[float] = None
        self.last_sample_time: Optional[float] = None
    
    def start(self):
        """Start monitoring."""
        self.start_time = time.time()
        self.last_sample_time = self.start_time
    
    def should_sample(self) -> bool:
        """Check if it's time to sample queue state."""
        if self.last_sample_time is None:
            return True
        return time.time() - self.last_sample_time >= self.sampling_interval
    
    def sample_queue_state(self, occupancy: int, occupancy_bytes: int, capacity: int):
        """Sample current queue state."""
        current_time = time.time()
        elapsed = current_time - self.start_time if self.start_time else 0
        self.metrics.record_queue_state(elapsed, occupancy, occupancy_bytes, capacity)
        self.last_sample_time = current_time
    
    def get_metrics(self) -> BottleneckMetrics:
        """Get collected metrics."""
        return self.metrics
    
    def reset(self):
        """Reset all metrics."""
        self.metrics = BottleneckMetrics()
        self.start_time = None
        self.last_sample_time = None
