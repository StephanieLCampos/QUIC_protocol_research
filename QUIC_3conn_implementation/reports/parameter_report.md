# QUIC Parameter Selection Report

## Executive Summary

This report identifies the three most impactful QUIC parameters for the multi-stream research project, selecting only from parameters that **natively exist in aioquic** and can be modified by changing constants or using the configuration API.

**Selected Parameters:**
1. Initial Congestion Window
2. Max ACK Delay
3. Loss Reduction Factor

## Other alternative parameters:
  | Constant                      | Value      | Effect on Localhost           |
  |-------------------------------|------------|-------------------------------|
  | K_INITIAL_WINDOW              | 10 packets | Yes - already testing         |
  | K_CUBIC_C                     | 0.4        | Yes - affects growth rate     |
  | K_CUBIC_LOSS_REDUCTION_FACTOR | 0.7        | No - needs packet loss        |
  | K_CUBIC_MAX_IDLE_TIME         | 2 sec      | Maybe - if idle periods exist |
  | K_MINIMUM_WINDOW              | 2 packets  | No - only used after loss     |

## Selection Methodology

Parameters were evaluated against four criteria:

| Criterion | Weight | Rationale |
|-----------|--------|-----------|
| Impact on Success Metrics | 40% | Direct contribution to achieving stated goals |
| Cross-Application Coverage | 25% | Effectiveness across all three transmission types |
| Research Value | 20% | Potential for meaningful insights and measurable effects |
| Implementation Feasibility | 15% | Must exist natively in aioquic |

### Success Criteria Reminder
- **File Transfer**: >90% of available bandwidth utilization
- **Video Streaming**: <50ms average latency
- **Conference Calls**: <20ms jitter

### Available Parameters in aioquic

| Parameter | Location | Default Value |
|-----------|----------|---------------|
| Initial Congestion Window | `recovery.py` → `K_INITIAL_WINDOW` | 12,000 bytes |
| Minimum Congestion Window | `recovery.py` → `K_MINIMUM_WINDOW` | 2,400 bytes |
| Loss Reduction Factor | `recovery.py` → `K_LOSS_REDUCTION_FACTOR` | 0.5 |
| Packet Threshold | `recovery.py` → `K_PACKET_THRESHOLD` | 3 |
| Time Threshold | `recovery.py` → `K_TIME_THRESHOLD` | 9/8 (1.125) |
| Granularity | `recovery.py` → `K_GRANULARITY` | 0.001s |
| Max ACK Delay | `configuration.py` → `max_ack_delay` | 0.025s |
| ACK Delay Exponent | `configuration.py` → `ack_delay_exponent` | 3 |
| Idle Timeout | `configuration.py` → `idle_timeout` | 60s |

**Note**: Max Congestion Window does NOT exist in aioquic and was excluded from consideration.

---

## Parameter 1: Initial Congestion Window

### Definition
The Initial Congestion Window (IW) determines how many bytes can be in flight immediately after connection establishment, before any ACKs are received.

**Location**: `src/aioquic/quic/recovery.py` → `K_INITIAL_WINDOW`
**Default**: 12,000 bytes (10 × 1200 byte packets)
**Recommended Test Range**: 2,400 – 120,000 bytes (2–100 packets)

### Why Selected

#### 1. Universal Startup Impact (Score: 10/10)

The initial congestion window is the **only parameter that affects every single connection from the first byte**. All three transmission types benefit:

| Transmission Type | Impact Mechanism |
|-------------------|------------------|
| **File Transfer** | Larger IW = more data sent before first RTT completes → faster short transfers, quicker ramp to full speed |
| **Video Streaming** | Larger IW = first video frames arrive faster → reduced initial buffering, lower startup latency |
| **Conference Calls** | Larger IW = faster establishment of bidirectional flow → quicker call connection |

#### 2. Direct Contribution to Success Criteria

**File Transfer (>90% bandwidth utilization)**:
- A larger IW reduces the "slow start" phase duration
- For a 100ms RTT network, the difference between IW=10 and IW=100 packets means reaching full throughput in ~3 RTTs vs ~7 RTTs
- This can mean 30-40% higher average throughput for transfers under 10 seconds

**Video Streaming (<50ms latency)**:
- First-frame latency is dominated by connection establishment + initial data transfer
- Larger IW allows first I-frame (~50KB) to be sent in 1-2 RTTs instead of 5+
- Directly reduces time-to-first-frame by 100-400ms depending on RTT

#### 3. Research Value

The relationship between IW and performance is:
- **Predictable**: Linear relationship with initial throughput
- **Measurable**: Clear before/after comparison possible
- **Documented**: RFC 6928 provides theoretical foundation
- **Controversial**: Debate exists about optimal values (10 vs 20 vs higher)

#### 4. Implementation

