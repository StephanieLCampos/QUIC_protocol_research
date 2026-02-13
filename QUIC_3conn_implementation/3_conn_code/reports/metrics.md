# Metrics System Documentation

This document explains how metrics are measured, collected, and exported in the QUIC 3-Connection simulation.

---

## Overview

The `/metrics` directory contains 4 files that work together:

| File | Purpose |
|------|---------|
| `collector.py` | Real-time data collection during simulation |
| `calculator.py` | Pure calculation functions for computing metrics |
| `epoch.py` | Epoch-based metrics with settling time support |
| `exporter.py` | Export utilities (CSV format) |

---

## The 6 Performance Metrics

| Metric | Unit | Description |
|--------|------|-------------|
| **Throughput** | bytes/sec | Data transfer rate |
| **RTT** | seconds | Round-trip time |
| **Latency** | seconds | One-way delay (estimated as RTT / 2) |
| **Jitter** | seconds | Variation in inter-packet delay |
| **Packet Loss Rate** | 0.0 - 1.0 | Fraction of packets lost |
| **Connection Establishment Time** | seconds | Time for QUIC handshake |

---

## Where Each Metric Is Measured

### 1. Throughput

**Location:** `calculator.py:50-66`

**Formula:**
```
throughput = total_bytes_sent / duration_seconds
```

**Data Source:**
- `bytes_sent` is incremented in `collector.py:70-79` every time `record_packet_sent(size)` is called
- `duration_seconds` is calculated from `start_time` to `end_time` in `collector.py:122-128`

**When Measured:**
- Every time `calculate_metrics()` is called (every 100ms during simulation)

---

### 2. RTT (Round-Trip Time)

**Location:** `calculator.py:177-180`

**Formula:**
```
rtt = mean(rtt_samples)
```

**Data Source:**
- RTT samples are read from aioquic's internal loss handler: `protocol._quic._loss._rtt_smoothed`
- Collected in `worker_process.py:288-290`:
  ```python
  rtt = self._get_rtt(protocol)
  if rtt and rtt > 0:
      self._metrics_collector.record_rtt_sample(rtt)
  ```

**How aioquic Calculates RTT:**
- aioquic uses the QUIC standard smoothed RTT calculation
- Updated when ACK frames are received
- `_rtt_smoothed` is an exponentially weighted moving average

---

### 3. Latency

**Location:** `calculator.py:129-144`

**Formula:**
```
latency = rtt / 2
```

**Assumption:**
- Symmetric network path (send delay = receive delay)
- This is an estimation; actual one-way latency requires synchronized clocks

---

### 4. Jitter

**Location:** `calculator.py:68-103`

**Formula:**
```
jitter = standard_deviation(inter_packet_delays)
```

**Calculation Steps:**
1. Calculate delays between consecutive packet timestamps:
   ```python
   delays = [timestamps[i] - timestamps[i-1] for i in range(1, len(timestamps))]
   ```
2. Compute standard deviation of delays using `statistics.stdev()`

**Data Source:**
- Packet send timestamps recorded in `collector.py:79`:
  ```python
  self.send_timestamps.append(time.time())
  ```

**Why This Matters:**
- Low jitter is critical for conference calls (real-time audio)
- High jitter causes audio gaps and video stuttering

---

### 5. Packet Loss Rate

**Location:** `calculator.py:105-127`

**Formula:**
```
packet_loss_rate = (packets_sent - packets_received) / packets_sent
```

**Data Source:**
- `collector.py:143-162` attempts to read from aioquic's internal tracking:
  ```python
  loss_handler = getattr(self.connection, "_loss", None)
  actual_packets_lost = getattr(loss_handler, "_packets_lost", 0)
  ```

**Fallback:**
- If aioquic internals aren't accessible, uses manual counters

---

### 6. Connection Establishment Time

**Location:** `collector.py:130-135`

**Formula:**
```
connection_time = connection_ready_time - start_time
```

**Data Source:**
- `start_time` set when `collector.start()` is called
- `connection_ready_time` set when `record_connection_ready()` is called after QUIC handshake completes

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      Worker Process                              │
│                                                                  │
│  ┌──────────────┐    ┌──────────────────┐    ┌───────────────┐  │
│  │  Synthesizer │───>│  QUIC Connection │───>│ MetricsCollector│ │
│  │ (generates   │    │  (sends data,    │    │ (records events)│ │
│  │  packets)    │    │  gets ACKs)      │    │                 │ │
│  └──────────────┘    └──────────────────┘    └───────┬─────────┘ │
│                                                       │          │
│                                              ┌────────▼────────┐ │
│                                              │MetricsCalculator│ │
│                                              │ (computes 6     │ │
│                                              │  metrics)       │ │
│                                              └────────┬────────┘ │
│                                                       │          │
└───────────────────────────────────────────────────────┼──────────┘
                                                        │
                                            ┌───────────▼───────────┐
                                            │    Metrics Queue      │
                                            │ (IPC to main process) │
                                            └───────────┬───────────┘
                                                        │
                    ┌───────────────────────────────────▼───────────┐
                    │              Main Process                      │
                    │  ┌─────────────────┐    ┌──────────────────┐  │
                    │  │ ProcessOrchestrator│  │    Web UI        │ │
                    │  │ (stores metrics) │──>│ (displays live)  │  │
                    │  └─────────────────┘    └──────────────────┘  │
                    │           │                                    │
                    │           ▼                                    │
                    │  ┌─────────────────┐                          │
                    │  │ MetricsExporter │                          │
                    │  │ (JSON/CSV files)│                          │
                    │  └─────────────────┘                          │
                    └────────────────────────────────────────────────┘
