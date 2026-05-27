# Docker Metrics and Parameters

This document describes all metrics and parameters available from the Docker environment for the QUIC 3-connection simulation.

---

## 1. Per-Connection Metrics (Measured)

These metrics are measured by each worker process and sent via the metrics queue every ~100ms.

### Primary Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `throughput` | float | bytes/sec | Offered throughput (application send rate) |
| `throughput_acked` | float | bytes/sec | ACK-verified delivery rate (cumulative average) |
| `throughput_acked_delta` | float | bytes/sec | Per-epoch delta throughput (responsive to changes) |
| `rtt` | float | seconds | Round-trip time (smoothed from aioquic) |
| `latency` | float | seconds | One-way delay estimate (RTT / 2) |
| `jitter` | float | seconds | RTT variance (RTTVAR from aioquic) |
| `packet_loss_rate` | float | 0.0-1.0 | Packet loss ratio |

### Byte Counters

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `bytes_sent` | int | bytes | Total bytes sent by application |
| `bytes_acked` | int | bytes | Total bytes acknowledged by receiver |

### Congestion Control Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `avg_cwnd` | float | bytes | Average congestion window size |
| `avg_bytes_in_flight` | float | bytes | Average unacknowledged bytes in transit |

### Connection Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `connection_establishment_time` | float | seconds | Time for QUIC handshake |
| `packets_sent` | int | count | Total packets sent |
| `packets_lost` | int | count | Total packets detected as lost |

---

## 2. Per-Connection Parameters (Tunable)

These parameters can be adjusted dynamically during simulation via Q-learning or manual control.

### Dynamic Parameters

| Parameter | Type | Range | Step | Description |
|-----------|------|-------|------|-------------|
| `loss_reduction_factor` | float | 0.3 - 0.7 | 0.1 | Multiplicative decrease after loss detection |
| `cubic_c` | float | 0.2 - 0.5 | 0.1 | CUBIC algorithm aggressiveness constant |
| `minimum_window` | int | 2 - 6 | 1 | Minimum congestion window (packets) |
| `packet_threshold` | int | 2 - 4 | 1 | Duplicate ACKs before fast retransmit |

### Static Parameters (Set at Start)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `time_threshold` | float | 1.125 | Time-based loss detection multiplier |
| `cubic_max_idle_time` | float | 2.0 | Max idle time before cwnd reset (seconds) |
| `initial_cw` | int | 14720 | Initial congestion window (bytes) |
| `max_ack_delay` | float | 0.025 | Maximum ACK delay (seconds) |
| `max_data` | int | 1048576 | Connection-level flow control (bytes) |
| `max_stream_data` | int | 1048576 | Stream-level flow control (bytes) |

### Initial Parameter Values by Connection

| Parameter | Video (Conn 1) | File (Conn 2) | Conference (Conn 3) |
|-----------|----------------|---------------|---------------------|
| `loss_reduction_factor` | 0.6 | 0.7 | 0.5 |
| `cubic_c` | 0.4 | 0.5 | 0.3 |
| `minimum_window` | 4 | 2 | 6 |
| `packet_threshold` | 2 | 2 | 2 |

---

## 3. Network Scenario Configuration

Set via the `SCENARIO` environment variable in Docker.

### Available Scenarios

| Scenario | Bandwidth | RTT | Loss | Queue | Description |
|----------|-----------|-----|------|-------|-------------|
| `stable_high` | 100 Mbps | 10ms | 0.1% | FIFO (200) | Ideal conditions |
| `congested_low` | 5 Mbps | 30ms | 2% | RED (50) | Crowded network |
| `varying` | 20±8 Mbps | 20ms | 1% | CoDel (100) | Time-varying bandwidth |
| `lossy` | 10 Mbps | 40ms | 5% | FIFO (75) | High packet loss (Gilbert-Elliott) |
| `asymmetric` | 50/10 Mbps | 25ms | 0.5% | FIFO (150) | Asymmetric up/down |
| `per_ideal` | 50 Mbps | 20ms | 0% | FIFO (100) | Zero loss baseline |
| `per_1` | 50 Mbps | 20ms | 1% | FIFO (100) | 1% packet error rate |
| `per_5` | 50 Mbps | 20ms | 5% | FIFO (100) | 5% packet error rate |
| `per_10` | 50 Mbps | 20ms | 10% | FIFO (100) | 10% packet error rate |
| `per_20` | 50 Mbps | 20ms | 20% | FIFO (100) | 20% packet error rate |

