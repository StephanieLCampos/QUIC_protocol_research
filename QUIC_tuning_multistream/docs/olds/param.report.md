# QUIC Parameter Selection Report

## Executive Summary

This report identifies the three most impactful QUIC parameters for the multi-stream research project. The selection is based on analysis of how each parameter affects the project's three transmission types (Video Streaming, File Transfer, Conference Calls) and their respective success criteria.

**Selected Parameters:**
1. Initial Congestion Window
2. Max Congestion Window
3. Max ACK Delay

---

## Selection Methodology

Parameters were evaluated against four criteria:

| Criterion | Weight | Rationale |
|-----------|--------|-----------|
| Impact on Success Metrics | 40% | Direct contribution to achieving stated goals |
| Cross-Application Coverage | 25% | Effectiveness across all three transmission types |
| Research Value | 20% | Potential for meaningful insights and measurable effects |
| Implementation Feasibility | 15% | Practical ability to modify in aioquic |

### Success Criteria Reminder
- **File Transfer**: >90% of available bandwidth utilization
- **Video Streaming**: <50ms average latency
- **Conference Calls**: <20ms jitter

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
- For a 100ms RTT network, the difference between IW=10 and IW=100 means reaching full throughput in ~3 RTTs vs ~7 RTTs
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

#### 4. Implementation Simplicity

```python
# In recovery.py - single constant change
K_INITIAL_WINDOW = 10 * MAX_DATAGRAM_SIZE  # Original
K_INITIAL_WINDOW = 50 * MAX_DATAGRAM_SIZE  # Modified for testing
```

**Risk Assessment**: LOW
- Too large: May cause packet loss on initial burst, triggering recovery
- Too small: Unnecessarily slow startup
- Both extremes produce measurable, non-catastrophic effects

---

## Parameter 2: Max Congestion Window

### Definition
The Maximum Congestion Window caps the maximum number of bytes that can be in flight at any time, regardless of how much the congestion control algorithm would otherwise allow.

**Location**: `src/aioquic/quic/recovery.py` → Custom implementation required
**Default**: Unlimited (no cap in standard aioquic)
**Recommended Test Range**: 50KB – 10MB

### Why Selected

#### 1. Critical for Throughput Optimization (Score: 9/10)

The max congestion window directly determines the **theoretical maximum throughput** achievable:

```
Max Throughput = Max Congestion Window / RTT
```

| RTT | Max CW = 100KB | Max CW = 1MB | Max CW = 10MB |
|-----|----------------|--------------|---------------|
| 10ms | 80 Mbps | 800 Mbps | 8 Gbps |
| 50ms | 16 Mbps | 160 Mbps | 1.6 Gbps |
| 100ms | 8 Mbps | 80 Mbps | 800 Mbps |

This is the **bandwidth-delay product (BDP)** relationship—fundamental to network performance.

#### 2. Direct Contribution to Success Criteria

**File Transfer (>90% bandwidth utilization)**:
- If Max CW < BDP of the network path, throughput is artificially capped
- To achieve 90% utilization on a 100Mbps link with 50ms RTT:
  - Required BDP = 100Mbps × 0.05s = 625KB
  - Max CW must be ≥625KB to reach full utilization
- This parameter is **essential** for the primary file transfer goal

**Video Streaming (<50ms latency)**:
- Prevents buffer bloat by capping in-flight data
- Excessive buffering adds latency; appropriate cap maintains low delay
- Sweet spot exists between throughput and latency

#### 3. Research Value

Max Congestion Window enables study of:
- **BDP matching**: Does matching CW to network BDP optimize performance?
- **Buffer bloat**: How does excessive CW affect latency?
- **Fairness**: How do different CW caps affect stream competition?
- **Trade-offs**: Throughput vs latency across transmission types

This creates rich research opportunities for multi-stream scenarios where streams compete for the same congestion window.

#### 4. Implementation

```python
# Add to recovery.py
K_MAX_WINDOW = 1000000  # 1MB cap

# Modify in QuicPacketRecovery.on_packet_acked()
def on_packet_acked(self, packet):
    # ... existing congestion window increase logic ...

    # Add cap enforcement
    self.congestion_window = min(self.congestion_window, K_MAX_WINDOW)
```

**Risk Assessment**: MEDIUM
- Too small: Artificially limits throughput below network capacity
- Too large: May cause buffer bloat and increased latency
- Interaction with multiple streams creates complex but interesting dynamics

---

## Parameter 3: Max ACK Delay

### Definition
Max ACK Delay specifies the maximum time a receiver will wait before sending an acknowledgment for received packets. Lower values mean more frequent ACKs; higher values mean more batched ACKs.

**Location**: `src/aioquic/quic/configuration.py` → `max_ack_delay`
**Default**: 25ms
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

#### 4. Implementation Simplicity

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

## Parameter Comparison Matrix

