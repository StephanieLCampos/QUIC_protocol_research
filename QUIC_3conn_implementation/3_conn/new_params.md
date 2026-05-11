# New Parameters Available for Mid-Connection Tuning

This document lists all aioquic parameters that can be changed mid-connection and will affect the current connection's behavior.

## Overview

These parameters are **continuously read** by the congestion control and loss detection algorithms. Changing them mid-connection will affect the connection's behavior on the next relevant event.

---

## Available Dynamic Parameters

### From Cubic Congestion Control

**File:** `aioquic/quic/congestion/cubic.py`

| Parameter | Default | What It Controls | When Effect Occurs |
|-----------|---------|------------------|-------------------|
| `K_CUBIC_LOSS_REDUCTION_FACTOR` | 0.7 | How much cwnd reduces on loss | Next loss event |
| `K_CUBIC_C` | 0.4 | Cubic curve aggressiveness | Next cwnd calculation |
| `K_MINIMUM_WINDOW` | 2 | Minimum cwnd floor (packets) | Next cwnd adjustment |
| `K_CUBIC_MAX_IDLE_TIME` | 2 | Seconds idle before cwnd reset | Next packet send |

### From Recovery/Loss Detection

**File:** `aioquic/quic/recovery.py`

| Parameter | Default | What It Controls | When Effect Occurs |
|-----------|---------|------------------|-------------------|
| `K_PACKET_THRESHOLD` | 3 | Packets before declaring loss | Next loss detection |
| `K_TIME_THRESHOLD` | 9/8 | Time multiplier for loss delay | Next loss detection |

### From Base Congestion Control

**File:** `aioquic/quic/congestion/base.py`

| Parameter | Default | What It Controls | When Effect Occurs |
|-----------|---------|------------------|-------------------|
| `K_GRANULARITY` | 0.001 | Timer granularity (1ms) | Next timer calculation |

---

## How To Change Parameters Mid-Connection

```python
from aioquic.quic.congestion import cubic
from aioquic.quic import recovery

# Congestion control parameters
cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = 0.6  # Reduce less on loss
cubic.K_CUBIC_C = 0.3                       # Less aggressive growth
cubic.K_MINIMUM_WINDOW = 4                  # Higher floor (4 packets)
cubic.K_CUBIC_MAX_IDLE_TIME = 5             # Longer before idle reset

# Loss detection parameters
recovery.K_PACKET_THRESHOLD = 4             # Wait for 4 packets before loss
recovery.K_TIME_THRESHOLD = 1.5             # More time before declaring loss
```

---

## Detailed Parameter Descriptions

### K_CUBIC_LOSS_REDUCTION_FACTOR

**Purpose:** Controls how much the congestion window is reduced when packet loss is detected.

**Formula:** `new_cwnd = cwnd × K_CUBIC_LOSS_REDUCTION_FACTOR`

**Visual:**
```
cwnd
  │
  │         Loss here
  │            ↓
  │    ╱╲     ╱╲
  │   ╱  ╲   ╱  ╲
  │  ╱    ╲_╱    ╲
  │ ╱                    factor = 0.5: drops to 50%
  │╱                     factor = 0.7: drops to 70%
  └─────────────────────────────►
```

**Values:**
| Value | Behavior | Use Case |
|-------|----------|----------|
| 0.4 | Aggressive reduction | Conservative, congestion-sensitive |
| 0.5 | Standard TCP-like | Balanced |
| 0.6 | Moderate reduction | Slightly aggressive |
| 0.7 | Gentle reduction (default) | Fast recovery, loss-tolerant |
| 0.8 | Very gentle | High-bandwidth, low-loss networks |

**Code location:**
```python
# In cubic.py on_packets_lost()
new_ssthresh = max(
    int(flight_size * K_CUBIC_LOSS_REDUCTION_FACTOR),
    K_MINIMUM_WINDOW * self._max_datagram_size,
)
```

---

### K_CUBIC_C

**Purpose:** Controls the aggressiveness of the cubic growth curve during congestion avoidance.

**Formula:** Part of `W_cubic(t) = C × (t - K)³ + W_max`

**Visual:**
```
cwnd
  │
  │                    C = 0.6 (aggressive)
  │                  ╱
  │               ╱
  │            ╱    C = 0.4 (default)
  │         ╱    ╱
  │      ╱    ╱
  │   ╱    ╱       C = 0.2 (conservative)
  │╱    ╱       ╱
  └─────────────────────────────►
         time after loss recovery
```

**Values:**
| Value | Behavior | Use Case |
|-------|----------|----------|
| 0.2 | Slow, cautious growth | Congested networks, fairness |
| 0.3 | Moderate growth | Shared bottlenecks |
| 0.4 | Standard (default) | General purpose |
| 0.5 | Faster growth | High-bandwidth networks |
| 0.6 | Aggressive growth | Low-latency, high-bandwidth |

