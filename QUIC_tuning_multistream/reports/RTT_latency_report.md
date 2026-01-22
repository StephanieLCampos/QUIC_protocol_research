# RTT vs. Latency: Understanding the Difference

## Executive Summary

**Question**: Is RTT (Round-Trip Time) the same as measuring latency?

**Answer**: **No, they are related but distinct concepts.** RTT is a specific, measurable network metric, while "latency" is a broader term that can refer to several different timing measurements. Understanding the difference is critical for correctly interpreting your QUIC research results.

---

## Definitions

### Round-Trip Time (RTT)

RTT is the time for a packet to travel from sender to receiver **and back**:

```
Sender                                              Receiver
  │                                                    │
  │──────────── Data Packet ─────────────────────────►│
  │                                                    │
  │                        RTT                         │
  │                                                    │
  │◄───────────── ACK Packet ─────────────────────────│
  │                                                    │
```

**RTT = Time(send packet) → Time(receive ACK)**

### Latency

"Latency" is a general term that can mean several things:

| Latency Type | Definition | Relationship to RTT |
|--------------|------------|---------------------|
| **One-way latency** | Time from sender to receiver | ≈ RTT / 2 |
| **End-to-end latency** | Time from data creation to consumption | > RTT / 2 |
| **Network latency** | Transmission time through network | ≈ RTT / 2 |
| **Application latency** | Includes processing overhead | >> RTT / 2 |

---

## Key Differences

### 1. Direction: Round-Trip vs. One-Way

```
RTT (Round-Trip):
  Sender ──────────────────────────────► Receiver
         ◄──────────────────────────────
         |←───────── RTT = 100ms ──────→|

One-Way Latency:
  Sender ──────────────────────────────► Receiver
         |←─── One-way ≈ 50ms ────→|
```

**Important**: One-way latency is approximately RTT/2, but only if the network path is symmetric. In practice:
- Upload and download speeds may differ
- Routing may be asymmetric
- One-way latency ≠ RTT/2 exactly

### 2. What's Included

| Metric | Network Time | Processing Time | ACK Delay | Buffering |
|--------|:------------:|:---------------:|:---------:|:---------:|
| **RTT** | ✅ | Minimal | ✅ | ❌ |
| **One-way latency** | ✅ | ❌ | ❌ | ❌ |
| **End-to-end latency** | ✅ | ✅ | ✅ | ✅ |

### 3. Measurability

| Metric | How to Measure | Difficulty |
|--------|----------------|------------|
| **RTT** | Time between sending packet and receiving ACK | Easy (QUIC does this automatically) |
| **One-way latency** | Timestamp at sender vs. receiver | Hard (requires synchronized clocks) |
| **End-to-end latency** | Timestamp at creation vs. consumption | Medium (application-level measurement) |

---

## RTT in QUIC/aioquic

### What aioquic Measures

aioquic tracks RTT internally for congestion control:

```python
# Accessing RTT metrics from QuicConnection
conn._loss._rtt_latest    # Most recent RTT sample
conn._loss._rtt_smoothed  # Exponentially weighted moving average (EWMA)
conn._loss._rtt_min       # Minimum RTT observed (likely closest to true RTT)
conn._loss._rtt_variance  # RTT variance (for timeout calculations)
```

### How QUIC Calculates RTT

```python
# Simplified RTT calculation in QUIC
def on_ack_received(self, ack_frame):
    for packet_number in ack_frame.acked_packets:
        sent_time = self.sent_packets[packet_number].sent_time
        ack_delay = ack_frame.ack_delay  # Receiver's processing delay

        # RTT = now - sent_time - ack_delay
        rtt_sample = time.time() - sent_time - ack_delay

        # Update smoothed RTT (EWMA)
        self._rtt_smoothed = 0.875 * self._rtt_smoothed + 0.125 * rtt_sample
```

### RTT Components in QUIC

```
┌────────────────────────────────────────────────────────────────────┐
│                         QUIC RTT                                   │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  Sender              Network                Receiver               │
│    │                                           │                   │
│    │◄──── Transmission Delay (outbound) ─────►│                   │
│    │                                           │                   │
│    │                                    ┌──────┴──────┐            │
│    │                                    │ Processing  │            │
│    │                                    │ + ACK Delay │            │
│    │                                    └──────┬──────┘            │
│    │                                           │                   │
│    │◄──── Transmission Delay (return) ────────│                   │
│    │                                           │                   │
├────────────────────────────────────────────────────────────────────┤
│  RTT = Outbound + Processing + ACK Delay + Return                  │
│                                                                    │
│  Note: QUIC subtracts reported ACK Delay to get network RTT        │
└────────────────────────────────────────────────────────────────────┘
```