### Scenario Config Fields (BottleneckConfig)

#### Primary Parameters (Displayed on UI)

| Config Field | Type | Unit | Description | UI Display |
|--------------|------|------|-------------|------------|
| `capacity_bps` | int | bits/sec | Link bandwidth capacity | "100 Mbps" |
| `propagation_delay` | float | seconds | One-way propagation delay (RTT = 2×) | "10 ms RTT" |
| `loss_rate` | float | 0.0-1.0 | Configured packet loss rate | "0.1%" |
| `queue_size_packets` | int | packets | Buffer/queue size | "100 packets" |
| `queue_discipline` | enum | - | Queue algorithm: FIFO, RED, CoDel, PIE | "FIFO" |
| `time_varying` | bool | - | Whether bandwidth varies over time | "Yes" / "No" |

#### Secondary Parameters (Conditional)

| Config Field | Type | Unit | Description | When Shown |
|--------------|------|------|-------------|------------|
| `variation_period` | float | seconds | Period of bandwidth variation cycle | Only if `time_varying=True` |
| `variation_amplitude` | float | 0.0-1.0 | Amplitude of variation (±%) | Only if `time_varying=True` |
| `uplink_capacity_bps` | int | bits/sec | Uplink bandwidth (asymmetric) | Only for asymmetric scenario |
| `downlink_capacity_bps` | int | bits/sec | Downlink bandwidth (asymmetric) | Only for asymmetric scenario |
| `loss_model` | enum | - | RANDOM or GILBERT_ELLIOTT | Advanced view |

#### Queue Discipline Parameters

| Config Field | Type | Default | Description |
|--------------|------|---------|-------------|
| `red_min_threshold` | int | 30 | RED: Min queue threshold (packets) |
| `red_max_threshold` | int | 90 | RED: Max queue threshold (packets) |
| `red_max_probability` | float | 0.1 | RED: Max drop probability |
| `codel_target_delay` | float | 0.005 | CoDel: Target delay (5ms) |
| `codel_interval` | float | 0.100 | CoDel: Interval (100ms) |

#### Gilbert-Elliott Loss Model Parameters

| Config Field | Type | Default | Description |
|--------------|------|---------|-------------|
| `ge_good_to_bad` | float | 0.1 | Transition probability: good → bad |
| `ge_bad_to_good` | float | 0.9 | Transition probability: bad → good |
| `ge_loss_in_bad` | float | 0.5 | Loss rate when in bad state |

### Scenario Config Source

The `BottleneckConfig` class is defined in `wireless_bottleneck/config.py`:

```python
@dataclass
class BottleneckConfig:
    capacity_bps: int = 10_000_000        # 10 Mbps default
    propagation_delay: float = 0.020       # 20ms one-way
    loss_rate: float = 0.01                # 1% default
    loss_model: LossModel = LossModel.RANDOM
    queue_size_packets: int = 100
    queue_discipline: QueueDiscipline = QueueDiscipline.FIFO
    time_varying: bool = False
    variation_period: float = 1.0          # seconds
    variation_amplitude: float = 0.3       # ±30%
```

---

## 4. Metrics Used in Q-Learning State

### Currently Used

| Metric | State Component | Source |
|--------|-----------------|--------|
| `latency` | `latency_bin` (0-3) | Connection 1 (Video) |
| `throughput_acked_delta` | `throughput_bin` (0-3) | Connection 2 (File) |
| `jitter` | `jitter_bin` (0-3) | Connection 3 (Conference) |
| `packet_loss_rate` | `loss_bin` (0-3) | Average of all 3 connections |
| Derived | `latency_trend` (0-2) | Change in latency |
| Derived | `throughput_trend` (0-2) | Change in throughput |
| Derived | `jitter_trend` (0-2) | Change in jitter |

### State Bin Thresholds