**Code location:**
```python
# In cubic.py W_cubic()
target_segments = K_CUBIC_C * (t - self.K) ** 3 + (W_max_segments)
```

---

### K_MINIMUM_WINDOW

**Purpose:** Sets the absolute floor for the congestion window. cwnd will never go below this value.

**Formula:** `min_cwnd = K_MINIMUM_WINDOW × max_datagram_size`

**Visual:**
```
cwnd
  │
  │
  │    ╲
  │     ╲  Severe loss
  │      ╲
  │       ╲
  │────────────── K_MINIMUM_WINDOW = 4 (floor at 4800 bytes)
  │
  │────────────── K_MINIMUM_WINDOW = 2 (floor at 2400 bytes)
  │
  └─────────────────────────────►
```

**Values:**
| Value | Floor (bytes) | Use Case |
|-------|---------------|----------|
| 2 | 2,400 | Default, most conservative |
| 4 | 4,800 | Guaranteed minimum throughput |
| 6 | 7,200 | Higher minimum for critical apps |
| 10 | 12,000 | Aggressive minimum guarantee |

**Code location:**
```python
# In cubic.py on_packets_lost()
self.congestion_window = max(
    self.ssthresh, K_MINIMUM_WINDOW * self._max_datagram_size
)
```

---

### K_CUBIC_MAX_IDLE_TIME

**Purpose:** If no ACKs received for this many seconds, reset cwnd to initial window (connection went idle).

**Visual:**
```
Activity:  ████████░░░░░░░░░░░░░░████████
                   │              │
                   └──── idle ────┘

If idle >= K_CUBIC_MAX_IDLE_TIME:
    cwnd resets to K_INITIAL_WINDOW
```

**Values:**
| Value | Behavior | Use Case |
|-------|----------|----------|
| 1 | Quick reset after 1s idle | Bursty traffic |
| 2 | Default | General purpose |
| 5 | Patient, keep cwnd longer | Sporadic traffic |
| 10 | Very patient | Long gaps between activity |

**Code location:**
```python
# In cubic.py on_packet_sent()
elapsed_idle = packet.sent_time - self.last_ack
if elapsed_idle >= K_CUBIC_MAX_IDLE_TIME:
    self.reset()
```

---

### K_PACKET_THRESHOLD

**Purpose:** Number of packets that must be acknowledged after a packet before declaring it lost.

**Visual:**
```
Packets:  1  2  3  4  5  6  7  8  9
Sent:     ✓  ✓  ✓  ✓  ✓  ✓  ✓  ✓  ✓
ACKed:    ✓  ?  ✓  ✓  ✓
                ↑  ↑  ↑
                3 packets ACKed after packet 2

K_PACKET_THRESHOLD = 3: Packet 2 declared LOST
K_PACKET_THRESHOLD = 5: Still waiting (only 3 later ACKs)
```

**Values:**
| Value | Behavior | Use Case |
|-------|----------|----------|
| 2 | Fast loss detection | Low-latency requirements |
| 3 | Standard (default) | Balanced |
| 4 | Patient | Networks with reordering |
| 5 | Very patient | High-reordering networks |

**Code location:**
```python
# In recovery.py _detect_loss()
packet_threshold = space.largest_acked_packet - K_PACKET_THRESHOLD
```

---

### K_TIME_THRESHOLD

**Purpose:** Multiplier for RTT to determine time-based loss detection. Packet is lost if not ACKed within `RTT × K_TIME_THRESHOLD`.

**Formula:** `loss_delay = K_TIME_THRESHOLD × max(latest_rtt, smoothed_rtt)`

**Visual:**
```
K_TIME_THRESHOLD = 1.125 (9/8, default):
  RTT = 40ms → loss_delay = 45ms

K_TIME_THRESHOLD = 1.5:
  RTT = 40ms → loss_delay = 60ms

K_TIME_THRESHOLD = 2.0:
  RTT = 40ms → loss_delay = 80ms

Timeline:
  Packet sent ────────[loss_delay]────────► Declared lost
```

**Values:**
| Value | Behavior | Use Case |
|-------|----------|----------|
| 1.0 | Aggressive (RTT exactly) | Low-jitter networks |
| 1.125 | Standard (default) | General purpose |
| 1.5 | Patient | High-jitter networks |
| 2.0 | Very patient | Satellite, variable delay |

**Code location:**
```python
# In recovery.py _detect_loss()
loss_delay = K_TIME_THRESHOLD * (
    max(self._rtt_latest, self._rtt_smoothed)
    if self._rtt_initialized
    else self._rtt_initial
)
```

---

## Suggested Values for Different Application Types