---

## Latency in Your Project Context

### From requirements_v3.md

Your project specifies:
> **Video Streaming**: <50ms average latency (RTT)

### What Does This Mean?

This likely refers to **end-to-end latency** — the time from when a video frame is sent to when it's received and available for display.

### Breaking Down Video Latency

```
┌─────────────────────────────────────────────────────────────────────┐
│                    End-to-End Video Latency                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Frame          One-Way         Receiver        Frame               │
│  Created        Network         Processing      Available           │
│     │           Latency            │               │                │
│     ▼                              ▼               ▼                │
│  ───┼───────────────┼──────────────┼───────────────┼───            │
│     │               │              │               │                │
│     │◄─ ~RTT/2 ────►│◄─ ACK Wait ─►│◄─ Buffering ─►│               │
│     │               │              │               │                │
│     │◄────────── End-to-End Latency ──────────────►│               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Latency Components for Video Streaming

| Component | Typical Value | Controllable? |
|-----------|---------------|:-------------:|
| One-way network latency | RTT/2 (e.g., 25ms) | No (network property) |
| Sender processing | <1ms (synthetic data) | Yes |
| QUIC packetization | <1ms | Minimal |
| Max ACK Delay impact | 0-25ms | ✅ Yes (parameter) |
| Receiver buffering | 0-33ms (1 frame) | Application choice |
| Receiver processing | <1ms (synthetic data) | Yes |

**Key Insight**: Max ACK Delay (one of your three parameters) directly affects perceived latency, even though it's not part of one-way network latency.

---

## Relationship Between RTT and Your Success Criteria

### Video Streaming: <50ms Latency

To achieve <50ms end-to-end latency:

```
End-to-End Latency ≈ RTT/2 + Processing + Buffering

If target = 50ms and Processing + Buffering ≈ 5ms:
  RTT/2 must be < 45ms
  Therefore RTT must be < 90ms
```

| Network RTT | One-Way | + 5ms Overhead | Meets <50ms? |
|-------------|---------|----------------|:------------:|
| 40ms | 20ms | 25ms | ✅ Yes |
| 80ms | 40ms | 45ms | ✅ Yes |
| 100ms | 50ms | 55ms | ❌ No |
| 200ms | 100ms | 105ms | ❌ No |

### Conference Calls: <20ms Jitter

Jitter is **not** latency — it's the **variation** in latency:

```python
# Jitter calculation
delays = [packet_latencies[i+1] - packet_latencies[i] for i in range(n-1)]
jitter = statistics.stdev(delays)  # Standard deviation of inter-packet delays
```

RTT variation contributes to jitter, but Max ACK Delay variation is often the bigger factor.

### File Transfer: >90% Bandwidth

For throughput, RTT determines how quickly the congestion window can grow:

```
Throughput = Congestion Window / RTT

With RTT = 100ms and CW = 1MB:
  Max throughput = 1,000,000 / 0.1 = 10 MB/s = 80 Mbps
```

Lower RTT = faster feedback = faster CW growth = higher throughput.

---

## How to Measure Each Metric

### Measuring RTT (Easy)

```python
class RTTMonitor:
    """Monitor RTT from QUIC connection."""

    def __init__(self, connection):
        self.conn = connection
        self.samples = []

    def sample(self):
        """Collect current RTT metrics."""
        self.samples.append({
            "timestamp": time.time(),
            "rtt_smoothed": self.conn._loss._rtt_smoothed,
            "rtt_min": self.conn._loss._rtt_min,
            "rtt_latest": self.conn._loss._rtt_latest,
        })

    def get_average_rtt(self) -> float:
        """Return average smoothed RTT in milliseconds."""
        if not self.samples:
            return 0
        return statistics.mean(s["rtt_smoothed"] for s in self.samples) * 1000
```

### Measuring One-Way Latency (Hard)

Requires synchronized clocks or estimation:

```python
# Option 1: Estimate from RTT (assumes symmetric path)
one_way_latency = rtt / 2

# Option 2: Use timestamps (requires clock synchronization)
# NTP sync accuracy is typically 1-10ms, which may be larger than what you're measuring