```

---

## MetricsCollector Class

**File:** `collector.py`

### Key Attributes

| Attribute | Type | Purpose |
|-----------|------|---------|
| `connection` | aioquic.QuicConnection | Reference to QUIC connection for RTT access |
| `bytes_sent` | int | Cumulative bytes transmitted |
| `packets_sent` | int | Cumulative packets transmitted |
| `rtt_samples` | List[float] | Collected RTT measurements |
| `send_timestamps` | List[float] | Packet send times for jitter calculation |
| `start_time` | float | Simulation start timestamp |

### Key Methods

```python
def start()                      # Mark simulation start
def stop()                       # Mark simulation end
def record_packet_sent(size)     # Called after each packet transmission
def record_rtt_sample(rtt)       # Called with RTT from aioquic
def calculate_metrics()          # Returns MetricsResult with all 6 metrics
def get_current_metrics()        # Returns dict for epoch sampling
def reset_for_new_epoch()        # Soft reset for new epoch measurement
```

---

## Epoch-Based Metrics

**File:** `epoch.py`

### What is an Epoch?

An **epoch** is a stable measurement period with fixed parameters. Epochs are used to:
1. Measure performance under specific parameter settings
2. Allow settling time after parameter changes
3. Provide clean before/after comparisons

### Epoch Lifecycle

```
Parameter Change
      │
      ▼
┌─────────────┐
│  Settling   │  ← No metrics collected (default: 2 seconds)
│   Period    │    CUBIC needs time to adjust cwnd
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Active    │  ← Metrics collected every 100ms
│   Epoch     │    Samples stored in raw_samples[]
└──────┬──────┘
       │
       ▼ (next param change or simulation end)
┌─────────────┐
│  Finalize   │  ← Calculate aggregated metrics
│   Epoch     │    Add to epoch history
└─────────────┘
```

### EpochManager Class

**Location:** `epoch.py:189-348`

```python
class EpochManager:
    def start()                    # Start first epoch
    def on_parameter_change(params) # End current epoch, start settling
    def collect_sample()           # Collect metric sample (if not settling)
    def finalize()                 # End simulation, finalize current epoch
    def get_history()              # Return ConnectionEpochHistory
```

### Epoch Data Structure

```python
@dataclass
class Epoch:
    epoch_id: int              # 0, 1, 2, ...
    connection_id: int         # 1, 2, or 3
    application_type: str      # "video_streaming", etc.
    start_time: float          # When active measurement began
    end_time: float            # When epoch ended
    settling_start: float      # When param change occurred
    settling_duration: float   # How long we waited
    parameters: ParameterSnapshot  # Parameters for this epoch
    metrics: EpochMetrics      # Aggregated metrics (calculated at end)
    raw_samples: List[Dict]    # Individual 100ms samples
```

### EpochMetrics

Aggregated metrics calculated from raw samples:

| Field | Calculation |
|-------|-------------|
| `throughput_bps` | Mean of sample throughputs |
| `avg_rtt_seconds` | Mean of sample RTTs |
| `min_rtt_seconds` | Minimum RTT observed |
| `max_rtt_seconds` | Maximum RTT observed |
| `jitter_seconds` | Mean of sample jitters |
| `packet_loss_rate` | From last sample |
| `bytes_sent` | Last sample - first sample |

---

## Export Formats

### JSON Exports (via result.py)

| File | Contents |
|------|----------|
| `result_TIMESTAMP.json` | Final summary with fairness index |
| `metrics_TIMESTAMP.json` | Time-series metrics history |
| `epochs_TIMESTAMP.json` | Epoch-based metrics per connection |

### CSV Exports (via exporter.py)

| Method | Output |
|--------|--------|
| `export_metrics_to_csv()` | Time-series for one connection |
| `export_epochs_to_csv()` | Flattened epoch data |
| `export_comparison_csv()` | All connections side-by-side |
| `export_summary_csv()` | Single row for batch analysis |

---

## Configuration

### EpochConfig

```python
@dataclass
class EpochConfig:
    settling_time: float = 2.0      # Seconds to wait after param change
    min_epoch_duration: float = 2.0  # Minimum measurement time
    sample_interval: float = 0.1     # How often to collect (100ms)
```

### Adjusting Settling Time

For network simulation scenarios with higher latency:

```bash
# Local loopback (2-5ms RTT): default 2s is fine
uv run python -m main run --settling-time 2

# Congested network (50-100ms RTT): use longer settling
uv run python -m main run --settling-time 8
```

---

## Code References

| Component | File:Line |
|-----------|-----------|
| MetricsResult dataclass | `calculator.py:14-33` |
| Throughput calculation | `calculator.py:49-66` |
| Jitter calculation | `calculator.py:68-103` |
| Packet loss calculation | `calculator.py:105-127` |
| RTT sampling from aioquic | `worker_process.py:330-335` |
| Epoch finalization | `epoch.py:316-343` |
| Metrics sent via IPC | `worker_process.py:136-157` |
| CSV export | `exporter.py:21-59` |

---

## Example: Reading Metrics in Code

```python
from metrics import MetricsCollector, MetricsCalculator

# During simulation
collector = MetricsCollector()
collector.connection = quic_connection
collector.start()

# After each packet
collector.record_packet_sent(packet_size)

# Sample RTT from aioquic
rtt = protocol._quic._loss._rtt_smoothed
collector.record_rtt_sample(rtt)

# Get current metrics
result = collector.calculate_metrics()
print(f"Throughput: {result.throughput / 1e6:.2f} Mbps")
print(f"RTT: {result.rtt * 1000:.1f} ms")
print(f"Jitter: {result.jitter * 1000:.2f} ms")
print(f"Loss: {result.packet_loss_rate * 100:.1f}%")
```
