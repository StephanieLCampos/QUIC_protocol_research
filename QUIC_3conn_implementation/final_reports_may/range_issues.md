# Parameter Value Analysis for QUIC Congestion Control

**Date:** May 12, 2026
**Purpose:** Analyze whether initial parameter values align with each connection's optimization goal

---

## Executive Summary

Analysis reveals that the initial parameter values for **Video Streaming** and **File Transfer** appear to be **inverted** relative to their optimization goals. The **Conference Call** values are correctly configured.

| Connection | Goal | Current Config | Assessment |
|------------|------|----------------|------------|
| Video Streaming | Low Latency | High retention, aggressive growth | **INVERTED** |
| File Transfer | High Throughput | Aggressive reduction, conservative growth | **INVERTED** |
| Conference Call | Low Jitter | Balanced, stable values | **CORRECT** |

---

## Parameter Effects Reference

### loss_reduction_factor (0.3 - 0.7)
The multiplicative factor applied to cwnd after loss detection (CUBIC's beta parameter).

| Value | Effect | Best For |
|-------|--------|----------|
| **0.3 (Low)** | Aggressive reduction: cwnd drops to 30% after loss | Low Latency (clears queues fast) |
| **0.5 (Medium)** | Balanced reduction: cwnd drops to 50% after loss | Low Jitter (stable) |
| **0.7 (High)** | Conservative reduction: cwnd drops to 70% after loss | High Throughput (maintains cwnd) |

**Intuition:** After detecting packet loss, how much should we reduce our sending rate?
- Low latency needs aggressive reduction to drain queues quickly
- High throughput needs conservative reduction to maintain high sending rate

---

### cubic_c (0.2 - 0.4)
The CUBIC scaling constant controlling cwnd growth aggressiveness.

| Value | Effect | Best For |
|-------|--------|----------|
| **0.2 (Low)** | Slow, conservative cwnd growth | Low Latency, Low Jitter (avoids queue buildup) |
| **0.3 (Medium)** | Moderate growth | Balanced |
| **0.4 (High)** | Fast, aggressive cwnd growth | High Throughput (reaches capacity faster) |

**Intuition:** How quickly should we increase our sending rate after recovery?
- Low latency needs slow growth to avoid building queues
- High throughput needs fast growth to maximize utilization

---

### minimum_window (2 - 4)
The floor for cwnd - it never drops below this value (in packets).

| Value | Effect | Best For |
|-------|--------|----------|
| **2 (Low)** | Can drop to very small cwnd | Low Latency (responsive to congestion) |
| **4 (High)** | Maintains higher cwnd floor | High Throughput, Low Jitter (stable floor) |

**Intuition:** What's the minimum amount of data we should keep in flight?
- Low latency benefits from ability to drop very low
- High throughput and low jitter benefit from stable minimum

---

### packet_threshold (3 - 4)
Number of duplicate ACKs before declaring packet loss (fast retransmit threshold).

| Value | Effect | Best For |
|-------|--------|----------|
| **3 (Low)** | Faster loss detection | Low Latency (quick response) |
| **4 (High)** | Slower, more conservative detection | High Throughput (fewer false positives) |

**Intuition:** How many duplicate ACKs should we wait before assuming loss?
- Low latency needs fast detection to respond quickly
- High throughput may prefer fewer false positives from reordering

---

## Current Configuration Analysis

### Video Streaming (Connection 1) - Goal: LOW LATENCY

**Current Values:**
```
loss_reduction_factor: 0.7
cubic_c: 0.4
minimum_window: 2
packet_threshold: 4
```

| Parameter | Current | Expected for Low Latency | Analysis |
|-----------|---------|-------------------------|----------|
| loss_reduction_factor | 0.7 (conservative) | 0.3-0.5 (aggressive) | **WRONG** - Keeps cwnd high, builds queues |
| cubic_c | 0.4 (aggressive) | 0.2-0.3 (conservative) | **WRONG** - Fast growth builds queues |
| minimum_window | 2 (low) | 2 (low) | CORRECT |
| packet_threshold | 4 (slow) | 3 (fast) | **WRONG** - Slow detection delays response |

**Problem:** These values prioritize maintaining high cwnd and growing aggressively, which is the opposite of what low latency requires. High cwnd = more data in flight = more queuing delay = higher latency.

**For Low Latency, You Want:**
- Aggressive cwnd reduction after loss (drain queues)
- Conservative cwnd growth (avoid filling queues)
- Fast loss detection (respond quickly)

---

### File Transfer (Connection 2) - Goal: HIGH THROUGHPUT

**Current Values:**
```
loss_reduction_factor: 0.3
cubic_c: 0.2
minimum_window: 4
packet_threshold: 3
```

| Parameter | Current | Expected for High Throughput | Analysis |
|-----------|---------|------------------------------|----------|
| loss_reduction_factor | 0.3 (aggressive) | 0.6-0.7 (conservative) | **WRONG** - Drops cwnd too much |
| cubic_c | 0.2 (conservative) | 0.3-0.4 (aggressive) | **WRONG** - Grows too slowly |
| minimum_window | 4 (high) | 4 (high) | CORRECT |
| packet_threshold | 3 (fast) | 3-4 (either) | OK |

**Problem:** These values aggressively cut cwnd after loss and grow slowly, severely limiting throughput. This is the opposite of what high throughput requires.

**For High Throughput, You Want:**
- Conservative cwnd reduction (keep cwnd high)
- Aggressive cwnd growth (reach capacity fast)
- High minimum window (maintain throughput floor)

---

### Conference Call (Connection 3) - Goal: LOW JITTER

**Current Values:**
```
loss_reduction_factor: 0.5
cubic_c: 0.2
minimum_window: 4
packet_threshold: 3
```

| Parameter | Current | Expected for Low Jitter | Analysis |
|-----------|---------|------------------------|----------|
| loss_reduction_factor | 0.5 (balanced) | 0.5 (balanced) | CORRECT |
| cubic_c | 0.2 (conservative) | 0.2 (conservative) | CORRECT |
| minimum_window | 4 (stable) | 4 (stable) | CORRECT |
| packet_threshold | 3 (fast) | 3 (consistent) | CORRECT |

**Assessment:** These values are well-suited for low jitter. Balanced reduction and conservative growth avoid large cwnd swings, resulting in stable, consistent latency.

---

## Recommended Configuration

Based on congestion control theory and optimization goals:

### Video Streaming (Low Latency)
```
loss_reduction_factor: 0.3  # Aggressive reduction to clear queues
cubic_c: 0.2                # Conservative growth to avoid queue buildup
minimum_window: 2           # Allow small cwnd for responsiveness
packet_threshold: 3         # Fast loss detection
```

### File Transfer (High Throughput)
```
loss_reduction_factor: 0.7  # Conservative reduction to maintain cwnd
cubic_c: 0.4                # Aggressive growth to maximize throughput
minimum_window: 4           # High floor for sustained throughput
packet_threshold: 3         # Fast detection for quick recovery
```

### Conference Call (Low Jitter)
```
loss_reduction_factor: 0.5  # Balanced (no change needed)
cubic_c: 0.2                # Conservative (no change needed)
minimum_window: 4           # Stable floor (no change needed)
packet_threshold: 3         # Consistent (no change needed)
```

---

## Summary of Required Changes

| Connection | Parameter | Current | Recommended | Change |
|------------|-----------|---------|-------------|--------|
| Video Streaming | loss_reduction_factor | 0.7 | **0.3** | -0.4 |
| Video Streaming | cubic_c | 0.4 | **0.2** | -0.2 |
| Video Streaming | packet_threshold | 4 | **3** | -1 |
| File Transfer | loss_reduction_factor | 0.3 | **0.7** | +0.4 |
| File Transfer | cubic_c | 0.2 | **0.4** | +0.2 |
| Conference Call | (all) | - | - | No changes |

---

## Conclusion

The Video Streaming and File Transfer configurations appear to have their values **swapped**. The current Video Streaming config is optimized for throughput, while the File Transfer config is optimized for latency. Applying the recommended changes would align each connection's parameters with its stated optimization goal.

The Q-learning agent can learn to correct these values over time, but starting with properly aligned initial values will:
1. Reduce the learning time needed
2. Provide a better baseline for comparison
3. Ensure the agent starts from a reasonable configuration