#### Latency Bins (from Connection 1)
| Bin | Range | Meaning |
|-----|-------|---------|
| 0 | < 10ms | Excellent |
| 1 | 10-25ms | Good |
| 2 | 25-50ms | Fair |
| 3 | > 50ms | Poor |

#### Throughput Bins (from Connection 2)
| Bin | Range | Meaning |
|-----|-------|---------|
| 0 | < 1 MB/s | Poor |
| 1 | 1-2 MB/s | Fair |
| 2 | 2-3 MB/s | Good |
| 3 | > 3 MB/s | Excellent |

#### Jitter Bins (from Connection 3)
| Bin | Range | Meaning |
|-----|-------|---------|
| 0 | < 5ms | Excellent |
| 1 | 5-15ms | Good |
| 2 | 15-30ms | Fair |
| 3 | > 30ms | Poor |

#### Loss Bins (average of all connections)
| Bin | Range | Meaning |
|-----|-------|---------|
| 0 | < 1% | Excellent |
| 1 | 1-5% | Good |
| 2 | 5-10% | Fair |
| 3 | > 10% | Poor |

#### Trend Values
| Value | Meaning |
|-------|---------|
| 0 | Worsening (>5% change in bad direction) |
| 1 | Stable (within ±5%) |
| 2 | Improving (>5% change in good direction) |

---

## 5. Available but Unused Metrics

These metrics are collected but not currently used in the Q-learning state.

### Measured Metrics

| Metric | Potential Use |
|--------|---------------|
| `rtt` | Could add `rtt_bin` for network condition context |
| `throughput` (offered) | Compare with acked to detect bottleneck |
| `avg_cwnd` | Could indicate congestion level |
| `avg_bytes_in_flight` | Could indicate congestion/buffering |
| `connection_establishment_time` | Initial connection quality indicator |

### Scenario Config (Network Conditions)

| Config | Potential Use |
|--------|---------------|
| `capacity_bps` | Add `bandwidth_bin` for capacity awareness |
| `propagation_delay` | Add `base_rtt_bin` for delay context |
| `loss_rate` | Compare configured vs measured loss |

### Parameters

| Parameter | Potential Use |
|-----------|---------------|
| Current parameter values | Add to state for action context |
| Parameter history | Track recent changes |

---

## 6. Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         DOCKER CONTAINER                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Environment Variables:                                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ SCENARIO=stable_high                                     │   │
│  │ DURATION=120                                             │   │
│  │ SERVER_HOST=quic-server                                  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Network Bottleneck (tc/netem)               │   │
│  │  - Rate limiting: capacity_bps                          │   │
│  │  - Delay: propagation_delay                             │   │
│  │  - Loss: loss_rate                                      │   │
│  │  - Queue: queue_size_packets                            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   Worker Processes                       │   │
│  │                                                          │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐     │   │
│  │  │  Worker 1    │ │  Worker 2    │ │  Worker 3    │     │   │
│  │  │  (Video)     │ │  (File)      │ │  (Conference)│     │   │
│  │  │              │ │              │ │              │     │   │
│  │  │ Measures:    │ │ Measures:    │ │ Measures:    │     │   │
│  │  │ - latency    │ │ - throughput │ │ - jitter     │     │   │
│  │  │ - rtt        │ │ - rtt        │ │ - rtt        │     │   │
│  │  │ - loss_rate  │ │ - loss_rate  │ │ - loss_rate  │     │   │
│  │  │ - cwnd       │ │ - cwnd       │ │ - cwnd       │     │   │
│  │  │              │ │              │ │              │     │   │
│  │  │ Params:      │ │ Params:      │ │ Params:      │     │   │
│  │  │ - lrf=0.6    │ │ - lrf=0.7    │ │ - lrf=0.5    │     │   │
│  │  │ - cubic=0.4  │ │ - cubic=0.5  │ │ - cubic=0.3  │     │   │
│  │  │ - min_win=4  │ │ - min_win=2  │ │ - min_win=6  │     │   │
│  │  │ - pkt_th=2   │ │ - pkt_th=2   │ │ - pkt_th=2   │     │   │
│  │  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘     │   │
│  │         │                │                │              │   │
│  │         └────────────────┼────────────────┘              │   │
│  │                          │                               │   │
│  │                          ▼                               │   │
│  │              ┌───────────────────────┐                   │   │
│  │              │    Metrics Queue      │                   │   │
│  │              │  (multiprocessing)    │                   │   │
│  │              └───────────┬───────────┘                   │   │
│  └──────────────────────────┼───────────────────────────────┘   │
│                             │                                   │
│                             ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    ML Controller                         │   │
│  │                                                          │   │
│  │  Receives from queue:                                    │   │
│  │  metrics = {                                             │   │
│  │    1: {latency, throughput, jitter, loss_rate,          │   │
│  │        rtt, bytes_sent, bytes_acked, current_params},   │   │
│  │    2: {...},                                             │   │
│  │    3: {...}                                              │   │
│  │  }                                                       │   │
│  │                                                          │   │
│  │  Passes to Q-learning agent                              │   │
│  │  Receives parameter update decisions                     │   │
│  │  Sends updates back to workers                           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                             │                                   │
│                             ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                  Q-Learning Agent                        │   │
│  │                                                          │   │
│  │  Builds state:                                           │   │
│  │  - latency_bin from metrics[1]["latency"]               │   │
│  │  - throughput_bin from metrics[2]["throughput_acked"]   │   │
│  │  - jitter_bin from metrics[3]["jitter"]                 │   │
│  │  - trends from previous values                          │   │
│  │  - loss_bin from avg(metrics[*]["packet_loss_rate"])    │   │
│  │                                                          │   │
│  │  Selects action (0-24)                                   │   │
│  │  Updates Q-table                                         │   │
│  │  Returns parameter changes                               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. Output Files Generated