### Video Streaming
```python
K_CUBIC_LOSS_REDUCTION_FACTOR = 0.6  # Moderate reduction
K_CUBIC_C = 0.4                       # Standard growth
K_MINIMUM_WINDOW = 4                  # Ensure minimum quality
K_PACKET_THRESHOLD = 3                # Standard detection
K_TIME_THRESHOLD = 1.125              # Standard timing
```

### File Transfer
```python
K_CUBIC_LOSS_REDUCTION_FACTOR = 0.7  # Quick recovery
K_CUBIC_C = 0.5                       # Aggressive growth
K_MINIMUM_WINDOW = 2                  # Can go low, throughput matters
K_PACKET_THRESHOLD = 3                # Standard detection
K_TIME_THRESHOLD = 1.125              # Standard timing
```

### Conference Call (Real-Time)
```python
K_CUBIC_LOSS_REDUCTION_FACTOR = 0.5  # Conservative
K_CUBIC_C = 0.3                       # Smooth growth
K_MINIMUM_WINDOW = 6                  # Protect audio quality
K_PACKET_THRESHOLD = 2                # Fast loss detection
K_TIME_THRESHOLD = 1.0                # Quick response
```

---

## Adding New Parameters to Your Grid Search

### Step 1: Update parameters.py

```python
@dataclass
class GridSearchParams:
    """Parameter values for grid search."""

    # Existing parameters
    initial_cw_values: List[int] = None
    max_ack_delay_values: List[float] = None
    loss_factor_values: List[float] = None

    # NEW dynamic parameters
    cubic_c_values: List[float] = None
    minimum_window_values: List[int] = None
    packet_threshold_values: List[int] = None

    def __post_init__(self):
        if self.initial_cw_values is None:
            self.initial_cw_values = [12000, 36000, 72000, 120000]
        if self.max_ack_delay_values is None:
            self.max_ack_delay_values = [0.002, 0.010, 0.025, 0.050]
        if self.loss_factor_values is None:
            self.loss_factor_values = [0.4, 0.5, 0.6, 0.7]

        # NEW defaults
        if self.cubic_c_values is None:
            self.cubic_c_values = [0.2, 0.4, 0.6]
        if self.minimum_window_values is None:
            self.minimum_window_values = [2, 4, 6]
        if self.packet_threshold_values is None:
            self.packet_threshold_values = [2, 3, 4]
```

### Step 2: Update runner.py

```python
from aioquic.quic.congestion import cubic as aioquic_cubic
from aioquic.quic import recovery as aioquic_recovery

class SimulationRunner:
    def __init__(
        self,
        application_type: str,
        initial_cw: int,
        max_ack_delay: float,
        loss_reduction_factor: float,
        cubic_c: float = 0.4,           # NEW
        minimum_window: int = 2,         # NEW
        packet_threshold: int = 3,       # NEW
        settings: Optional[Settings] = None,
    ):
        self.application_type = application_type
        self.initial_cw = initial_cw
        self.max_ack_delay = max_ack_delay
        self.loss_reduction_factor = loss_reduction_factor
        self.cubic_c = cubic_c                     # NEW
        self.minimum_window = minimum_window       # NEW
        self.packet_threshold = packet_threshold   # NEW
        self.settings = settings or DEFAULT_SETTINGS

    def _apply_recovery_parameters(self):
        """Apply all congestion control parameters."""
        max_datagram_size = 1200
        initial_window_packets = self.initial_cw // max_datagram_size

        # Existing
        aioquic_cubic.K_INITIAL_WINDOW = initial_window_packets
        aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = self.loss_reduction_factor

        # NEW
        aioquic_cubic.K_CUBIC_C = self.cubic_c
        aioquic_cubic.K_MINIMUM_WINDOW = self.minimum_window
        aioquic_recovery.K_PACKET_THRESHOLD = self.packet_threshold
```

---

## Summary

### 6 Parameters Available for Dynamic Tuning

| Parameter | Module | Default | Controls |
|-----------|--------|---------|----------|
| `K_CUBIC_LOSS_REDUCTION_FACTOR` | cubic | 0.7 | cwnd reduction on loss |
| `K_CUBIC_C` | cubic | 0.4 | Growth curve aggressiveness |
| `K_MINIMUM_WINDOW` | cubic | 2 | Minimum cwnd floor |
| `K_CUBIC_MAX_IDLE_TIME` | cubic | 2 | Idle detection threshold |
| `K_PACKET_THRESHOLD` | recovery | 3 | Packet-based loss detection |
| `K_TIME_THRESHOLD` | recovery | 1.125 | Time-based loss detection |

### Research Potential

These parameters can be:
1. **Set differently per connection** based on application type
2. **Changed mid-connection** by ML for real-time adaptation
3. **Tuned to network conditions** (lossy vs stable, high vs low bandwidth)
4. **Optimized for fairness** when multiple connections share a bottleneck