# Option 3: Application-level measurement
class LatencyMeasurement:
    """Measure application-level latency with embedded timestamps."""

    def create_packet(self, data: bytes) -> bytes:
        """Embed send timestamp in packet."""
        timestamp = struct.pack(">d", time.time())  # 8-byte timestamp
        return timestamp + data

    def measure_latency(self, packet: bytes) -> float:
        """Extract timestamp and calculate latency."""
        send_time = struct.unpack(">d", packet[:8])[0]
        receive_time = time.time()
        return receive_time - send_time  # One-way latency

# Note: This measures one-way latency but requires:
# - Clock synchronization between sender/receiver
# - Or running both on same machine (localhost testing)
```

### Measuring End-to-End Latency

```python
class EndToEndLatencyTracker:
    """Track latency from frame creation to availability."""

    def __init__(self):
        self.pending_frames = {}  # frame_id -> send_time
        self.latencies = []

    def on_frame_sent(self, frame_id: int):
        """Record when frame was sent."""
        self.pending_frames[frame_id] = time.time()

    def on_frame_received(self, frame_id: int):
        """Record when frame was received and calculate latency."""
        if frame_id in self.pending_frames:
            send_time = self.pending_frames.pop(frame_id)
            latency = time.time() - send_time
            self.latencies.append(latency)
            return latency * 1000  # Return in milliseconds
        return None

    def get_average_latency(self) -> float:
        """Average end-to-end latency in milliseconds."""
        if not self.latencies:
            return 0
        return statistics.mean(self.latencies) * 1000
```

---

## Impact of Your Parameters on RTT vs. Latency

### Initial Congestion Window

| Metric | Impact |
|--------|--------|
| RTT | No direct impact (RTT is network property) |
| Latency | Reduces initial latency for large messages (more data in first RTT) |

```
Small Initial CW (12KB):
  50KB frame needs 5 RTTs to fully send
  First-frame latency = 5 × RTT

Large Initial CW (120KB):
  50KB frame sends in 1 RTT
  First-frame latency = 1 × RTT
```

### Max ACK Delay

| Metric | Impact |
|--------|--------|
| RTT | Directly included (QUIC subtracts it, but affects pacing) |
| Latency | Adds to perceived latency (receiver waits before ACKing) |

```
With Max ACK Delay = 25ms:
  - Sender waits up to 25ms longer for ACK
  - Congestion window growth is slower
  - Perceived latency increases

With Max ACK Delay = 2ms:
  - ACKs return faster
  - CW grows faster
  - Lower perceived latency
```

### Loss Reduction Factor

| Metric | Impact |
|--------|--------|
| RTT | No direct impact |
| Latency | Affects latency during/after loss events (recovery time) |

---

## Practical Recommendations for Your Research

### 1. What to Measure

| For This Goal | Measure This | How |
|---------------|--------------|-----|
| Video <50ms latency | End-to-end latency | Timestamp frames at send/receive |
| Conference <20ms jitter | Inter-packet delay variance | Track receive timestamps |
| File >90% bandwidth | Throughput | Bytes transferred / time |

### 2. Use RTT as a Baseline

```python
def analyze_results(rtt_ms: float, measured_latency_ms: float):
    """Understand where latency comes from."""
    theoretical_one_way = rtt_ms / 2
    overhead = measured_latency_ms - theoretical_one_way

    print(f"RTT: {rtt_ms:.1f}ms")
    print(f"Theoretical one-way: {theoretical_one_way:.1f}ms")
    print(f"Measured latency: {measured_latency_ms:.1f}ms")
    print(f"Overhead (processing, buffering, ACK delay): {overhead:.1f}ms")
```

### 3. Report Both Metrics

In your research findings, report:

```
Test Conditions:
- Network RTT: 50ms (measured via QUIC)
- Max ACK Delay: 10ms

