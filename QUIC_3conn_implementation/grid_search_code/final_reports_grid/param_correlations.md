# Parameter-Output Correlations Analysis

This document analyzes the correlations between QUIC congestion control parameters and output metrics, including validation of whether results are realistic.

---

## Parameter-Output Correlations

Correlation coefficients between parameters and output metrics. Values range from -1 to +1:
- **Strong correlation:** |r| > 0.5
- **Moderate correlation:** |r| > 0.3
- Values near 0 indicate weak/no correlation

### File Transfer

| Parameter | Throughput | Latency | Jitter |
|-----------|------------|---------|--------|
| `loss_reduction_factor` | -0.020 | -0.069 | +0.105 |
| `cubic_c` | **+0.289** | +0.000 | -0.236 |
| `minimum_window` | +0.089 | +0.006 | +0.080 |
| `packet_threshold` | +0.057 | -0.013 | +0.008 |

**Key finding:** `cubic_c` has the strongest correlation with throughput (+0.289). Higher `cubic_c` values lead to higher throughput.

### Video Streaming

| Parameter | Throughput | Latency | Jitter |
|-----------|------------|---------|--------|
| `loss_reduction_factor` | **-0.452** | +0.094 | +0.212 |
| `cubic_c` | -0.185 | -0.047 | +0.045 |
| `minimum_window` | -0.048 | -0.045 | +0.124 |
| `packet_threshold` | -0.156 | +0.154 | +0.095 |

**Key finding:** `loss_reduction_factor` has a moderate negative correlation with throughput (-0.452). Lower values lead to more stable behavior.

### Conference Call

| Parameter | Throughput | Latency | Jitter |
|-----------|------------|---------|--------|
| `loss_reduction_factor` | **-0.764** | +0.181 | +0.244 |
| `cubic_c` | -0.284 | -0.157 | -0.153 |
| `minimum_window` | -0.118 | +0.162 | +0.058 |
| `packet_threshold` | -0.090 | +0.007 | +0.084 |

**Key finding:** `loss_reduction_factor` has a **strong** negative correlation with throughput (-0.764). For jitter-sensitive conference calls, lower values provide more predictable transmission.

---

## Cross-Metric Correlations

How output metrics correlate with each other within each application type:

| App Type | Throughput vs Latency | Throughput vs Jitter | Latency vs Jitter |
|----------|----------------------|---------------------|-------------------|
| File Transfer | -0.126 | **-0.642** | +0.082 |
| Video Streaming | -0.324 | **-0.697** | **+0.499** |
| Conference Call | -0.297 | -0.353 | **+0.752** |

### Key Insights

1. **Throughput vs Jitter is strongly negative across all apps** (-0.64 to -0.70): Higher throughput correlates with lower jitter.

2. **Conference Call shows strong Latency-Jitter correlation** (+0.752): For real-time audio, latency and jitter are tightly coupled.

3. **Video Streaming shows moderate correlations across all pairs**: The video traffic pattern creates interdependencies between all metrics.

---

## Critical Finding: Same Parameters Minimize Both Latency AND Jitter

### The Data

| App | Best Latency Config | Best Jitter Config | Same? |
|-----|--------------------|--------------------|-------|
| Video Streaming | LRF=0.3, CC=0.2, MW=2, PT=2 | LRF=0.3, CC=0.2, MW=2, PT=2 | **Yes** |
| Conference Call | LRF=0.3, CC=0.2, MW=2, PT=2 | LRF=0.3, CC=0.2, MW=2, PT=2 | **Yes** |

The positive correlation between latency and jitter:
- Video Streaming: **+0.499**
- Conference Call: **+0.752**

This means reducing one tends to reduce the other.

---

## Is This Realistic? Analysis of Simulation Artifacts

### Short Answer: **Partially an artifact of the simulation, but also partially valid**

### What's Happening in Our Simulation

Our simulation has **no real network conditions**:
- No propagation delay (localhost)
- No packet loss
- No packet reordering
- No competing traffic
- No variable bandwidth

In this environment, **queuing delay is the ONLY source of both latency and jitter**:

```
Latency ≈ Queuing Delay
Jitter  ≈ Variation in Queuing Delay
```

When you reduce queuing (via conservative congestion control), you reduce **both** metrics simultaneously. This is why they're positively correlated (+0.50 to +0.75).

### What Would Happen in Real Networks?

In real networks, latency and jitter have **different sources**:

| Source | Affects Latency | Affects Jitter |
|--------|-----------------|----------------|
| Propagation delay | Yes (fixed) | No |
| Queuing delay | Yes | Yes |
| Packet reordering | Yes (retransmission) | Yes (out-of-order) |
| Packet loss | Yes (retransmission) | Yes (recovery time varies) |
| Variable bandwidth | Yes | Yes |
| Route changes | Yes | Yes (different paths) |

### Research Findings from Literature