| Parameter | File Transfer | Video | Conference | Implementation | Research Value |
|-----------|--------------|-------|------------|----------------|----------------|
| **Initial CW** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | Easy | High |
| **Max CW** | ⭐⭐⭐ | ⭐⭐ | ⭐ | Medium | High |
| **Max ACK Delay** | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | Easy | High |
| Loss Reduction Factor | ⭐⭐ | ⭐⭐ | ⭐ | Easy | Medium |
| ACK Frequency | ⭐⭐ | ⭐⭐ | ⭐⭐⭐ | Hard | High |
| Min CW | ⭐ | ⭐ | ⭐ | Easy | Low |
| Packet Threshold | ⭐ | ⭐ | ⭐ | Easy | Medium |

---

## Parameters Not Selected (and Why)

### ACK Frequency (Full Implementation)
- **Reason for exclusion**: Requires significant modification to `connection.py` ACK generation logic
- **Alternative**: Max ACK Delay provides similar latency control benefits with much simpler implementation
- **Recommendation**: Consider as Phase 2 enhancement if Max ACK Delay results show promise

### Loss Reduction Factor (K_LOSS_REDUCTION_FACTOR)
- **Reason for exclusion**: Primarily affects recovery scenarios; less impactful during normal operation
- **Trade-off**: Would be valuable for studying lossy network conditions
- **Recommendation**: Include if testing in high-loss environments (>1% packet loss)

### Minimum Congestion Window
- **Reason for exclusion**: Only affects edge cases when network is severely congested
- **Limited research value**: Rarely triggers in typical test scenarios

---

## Recommended Test Matrix

### Suggested Parameter Values

| Parameter | Conservative | Moderate | Aggressive |
|-----------|--------------|----------|------------|
| Initial CW | 12KB (10 pkts) | 60KB (50 pkts) | 120KB (100 pkts) |
| Max CW | 100KB | 1MB | 10MB |
| Max ACK Delay | 25ms | 10ms | 2ms |

### Test Combinations (27 total)

For comprehensive analysis, test all combinations:
- 3 Initial CW values × 3 Max CW values × 3 ACK Delay values = 27 combinations
- Run each combination for all 3 transmission types
- Total test runs: 27 × 3 = 81 scenarios

### Priority Test Scenarios

If time is limited, prioritize these 9 combinations:

| Scenario | Initial CW | Max CW | ACK Delay | Target Use Case |
|----------|------------|--------|-----------|-----------------|
| 1 | 12KB | 100KB | 25ms | Baseline (defaults) |
| 2 | 120KB | 10MB | 25ms | File Transfer optimized |
| 3 | 60KB | 1MB | 2ms | Video optimized |
| 4 | 12KB | 100KB | 2ms | Conference optimized |
| 5 | 120KB | 10MB | 2ms | Maximum performance |
| 6 | 12KB | 100KB | 10ms | Balanced |
| 7 | 60KB | 1MB | 10ms | Balanced + moderate startup |
| 8 | 120KB | 1MB | 10ms | Fast start, moderate steady |
| 9 | 60KB | 10MB | 25ms | High throughput ceiling |

---

## Expected Outcomes

### Hypothesis 1: Initial Congestion Window
> Increasing Initial CW from 10 to 50 packets will reduce time-to-first-byte by 40-60% for all transmission types.

**Measurable via**: Connection establishment time, first-frame latency

### Hypothesis 2: Max Congestion Window
> Setting Max CW to match network BDP will achieve >90% bandwidth utilization for file transfers while limiting Max CW to 500KB will keep video streaming latency <50ms.

**Measurable via**: Throughput (bytes/sec), average latency

### Hypothesis 3: Max ACK Delay
> Reducing Max ACK Delay from 25ms to 2ms will reduce jitter by 50% or more, enabling conference calls to meet the <20ms jitter target.

**Measurable via**: Jitter (inter-packet delay variance)

---

## Conclusion

The three selected parameters—**Initial Congestion Window**, **Max Congestion Window**, and **Max ACK Delay**—provide:

1. **Complete coverage** of the project's success criteria
2. **Orthogonal control** over different aspects of performance (startup, throughput ceiling, latency)
3. **Practical implementation** within the aioquic framework
4. **Rich research potential** for understanding QUIC performance trade-offs

These parameters form a minimal but sufficient set for comprehensive QUIC performance research across diverse transmission types.

---

## Appendix: Quick Implementation Reference

```python
# recovery.py modifications
K_INITIAL_WINDOW = 50 * MAX_DATAGRAM_SIZE  # 60KB
K_MAX_WINDOW = 1000000  # 1MB (add this constant)

# In QuicPacketRecovery.on_packet_acked(), add:
self.congestion_window = min(self.congestion_window, K_MAX_WINDOW)

# configuration.py - use via API
config = QuicConfiguration(
    is_client=True,
    max_ack_delay=0.010,  # 10ms
)
```
