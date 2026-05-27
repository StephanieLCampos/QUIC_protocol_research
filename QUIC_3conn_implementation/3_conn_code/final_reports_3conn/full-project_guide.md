# Full Project Guide: QUIC 3-Connection Simulation

This guide covers how to run the QUIC 3-connection simulation with wireless bottleneck emulation and Q-learning optimization.

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Running with Docker (Recommended)](#running-with-docker-recommended)
4. [Running Locally (macOS)](#running-locally-macos)
5. [Network Scenarios](#network-scenarios)
6. [Q-Learning Integration](#q-learning-integration)
7. [Throughput Metrics](#throughput-metrics)
8. [Results and Output](#results-and-output)
9. [Browser UI Dashboard](#browser-ui-dashboard)
10. [How to Know If It's Working](#how-to-know-if-its-working)
11. [Troubleshooting](#troubleshooting)

---

## Overview

This project simulates 3 concurrent QUIC connections with different application types:

| Connection | Application Type | Optimization Goal |
|------------|------------------|-------------------|
| 1 | Video Streaming | Minimize latency |
| 2 | File Transfer | Maximize throughput |
| 3 | Conference Call | Minimize jitter |

The simulation uses Linux TC (Traffic Control) to create realistic network bottlenecks, and Q-learning to dynamically optimize QUIC congestion control parameters.

---

## Prerequisites

### For Docker (Recommended)
- Docker Desktop installed
- Docker Compose

### For Local Development
- Python 3.11+
- uv package manager
- macOS or Linux

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
cd 3_conn_code
uv sync
```

---

## Running with Docker (Recommended)

Docker is required for the TC bottleneck to work properly. The bottleneck uses Linux kernel features that don't work on macOS loopback.

### Directory Structure

```
QUIC_3conn_implementation/
├── docker-compose.yml      # Multi-container orchestration
├── Dockerfile              # Container image
├── 3_conn_code/            # Main application code
├── wireless_bottleneck/    # Network emulation module
└── results/                # Output directory (shared volume)
```

### Build the Docker Image

```bash
cd /Users/steph/dev/research_folder/GIT_QUIC_3conn/QUIC_3conn_implementation

# Build the image
docker-compose build
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SCENARIO` | `congested_low` | Network scenario to use |
| `DURATION` | `30` | Simulation duration in seconds |

### Run with Q-Learning + UI (Default)

The current `docker-compose.yml` has `--with-ml` and `--ui` enabled by default.

```bash
# Default scenario (congested_low) with Q-learning and UI
docker-compose up

# Varying scenario with Q-learning and UI
SCENARIO=varying docker-compose up

# Custom duration (120 seconds)
SCENARIO=varying DURATION=120 docker-compose up

# Other scenarios
SCENARIO=lossy DURATION=60 docker-compose up
SCENARIO=stable_high DURATION=90 docker-compose up
```

Then open **http://localhost:8000** in your browser to see real-time metrics.

### Run with Q-Learning (Without UI)

If you don't need the browser UI:

```bash
# Start server and prober first
docker-compose up -d server prober

# Run clients with Q-learning but no UI
docker-compose run --rm clients python -m main clients \
  --server 192.168.200.10 \
  --duration 120 \
  --scenario varying \
  --with-ml \
  --output-dir output

# Clean up when done
docker-compose down
```

### Run Without Q-Learning (Baseline Test)

```bash
# Start server and prober
docker-compose up -d server prober

# Run clients without Q-learning
docker-compose run --rm clients python -m main clients \
  --server 192.168.200.10 \
  --duration 60 \
  --scenario congested_low \
  --output-dir output

# Clean up
docker-compose down
```

### All Docker Command Flags

| Flag | Description |
|------|-------------|
| `--server <IP>` | Server address (192.168.200.10 in Docker) |
| `--duration <seconds>` | How long to run the simulation |
| `--scenario <name>` | Network scenario to use |
| `--with-ml` | Enable Q-learning optimization |
| `--ui` | Enable browser UI dashboard (port 8000) |
| `--output-dir <path>` | Where to save results |

### Stop and Clean Up

```bash
# Stop all containers
docker-compose down

# Remove volumes and images (full cleanup)
docker-compose down -v --rmi all
```

---

## Running Locally (macOS)

**Note:** TC bottleneck does NOT work on macOS loopback. Use `--bandwidth-cap` for application-level throttling instead.

### Basic Run

```bash
cd /Users/steph/dev/research_folder/GIT_QUIC_3conn/QUIC_3conn_implementation/3_conn_code

# Simple run (no bottleneck)
uv run python -m main run --duration 60

# With application-level bandwidth cap (30 Mbps shared)
uv run python -m main run --duration 60 --bandwidth-cap 30

# With simulated packet loss
uv run python -m main run --duration 60 --bandwidth-cap 30 --loss-rate 0.02
```

### Run with Q-Learning

```bash
# Q-learning with bandwidth cap
uv run python -m main run --with-ml --duration 60 --bandwidth-cap 30

# Q-learning with scenario (TC won't work, but parameters are set)
uv run python -m main run --with-ml --scenario congested_low --duration 60 --bandwidth-cap 5
```

### Run with Browser UI

```bash
# UI without Q-learning
uv run python -m main run --ui --duration 60 --bandwidth-cap 30

# UI with Q-learning
uv run python -m main run --ui --with-ml --duration 60 --bandwidth-cap 30
```

Then open: **http://localhost:8000**

---

## Network Scenarios

Available scenarios in `wireless_bottleneck/scenarios.py`:

| Scenario | Bandwidth | RTT | Loss | Description |
|----------|-----------|-----|------|-------------|
| `stable_high` | 100 Mbps | 10ms | 0.1% | High-capacity stable link |
| `congested_low` | 5 Mbps | 30ms | 2% | Congested network (default) |
| `varying` | 20 Mbps ±40% | 20ms | 1% | Fluctuating bandwidth |
| `lossy` | 10 Mbps | 40ms | 5% | High packet loss |
| `asymmetric` | 50↓/10↑ Mbps | 25ms | 0.5% | Asymmetric (like DSL/mobile) |

### PER (Packet Error Rate) Scenarios

| Scenario | Bandwidth | Loss | Description |
|----------|-----------|------|-------------|
| `per_ideal` | 50 Mbps | 0% | Perfect channel |
| `per_1` | 50 Mbps | 1% | Light noise |
| `per_5` | 50 Mbps | 5% | Moderate degradation |
| `per_10` | 50 Mbps | 10% | Heavy degradation |
| `per_20` | 50 Mbps | 20% | Severe degradation |

### How `varying` Works

The `varying` scenario uses sinusoidal bandwidth variation:

```
Capacity = base_capacity * (1 + amplitude * sin(2π * time / period))

With: base=20Mbps, amplitude=0.4, period=2s
Result: Bandwidth oscillates between 12-28 Mbps every 2 seconds
```

---

## Q-Learning Integration

### How It Works

The Q-learning agent:
1. Observes metrics every 100ms
2. Makes decisions every 2 seconds (CONTROL_INTERVAL)
3. Adjusts QUIC CUBIC parameters based on learned Q-values
4. Balances latency (video), throughput (file), and jitter (conference)

### Tunable Parameters

| Parameter | Range | Step | Affects |
|-----------|-------|------|---------|
| `loss_reduction_factor` | 0.3 - 0.7 | 0.1 | How much to reduce cwnd on loss |
| `cubic_c` | 0.2 - 0.4 | 0.1 | CUBIC aggressiveness |
| `minimum_window` | 2 - 4 | 1 | Minimum congestion window |
| `packet_threshold` | 3 - 4 | 1 | Packets before loss detection |

### Q-Learning Hyperparameters

Located in `ml_callbacks/q_learning_agent.py`:

```python
ALPHA = 0.10          # Learning rate
GAMMA = 0.90          # Discount factor
EPSILON_START = 0.30  # Initial exploration
EPSILON_MIN = 0.05    # Minimum exploration
EPSILON_DECAY = 0.995 # Decay per step
CONTROL_INTERVAL = 2.0 # Seconds between decisions
```

---

## Throughput Metrics

Three throughput measurements are available:

| Metric | Source | Description | Use Case |
|--------|--------|-------------|----------|
| `throughput` | Client send rate | Application send rate | Not bottleneck-aware |
| `throughput_acked` | Client ACKs | Cumulative ACK-verified delivery | Stable conditions |
| `throughput_acked_delta` | Client ACKs | Per-epoch (~100ms) delivery rate | Varying conditions |

### Configuring Which Metric Q-Learning Uses

Edit `ml_callbacks/q_learning_agent.py` line ~122:

```python
THROUGHPUT_METRIC = "delta"   # Per-epoch (default) - good for varying
THROUGHPUT_METRIC = "acked"   # Cumulative - good for stable scenarios
THROUGHPUT_METRIC = "offered" # Send rate - not recommended
```

### When to Use Each

| Scenario Type | Recommended Metric |
|---------------|-------------------|
| `congested_low`, `stable_high`, `lossy` | `acked` (cumulative) |
| `varying`, dynamic conditions | `delta` (per-epoch) |

---

## Results and Output

### Output Location

- **Docker:** `./results/` (shared volume)
- **Local:** `./output/` or specified with `--output-dir`

```bash
# List results
ls -la results/

# View latest summary
cat results/median_metrics_summary_*.json | python -m json.tool
```

### Output Files

| File | Description |
|------|-------------|
| `results_*.json` | Complete simulation data |
| `bottleneck_summary_*.json` | Bottleneck effectiveness summary |
| `median_metrics_summary_*.json` | Per-connection median metrics |
| `metrics_history_*.json` | Full time series for plotting |
| `epoch_history_*.json` | Q-learning epoch data |
| `server_metrics_latest.json` | Server-side measurements |

### Key Metrics in Summary

```json
{
  "connections": {
    "2": {
      "application_type": "file_transfer",
      "client_offered_mbps": 220.0,      // App send rate
      "client_acked_mbps": 1.9,          // ACK-verified throughput
      "server_received_mbps": 1.94,      // Server measurement
      "delivery_ratio_percent": 0.88,    // % delivered
      "rtt_median_ms": 41.5,
      "latency_median_ms": 20.8,
      "jitter_median_ms": 0.09
    }
  }
}
```

---

## Browser UI Dashboard

The browser UI provides real-time visualization of metrics.

### Running with UI (Docker - Recommended)

The `docker-compose.yml` exposes port 8000 and enables UI by default:

```bash
cd /Users/steph/dev/research_folder/GIT_QUIC_3conn/QUIC_3conn_implementation

# Run with UI (default)
SCENARIO=varying DURATION=120 docker-compose up
```

Open: **http://localhost:8000**

### Running with UI (Local - macOS)

```bash
cd /Users/steph/dev/research_folder/GIT_QUIC_3conn/QUIC_3conn_implementation/3_conn_code

uv run python -m main run --ui --with-ml --duration 120 --bandwidth-cap 30
```

Open: **http://localhost:8000**

### UI Features

- Real-time throughput graphs per connection
- Latency and jitter visualization
- Current parameter values
- Q-learning state and action display

### Architecture (Docker with UI)

```
┌─────────────────────────────────────────────────────────────┐
│  Your Mac (Host)                                            │
│                                                             │
│   Browser ──────► http://localhost:8000                     │
│                         │                                   │
│                         │ port 8000 mapped                  │
│                         ▼                                   │
│   ┌─────────────────────────────────────────────────────┐  │
│   │  Docker: quic-clients container                      │  │
│   │                                                      │  │
│   │   FastAPI UI Server ◄── real-time metrics            │  │
│   │         │                      │                     │  │
│   │         │              ProcessOrchestrator           │  │
│   │         │                      │                     │  │
│   │         │              3 Worker Processes            │  │
│   │         │                      │                     │  │
│   │         │              Q-Learning Agent              │  │
│   └─────────┼──────────────────────┼─────────────────────┘  │
│             │                      │                        │
│             │           Docker Network (192.168.200.0/24)   │
│             │                      │                        │
│   ┌─────────┼──────────────────────┼─────────────────────┐  │
│   │  Docker: quic-server container │                     │  │
│   │                                ▼                     │  │
│   │              TC Bottleneck (varies by scenario)      │  │
│   │                                │                     │  │
│   │              QUIC Server ◄─────┘                     │  │
│   └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## How to Know If It's Working

### 1. Check Terminal Logs

**Good Q-learning output:**
```
[QLAgent] Initialised - 25 actions, control_interval=2.0s, α=0.1 γ=0.9 ε=0.30→0.05
[QLAgent step=  10] state=(1, 2, 0, 1, 2, 1) action=file.cubic_c ↑ ε=0.285
lat=18.5ms tp=1.85Mbps(Δ=2.10) jit=5.2ms avg_R=+0.412 Q-states=8
```

**What to look for:**
- `Q-states` increasing = agent is exploring state space
- `avg_R` trending positive = agent is learning
- `ε` decreasing = moving from exploration to exploitation
- `tp=X.XX(Δ=Y.YY)` = realistic values (not 200+ Mbps)

### 2. Check Results Summary

```bash
cat results/bottleneck_summary_*.json | python -m json.tool | head -30
```

**Good indicators:**

| Metric | Good Value | Bad Value |
|--------|------------|-----------|
| `bottleneck_applied` | `true` | `false` |
| `bottleneck_limiting_traffic` | `true` | `false` |
| `client_acked_mbps` | Near bottleneck cap | Same as offered |
| `delivery_ratio_percent` | < 100% for file transfer | 100% for all |

### 3. Verify Throughput Makes Sense

For `congested_low` (5 Mbps cap):
- File transfer `client_offered_mbps`: ~200+ Mbps (unlimited send)
- File transfer `client_acked_mbps`: ~1-3 Mbps (bottlenecked)
- Video/Conference `client_acked_mbps`: ~0.1-1.3 Mbps (their actual rate)

---

## Troubleshooting

### "wireless_bottleneck module not found"

```bash
# Ensure you're in the right directory
cd /Users/steph/dev/research_folder/GIT_QUIC_3conn/QUIC_3conn_implementation/3_conn_code

# The module is at ../wireless_bottleneck
# It's automatically added to Python path
```

### Bottleneck Not Working (Still Getting High Throughput)

This happens on macOS loopback - TC doesn't work. Solutions:

1. **Use Docker** (recommended)
2. **Use `--bandwidth-cap`** for application-level limiting:
   ```bash
   uv run python -m main run --bandwidth-cap 5 --duration 60
   ```

### Docker Build Fails

```bash
# Clean rebuild
docker-compose down -v --rmi all
docker-compose build --no-cache
```

### Q-Learning Not Improving

- Run longer (at least 120 seconds for meaningful learning)
- Check if bottleneck is actually working (delivery_ratio < 100%)
- Try different scenarios to give agent variety

### Results Directory Empty

```bash
# Check Docker volume mounting
docker-compose config | grep volumes

# Ensure results directory exists
mkdir -p results
```

---

## Quick Reference Commands

```bash
# === DOCKER (Recommended) ===
cd /Users/steph/dev/research_folder/GIT_QUIC_3conn/QUIC_3conn_implementation

# Build
docker-compose build

# Run with Q-learning + UI (default settings)
docker-compose up

# Run varying scenario + Q-learning + UI
SCENARIO=varying DURATION=120 docker-compose up

# Run without UI (Q-learning only)
docker-compose up -d server prober
docker-compose run --rm clients python -m main clients \
  --server 192.168.200.10 --duration 120 --scenario varying --with-ml --output-dir output
docker-compose down

# Run without Q-learning (baseline)
docker-compose up -d server prober
docker-compose run --rm clients python -m main clients \
  --server 192.168.200.10 --duration 60 --scenario congested_low --output-dir output
docker-compose down

# Stop
docker-compose down

# Full cleanup
docker-compose down -v --rmi all

# === LOCAL (macOS) ===
cd /Users/steph/dev/research_folder/GIT_QUIC_3conn/QUIC_3conn_implementation/3_conn_code

# Run with bandwidth cap + Q-learning (no UI)
uv run python -m main run --with-ml --bandwidth-cap 5 --duration 60

# Run with UI + Q-learning
uv run python -m main run --ui --with-ml --bandwidth-cap 5 --duration 120

# Run without Q-learning (baseline)
uv run python -m main run --bandwidth-cap 5 --duration 60

# === CHECK RESULTS ===
cat results/median_metrics_summary_*.json | python -m json.tool
cat results/bottleneck_summary_*.json | python -m json.tool
ls -la results/
```

---

## File Locations

| Component | Path |
|-----------|------|
| Main application | `3_conn_code/` |
| Q-learning agent | `3_conn_code/ml_callbacks/q_learning_agent.py` |
| Metrics collector | `3_conn_code/metrics/collector.py` |
| Wireless bottleneck | `wireless_bottleneck/` |
| Network scenarios | `wireless_bottleneck/scenarios.py` |
| Docker config | `docker-compose.yml` |
| Results output | `results/` |
