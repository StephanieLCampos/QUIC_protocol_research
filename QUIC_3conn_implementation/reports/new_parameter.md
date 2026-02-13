# Loss Reduction Factor (Beta): Deep Dive

## Executive Summary

The **Loss Reduction Factor** (also known as **beta** or **β_cubic**) is a critical parameter in CUBIC congestion control that determines how aggressively the protocol reduces its sending rate when packet loss is detected. This document explains what the parameter does, why it was chosen for this research, and how it affects network performance.

---

## What Is the Loss Reduction Factor?

### Definition

The Loss Reduction Factor (β) is the **multiplicative decrease factor** used by congestion control algorithms when they detect packet loss. It determines what fraction of the congestion window is retained after a loss event.

```
New Congestion Window = Current Congestion Window × β
```

### Example

If the current congestion window is 100 packets and β = 0.7:
```
After packet loss: New Window = 100 × 0.7 = 70 packets
```

The sender retains 70% of its sending capacity and must rebuild from there.

---

## How It Works in CUBIC

### The CUBIC Congestion Control Algorithm

CUBIC is the default congestion control algorithm for:
- Linux (since kernel 2.6.19)
- aioquic (the QUIC library used in this project)
- Most modern TCP/QUIC implementations

### Mathematical Formulas

When packet loss is detected, CUBIC performs these operations:

1. **Save the current window as W_max**:
   ```
   W_max = cwnd (current congestion window)
   ```

2. **Reduce the congestion window**:
   ```
   cwnd_new = cwnd × β_cubic
   ssthresh = cwnd × β_cubic
   ```

3. **Calculate recovery time K**:
   ```
   K = ∛(W_max × (1 - β_cubic) / C)
   ```
   Where C is a scaling constant (0.4 in CUBIC)

4. **Window growth function**:
   ```
   W_cubic(t) = C × (t - K)³ + W_max
   ```
   Where t is time since the last congestion event

### Visual Representation

```
Congestion Window
       ^
       |           ┌──────────── W_max
       |          /│
       |         / │
       |        /  │ Packet Loss Detected!
       |       /   │
       |      /    ▼
       |     /     ┌──── cwnd × β (new window)
       |    /     /│
       |   /     / │
       |  /     /  │ Recovery (cubic growth)
       | /     /   │
       |/     /    │
       └─────┴─────┴──────────────────────> Time
               K (recovery time)
```

---

## Default Values and Standards

### RFC Standards

| Specification | Default β Value | Status |
|---------------|-----------------|--------|
| RFC 5681 (Standard TCP/Reno) | 0.5 | Active |
| RFC 8312 (CUBIC) | 0.7 | Obsoleted |
| RFC 9438 (CUBIC) | 0.7 | Current |

### aioquic Implementation

```python
# From aioquic/quic/congestion/cubic.py
K_CUBIC_LOSS_REDUCTION_FACTOR = 0.7  # Default value
```

This project patches this constant at runtime to test different values.

---

## Why 0.7 Instead of 0.5?

### The Trade-off

| Factor | β = 0.5 (TCP Reno) | β = 0.7 (CUBIC) |
|--------|:------------------:|:---------------:|
| Window retention after loss | 50% | 70% |
| Throughput recovery | Slower | Faster |
| Fairness convergence | Faster | Slower |
| Aggressiveness | More aggressive | Less aggressive |
| Suitable for | Low BDP networks | High BDP networks |

**BDP** = Bandwidth-Delay Product (bandwidth × RTT)

### Why CUBIC Uses 0.7

From RFC 9438:

> "The parameter β_cubic SHOULD be set to 0.7, which is different from the multiplicative decrease factor used in RFC 5681... This design decision improves the scalability of CUBIC."

The reasoning:
1. **High-bandwidth networks**: Networks today have much higher bandwidth than when TCP Reno was designed (1990s)
2. **Scalability**: With β = 0.5, recovering from loss in a 10 Gbps network takes too long
3. **Efficiency**: Retaining more window means less wasted bandwidth during recovery
4. **Trade-off accepted**: Slower convergence to fairness is acceptable in modern networks

---

## Values Tested in This Research

### Parameter Range

| Value | Description | Behavior |
|-------|-------------|----------|
| **0.4** | Very aggressive | Drops to 40% on loss, slow recovery |
| **0.5** | TCP Reno standard | Drops to 50%, moderate recovery |
| **0.6** | Moderate | Drops to 60%, balanced |
| **0.7** | CUBIC default | Drops to 70%, fast recovery |

### Why These Values Were Chosen

1. **0.4**: Tests extremely aggressive loss response (below any standard)
2. **0.5**: Matches RFC 5681 (standard TCP) for comparison
3. **0.6**: Intermediate value between standards
4. **0.7**: Matches RFC 9438 (CUBIC standard)

The range 0.4-0.7 spans from "more aggressive than standard TCP" to "CUBIC standard", allowing observation of how different levels of aggression affect performance.

---

## Why Is This Parameter Important?

### 1. Direct Impact on Recovery Speed

```
Example: Starting window = 1000 packets, 3 consecutive losses

With β = 0.4 (aggressive):
  After loss 1: 1000 × 0.4 = 400 packets
  After loss 2:  400 × 0.4 = 160 packets
  After loss 3:  160 × 0.4 =  64 packets
  → 93.6% reduction in sending rate

With β = 0.7 (conservative):
  After loss 1: 1000 × 0.7 = 700 packets
  After loss 2:  700 × 0.7 = 490 packets
  After loss 3:  490 × 0.7 = 343 packets
  → 65.7% reduction in sending rate
```