Results:
- Measured end-to-end latency: 38ms
- Breakdown: RTT/2 (25ms) + overhead (13ms)
- Meets <50ms target: Yes
```

---

## Localhost-Specific Considerations

### Is RTT/2 = Latency Valid on Localhost?

**Yes.** On localhost (127.0.0.1), RTT/2 is a valid estimate of one-way latency
because the path is **perfectly symmetric**.

### Why Localhost is Different

On a real network, RTT/2 might not equal one-way latency due to:
- Asymmetric routing (different paths in each direction)
- Different upload/download speeds
- Variable network conditions

On localhost, **none of these issues exist**:

| Factor | Real Network | Localhost |
|--------|--------------|-----------|
| Path symmetry | Often asymmetric | ✅ Perfectly symmetric |
| Propagation delay | Variable | ✅ ~0ms |
| Bandwidth asymmetry | Common | ✅ None |
| Network congestion | Variable | ✅ None |

### What Localhost RTT Actually Measures

```
┌─────────────────────────────────────────────────────────────────┐
│  Localhost RTT Components:                                      │
├─────────────────────────────────────────────────────────────────┤
│  ✅ QUIC encryption (TLS 1.3)      ~0.2ms  - Real overhead      │
│  ✅ aioquic library processing     ~0.1ms  - Real overhead      │
│  ✅ Python/asyncio event loop      ~0.1ms  - Real overhead      │
│  ✅ Kernel loopback interface      ~0.01ms - Negligible         │
│  ❌ Network propagation            0ms     - Not applicable     │
│  ❌ ACK delay                      0ms     - Subtracted by QUIC │
├─────────────────────────────────────────────────────────────────┤
│  Total RTT: ~1-7ms depending on traffic pattern                 │
│  One-way Latency (RTT/2): ~0.5-3.5ms                            │
└─────────────────────────────────────────────────────────────────┘
```

### Important: Processing Overhead IS Included

A common misconception is that localhost has "no overhead." In reality:

| Overhead Type | Present? | Included in RTT? | Symmetric? |
|---------------|:--------:|:----------------:|:----------:|
| QUIC encryption | ✅ Yes | ✅ Yes | ✅ Yes |
| Python runtime | ✅ Yes | ✅ Yes | ✅ Yes |
| Kernel networking | ✅ Yes | ✅ Yes | ✅ Yes |
| Network propagation | ❌ No | N/A | N/A |

**This overhead is valid to include** because:
1. It's real QUIC protocol latency (not artificial)
2. It's symmetric (same in both directions)
3. It's consistent across all tests

### Validation: Your Measured Values

| Application | RTT | Latency (RTT/2) | Valid? |
|-------------|-----|-----------------|:------:|
| Video Streaming | 2.45 ms | 1.22 ms | ✅ |
| Conference Call | 3.47 ms | 1.74 ms | ✅ |
| File Transfer | 6.95 ms | 3.48 ms | ✅ |

These values are consistent with TLS 1.3 + Python async overhead on localhost.

### References

- [RFC 9002 - QUIC Loss Detection and Congestion Control](https://datatracker.ietf.org/doc/rfc9002/)
- [APNIC Blog - Update QUIC timers once per RTT](https://blog.apnic.net/2023/07/27/update-quic-timers-once-per-rtt/)

---

## Summary

### Are RTT and Latency the Same?

| Aspect | RTT | Latency |
|--------|-----|---------|
| **Definition** | Round-trip time | One-way or end-to-end time |
| **Direction** | Sender → Receiver → Sender | Sender → Receiver |
| **Relationship** | One-way ≈ RTT/2 | Latency ≈ RTT/2 + overhead |
| **Measured by QUIC** | ✅ Automatically | ❌ Must measure manually |
| **What it tells you** | Network path characteristics | User-perceived delay |
| **Valid on localhost?** | ✅ Yes | ✅ Yes (as RTT/2) |

### Key Takeaways

1. **RTT ≠ Latency**, but they're related (latency ≈ RTT/2 + overhead)
2. **QUIC measures RTT** automatically; you must measure latency yourself
3. **On localhost, RTT/2 = Latency** because the path is perfectly symmetric
4. **Your <50ms latency goal** requires RTT < ~90ms (assuming 5ms overhead)
5. **Max ACK Delay** directly affects perceived latency (one of your parameters)
6. **Report both metrics** in your research for complete analysis

### Formula for Your Project

```
End-to-End Latency ≈ (RTT / 2) + Max_ACK_Delay_Impact + Processing_Overhead

Where:
- RTT/2: Network one-way delay (not controllable)
- Max_ACK_Delay_Impact: 0 to max_ack_delay (your parameter)
- Processing_Overhead: <1ms with synthetic data
```

For the video streaming goal of <50ms latency:
- Control Max ACK Delay to minimize its contribution
- Test on networks with RTT < 90ms
- Measure actual end-to-end latency, not just RTT

### References

- [RFC 9002 - QUIC Loss Detection and Congestion Control](https://datatracker.ietf.org/doc/rfc9002/)
- [APNIC Blog - Update QUIC timers once per RTT](https://blog.apnic.net/2023/07/27/update-quic-timers-once-per-rtt/)
- [APNIC Blog - QUIC timers don't work well](https://blog.apnic.net/2023/07/21/quic-timers-dont-work-well/)