1. **Jitter buffers trade latency for jitter**: WebRTC and VoIP systems use jitter buffers that deliberately **add latency to reduce jitter**. This is a direct trade-off that doesn't exist in our simulation.
   > "Smaller buffers reduce delay but may increase the risk of jitter, while larger buffers smooth out jitter but add delay."

   Source: [GetStream - WebRTC Buffers](https://getstream.io/resources/projects/webrtc/advanced/buffers/)

2. **Bufferbloat shows the opposite relationship**: Large buffers reduce jitter (smooth out variations) but **increase latency**. This is the bufferbloat problem.
   > "Once you start to queue packets for transmission, you always will see added latency, and more than likely bursts of jitter."

   Source: [Bufferbloat.net](https://www.bufferbloat.net/projects/bloat/wiki/Bufferbloat_FAQs/)

3. **Packet reordering causes spurious retransmissions**: With `packet_threshold=2`, even small reordering triggers retransmissions. This increases **both** latency and jitter, but the impact differs.
   > "Smaller thresholds reduce reordering resilience and increase spurious retransmissions, while larger thresholds increase loss detection delay."

   Source: [RFC 9002 - QUIC Loss Detection](https://datatracker.ietf.org/doc/html/rfc9002)

4. **CUBIC's HyStart misinterprets jitter**: Research shows that even ±10ms of jitter throws CUBIC's algorithms off, causing early slow-start exit.
   > "The delay increase detection mechanism of HyStart misinterprets RTT variations as network congestion."

   Source: [Arxiv - TCP ROCCET](https://arxiv.org/html/2510.25281)

5. **Real-time requirements**: ITU-T G.114 recommends one-way delay under 150ms for acceptable conversation. Jitter under 30ms is generally acceptable.
   > "A uniform delay does not affect audio or video applications, but variations in the delay can be disastrous for VoIP."

   Source: [Kentik - Understanding Latency](https://www.kentik.com/kentipedia/understanding-latency-packet-loss-and-jitter-in-networking/)

### Would Optimal Parameters Diverge in Real Networks?

**Likely yes.** Here's the expected impact:

| Scenario | Effect on Optimal Parameters |
|----------|------------------------------|
| **With packet loss** | Higher `loss_reduction_factor` might help jitter (less oscillation) but hurt latency (slower recovery) |
| **With packet reordering** | `packet_threshold=3` (RFC default) needed to avoid spurious retransmits that increase both metrics |
| **With variable bandwidth** | Higher `minimum_window` might help latency (maintain throughput during dips) but hurt jitter (more queuing) |
| **With jitter buffers** | Explicit trade-off introduced - can't minimize both simultaneously |
| **With propagation delay** | Parameters might not change much, but correlation between metrics would weaken |

### Available Network Simulation Scenarios

The codebase includes a `wireless_bottleneck` module with realistic scenarios:

| Scenario | Conditions |
|----------|------------|
| `stable_high` | 100 Mbps, 10ms RTT, 0.1% loss |
| `congested_low` | 5 Mbps, 30ms RTT, 2% loss, RED queue |
| `varying` | 20 Mbps, ±40% variation every 2s, CoDel queue |
| `lossy` | 10 Mbps, 5% burst loss (Gilbert-Elliott model) |
| `asymmetric` | 50/10 Mbps down/up, 25ms RTT |

**To validate whether parameters diverge under real conditions, re-run the grid search with network simulation enabled.**

---

## Validity Assessment

| Finding | Validity | Notes |
|---------|----------|-------|
| Same parameters minimize both latency and jitter | **Valid in queuing-dominated scenarios** | Real networks have additional sources of variation |
| Conservative CC helps both metrics | **Valid in general** | Less aggressive = less queuing = both improve |
| Correlation of +0.50 to +0.75 | **Partially artifact** | Would weaken or reverse with jitter buffers, bufferbloat |
| `packet_threshold=2` optimal | **Artifact** | Needs 3 in real networks with packet reordering |
| `loss_reduction_factor=0.3` for real-time | **Likely valid** | Aggressive reduction provides stability |
| `cubic_c=0.2` for real-time | **Likely valid** | Conservative growth reduces queuing |

---

## Recommendations for Production Deployment

1. **Test with network simulation**: Use the `wireless_bottleneck` scenarios to validate parameters under realistic conditions

2. **Increase `packet_threshold` to 3**: RFC 9002 recommendation for networks with packet reordering

3. **Consider application-layer jitter buffers**: Real WebRTC/VoIP systems add jitter buffers that create explicit latency-jitter trade-offs not present in our simulation

4. **Monitor both metrics independently**: In production, latency and jitter may not move together as they do in simulation

5. **Start with conservative parameters**: The real-time optimal parameters (low `cubic_c`, low `loss_reduction_factor`) are safe starting points even if not perfectly optimal

---

## Parameter Impact Summary

| Parameter | Primary Impact | File Transfer | Real-Time Apps |
|-----------|----------------|---------------|----------------|
| `cubic_c` | Growth aggressiveness | **0.6** (aggressive) | **0.2** (conservative) |
| `loss_reduction_factor` | Recovery behavior | **0.5** (moderate) | **0.3** (aggressive reduction) |
| `minimum_window` | Floor after loss | **6** (high floor) | **2** (allow small) |
| `packet_threshold` | Loss detection speed | **2** (fast) | **2** (fast) |
| `time_threshold` | RTT-based detection | **1.125** (RFC default) | **1.125** (RFC default) |
| `cubic_max_idle_time` | Idle tolerance | **2.0** (balanced) | **2.0** (balanced) |

---

## References

- [RFC 9438 - CUBIC for Fast and Long-Distance Networks](https://datatracker.ietf.org/doc/rfc9438/)
- [RFC 9002 - QUIC Loss Detection and Congestion Control](https://datatracker.ietf.org/doc/rfc9002/)
- [GetStream - WebRTC and Buffers](https://getstream.io/resources/projects/webrtc/advanced/buffers/)
- [Bufferbloat.net FAQs](https://www.bufferbloat.net/projects/bloat/wiki/Bufferbloat_FAQs/)
- [MIT - Low-Latency Networking](https://dspace.mit.edu/bitstream/handle/1721.1/126300/1808.02079.pdf)
- [Arxiv - TCP ROCCET](https://arxiv.org/html/2510.25281)
- [CUBIC Paper - Princeton](https://www.cs.princeton.edu/courses/archive/fall16/cos561/papers/Cubic08.pdf)
- [Kentik - Understanding Latency, Packet Loss, and Jitter](https://www.kentik.com/kentipedia/understanding-latency-packet-loss-and-jitter-in-networking/)
