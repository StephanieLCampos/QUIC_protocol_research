# QUIC 3-Connection Simulation - Full Report

This report documents the architecture, usage, and integration of the QUIC 3-connection simulation system with wireless bottleneck network emulation and Q-learning parameter optimization.

## Table of Contents

1. [Project Structure](#project-structure)
2. [Running the Simulation](#running-the-simulation)
3. [Output Files Explained](#output-files-explained)
4. [Wireless Bottleneck Integration](#wireless-bottleneck-integration)
5. [Verifying the Network Simulator](#verifying-the-network-simulator)
6. [Q-Learning Integration](#q-learning-integration)
7. [How Bottleneck and Q-Learning Connect](#how-bottleneck-and-q-learning-connect)

---

## Project Structure

### Root Directory

```
QUIC_3conn_implementation/
├── 3_conn_code/          # Main simulation code (runnable)
├── 3_conn/               # Documentation and drafts only
├── wireless_bottleneck/  # Network emulation module
├── docker-compose.yml    # Multi-container setup
├── Dockerfile            # Container image definition
├── setup_veth.sh         # Virtual ethernet setup script
└── WIRELESS_BOTTLENECK_GUIDE.md
```

### 3_conn_code Directory (Main Code)

```
3_conn_code/
├── main.py                 # Entry point
├── test_simple_quic.py     # Tests
├── README.md
├── config/                 # Configuration classes
│   ├── connection_config.py
│   └── multi_connection_config.py
├── simulation/             # Core simulation engine
│   ├── process_orchestrator.py  # Manages 3 worker processes
│   ├── worker_process.py        # Individual connection worker
│   ├── client.py                # QUIC client
│   ├── server.py                # QUIC server
│   ├── ml_controller.py         # ML parameter tuning coordinator
│   ├── token_bucket.py          # Rate limiting
│   ├── buffer_manager.py
│   ├── ipc_messages.py          # Inter-process communication
│   └── result.py
├── synthesizers/           # Traffic generators
│   ├── video_streaming.py       # 30 fps, I-frames (50KB) + P-frames (5KB)
│   ├── file_transfer.py         # Continuous 64KB chunks
│   └── conference_call.py       # 320 bytes every 20ms
├── metrics/                # Metrics collection & export
│   ├── collector.py
│   ├── calculator.py
│   ├── epoch.py
│   └── exporter.py
├── web/                    # Browser dashboard
│   └── server.py
├── ml_callbacks/           # ML agents
│   └── q_learning_agent.py
└── examples/
    └── run_3conn_through_bottleneck.py
```

### wireless_bottleneck Directory

```
wireless_bottleneck/
├── __init__.py
├── bottleneck.py    # WirelessBottleneck class using Linux tc
├── config.py        # BottleneckConfig dataclass
├── scenarios.py     # Predefined network scenarios
├── monitor.py       # Real-time metrics monitoring
├── validate.py      # Validation tests
├── cli.py           # Command-line interface
└── README.md
```

### Code Dependencies Outside 3_conn_code

| File | Usage |
|------|-------|
| `Dockerfile` (root) | Copies `3_conn_code/` into container, runs `python -m main` |
| `docker-compose.yml` (root) | Mounts `./results:/app/3_conn_code/output` for result export |
| `wireless_bottleneck/` | Network emulation module imported by `3_conn_code` |

### 3_conn Directory (Documentation Only)

Contains planning documents and drafts - no executable code:
- `draft_*.md` - Development notes
- `docker_report.md` - Docker setup documentation
- `multi_process_implementation_plan.md` - Architecture planning
- `Param_info.md`, `new_params.md` - Parameter documentation

---

## Running the Simulation

### Installation

```bash
cd 3_conn_code

# Using uv (recommended)
uv sync

# Or with pip
pip install -e .
```

### Quick Start Commands

```bash
# Basic simulation (30 seconds)
uv run python -m main run

# With browser UI dashboard at http://localhost:8000
uv run python -m main run --ui

# With ML-based parameter optimizer
uv run python -m main run --with-ml

# Custom duration and network scenario
uv run python -m main run --duration 60 --scenario congested_low

# With longer settling time for network simulation
uv run python -m main run --ui --duration 120 --settling-time 5 --scenario congested_low
```

### Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--duration N` | Simulation duration in seconds | 30 |
| `--metrics-interval N` | Metrics collection interval | 0.1 |
| `--output-dir PATH` | Output directory for results | output |
| `--scenario NAME` | Network scenario | congested_low |
| `--with-ml` | Enable Q-learning parameter tuning | disabled |
| `--ml-callback MODULE:FUNC` | Custom ML callback | q_learning_agent |
| `--ui` | Enable browser dashboard | disabled |
| `--port N` | Port for browser UI | 8000 |
| `--settling-time N` | Wait time after parameter changes | 2.0 |
| `--bandwidth-cap N` | Shared bandwidth limit in Mbps | none |
| `--loss-rate N` | Simulated packet loss (0.0-1.0) | 0.0 |
| `--delay-ms N` | Simulated one-way delay in ms | 0.0 |

### Application Types

| Connection | Type | Traffic Pattern |
|------------|------|-----------------|
| 1 | Video Streaming | 30 fps, I-frames (50KB) + P-frames (5KB) |
| 2 | File Transfer | Continuous 64KB chunks |
| 3 | Conference Call | 320 bytes every 20ms |

### Output Files

Results are saved to the output directory:

- `result_TIMESTAMP.json` - Final summary with fairness index and per-connection metrics
- `metrics_TIMESTAMP.json` - Time-series metrics history
- `epochs_TIMESTAMP.json` - Epoch-based metrics for ML analysis
- `bottleneck_summary_TIMESTAMP.json` - Network bottleneck verification data

---

## Output Files Explained

This section provides detailed explanations of each output file generated by the simulation.

### 1. `results_*.json` - Complete Simulation Results

The main output file containing all simulation data.

```json
{
  "simulation_id": "20260330_154523",
  "duration_seconds": 30.0,
  "network_scenario": "congested_low",
  "fairness_index": 0.85,
  "total_offered_throughput_Mbps": 8.5,

  "bottleneck_summary": { ... },
  "robust_metrics_summary": { ... },

  "connections": {
    "1": { /* full data for video streaming */ },
    "2": { /* full data for file transfer */ },
    "3": { /* full data for conference call */ }
  }
}
```

**Use this for**: Complete analysis, all data in one place

---

### 2. `bottleneck_summary_*.json` - Network Constraint Verification

Quick check to verify the bottleneck is working.

```json
{
  "bottleneck_summary": {
    "bottleneck_applied": true,
    "bottleneck_limiting_traffic": true,
    "configured_capacity_mbps": 5.0,
    "observed_link_throughput_mbps": 4.92,
    "total_offered_throughput_mbps": 8.5,
    "cap_utilization_percent": 98.4,
    "offered_to_observed_ratio": 1.73
  }
}
```

| Field | Meaning |
|-------|---------|
| `bottleneck_applied` | Was tc configured? |
| `bottleneck_limiting_traffic` | Is offered > observed? (apps want more than allowed) |
| `configured_capacity_mbps` | What we set (e.g., 5 Mbps) |
| `observed_link_throughput_mbps` | What actually went through |
| `total_offered_throughput_mbps` | What apps tried to send |
| `cap_utilization_percent` | How close to the limit (98% = good) |
| `offered_to_observed_ratio` | >1 means bottleneck is limiting |

**Use this for**: Verifying the network simulation is working correctly

---

### 3. `epoch_history_*.json` - Parameter Change Analysis

Tracks metrics for each "epoch" (stable period between parameter changes).

```json
{
  "connections": {
    "1": {
      "application_type": "video_streaming",
      "epoch_count": 3,
      "epochs": [
        {
          "epoch_id": 0,
          "timing": {
            "start_time": 1711814723.5,
            "duration_seconds": 10.2,
            "settling_duration_seconds": 2.0
          },
          "parameters": {
            "dynamic": {
              "loss_reduction_factor": 0.6,
              "cubic_c": 0.4,
              "minimum_window": 4,
              "packet_threshold": 3
            }
          },
          "metrics": {
            "throughput_mbps": 1.85,
            "avg_rtt_ms": 28.5,
            "jitter_ms": 8.2,
            "packet_loss_percent": 1.8
          }
        },
        { /* epoch 1 - after first param change */ },
        { /* epoch 2 - after second param change */ }
      ]
    }
  }
}
```

| Field | Meaning |
|-------|---------|
| `epoch_id` | Sequence number (0 = initial, 1+ = after param changes) |
| `settling_duration_seconds` | Wait time after param change before measuring |
| `parameters.dynamic` | The QUIC params active during this epoch |
| `metrics` | Performance measured during this stable period |

**Use this for**:
- Seeing how parameter changes affected performance
- ML training data (state -> action -> reward)
- Before/after comparisons

---

### 4. `metrics_history_*.json` - Full Time Series

Raw metrics sampled every 100ms for detailed analysis.

```json
{
  "connections": {
    "1": {
      "application_type": "video_streaming",
      "metrics_history": [
        {
          "timestamp": 0.1,
          "throughput": 125000,
          "rtt": 0.028,
          "latency": 0.028,
          "jitter": 0.005,
          "packet_loss_rate": 0.02,
          "cwnd": 14000,
          "bytes_sent": 12500,
          "packets_sent": 10
        },
        { /* t=0.2s */ },
        { /* t=0.3s */ }
      ]
    }
  }
}
```

| Field | Unit | Description |
|-------|------|-------------|
| `timestamp` | seconds | Time since simulation start |
| `throughput` | bytes/sec | Current transfer rate |
| `rtt` | seconds | Round-trip time |
| `jitter` | seconds | RTT variance |
| `packet_loss_rate` | 0.0-1.0 | Fraction of packets lost |
| `cwnd` | bytes | Congestion window size |
| `bytes_sent` | bytes | Cumulative bytes sent |

**Use this for**:
- Plotting graphs over time
- Detailed debugging
- Analyzing transient behavior

---

### 5. `median_metrics_summary_*.json` - Statistical Summary

Trimmed medians (removes warmup/cooldown noise) for quick comparison.

```json
{
  "method": "trimmed_median",
  "warmup_ratio": 0.2,
  "cooldown_ratio": 0.1,
  "connections": {
    "1": {
      "application_type": "video_streaming",
      "offered_throughput_median_mbps": 1.82,
      "rtt_median_ms": 28.5,
      "latency_median_ms": 28.5,
      "jitter_median_ms": 7.8,
      "packet_loss_rate_median": 0.018,
      "samples_used": 210,
      "samples_total": 300
    },
    "2": { /* file_transfer */ },
    "3": { /* conference_call */ }
  }
}
```

| Field | Meaning |
|-------|---------|
| `warmup_ratio: 0.2` | Drops first 20% of samples (startup noise) |
| `cooldown_ratio: 0.1` | Drops last 10% of samples (shutdown noise) |
| `samples_used` | How many samples after trimming |
| `*_median_*` | Middle value (robust to outliers) |

**Use this for**:
- Comparing runs quickly
- Reporting stable-state performance
- Avoiding misleading averages from startup/shutdown

---

### Output Files Summary Table

| File | Purpose | When to Use |
|------|---------|-------------|
| `results_*.json` | Everything | Full analysis |
| `bottleneck_summary_*.json` | Network verification | Check if bottleneck works |
| `epoch_history_*.json` | Parameter change effects | ML analysis, before/after |
| `metrics_history_*.json` | Raw time series | Plotting, debugging |
| `median_metrics_summary_*.json` | Quick stats | Comparing runs |

---

## Wireless Bottleneck Integration

### Why Docker is Required

The **multi-container Docker setup is required** for actual bandwidth/loss enforcement. Single-container and macOS setups bypass the tc rules due to Linux kernel optimizations.

| Method | Bandwidth | Loss | Why |
|--------|-----------|------|-----|
| Multi-container Docker | Yes | Yes | Traffic crosses eth0 where tc rules apply |
| Single-container Docker | No | No | Kernel bypasses tc on loopback |
| macOS native | No | No | No tc support |

### Running with Docker (Recommended)

```bash
cd /Users/steph/dev/research_folder/GIT_QUIC_3conn/QUIC_3conn_implementation

# Build the Docker image
docker build -t quic-wireless -f Dockerfile .

# Run multi-container setup
docker-compose up

# Results saved to ./results/ directory

# Clean up
docker-compose down
```

### Multi-Container Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│              Docker Bridge Network 192.168.200.0/24             │
├─────────────────────┬─────────────────────┬─────────────────────┤
│  Server Container   │  Client Container   │  Prober Container   │
│  192.168.200.10     │  192.168.200.20     │  192.168.200.30     │
│                     │                     │                     │
│  eth0 ─── tc qdisc  │  eth0               │  eth0               │
│  (HTB + netem)      │                     │  (ping probe)       │
│                     │                     │                     │
│  QUIC Server        │  3 QUIC Clients     │  RTT Measurement    │
└─────────────────────┴─────────────────────┴─────────────────────┘
         ↑ Traffic here IS constrained (crosses network interface)
```

### Available Scenarios

```bash
# Use a different scenario
SCENARIO=lossy docker-compose up
```

| Scenario | Bandwidth | RTT | Loss | Description |
|----------|-----------|-----|------|-------------|
| `congested_low` | 5 Mbps | 30ms | 2% | Typical congested WiFi |
| `stable_high` | 100 Mbps | 10ms | 0.1% | Fast stable link |
| `varying` | 5-20 Mbps | 20ms | 1% | Variable capacity |
| `lossy` | 10 Mbps | 25ms | 5% | High loss environment |
| `asymmetric` | 50/10 Mbps | 15ms | 0.5% | Asymmetric link |

### Local Testing (No Real Bottleneck)

For testing without Docker (app-level limiting only):

```bash
cd 3_conn_code
uv run python -m main run --bandwidth-cap 30 --delay-ms 25 --loss-rate 0.02
```

This simulates constraints at the application level but doesn't use real Linux traffic control.

---

## Verifying the Network Simulator

### 1. Check Server Logs During Startup

When `docker-compose up` runs, look for these messages in the server container:

```
quic-server | [Orchestrator] Multi-container Docker mode: applying bottleneck on eth0
quic-server | Setting up wireless bottleneck on eth0...
quic-server | Successfully configured bottleneck: 5000 kbit/s, 15ms delay, 2.0% loss
quic-server | [Orchestrator] Wireless bottleneck activated for scenario: congested_low
```

If you see `"Local mode: applying bottleneck on lo"` instead, the bottleneck won't limit bandwidth.

### 2. Check Output Files

After the run, check `./results/bottleneck_summary_*.json`:

```json
{
  "bottleneck_applied": true,
  "bottleneck_limiting_traffic": true,
  "offered_throughput_mbps": 8.5,
  "observed_link_throughput_mbps": 4.9
}
```

**Key indicators:**

| Field | Working | Not Working |
|-------|---------|-------------|
| `bottleneck_applied` | `true` | `false` |
| `bottleneck_limiting_traffic` | `true` | `false` |
| `observed_link_throughput_mbps` | ~5 (for congested_low) | 0 or very high |
| `offered_throughput_mbps` | Higher than observed | Equal to observed |

### 3. Check Console Output

At the end of the run:

```
Total Offered Throughput (app): 8.50 Mbps    <- What apps tried to send
Observed Link Throughput (tc): 4.92 Mbps     <- What actually went through
Bottleneck limiting traffic: True             <- Bottleneck is working!
```

If bottleneck is working:
- **Offered > Observed** (apps want more than link allows)
- **Observed ~ scenario limit** (e.g., ~5 Mbps for `congested_low`)

### 4. Run Validation Script

```bash
# Enter a running container
docker exec -it quic-server bash

# Run validation
python -m wireless_bottleneck.cli validate
```

Expected output:

```
WIRELESS BOTTLENECK VALIDATION
======================================================================
Test 1: Basic bottleneck setup
- Bottleneck configured successfully
- Bottleneck is active
- Retrieved tc statistics
- Bottleneck torn down successfully

Test 2: Context manager usage
- Bottleneck context manager entered
- Bottleneck is active within context
...
All tests passed!
```

### 5. Check tc Rules Directly

```bash
# Inside the server container
docker exec -it quic-server bash

# View active tc rules
tc qdisc show dev eth0
tc class show dev eth0
```

Expected output when working:

```
qdisc htb 1: root ... default 11
qdisc netem 10: parent 1:11 limit 1000 delay 15ms loss 2%
```

If you see `qdisc noqueue` or `qdisc fq_codel`, the bottleneck isn't applied.

### 6. Compare Scenarios

Run with different scenarios and verify throughput changes:

```bash
# Low bandwidth scenario
SCENARIO=congested_low docker-compose up   # Expect ~5 Mbps

# High bandwidth scenario
SCENARIO=stable_high docker-compose up     # Expect ~100 Mbps
```

### Quick Diagnostic Checklist

| Check | Pass | Fail |
|-------|------|------|
| Server logs show "eth0" | Yes | Shows "lo" |
| `bottleneck_applied: true` | Yes | `false` |
| Observed throughput ~ scenario limit | Yes | Much higher |
| `tc qdisc show` shows htb + netem | Yes | Shows noqueue |
| Offered > Observed throughput | Yes | Equal |

---

## Q-Learning Integration

### Overview

The Q-learning agent (`ml_callbacks/q_learning_agent.py`) implements tabular Q-learning to dynamically tune QUIC CUBIC congestion control parameters across three connections, each with different performance goals:

- **Connection 1 (Video Streaming)**: Minimize latency
- **Connection 2 (File Transfer)**: Maximize throughput
- **Connection 3 (Conference Call)**: Minimize jitter

### Running with Q-Learning

```bash
# Default Q-learning agent
uv run python -m main run --with-ml --duration 120

# Explicit module path
uv run python -m main run --ml-callback ml_callbacks.q_learning_agent:q_learning_callback

# With network scenario (recommended)
uv run python -m main run --with-ml --scenario congested_low --duration 120

# In Docker with bottleneck
SCENARIO=congested_low docker-compose up
# Then modify docker-compose.yml to add --with-ml to the clients command
```

### State Space (1,728 combinations)

The agent discretizes metrics into bins:

**Latency bins** (0=best, 3=worst):
- 0: <10ms
- 1: 10-25ms
- 2: 25-50ms
- 3: >50ms

**Throughput bins** (0=worst, 3=best):
- 0: <1 MB/s
- 1: 1-2 MB/s
- 2: 2-3 MB/s
- 3: >3 MB/s

**Jitter bins** (0=best, 3=worst):
- 0: <5ms
- 1: 5-15ms
- 2: 15-30ms
- 3: >30ms

**Trend indicators** (3 levels each):
- 0: Worsening
- 1: Stable
- 2: Improving

**Total state space**: 4^3 * 3^3 = 1,728 states

### Action Space (25 actions)

- **Actions 0-23**: Change one parameter on one connection by one step
  - 4 parameters x 3 connections x 2 directions (increase/decrease) = 24
- **Action 24**: No-op (do nothing)

### Tunable Parameters

| Parameter | Step | Range | Description |
|-----------|------|-------|-------------|
| `loss_reduction_factor` | 0.1 | 0.3-0.7 | cwnd reduction on packet loss (beta) |
| `cubic_c` | 0.1 | 0.2-0.4 | CUBIC growth aggressiveness |
| `minimum_window` | 1 | 2-4 | Minimum cwnd floor (packets) |
| `packet_threshold` | 1 | 3-4 | Packets before declaring loss |

### Reward Function

```
R = mean(U_stream, U_file, U_conf)
    - lambda * std(utilities)     # Fairness penalty (lambda = 0.10)
    - mu * changed                # Stability penalty (mu = 0.05)
```

**Utility functions** (normalized 0-1, where 1 is best):

- `U_stream = (latency_worst - latency) / (latency_worst - latency_best)`
- `U_file = throughput / throughput_max`
- `U_conf = (jitter_worst - jitter) / jitter_worst`

### Q-Learning Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| Alpha (learning rate) | 0.10 | How fast to update Q-values |
| Gamma (discount) | 0.90 | Future reward importance |
| Epsilon (exploration) | 0.30 -> 0.05 | Exploration probability (decays) |
| Epsilon decay | 0.995 | Multiplicative decay per step |
| Control interval | 2.0s | Time between decisions |

### Q-Learning Agent Output

During execution, the agent logs its decisions:

```
[QLAgent step=  10] state=(1, 2, 1, 1, 2, 1) action=file.cubic_c up
                    eps=0.285 lat=18.5ms tp=1.85Mbps jit=8.2ms
                    avg_R=+0.542 Q-states=45
```

### Checkpoint Persistence

The Q-table is saved to `output/q_learning_checkpoint.json` every 50 steps, allowing the agent to accumulate experience across multiple runs.

---

## How Bottleneck and Q-Learning Connect

The wireless bottleneck and Q-learning work together in a feedback loop:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Feedback Loop                                 │
│                                                                      │
│  ┌──────────────────┐     constrains      ┌──────────────────────┐  │
│  │ Wireless         │ ─────────────────── │ 3 QUIC Connections   │  │
│  │ Bottleneck       │    bandwidth/RTT    │ (video, file, conf)  │  │
│  │ (tc qdisc)       │       /loss         │                      │  │
│  └──────────────────┘                     └──────────┬───────────┘  │
│                                                      │              │
│                                              metrics │              │
│                                      (throughput, latency, jitter)  │
│                                                      v              │
│  ┌──────────────────┐   param updates    ┌──────────────────────┐  │
│  │ Worker Processes │ <───────────────── │ Q-Learning Agent     │  │
│  │ (aioquic params) │                    │ (ml_callbacks/)      │  │
│  └──────────────────┘                    └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### The Connection Flow

1. **Wireless Bottleneck** creates realistic network constraints:
   - Bandwidth limit (e.g., 5 Mbps for `congested_low`)
   - RTT delay (e.g., 30ms)
   - Packet loss (e.g., 2%)

2. **3 QUIC Connections** compete for the constrained bandwidth

3. **Metrics** are collected every 0.1s from each connection:
   - `latency` (RTT) - for video streaming optimization
   - `throughput` - for file transfer optimization
   - `jitter` - for conference call optimization

4. **Q-Learning Agent** observes these metrics and decides parameter changes every 2s:
   - Tunes `loss_reduction_factor`, `cubic_c`, `minimum_window`, `packet_threshold`
   - Goal: optimize each connection for its purpose while maintaining fairness

### Why the Bottleneck Matters for Q-Learning

Without the bottleneck, Q-learning has **nothing to optimize**:

| Scenario | Throughput | Q-Learning Effectiveness |
|----------|------------|--------------------------|
| No bottleneck | ~40+ Mbps per connection | Useless - all connections get everything |
| With 5 Mbps bottleneck | Connections compete | Useful - agent learns trade-offs |

The bottleneck creates **scarcity** that forces trade-offs, giving the Q-learning agent meaningful decisions to make.

### Running Both Together

```bash
# In Docker (recommended - real tc bottleneck)
docker build -t quic-wireless -f Dockerfile .
SCENARIO=congested_low docker-compose up

# Or locally with app-level bandwidth cap (fallback)
cd 3_conn_code
uv run python -m main run --with-ml --bandwidth-cap 30 --duration 120
```

### MLController Integration

The `MLController` class (`simulation/ml_controller.py`) coordinates the Q-learning agent:

1. Runs a control loop every 0.1s (configurable via `--metrics-interval`)
2. Collects metrics from all 3 worker processes via IPC queue
3. Calls the Q-learning callback with current metrics
4. Sends parameter updates to specific workers via IPC pipes

The Q-learning agent internally throttles to only make decisions every 2s (`CONTROL_INTERVAL`) to give CUBIC congestion control time to respond to parameter changes.

---

## Summary

This system provides a complete framework for:

1. **Simulating 3 concurrent QUIC connections** with different traffic patterns (video, file transfer, conference call)

2. **Emulating realistic network conditions** using Linux tc (traffic control) with configurable bandwidth, delay, and loss

3. **Optimizing QUIC parameters dynamically** using Q-learning that learns from the constrained network environment

The key insight is that the wireless bottleneck creates the constrained environment where the Q-learning agent can learn meaningful trade-offs between different connection types and their optimization goals.