### 2. Affects Different Applications Differently

| Application Type | Preferred β | Reasoning |
|------------------|-------------|-----------|
| File Transfer | Higher (0.6-0.7) | Maximizes throughput, tolerates some unfairness |
| Video Streaming | Medium (0.5-0.6) | Balance between throughput and stability |
| Conference Call | Depends | Jitter matters more than absolute throughput |

### 3. Interaction with Other Parameters

The Loss Reduction Factor interacts with:

| Parameter | Interaction |
|-----------|-------------|
| Initial Congestion Window | Larger ICW means more to lose on first loss event |
| Max ACK Delay | Higher delay means slower loss detection, delayed response |
| Network RTT | Higher RTT means slower recovery regardless of β |

---

## Why Was This Parameter Chosen for Research?

### Research Justification

1. **Standardized but Tunable**: RFC 9438 says β "SHOULD be" 0.7, not "MUST be" 0.7, indicating it's a tunable parameter

2. **Application-Dependent Optimal**: Different applications may benefit from different values:
   - Bulk transfers: Higher β for faster recovery
   - Real-time: Lower β for faster congestion response

3. **Under-Researched**: Most QUIC research focuses on Initial Congestion Window and RTT; loss reduction is less studied

4. **Measurable Impact**: Changes to β have observable effects on:
   - Throughput (how fast recovery occurs)
   - Jitter (stability during loss events)
   - RTT (congestion level affects queuing delay)

5. **Complements Other Parameters**:
   - ICW affects startup behavior
   - Max ACK Delay affects steady-state timing
   - Loss Reduction Factor affects loss response behavior

   Together, they cover the full lifecycle of a QUIC connection.

---

## How It's Implemented in This Project

### Runtime Patching

Since aioquic doesn't expose β as a configuration option, this project patches the constant at runtime:

```python
# From simulation/runner.py

# Store original value
from aioquic.quic.congestion import cubic as aioquic_cubic
_ORIGINAL_K_LOSS_REDUCTION_FACTOR = aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR

# Apply test value
def _apply_recovery_parameters(self):
    aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = self.loss_reduction_factor

# Restore after test
def _restore_recovery_parameters(self):
    aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = _ORIGINAL_K_LOSS_REDUCTION_FACTOR
```

### Isolation

Each simulation:
1. Sets the test value before running
2. Runs the complete simulation
3. Restores the original value in a `finally` block

This ensures each test is isolated and parameters don't leak between runs.

---

## Limitations in Localhost Testing

### Minimal Observable Effect

On localhost (127.0.0.1), the Loss Reduction Factor has **minimal observable effect** because:

1. **No real packet loss**: Localhost has 0% packet loss
2. **No loss events trigger**: Without loss, β is never applied
3. **Theoretical only**: The parameter is set but rarely activated

### What Would Be Different on Real Networks

On real networks with packet loss:

| Network Condition | β = 0.4 Effect | β = 0.7 Effect |
|-------------------|----------------|----------------|
| 1% packet loss | Frequent aggressive drops | Moderate drops, faster recovery |
| Congested link | Rapid backing off | Maintains more throughput |
| Competing flows | Faster fairness convergence | Higher individual throughput |

### Value of Including It

Despite limited localhost impact, including this parameter:
1. Documents the complete research methodology
2. Enables future real-network testing
3. Shows understanding of QUIC congestion control
4. Provides baseline for comparison with loss-inducing tests

---

## Results from This Research

### Optimal Configurations Found

| Application Type | Optimal β | Optimized Metric |
|------------------|-----------|------------------|
| Video Streaming | 0.5 | RTT: 2.45 ms |
| File Transfer | 0.6 | Throughput: 41.21 MB/s |
| Conference Call | 0.6 | Jitter: 0.547 ms |

### Interpretation

Since localhost has no packet loss, these results primarily reflect:
- Interaction effects with other parameters
- Minor overhead differences in congestion control paths
- Statistical variation in measurements

For definitive conclusions about Loss Reduction Factor impact, real-network testing with actual packet loss would be required.

---

## Summary

### What It Is
The Loss Reduction Factor (β) determines how much of the congestion window is retained when packet loss occurs.

### What It Does
```
New Window = Current Window × β
```
Higher β = Less aggressive = Retains more sending capacity after loss.

### Why It's Important
- Directly affects recovery speed from congestion
- Impacts throughput, fairness, and stability
- Different optimal values for different applications

### Why It Was Chosen
- Completes the three-parameter study of QUIC congestion control
- Under-researched compared to other QUIC parameters
- Tunable per RFC 9438 (SHOULD, not MUST)
- Enables future real-network research

### Values Tested
- 0.4, 0.5, 0.6, 0.7 (aggressive to conservative)

---

## References

- [RFC 9438 - CUBIC for Fast and Long-Distance Networks](https://datatracker.ietf.org/doc/rfc9438/) (Current standard)
- [RFC 8312 - CUBIC for Fast Long-Distance Networks](https://datatracker.ietf.org/doc/html/rfc8312) (Obsoleted)
- [RFC 5681 - TCP Congestion Control](https://datatracker.ietf.org/doc/html/rfc5681) (Standard TCP)
- [CUBIC: A New TCP-Friendly High-Speed TCP Variant (Original Paper)](https://www.cs.princeton.edu/courses/archive/fall16/cos561/papers/Cubic08.pdf)
- [aioquic GitHub Repository](https://github.com/aiortc/aioquic)
