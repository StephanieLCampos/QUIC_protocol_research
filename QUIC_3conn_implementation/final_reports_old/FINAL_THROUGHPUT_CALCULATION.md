# Final Throughput Calculation: Effective Throughput (cwnd/RTT)

## Overview

This document describes the recommended throughput measurement approach for the QUIC 3-connection simulation with Q-learning optimization.

---

## The Formula

```
effective_throughput = congestion_window / RTT
```

Where:
- **congestion_window (cwnd)**: Maximum bytes allowed "in flight" at any time (bytes)
- **RTT**: Round-trip time (seconds)
- **Result**: Throughput in bytes per second

---

## Why This Formula Works

### The Congestion Control Bottleneck

In any network with congestion control, the sending rate is limited by:

```
sending_rate <= cwnd / RTT
```

This is fundamental to TCP and QUIC. The sender cannot have more than `cwnd` bytes unacknowledged at any time. Each RTT, the sender can transmit at most `cwnd` bytes worth of new data.

### Real-World Analogy

Imagine a pipe:
- **cwnd** = how much water the pipe can hold
- **RTT** = how long water takes to flow through
- **Throughput** = water delivered per second = pipe_capacity / travel_time

---

## How It Differs From Other Approaches

### Approach 1: Offered Throughput (Current)

```
offered_throughput = bytes_sent / time
```

**Problem**: Measures what the application *tried* to send, not what the network *allowed* through.

**Example**: File transfer offers 210 Mbps, but bottleneck only allows 3.6 Mbps total.

### Approach 2: Proportional Estimation

```
actual = tc_observed × (offered / total_offered)
```

**Problem**: Mathematical estimation that doesn't reflect actual congestion control behavior. If Q-learning changes cwnd, this formula doesn't capture it.

### Approach 3: Effective Throughput (Recommended)

```
actual = cwnd / RTT
```

**Advantage**: Directly reflects the congestion control state. When Q-learning changes parameters that affect cwnd, the measurement shows it immediately.

---

## Why This Is Better for Q-Learning

### Direct Parameter Impact

Q-learning tunes congestion control parameters:

| Parameter | Effect on cwnd | Effect on effective_throughput |
|-----------|---------------|-------------------------------|
| `initial_cwnd` | Sets starting cwnd | Higher = faster start |
| `max_cwnd` | Caps maximum cwnd | Lower = limits throughput |
| `ssthresh` | Triggers slow start exit | Affects cwnd growth |
| `cubic_beta` | Multiplicative decrease | Higher = less cwnd reduction on loss |

With cwnd/RTT measurement, Q-learning sees the **direct result** of its parameter choices.

### Feedback Loop

```
┌─────────────────────────────────────────────────────────────┐
│                      Q-LEARNING LOOP                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   1. Q-Learning selects parameters                         │
│          │                                                  │
│          ▼                                                  │
│   2. QUIC/CUBIC uses parameters                            │
│          │                                                  │
│          ▼                                                  │
│   3. Congestion control adjusts cwnd based on:             │
│      - Network conditions (loss, delay)                    │
│      - Parameter settings (max_cwnd, beta, etc.)           │
│          │                                                  │
│          ▼                                                  │
│   4. Effective throughput = cwnd / RTT                     │
│          │                                                  │
│          ▼                                                  │
│   5. Q-Learning receives reward based on:                  │
│      - Throughput achieved                                 │
│      - Fairness across connections                         │
│      - Latency/jitter requirements                         │
│          │                                                  │
│          ▼                                                  │
│   6. Q-Learning updates policy → back to step 1            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Clear Learning Signal

| Scenario | Proportional Method | cwnd/RTT Method |
|----------|--------------------|-----------------|
| Q-learning reduces file transfer's max_cwnd | File still "offers" 210 Mbps, appears to dominate | File's cwnd is capped, throughput visibly drops |
| Q-learning increases video's initial_cwnd | Video still offers 1.33 Mbps, same proportion | Video's cwnd grows faster, throughput increases |
| Network congestion increases | No change (based on offered) | cwnd shrinks due to loss, throughput drops |

---

## What Gets Measured

### Per Connection

| Metric | Source | Description |
|--------|--------|-------------|
| `cwnd` | `protocol._quic._loss.congestion_window` | Current congestion window (bytes) |
| `RTT` | `protocol._quic._loss._rtt_smoothed` | Smoothed RTT (seconds) |
| `effective_throughput` | `cwnd / RTT` | Achievable throughput (bytes/sec) |

### Already Collected

The simulation already collects:
- `cwnd_samples`: List of cwnd values sampled during simulation
- `rtt`: RTT measurements per sample

No new data collection needed - just a different calculation.

---

## Implementation Details

### Calculation

```python
def get_effective_throughput(self) -> float:
    """
    Calculate effective throughput based on cwnd/RTT.

    This reflects the actual throughput achievable given
    the current congestion control state.
    """
    if not self.cwnd_samples or not self.rtt_samples:
        return 0.0

    avg_cwnd = statistics.mean(self.cwnd_samples)  # bytes
    avg_rtt = statistics.mean(self.rtt_samples)    # seconds

    if avg_rtt <= 0:
        return 0.0

    return avg_cwnd / avg_rtt  # bytes per second
```

### Output Format

```json
{
  "per_connection_throughput": {
    "1": {
      "application_type": "video_streaming",
      "offered_throughput_mbps": 1.33,
      "effective_throughput_mbps": 1.25
    },
    "2": {
      "application_type": "file_transfer",
      "offered_throughput_mbps": 210.0,
      "effective_throughput_mbps": 2.22
    },
    "3": {
      "application_type": "conference_call",
      "offered_throughput_mbps": 0.11,
      "effective_throughput_mbps": 0.10
    }
  }
}
```

---

## Example Calculation

### Given

| Connection | avg_cwnd | avg_rtt |
|------------|----------|---------|
| Video | 50,000 bytes | 40 ms |
| File Transfer | 100,000 bytes | 45 ms |
| Conference | 15,000 bytes | 38 ms |

### Calculation

```
Video:
  effective = 50,000 / 0.040 = 1,250,000 bytes/sec
            = 1,250,000 × 8 / 1,000,000 = 10.0 Mbps

File Transfer:
  effective = 100,000 / 0.045 = 2,222,222 bytes/sec
            = 2,222,222 × 8 / 1,000,000 = 17.8 Mbps

Conference:
  effective = 15,000 / 0.038 = 394,737 bytes/sec
            = 394,737 × 8 / 1,000,000 = 3.16 Mbps
```

---

## Validation

### Sum Should Approximate tc Observed

The sum of effective throughputs should be close to (but not exceed) the tc observed throughput:

```
sum(effective_throughput) ≈ tc_observed_throughput
```

Small differences are expected due to:
- Protocol overhead
- Timing of cwnd samples
- RTT variation

### Effective <= Offered

For each connection:

```
effective_throughput <= offered_throughput
```

A connection cannot achieve more than it tried to send.

---

## Summary

| Aspect | Description |
|--------|-------------|
| **What** | Measure throughput as `cwnd / RTT` |
| **Why** | Reflects actual congestion control state |
| **Better for Q-learning** | Direct feedback on parameter changes |
| **What changes** | One calculation in result.py |
| **What stays same** | Everything else (parameters, simulation, other metrics) |

---

## References

- RFC 9002 - QUIC Loss Detection and Congestion Control
- RFC 9438 - CUBIC for Fast and Long-Distance Networks
- `aioquic/quic/recovery.py` - congestion_window and RTT implementation