After simulation, these files are created in the output directory:

| File | Contents |
|------|----------|
| `metrics_timeseries.csv` | Time-series of all metrics + total throughput |
| `metrics.json` | Final metrics per connection + totals |
| `qlearning_actions.json` | Parameter change history with before/after metrics |
| `qlearning_actions.csv` | Same as above in CSV format |
| `q_table.json` | Learned Q-values for all visited states |
| `rewards.csv` | Reward at each Q-learning step |
| `config.json` | Run configuration and hyperparameters |
| `README.md` | Human-readable summary |

---

## 8. Accessing Metrics in Code

### From Worker Process

```python
# In worker_process.py - metrics sent to queue
self._send_metrics()

# Metrics payload structure
payload = {
    "throughput": metrics.throughput,
    "throughput_acked": metrics.throughput_acked,
    "throughput_acked_delta": throughput_acked_delta,
    "rtt": metrics.rtt,
    "latency": metrics.latency,
    "jitter": metrics.jitter,
    "packet_loss_rate": metrics.packet_loss_rate,
    "bytes_sent": self._metrics_collector.bytes_sent,
    "bytes_acked": metrics.bytes_acked,
    "current_params": {
        "loss_reduction_factor": self.config.loss_reduction_factor,
        "cubic_c": self.config.cubic_c,
        "minimum_window": self.config.minimum_window,
        "packet_threshold": self.config.packet_threshold,
    },
}
```

### In Q-Learning Agent

```python
# In q_learning_agent.py - building state from metrics
def _build_state(self, metrics: Dict[int, dict]) -> Tuple:
    lat = metrics[CONN_VIDEO].get("latency", 0.0)
    tp = metrics[CONN_FILE].get("throughput_acked_delta", 0.0)
    jit = metrics[CONN_CONF].get("jitter", 0.0)

    loss_rates = [metrics[c].get("packet_loss_rate", 0.0) for c in CONNECTIONS]
    avg_loss = sum(loss_rates) / len(loss_rates)

    # ... bin calculations ...

    return (lat_bin, tp_bin, jit_bin, lat_trend, tp_trend, jit_trend, loss_bin)
```

### Accessing Scenario Config

```python
# In process_orchestrator.py
scenario = get_scenario(scenario_name)
config = scenario.config

bandwidth = config.capacity_bps        # e.g., 100_000_000 (100 Mbps)
delay = config.propagation_delay       # e.g., 0.005 (5ms)
loss = config.loss_rate                # e.g., 0.001 (0.1%)
```
