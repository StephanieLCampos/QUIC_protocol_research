# NEW Throughput Implementation Plan

## Comprehensive Guide to Implementing ACK-Verified Network Throughput

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Types of Throughput Explained](#2-types-of-throughput-explained)
3. [Why ACK-Verified Throughput](#3-why-ack-verified-throughput)
4. [Current vs Proposed Measurement](#4-current-vs-proposed-measurement)
5. [Code Architecture Overview](#5-code-architecture-overview)
6. [Implementation Details](#6-implementation-details)
7. [File Changes Summary](#7-file-changes-summary)
8. [Step-by-Step Implementation](#8-step-by-step-implementation)
9. [Testing and Validation](#9-testing-and-validation)
10. [Backward Compatibility](#10-backward-compatibility)

---

## 1. Executive Summary

### What We're Implementing

**ACK-Verified Throughput** (\`throughput_acked\`) - A measurement of data that has been confirmed as successfully delivered through the network, not just data that was sent.

### Why We Need This

The current implementation measures "offered load" (bytes queued to send), which does NOT reflect:
- Network bottlenecks
- Packet loss impact
- Actual data delivery rate
- Congestion window limitations

### Key Benefit

When optimizing CUBIC congestion control parameters, we need to know: **"Did the data actually get through?"** - not just "Did we try to send it?"

---

## 2. Types of Throughput Explained

### 2.1 Offered Load (Current Implementation)

\`\`\`
Definition: Data sent/attempted by the application
Formula:    bytes_sent / time
Measures:   Application demand
\`\`\`

**Analogy**: Counting letters as you drop them in the mailbox.

### 2.2 True Throughput / Goodput (Proposed Implementation)

\`\`\`
Definition: Data successfully delivered to destination
Formula:    bytes_acked / time
Measures:   Actual network delivery
\`\`\`

**Analogy**: Counting letters only when you receive a delivery confirmation.

### 2.3 Effective Throughput (Additional Metric)

\`\`\`
Definition: Theoretical maximum given current network state
Formula:    congestion_window / RTT
Measures:   Network capacity utilization
\`\`\`

### 2.4 Comparison Table

| Metric | Formula | What It Shows | Affected by Bottleneck? |
|--------|---------|---------------|------------------------|
| **Offered Load** | bytes_sent / time | App tried to send | No |
| **True Throughput** | bytes_acked / time | Data delivered | **Yes** |
| **Effective Throughput** | cwnd / RTT | Max possible | **Yes** |

---

## 3. Why ACK-Verified Throughput

### 3.1 Standard Practice

| Tool/Context | What It Measures | Method |
|--------------|------------------|--------|
| iperf | Bytes received | At receiver |
| speedtest | Bytes received | At receiver |
| TCP research | Bytes acknowledged | Via ACKs |
| QUIC research | Bytes acknowledged | Via ACKs |

**Industry standard is to measure data that arrived, not data that was sent.**

### 3.2 Research Requirements

For QUIC congestion control parameter optimization:

| Goal | Required Metric |
|------|-----------------|
| "How much data did the app generate?" | Offered load |
| "How well did parameters perform?" | **True throughput** |
| "What's the network's max capacity?" | Effective throughput |

### 3.3 Real-World Scenarios

#### Scenario 1: Network Bottleneck (5 Mbps limit)

| Metric | Current | With New Implementation |
|--------|---------|------------------------|
| Offered load | 10 Mbps | 10 Mbps |
| True throughput | (not measured) | **5 Mbps** |

Current implementation would show 10 Mbps even though only 5 Mbps got through!

#### Scenario 2: 2% Packet Loss

| Metric | Current | With New Implementation |
|--------|---------|------------------------|
| Offered load | 10 Mbps | 10 Mbps |
| True throughput | (not measured) | **~9.8 Mbps** |

---

## 4. Current vs Proposed Measurement

### 4.1 Current Measurement Point

\`\`\`
+-----------------------------------------------------------------+
|                    CURRENT: Offered Load                         |
+-----------------------------------------------------------------+
|                                                                  |
|  Synthesizer                                                     |
|      |                                                           |
|      v                                                           |
|  send_stream_data(packet.data)                                  |
|      |                                                           |
|      v                                                           |
|  record_packet_sent(size)  <-- CURRENT MEASUREMENT POINT        |
|      |                                                           |
|      v                                                           |
|  +---------------+                                               |
|  | aioquic       |                                               |
|  | send buffer   |  <-- Data may queue here (NOT measured)      |
|  +-------+-------+                                               |
|          |                                                       |
|          v                                                       |
|      Network      <-- Bottleneck here (NOT measured)            |
|          |                                                       |
|          v                                                       |
|       Server      <-- Delivery here (NOT measured)              |
|                                                                  |
+-----------------------------------------------------------------+
\`\`\`

### 4.2 Proposed Measurement Points

\`\`\`
+-----------------------------------------------------------------+
|                    PROPOSED: Multiple Points                     |
+-----------------------------------------------------------------+
|                                                                  |
|  Synthesizer                                                     |
|      |                                                           |
|      v                                                           |
|  send_stream_data(packet.data)                                  |
|      |                                                           |
|      v                                                           |
|  record_packet_sent(size)  <-- POINT 1: Offered Load (keep)     |
|      |                                                           |
|      v                                                           |
|  +---------------+                                               |
|  | aioquic       |                                               |
|  | send buffer   |                                               |
|  +-------+-------+                                               |
|          |                                                       |
|          v                                                       |
|      Network                                                     |
|          |         <-- POINT 2: bytes_in_flight (cwnd limited)  |
|          v                                                       |
|       Server                                                     |
|          |                                                       |
|          v                                                       |
|      ACK sent                                                    |
|          |                                                       |
|          v                                                       |
|  ACK received      <-- POINT 3: bytes_acked (TRUE THROUGHPUT)   |
|                                                                  |
+-----------------------------------------------------------------+
\`\`\`

---

## 5. Code Architecture Overview

### 5.1 Directory Structure and Dependencies

\`\`\`
QUIC_3conn_implementation/
|
+-- 3_conn_code/                    <-- CORE CODE (change here)
|   +-- metrics/
|   |   +-- collector.py            <-- Add bytes_acked tracking
|   |   +-- calculator.py           <-- Add throughput_acked calculation
|   |   +-- exporter.py             <-- Add new columns to CSV
|   +-- simulation/
|   |   +-- worker_process.py       <-- Add network metric sampling
|   |   +-- result.py               <-- Add new fields to results
|   +-- synthesizers/               (no changes needed)
|
+-- research_code/                  <-- USES 3_conn_code (auto-inherits)
|   +-- experiment_runner.py        (no changes needed - imports from 3_conn_code)
|
+-- grid_search_code/               <-- USES 3_conn_code (needs RunResult update)
|   +-- runner/
|       +-- single_connection_runner.py  <-- Update RunResult dataclass
|
+-- wireless_bottleneck/            (no changes needed)
\`\`\`

### 5.2 Import Chain

\`\`\`
research_code/experiment_runner.py
    |
    | sys.path.insert(0, "3_conn_code")
    |
    +---> 3_conn_code/simulation/process_orchestrator.py
             +---> 3_conn_code/metrics/collector.py  <-- Changes propagate


grid_search_code/runner/single_connection_runner.py
    |
    | sys.path.insert(0, "3_conn_code")
    |
    +---> 3_conn_code/metrics/collector.py  <-- Changes propagate
\`\`\`

### 5.3 Key Insight: Change Once, Affects All

Because \`research_code\` and \`grid_search_code\` both import from \`3_conn_code\`:

| If you change... | Effect on... |
|------------------|--------------|
| \`3_conn_code/metrics/collector.py\` | **All three directories** |
| \`3_conn_code/metrics/calculator.py\` | **All three directories** |
| \`3_conn_code/simulation/worker_process.py\` | **All three directories** |

**Exception**: \`grid_search_code\` has its own \`RunResult\` dataclass that needs updating separately.

---

## 6. Implementation Details

### 6.1 Available aioquic Metrics

From \`aioquic/quic/recovery.py\`:

\`\`\`python
protocol._quic._loss.bytes_in_flight      # Bytes sent but not yet ACKed
protocol._quic._loss.congestion_window    # Current cwnd
protocol._quic._loss._rtt_smoothed        # Smoothed RTT (already used)
protocol._quic._loss._cc.ssthresh         # Slow start threshold
\`\`\`

### 6.2 Changes to 3_conn_code/metrics/collector.py

#### Add New Fields

\`\`\`python
@dataclass
class MetricsCollector:
    # Existing fields...
    bytes_sent: int = 0
    bytes_received: int = 0

    # NEW: ACK-verified tracking
    bytes_acked: int = 0
    _last_bytes_in_flight: int = 0

    # NEW: Network state tracking
    cwnd_samples: List[int] = field(default_factory=list)
    bytes_in_flight_samples: List[int] = field(default_factory=list)
\`\`\`

#### Add New Methods

\`\`\`python
def sample_network_metrics(self, protocol) -> None:
    """
    Sample network-level metrics from aioquic.
    
    Call this periodically (every 100ms) to track:
    - Congestion window
    - Bytes in flight
    - Compute bytes acknowledged
    """
    if protocol is None:
        return

    try:
        loss = protocol._quic._loss

        # Sample cwnd and bytes_in_flight
        cwnd = loss.congestion_window
        bytes_in_flight = loss.bytes_in_flight

        self.cwnd_samples.append(cwnd)
        self.bytes_in_flight_samples.append(bytes_in_flight)

        # Compute bytes acknowledged
        # bytes_acked = bytes_sent - bytes_in_flight
        current_acked = self.bytes_sent - bytes_in_flight
        if current_acked > self.bytes_acked:
            self.bytes_acked = current_acked

    except AttributeError:
        pass


def get_throughput_acked(self) -> float:
    """Get ACK-verified throughput in bytes per second."""
    if self.duration <= 0:
        return 0.0
    return self.bytes_acked / self.duration


def get_throughput_effective(self, protocol) -> float:
    """Get effective throughput based on cwnd/RTT."""
    if protocol is None:
        return 0.0

    try:
        loss = protocol._quic._loss
        cwnd = loss.congestion_window
        rtt = loss._rtt_smoothed

        if rtt <= 0:
            return 0.0

        return cwnd / rtt

    except AttributeError:
        return 0.0
\`\`\`

### 6.3 Changes to 3_conn_code/metrics/calculator.py

#### Update MetricsResult Dataclass

\`\`\`python
@dataclass
class MetricsResult:
    # Existing fields
    throughput: float           # Offered load - KEEP
    rtt: float
    latency: float
    jitter: float
    packet_loss_rate: float
    connection_establishment_time: float

    # NEW: Additional throughput metrics
    throughput_acked: float = 0.0       # ACK-verified throughput
    throughput_effective: float = 0.0   # cwnd/RTT theoretical max
    bytes_acked: int = 0                # Total bytes acknowledged
    avg_cwnd: float = 0.0               # Average congestion window
    avg_bytes_in_flight: float = 0.0    # Average bytes in flight
\`\`\`

### 6.4 Changes to grid_search_code/runner/single_connection_runner.py

#### Update RunResult Dataclass

\`\`\`python
@dataclass
class RunResult:
    success: bool
    combo: ParameterCombination

    # Existing metrics
    throughput: float = 0.0
    latency: float = 0.0
    jitter: float = 0.0
    rtt: float = 0.0
    packet_loss_rate: float = 0.0
    bytes_sent: int = 0
    error_message: Optional[str] = None

    # NEW: ACK-verified throughput metrics
    throughput_acked: float = 0.0
    throughput_effective: float = 0.0
    bytes_acked: int = 0
    avg_cwnd: float = 0.0
    avg_bytes_in_flight: float = 0.0
\`\`\`

---

## 7. File Changes Summary

### 7.1 Files That Need Manual Changes

| File | Changes Required | Priority |
|------|------------------|----------|
| \`3_conn_code/metrics/collector.py\` | Add new fields and methods | **HIGH** |
| \`3_conn_code/metrics/calculator.py\` | Update MetricsResult | **HIGH** |
| \`3_conn_code/simulation/worker_process.py\` | Add network sampling | **HIGH** |
| \`grid_search_code/runner/single_connection_runner.py\` | Update RunResult | **HIGH** |

### 7.2 Files That Auto-Inherit Changes

| File | Why No Changes Needed |
|------|----------------------|
| \`research_code/experiment_runner.py\` | Imports from 3_conn_code |
| \`research_code/results_extractor.py\` | Will see new fields automatically |
| All synthesizers | No throughput logic |

---

## 8. Step-by-Step Implementation

### Phase 1: Core Metrics (3_conn_code)

- [ ] Step 1.1: Update \`metrics/collector.py\` - Add new fields and methods
- [ ] Step 1.2: Update \`metrics/calculator.py\` - Update MetricsResult
- [ ] Step 1.3: Update \`simulation/worker_process.py\` - Add sampling

### Phase 2: Grid Search Integration

- [ ] Step 2.1: Update \`grid_search_code/runner/single_connection_runner.py\`

### Phase 3: Testing

- [ ] Step 3.1: Localhost validation (throughput ≈ throughput_acked)
- [ ] Step 3.2: Grid search validation (new columns in CSV)

---

## 9. Testing and Validation

### 9.1 Localhost Test

\`\`\`bash
cd 3_conn_code
uv run python -m main run --duration 30
\`\`\`

**Expected**: \`throughput ≈ throughput_acked\` (within 5%)

### 9.2 Grid Search Test

\`\`\`bash
cd grid_search_code
uv run python main.py run --app-type video_streaming --duration 10
\`\`\`

**Check CSV has new columns**: throughput_acked, bytes_acked, avg_cwnd

---

## 10. Backward Compatibility

### What Stays the Same

- \`throughput\` field remains (now called "offered load")
- All existing CSV columns preserved
- Existing analysis scripts work unchanged

### What's New (Additive)

| New Field | Description |
|-----------|-------------|
| \`throughput_acked\` | ACK-verified throughput |
| \`throughput_effective\` | cwnd/RTT theoretical max |
| \`bytes_acked\` | Total bytes acknowledged |
| \`avg_cwnd\` | Average congestion window |
| \`avg_bytes_in_flight\` | Average bytes in flight |

---

## 11. Summary

### What We're Implementing

**ACK-Verified Throughput** - measuring data confirmed delivered, not just sent.

### Why This Metric

- **Standard practice**: iperf, speedtest measure received data
- **Reflects reality**: Shows actual network performance
- **Bottleneck visibility**: Shows impact of congestion/loss
- **Parameter optimization**: Shows if changes improved delivery

### How It Works

\`\`\`
bytes_acked = bytes_sent - bytes_in_flight
throughput_acked = bytes_acked / duration
\`\`\`

### Final Result

| Metric | Purpose |
|--------|---------|
| \`throughput\` | App demand (offered load) |
| \`throughput_acked\` | **True network throughput** |
| \`throughput_effective\` | Theoretical max capacity |

---

## 12. References

- RFC 9002 - QUIC Loss Detection and Congestion Control
- RFC 9438 - CUBIC for Fast and Long-Distance Networks
- \`aioquic/quic/recovery.py\` - QuicPacketRecovery class
- \`Diff_throughput_info.md\` - Throughput types explanation