```python
# In recovery.py - single constant change
K_INITIAL_WINDOW = 10 * MAX_DATAGRAM_SIZE  # Original (12,000 bytes)
K_INITIAL_WINDOW = 50 * MAX_DATAGRAM_SIZE  # Modified (60,000 bytes)
```

**Risk Assessment**: LOW
- Too large: May cause packet loss on initial burst, triggering recovery
- Too small: Unnecessarily slow startup
- Both extremes produce measurable, non-catastrophic effects

---

## Parameter 2: Max ACK Delay

### Definition
Max ACK Delay specifies the maximum time a receiver will wait before sending an acknowledgment for received packets. Lower values mean more frequent ACKs; higher values mean more batched ACKs.

**Location**: `src/aioquic/quic/configuration.py` → `max_ack_delay`
**Default**: 25ms (0.025 seconds)
**Recommended Test Range**: 1ms – 100ms

### Why Selected

#### 1. Primary Latency Control Mechanism (Score: 9/10)

Max ACK Delay directly affects the **feedback loop speed** of QUIC congestion control:

```
Effective RTT Perception = Network RTT + ACK Delay
```

| Actual RTT | ACK Delay | Perceived RTT | Impact |
|------------|-----------|---------------|--------|
| 20ms | 1ms | 21ms | Fast feedback, responsive |
| 20ms | 25ms | 45ms | Delayed feedback, sluggish |
| 20ms | 50ms | 70ms | Very slow adaptation |

This has cascading effects:
- **Congestion window growth rate**: Tied to ACK receipt rate
- **Loss detection speed**: Delayed ACKs delay loss detection
- **Jitter perception**: Variable ACK timing creates jitter

#### 2. Direct Contribution to Success Criteria

**Video Streaming (<50ms latency)**:
- Default 25ms ACK delay consumes 50% of the latency budget
- Reducing to 5ms ACK delay saves 20ms per RTT
- Faster ACKs also mean faster congestion window ramp-up during bitrate increases

**Conference Calls (<20ms jitter)**:
- ACK delay variation directly translates to jitter
- If ACKs are delayed 0-25ms randomly, this contributes up to 25ms jitter
- Consistent low ACK delay (e.g., 2ms) reduces jitter contribution to ~2ms
- This is **critical** for meeting the <20ms jitter target

**File Transfer (>90% bandwidth utilization)**:
- Lower ACK delay = faster congestion window growth
- Each ACK triggers potential window increase
- More ACKs per second = faster ramp to full throughput

#### 3. Research Value

Max ACK Delay presents interesting trade-offs:

| Low ACK Delay | High ACK Delay |
|---------------|----------------|
| ✅ Lower latency | ✅ Lower overhead |
| ✅ Faster CW growth | ✅ Better batching efficiency |
| ✅ Lower jitter | ✅ Reduced CPU usage |
| ❌ More ACK packets | ❌ Slower responsiveness |
| ❌ Higher overhead | ❌ Higher jitter |

This creates a clear optimization problem with measurable outcomes.

#### 4. Implementation

```python
from aioquic.quic.configuration import QuicConfiguration

# Direct API configuration - no source modification needed!
config = QuicConfiguration(
    is_client=True,
    max_ack_delay=0.005,  # 5ms instead of default 25ms
)
```

**Risk Assessment**: LOW
- Too low: Increased ACK overhead (but measurable)
- Too high: Increased latency and jitter (but measurable)
- No risk of connection failure or data corruption

---

## Parameter 3: Loss Reduction Factor

### Definition
The Loss Reduction Factor determines how aggressively the congestion window is reduced when packet loss is detected. It's a multiplier applied to the current congestion window upon detecting congestion.

**Location**: `src/aioquic/quic/recovery.py` → `K_LOSS_REDUCTION_FACTOR`
**Default**: 0.5 (halve the congestion window on loss)
**Recommended Test Range**: 0.3 – 0.8

### Why Selected

#### 1. Controls Throughput Recovery Behavior (Score: 8/10)

When packet loss occurs, aioquic multiplies the congestion window by this factor:

```python
# In recovery.py on_packets_lost()
self.congestion_window = max(
    int(self.congestion_window * K_LOSS_REDUCTION_FACTOR),
    K_MINIMUM_WINDOW
)
```

| Factor | Behavior | Congestion Window After Loss (from 100KB) |
|--------|----------|-------------------------------------------|
| 0.3 | Very aggressive | 30KB |
| 0.5 | Standard (default) | 50KB |
| 0.7 | Conservative | 70KB |
| 0.8 | Minimal reduction | 80KB |

#### 2. Direct Contribution to Success Criteria

**File Transfer (>90% bandwidth utilization)**:
- Loss events are inevitable on real networks
- Recovery speed after loss directly impacts average throughput
- Higher factor (0.7) = faster recovery = higher sustained throughput
- Trade-off: Too high may cause repeated losses

