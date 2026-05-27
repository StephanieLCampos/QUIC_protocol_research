# Throughput Measurements Report

## QUIC 3-Connection Simulation with Q-Learning Optimization

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Problem Statement](#problem-statement)
3. [Throughput Measurement Types](#throughput-measurement-types)
4. [Cumulative ACK-Based Throughput](#cumulative-ack-based-throughput-throughput_acked)
5. [Per-Epoch Delta Throughput](#per-epoch-delta-throughput-throughput_acked_delta)
6. [Comparison: Cumulative vs Delta](#comparison-cumulative-vs-delta)
7. [Integration with Q-Learning](#integration-with-q-learning)
8. [Code Implementation](#code-implementation)
9. [Output Labels in Results](#output-labels-in-results)
10. [Recommendations](#recommendations)

---

## Executive Summary

This report documents two throughput measurement methods implemented for the QUIC 3-connection simulation:

| Metric | Formula | Responsiveness | Best For |
|--------|---------|----------------|----------|
| **Cumulative** (`throughput_acked`) | `total_bytes_acked / total_duration` | Slow (averages entire run) | Stable network conditions |
| **Per-Epoch Delta** (`throughput_acked_delta`) | `Δbytes_acked / Δtime` | Fast (~100ms windows) | Varying network conditions |

Both metrics measure **ACK-verified throughput** - the actual data delivery rate through network bottlenecks, not just the application send rate.

---

## Problem Statement

### The Original Issue

The original throughput metric (`throughput`) measured the **application send rate**:

```python
throughput = bytes_sent / duration
```

With a TC bottleneck limiting the network to 5 Mbps, this created a significant problem:

| Connection | Application Send Rate | Actual Delivery | Q-Learning Saw |
|------------|----------------------|-----------------|----------------|
| Video Streaming | 1.33 Mbps | 1.32 Mbps | 1.33 Mbps |
| **File Transfer** | **221 Mbps** | **1.88 Mbps** | **221 Mbps** |
| Conference Call | 0.115 Mbps | 0.115 Mbps | 0.115 Mbps |

**Critical Problem**: Q-learning thought File Transfer was performing excellently at 221 Mbps when it was actually bottlenecked to ~2 Mbps.

### The Solution

Implement ACK-based throughput measurements that reflect **actual data delivery** through the bottleneck, not just send attempts.

---

## Throughput Measurement Types

### Overview of All Metrics

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Throughput Metrics Hierarchy                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. OFFERED THROUGHPUT (throughput)                                          │
│     └── Formula: bytes_sent / duration                                       │
│     └── Measures: Application send rate                                      │
│     └── Problem: Doesn't reflect bottleneck - shows 221 Mbps when only       │
│                  2 Mbps gets through                                         │
│                                                                              │
│  2. CUMULATIVE ACK-BASED (throughput_acked)                                  │
│     └── Formula: bytes_acked / total_duration                                │
│     └── Measures: Average delivery rate over entire connection               │
│     └── Reflects: Actual throughput through bottleneck                       │
│     └── Limitation: Slow to respond to network changes                       │
│                                                                              │
│  3. PER-EPOCH DELTA (throughput_acked_delta)                                 │
│     └── Formula: (bytes_acked_now - bytes_acked_prev) / time_delta           │
│     └── Measures: Delivery rate in current ~100ms window                     │
│     └── Reflects: Real-time throughput changes                               │
│     └── Limitation: More noisy than cumulative                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Cumulative ACK-Based Throughput (`throughput_acked`)

### Definition

**Cumulative ACK-based throughput** measures the total bytes acknowledged by the receiver divided by the total connection duration.

### Formula

```
throughput_acked = bytes_acked / duration

where:
  bytes_acked = bytes_sent - bytes_in_flight
  duration = current_time - start_time
```

### How It Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        ACK-Based Measurement Flow                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  CLIENT                                          SERVER                      │
│    │                                               │                         │
│    │  ──────── Data Packet 1 (1500 bytes) ──────► │                         │
│    │  ──────── Data Packet 2 (1500 bytes) ──────► │                         │
│    │  ──────── Data Packet 3 (1500 bytes) ──────► │                         │
│    │                                               │                         │
│    │  bytes_sent = 4500                           │                         │
│    │  bytes_in_flight = 4500                      │                         │
│    │  bytes_acked = 0                             │                         │
│    │                                               │                         │
│    │  ◄──────── ACK for packets 1-2 ───────────  │                         │
│    │                                               │                         │
│    │  bytes_sent = 4500                           │                         │
│    │  bytes_in_flight = 1500  (only pkt 3)       │                         │
│    │  bytes_acked = 3000                          │                         │
│    │                                               │                         │
│    │  throughput_acked = 3000 / elapsed_time      │                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Source

The measurement uses aioquic's internal loss handler:

```python
# From aioquic's QuicPacketRecovery
loss_handler = protocol._quic._loss
bytes_in_flight = loss_handler.bytes_in_flight  # Sent but not ACKed

# Calculate acknowledged bytes
bytes_acked = bytes_sent - bytes_in_flight
```

### Characteristics

| Property | Value |
|----------|-------|
| **Update Frequency** | Every ~100ms (sampling interval) |
| **Calculation Window** | Entire connection duration |
| **Responsiveness** | Slow - averages all historical data |
| **Noise Level** | Low - very smooth values |
| **Accuracy** | High - reflects true delivery |

### Use Case

Best for **stable network conditions** where the bottleneck capacity doesn't change:

- `congested_low` (constant 5 Mbps)
- `stable_high` (constant 100 Mbps)
- `lossy` (constant 10 Mbps with packet loss)

### Limitation: Slow Response to Changes

```
Timeline: Bandwidth drops from 10 Mbps to 2 Mbps at t=30s

Time:           0s -------- 30s -------- 60s
Actual BW:      [   10 Mbps    ][   2 Mbps    ]

Cumulative measurement:
                10 → 10 → 10 → 8 → 7 → 6 → 5.5 → 5 Mbps
                              ↑
                     Still averaging old high-throughput data
```

---

## Per-Epoch Delta Throughput (`throughput_acked_delta`)

### Definition

**Per-epoch delta throughput** measures the bytes acknowledged in the **current measurement window only**, not the cumulative average.

### Formula

```
throughput_acked_delta = (bytes_acked_now - bytes_acked_prev) / (time_now - time_prev)

where:
  bytes_acked_now = current bytes_acked value
  bytes_acked_prev = bytes_acked from previous measurement (~100ms ago)
  time_now - time_prev ≈ 100ms (sampling interval)
```

### How It Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Delta Measurement Flow                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Time    bytes_acked    Δbytes    Δtime    Delta Throughput                 │
│  ─────   ───────────    ──────    ─────    ────────────────                 │
│  0.0s         0           -         -            -                          │
│  0.1s     12,500      12,500     0.1s      125,000 B/s (1.0 Mbps)           │
│  0.2s     25,200      12,700     0.1s      127,000 B/s (1.0 Mbps)           │
│  0.3s     37,800      12,600     0.1s      126,000 B/s (1.0 Mbps)           │
│                                                                              │
│  [Bandwidth drops at t=0.35s]                                                │
│                                                                              │
│  0.4s     40,300       2,500     0.1s       25,000 B/s (0.2 Mbps) ← Immediate│
│  0.5s     42,800       2,500     0.1s       25,000 B/s (0.2 Mbps)            │
│                                                                              │
│  Compare to cumulative at t=0.5s:                                            │
│  Cumulative: 42,800 / 0.5 = 85,600 B/s (0.68 Mbps) ← Still high!            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation

```python
def get_throughput_acked_delta(self) -> float:
    """
    Calculate throughput for the current measurement window only.
    """
    now = time.time()

    # First call - initialize
    if self._prev_delta_time is None:
        self._prev_delta_time = now
        self._prev_bytes_acked = self.bytes_acked
        return 0.0

    elapsed = now - self._prev_delta_time

    # Minimum 50ms between calculations to avoid noise
    if elapsed < 0.05:
        return self._last_delta_throughput

    # Calculate delta
    delta_bytes = self.bytes_acked - self._prev_bytes_acked
    delta_throughput = delta_bytes / elapsed if elapsed > 0 else 0.0

    # Update tracking for next call
    self._prev_bytes_acked = self.bytes_acked
    self._prev_delta_time = now
    self._last_delta_throughput = delta_throughput

    return delta_throughput
```

### Characteristics

| Property | Value |
|----------|-------|
| **Update Frequency** | Every ~100ms |
| **Calculation Window** | Last ~100ms only |
| **Responsiveness** | Fast - reflects current state |
| **Noise Level** | Higher - shows short-term fluctuations |
| **Accuracy** | High - reflects true delivery |

### Use Case

Best for **varying network conditions** where bandwidth changes over time:

- `varying` (20 Mbps ±40% oscillating)
- Custom dynamic scenarios
- Mobile/wireless conditions with fading

### Advantage: Fast Response to Changes

```
Timeline: Bandwidth drops from 10 Mbps to 2 Mbps at t=30s

Time:           0s -------- 30s -------- 60s
Actual BW:      [   10 Mbps    ][   2 Mbps    ]

Delta measurement:
                10 → 10 → 10 → 2 → 2 → 2 → 2 → 2 Mbps
                              ↑
                     Immediately reflects the change
```

---

## Comparison: Cumulative vs Delta

### Side-by-Side Comparison

| Aspect | Cumulative (`throughput_acked`) | Delta (`throughput_acked_delta`) |
|--------|--------------------------------|----------------------------------|
| **Formula** | `bytes_acked / total_time` | `Δbytes / Δtime` |
| **Window** | Entire connection | Last ~100ms |
| **Responsiveness** | Slow (seconds to minutes) | Fast (~100ms) |
| **Noise** | Very smooth | More variable |
| **Best For** | Stable conditions | Varying conditions |
| **Q-Learning** | Good for steady-state | Good for adaptation |

### Visual Comparison

```
Scenario: Bandwidth oscillates between 12-28 Mbps (varying scenario)

                    Actual Bandwidth
        28 ─┼─────╮          ╭─────╮          ╭─────
           │      ╲        ╱      ╲        ╱
        20 ─┼───────╳──────╳────────╳──────╳───────
           │      ╱        ╲      ╱        ╲
        12 ─┼─────╯          ╰─────╯          ╰─────
           └──────┬──────┬──────┬──────┬──────┬────
                  1s     2s     3s     4s     5s

        Cumulative Throughput (throughput_acked)
        28 ─┼
           │                    ╭──────────────────  (converges to average)
        20 ─┼────────────────────
           │
        12 ─┼
           └──────┬──────┬──────┬──────┬──────┬────

        Delta Throughput (throughput_acked_delta)
        28 ─┼─────╮          ╭─────╮          ╭─────  (tracks actual)
           │      ╲        ╱      ╲        ╱
        20 ─┼───────╳──────╳────────╳──────╳───────
           │      ╱        ╲      ╱        ╲
        12 ─┼─────╯          ╰─────╯          ╰─────
           └──────┬──────┬──────┬──────┬──────┬────
```

### When to Use Each

| Network Scenario | Recommended Metric | Reason |
|------------------|-------------------|--------|
| `stable_high` | Cumulative | Bandwidth constant |
| `congested_low` | Cumulative | Bandwidth constant |
| `lossy` | Cumulative | Bandwidth constant |
| `varying` | **Delta** | Bandwidth oscillates |
| `asymmetric` | Cumulative | Bandwidth constant |
| Custom dynamic | **Delta** | Bandwidth changes |

---

## Integration with Q-Learning

### How Q-Learning Uses Throughput

The Q-learning agent uses throughput for:

1. **State Building** - Discretize throughput into bins for Q-table lookup
2. **Reward Calculation** - Compute utility for File Transfer connection
3. **Logging** - Display throughput in agent logs

### Configuration

The throughput metric is configurable in `ml_callbacks/q_learning_agent.py`:

```python
# Line ~122
THROUGHPUT_METRIC = "delta"   # Options: "offered", "acked", "delta"
```

### Metric Selection Logic

```python
def _get_throughput(metrics: Dict[int, dict], conn_id: int) -> float:
    """Get throughput based on configured metric type."""
    conn_metrics = metrics.get(conn_id, {})

    if THROUGHPUT_METRIC == "delta":
        delta = conn_metrics.get("throughput_acked_delta", 0.0)
        # Fall back to cumulative if delta not available yet
        if delta > 0:
            return delta
        return conn_metrics.get("throughput_acked", 0.0)
    elif THROUGHPUT_METRIC == "acked":
        return conn_metrics.get("throughput_acked", 0.0)
    else:  # "offered"
        return conn_metrics.get("throughput", 0.0)
```

### Q-Learning Log Output

The agent logs show both metrics for comparison:

```
[QLAgent step=  10] state=(1, 2, 0, 1, 2, 1) action=file.cubic_c ↑ ε=0.285
lat=18.5ms tp=1.85Mbps(Δ=2.10) jit=5.2ms avg_R=+0.412 Q-states=8
           │              │         │
           │              │         └── Delta throughput for comparison
           │              └── Active metric being used
           └── Latency from video streaming connection
```

### Impact on Q-Learning Performance

| Metric | Stable Scenarios | Varying Scenarios |
|--------|-----------------|-------------------|
| `offered` | Wrong signal (221 vs 2 Mbps) | Wrong signal |
| `acked` | Correct, smooth | Correct but slow to adapt |
| `delta` | Correct, slightly noisy | Correct, fast adaptation |

---

## Code Implementation

### File Locations

| Component | File Path | Lines |
|-----------|-----------|-------|
| Delta tracking fields | `metrics/collector.py` | 63-66 |
| `get_throughput_acked_delta()` | `metrics/collector.py` | 221-251 |
| `reset_delta_tracking()` | `metrics/collector.py` | 253-257 |
| Delta reset in `reset()` | `metrics/collector.py` | 276-279 |
| Delta reset in `reset_for_new_epoch()` | `metrics/collector.py` | 359-363 |
| IPC payload with delta | `simulation/worker_process.py` | 138-165 |
| Q-learning metric selection | `ml_callbacks/q_learning_agent.py` | 118-122 |
| `_get_throughput()` helper | `ml_callbacks/q_learning_agent.py` | 208-230 |

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Throughput Data Flow                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Worker Process (per connection)                                     │    │
│  │                                                                      │    │
│  │  aioquic._loss.bytes_in_flight ──► MetricsCollector                 │    │
│  │                                         │                            │    │
│  │                              ┌──────────┴──────────┐                 │    │
│  │                              │                     │                 │    │
│  │                    calculate_metrics()    get_throughput_acked_delta()   │
│  │                              │                     │                 │    │
│  │                    throughput_acked    throughput_acked_delta        │    │
│  │                              │                     │                 │    │
│  │                              └──────────┬──────────┘                 │    │
│  │                                         │                            │    │
│  │                              _send_metrics() ─────────────────────►  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                            │                                 │
│                                   IPC Message Queue                          │
│                                            │                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Main Process                           │                            │    │
│  │                                         ▼                            │    │
│  │                              ProcessOrchestrator                     │    │
│  │                                         │                            │    │
│  │                              MLController.on_metrics()               │    │
│  │                                         │                            │    │
│  │                              Q-Learning Agent                        │    │
│  │                                         │                            │    │
│  │                    ┌────────────────────┼────────────────────┐       │    │
│  │                    │                    │                    │       │    │
│  │            _build_state()         _reward()            _log()        │    │
│  │                    │                    │                    │       │    │
│  │            _get_throughput() ◄──────────┴────────────────────┘       │    │
│  │                    │                                                 │    │
│  │         ┌──────────┴──────────┐                                      │    │
│  │         │                     │                                      │    │
│  │   THROUGHPUT_METRIC     THROUGHPUT_METRIC                            │    │
│  │      == "delta"            == "acked"                                │    │
│  │         │                     │                                      │    │
│  │   throughput_acked_delta  throughput_acked                           │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### IPC Message Payload

```python
# From worker_process.py _send_metrics()
payload = {
    "throughput": metrics.throughput,           # Offered (send rate)
    "throughput_acked": metrics.throughput_acked,       # Cumulative ACK-based
    "throughput_acked_delta": throughput_acked_delta,   # Per-epoch delta
    "rtt": metrics.rtt,
    "latency": metrics.latency,
    "jitter": metrics.jitter,
    "packet_loss_rate": metrics.packet_loss_rate,
    "bytes_sent": self._metrics_collector.bytes_sent,
    "bytes_acked": metrics.bytes_acked,
    "current_params": { ... },
}
```

---

## Output Labels in Results

### Results Summary Files

The output JSON files use distinct labels to differentiate throughput sources:

| Label | Source | Measurement |
|-------|--------|-------------|
| `client_offered_mbps` | Client | Application send rate |
| `client_acked_mbps` | Client | ACK-verified throughput |
| `server_received_mbps` | Server | Bytes received / duration |
| `delivery_ratio_percent` | Calculated | server_received / client_sent |

### Example Output

```json
{
  "connections": {
    "2": {
      "application_type": "file_transfer",
      "client_offered_mbps": 220.76,
      "client_acked_mbps": 1.94,
      "server_received_mbps": 1.94,
      "delivery_ratio_percent": 0.88,
      "rtt_median_ms": 41.53,
      "latency_median_ms": 20.77,
      "jitter_median_ms": 0.09
    }
  }
}
```

### Interpretation

- **client_offered_mbps = 220.76**: App tried to send at 220 Mbps
- **client_acked_mbps = 1.94**: Only 1.94 Mbps was ACK-verified as delivered
- **server_received_mbps = 1.94**: Server confirms receiving 1.94 Mbps
- **delivery_ratio_percent = 0.88%**: Only 0.88% of sent data got through (bottleneck working!)

---

## Recommendations

### Default Configuration

For most use cases, use **delta throughput** as the default:

```python
THROUGHPUT_METRIC = "delta"
```

Rationale:
- Works well for both stable and varying conditions
- Falls back to cumulative if delta not yet available
- Provides faster feedback for Q-learning adaptation

### Scenario-Specific Configuration

| Scenario | Recommended Setting |
|----------|---------------------|
| `stable_high` | Either works, `acked` is smoother |
| `congested_low` | Either works, `acked` is smoother |
| `varying` | **Must use `delta`** |
| `lossy` | Either works |
| `asymmetric` | Either works |
| Custom dynamic | **Must use `delta`** |

### Validation

To verify throughput measurements are working correctly:

1. Check `client_acked_mbps` is close to bottleneck capacity (not 200+ Mbps)
2. Compare `client_acked_mbps` with `server_received_mbps` (should be similar)
3. Verify `delivery_ratio_percent` < 100% for File Transfer (indicates bottleneck is active)

---

## Appendix: Mathematical Definitions

### Cumulative Throughput

```
                    Σ(acknowledged bytes from t=0 to t=now)
throughput_acked = ─────────────────────────────────────────
                              now - start_time

                    bytes_sent - bytes_in_flight
                 = ──────────────────────────────
                           duration
```

### Delta Throughput

```
                          bytes_acked(t) - bytes_acked(t - Δt)
throughput_acked_delta = ─────────────────────────────────────
                                        Δt

where Δt ≈ 100ms (sampling interval)
```

### Relationship

```
                              t
                           1  ⌠
throughput_acked(t) =      ─  │ throughput_acked_delta(τ) dτ
                           t  ⌡
                              0

(Cumulative is the time-average of all delta values)
```

---

## Document Information

| Field | Value |
|-------|-------|
| **Created** | April 2026 |
| **Project** | QUIC 3-Connection Simulation |
| **Purpose** | Document throughput measurement implementation |
| **Related Files** | `metrics/collector.py`, `ml_callbacks/q_learning_agent.py`, `simulation/worker_process.py` |