**Video Streaming (<50ms latency)**:
- Bitrate adaptation depends on available bandwidth estimation
- Faster recovery from loss = more stable bitrate = smoother playback
- Aggressive reduction (0.3) causes bitrate oscillations

**Conference Calls (<20ms jitter)**:
- Sudden bandwidth drops cause buffering and jitter
- Smoother congestion response = more consistent packet timing

#### 3. Research Value

Loss Reduction Factor enables study of the **aggression vs. stability trade-off**:

| More Aggressive (0.3-0.4) | Less Aggressive (0.7-0.8) |
|---------------------------|---------------------------|
| ✅ Quick response to congestion | ✅ Faster throughput recovery |
| ✅ Network-friendly | ✅ Higher average throughput |
| ❌ Slower recovery | ❌ Risk of repeated losses |
| ❌ Lower average throughput | ❌ May cause congestion for others |

This is a fundamental congestion control research question with decades of literature, making results highly comparable to existing research.

#### 4. Interaction with Other Parameters

Loss Reduction Factor interacts meaningfully with the other selected parameters:

- **With Initial CW**: Large initial window + aggressive reduction (0.3) = quick start but slow recovery if early loss occurs
- **With Max ACK Delay**: Low ACK delay + conservative reduction (0.7) = faster loss detection but gentler response

These interactions create a rich parameter space for multi-dimensional analysis.

#### 5. Implementation

```python
# In recovery.py - single constant change
K_LOSS_REDUCTION_FACTOR = 0.5  # Original
K_LOSS_REDUCTION_FACTOR = 0.7  # Less aggressive recovery
```

**Risk Assessment**: LOW-MEDIUM
- Too low (0.2): Very slow recovery, poor throughput
- Too high (0.9): May cause congestion collapse in lossy networks
- Safe range (0.4-0.7): Produces meaningful differences without breaking connections

---

## Parameter Comparison Matrix

| Parameter | File Transfer | Video | Conference | Implementation | Research Value |
|-----------|:-------------:|:-----:|:----------:|:--------------:|:--------------:|
| **Initial CW** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | Easy | High |
| **Max ACK Delay** | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | Easy (API) | High |
| **Loss Reduction Factor** | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | Easy | High |
| Minimum CW | ⭐ | ⭐ | ⭐ | Easy | Low |
| Packet Threshold | ⭐⭐ | ⭐ | ⭐ | Easy | Medium |
| Time Threshold | ⭐ | ⭐ | ⭐ | Easy | Medium |
| Granularity | ⭐ | ⭐ | ⭐ | Easy | Low |

---

## Parameters Not Selected (and Why)

### Minimum Congestion Window (K_MINIMUM_WINDOW)
- **Reason for exclusion**: Only affects edge cases when network is severely congested
- **When it matters**: After multiple consecutive loss events
- **Limited research value**: Rarely triggers in typical test scenarios with <5% loss

### Packet Threshold (K_PACKET_THRESHOLD)
- **Reason for exclusion**: Primarily affects loss detection timing, not steady-state performance
- **Default value (3)**: Already well-tuned based on TCP research
- **Recommendation**: Include if testing focuses on lossy network conditions

### Time Threshold (K_TIME_THRESHOLD)
- **Reason for exclusion**: Works in conjunction with Packet Threshold for loss detection
- **Low independent impact**: Changing alone produces minimal observable effect
- **Recommendation**: Could be studied alongside Packet Threshold as a pair

### Granularity (K_GRANULARITY)
- **Reason for exclusion**: Very low-level timer precision parameter
- **Minimal impact**: Only matters for sub-millisecond timing requirements
- **Not relevant**: Project metrics are in milliseconds, not microseconds

### ACK Delay Exponent
- **Reason for exclusion**: Only affects encoding precision of ACK delay values
- **No behavioral impact**: Does not change actual ACK timing
- **Commonly confused with**: Max ACK Delay (which does affect behavior)

---

## Recommended Test Matrix

### Suggested Parameter Values

| Parameter | Conservative | Moderate | Aggressive |
|-----------|--------------|----------|------------|
| Initial CW | 12KB (10 pkts) | 60KB (50 pkts) | 120KB (100 pkts) |
| Max ACK Delay | 25ms | 10ms | 2ms |
| Loss Reduction Factor | 0.5 | 0.6 | 0.7 |

### Test Combinations (27 total)

For comprehensive analysis, test all combinations:
- 3 Initial CW values × 3 Max ACK Delay values × 3 Loss Reduction Factor values = 27 combinations
- Run each combination for all 3 transmission types
- Total test runs: 27 × 3 = 81 scenarios

### Priority Test Scenarios

If time is limited, prioritize these 9 combinations:

| Scenario | Initial CW | ACK Delay | Loss Factor | Target Use Case |
|----------|------------|-----------|-------------|-----------------|
| 1 | 12KB | 25ms | 0.5 | Baseline (all defaults) |
| 2 | 120KB | 25ms | 0.7 | File Transfer optimized |
| 3 | 60KB | 2ms | 0.5 | Video optimized |
| 4 | 12KB | 2ms | 0.5 | Conference optimized |
| 5 | 120KB | 2ms | 0.7 | Maximum performance |
| 6 | 60KB | 10ms | 0.6 | Balanced |
| 7 | 12KB | 10ms | 0.7 | Conservative start, fast recovery |
| 8 | 120KB | 10ms | 0.5 | Fast start, standard recovery |
| 9 | 60KB | 25ms | 0.7 | Moderate start, fast recovery |

---

## Expected Outcomes

### Hypothesis 1: Initial Congestion Window
> Increasing Initial CW from 10 to 50 packets will reduce time-to-first-byte by 40-60% for all transmission types, with the largest impact on file transfers under 1MB.

**Measurable via**: Connection establishment time, first-frame latency, short transfer completion time

### Hypothesis 2: Max ACK Delay
> Reducing Max ACK Delay from 25ms to 2ms will reduce jitter by 50% or more, enabling conference calls to meet the <20ms jitter target. Video streaming latency will decrease by 15-25ms.

**Measurable via**: Jitter (inter-packet delay variance), average end-to-end latency

### Hypothesis 3: Loss Reduction Factor
> Increasing Loss Reduction Factor from 0.5 to 0.7 will improve average throughput by 10-20% for file transfers in networks with 1-2% packet loss, at the cost of slightly higher peak latency.

**Measurable via**: Average throughput (bytes/sec), throughput variance, recovery time after loss events

### Hypothesis 4: Parameter Interactions
> The optimal parameter combination will differ by transmission type:
> - File Transfer: High Initial CW + High Loss Factor + Moderate ACK Delay
> - Video Streaming: Moderate Initial CW + Low ACK Delay + Moderate Loss Factor
> - Conference Calls: Low-Moderate Initial CW + Very Low ACK Delay + Standard Loss Factor

**Measurable via**: Per-stream metrics comparison across parameter combinations

---

## Implementation Summary

All three parameters can be modified with minimal code changes:

### recovery.py Modifications

```python
# Located at top of src/aioquic/quic/recovery.py

# Parameter 1: Initial Congestion Window
K_INITIAL_WINDOW = 50 * MAX_DATAGRAM_SIZE  # 60KB (default: 10 * MAX_DATAGRAM_SIZE)

# Parameter 3: Loss Reduction Factor
K_LOSS_REDUCTION_FACTOR = 0.7  # Less aggressive (default: 0.5)
```

### Configuration API (No Source Modification)

```python
from aioquic.quic.configuration import QuicConfiguration

# Parameter 2: Max ACK Delay
config = QuicConfiguration(
    is_client=True,
    max_ack_delay=0.010,  # 10ms (default: 0.025)
)
```

### Creating a Parameter Preset System

```python
# parameter_presets.py
PRESETS = {
    "baseline": {
        "initial_cw_packets": 10,
        "max_ack_delay": 0.025,
        "loss_reduction_factor": 0.5,
    },
    "file_transfer": {
        "initial_cw_packets": 100,
        "max_ack_delay": 0.025,
        "loss_reduction_factor": 0.7,
    },
    "video_streaming": {
        "initial_cw_packets": 50,
        "max_ack_delay": 0.005,
        "loss_reduction_factor": 0.5,
    },
    "conference": {
        "initial_cw_packets": 10,
        "max_ack_delay": 0.002,
        "loss_reduction_factor": 0.5,
    },
}
```

---

## Conclusion

The three selected parameters—**Initial Congestion Window**, **Max ACK Delay**, and **Loss Reduction Factor**—provide:

1. **Complete coverage** of the project's success criteria
2. **Orthogonal control** over different aspects of performance:
   - Initial CW → Startup behavior
   - Max ACK Delay → Latency and jitter
   - Loss Reduction Factor → Throughput recovery
3. **Native availability** in aioquic (no custom implementation required)
4. **Simple implementation** via constant changes or API configuration
5. **Rich research potential** for understanding QUIC performance trade-offs

| Success Criterion | Primary Parameter | Supporting Parameter |
|-------------------|-------------------|----------------------|
| File Transfer >90% BW | Loss Reduction Factor | Initial CW |
| Video <50ms latency | Max ACK Delay | Initial CW |
| Conference <20ms jitter | Max ACK Delay | Loss Reduction Factor |

These parameters form a minimal but sufficient set for comprehensive QUIC performance research across diverse transmission types, using only native aioquic functionality.
