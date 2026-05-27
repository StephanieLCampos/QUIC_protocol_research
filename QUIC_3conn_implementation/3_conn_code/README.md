# QUIC 3-Connection Simulation

A multi-process QUIC simulation system that runs 3 concurrent connections with isolated congestion control parameters and mid-connection parameter modification.

## Features

- **3 Concurrent QUIC Connections** - Video streaming, file transfer, and conference call
- **Per-connection parameter isolation** - Each connection runs in a separate process with its own aioquic globals
- **Mid-connection parameter modification** - Dynamically tune 6 CC parameters while connections are active
- **Real-time browser dashboard** - Monitor metrics, buffer states, network config, and manually adjust parameters
- **Q-Learning ML controller** - Two Q-learning agents available for automated parameter optimization
- **Epoch-based metrics** - Collect stable metrics with settling time after parameter changes
- **Network scenario simulation** - Built-in wireless bottleneck scenarios (bandwidth, RTT, loss)

## Installation

```bash
cd 3_conn_code

# Install dependencies with uv
uv sync

# Or with pip
pip install -e .
```

## Quick Start

### Run Locally (without Docker)

```bash
# Run basic simulation (30 seconds)
uv run python -m main run

# Run with browser UI dashboard at http://localhost:8000
uv run python -m main run --ui

# Run with default Q-Learning agent (7-feature state)
uv run python -m main run --ui --with-ml --scenario congested_low --duration 60

# Run with Andy's Q-Learning agent (14-feature state)
uv run python -m main run --ui --with-ml --ml-agent andy --scenario congested_low --duration 60

# Run with custom port
uv run python -m main run --ui --port 8080

# Run for 60 seconds with a specific network scenario
uv run python -m main run --duration 60 --scenario congested_low

# Run with longer settling time for network simulation
uv run python -m main run --ui --duration 120 --settling-time 5 --scenario congested_low
```

### Run with Docker

```bash
cd /path/to/QUIC_3conn_implementation

# Run with default settings
docker compose up

# Run with specific scenario and duration
SCENARIO=congested_low DURATION=60 docker compose up

# Run with Andy's Q-learning agent
ML_AGENT=andy SCENARIO=varying DURATION=120 docker compose up

# Clear Q-table and start fresh training
CLEAR_QTABLE=1 ML_AGENT=andy SCENARIO=varying DURATION=600 docker compose up

# Run with lossy network
SCENARIO=lossy DURATION=120 docker compose up

# Rebuild containers after code changes
docker compose build && docker compose up
```

The browser dashboard will be available at **http://localhost:8000**

#### Docker Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SCENARIO` | `congested_low` | Network scenario (see table below) |
| `DURATION` | `30` | Simulation duration in seconds |
| `ML_AGENT` | `default` | Q-learning agent: `default` (7-feature) or `andy` (14-feature) |
| `CLEAR_QTABLE` | - | Set to `1` to delete Q-table checkpoint and start fresh training |

**Note:** Results are saved to the `./results/` directory on your host machine (mounted from `/app/3_conn_code/output` in the container).

## Commands

### `run` - Run Full Simulation

Run all 3 connections locally with optional network simulation.

```bash
uv run python -m main run [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--duration FLOAT` | 30 | Simulation duration in seconds |
| `--metrics-interval FLOAT` | 0.1 | Metrics collection interval in seconds |
| `--output-dir PATH` | output | Output directory for results |
| `--config PATH` | - | Path to JSON config file |
| `--scenario NAME` | congested_low | Network scenario (see below) |
| `--with-ml` | - | Enable ML controller for automatic parameter tuning |
| `--ml-agent {default,andy}` | default | Q-Learning agent: 'default' (7-feature) or 'andy' (14-feature) |
| `--ml-callback MODULE:FUNC` | - | Custom ML callback (overrides --ml-agent) |
| `--ui` | - | Enable browser UI dashboard |
| `--port INT` | 8000 | Port for browser UI |
| `--settling-time FLOAT` | 2.0 | Settling time after parameter changes |
| `--bandwidth-cap MBPS` | 0 | Shared bandwidth cap in Mbps (forces competition) |
| `--loss-rate RATE` | 0 | Simulated packet loss rate 0.0-1.0 (e.g., 0.02 = 2%) |
| `--delay-ms MS` | 0 | Simulated one-way propagation delay in ms |
| `--debug` | - | Enable verbose debug output |

**Network Scenarios:**

| Scenario | Bandwidth | RTT | Loss | Description |
|----------|-----------|-----|------|-------------|
| `stable_high` | 100 Mbps | 10ms | 0.1% | Ideal conditions |
| `congested_low` | 5 Mbps | 30ms | 2% | Crowded network |
| `varying` | 20±8 Mbps | 20ms | 1% | Time-varying bandwidth |
| `lossy` | 10 Mbps | 40ms | 5% | High packet loss |
| `asymmetric` | 50/10 Mbps | 25ms | 0.5% | Asymmetric up/down |
| `per_ideal` | 50 Mbps | 20ms | 0% | Zero loss baseline |
| `per_1` | 50 Mbps | 20ms | 1% | 1% packet error rate |
| `per_5` | 50 Mbps | 20ms | 5% | 5% packet error rate |
| `per_10` | 50 Mbps | 20ms | 10% | 10% packet error rate |
| `per_20` | 50 Mbps | 20ms | 20% | 20% packet error rate |

---

### `server` - Server-Only Mode (Multi-Container)

Run just the server for distributed/Docker deployments.

```bash
uv run python -m main server [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--duration FLOAT` | 60 | Server run duration in seconds |
| `--scenario NAME` | congested_low | Network scenario for bottleneck |
| `--debug` | - | Enable verbose debug output |

---

### `clients` - Clients-Only Mode (Multi-Container)

Run just the clients, connecting to a remote server.

```bash
uv run python -m main clients --server <IP> [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--server IP` | (required) | Server IP address |
| `--duration FLOAT` | 30 | Client run duration in seconds |
| `--scenario NAME` | congested_low | Network scenario (for display) |
| `--output-dir PATH` | output | Output directory for results |
| `--with-ml` | - | Enable Q-learning ML controller |
| `--ml-agent {default,andy}` | default | Q-Learning agent to use |
| `--ui` | - | Enable browser UI dashboard on port 8000 |
| `--debug` | - | Enable verbose debug output |

---

### `probe` - Network RTT Probe

Run a standalone ping-based RTT probe for network characterization.

```bash
uv run python -m main probe --target <HOST> [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--target HOST` | (required) | Probe target host/IP |
| `--duration FLOAT` | 30 | Probe duration in seconds |
| `--interval FLOAT` | 0.5 | Ping interval in seconds |
| `--scenario NAME` | congested_low | Scenario label for output filename |
| `--output-dir PATH` | output | Output directory for probe files |
| `--debug` | - | Enable verbose debug output |

## Q-Learning Agents

Two Q-learning agents are available for automated parameter optimization:

### Default Agent (7-feature state)

```bash
uv run python -m main run --with-ml --ml-agent default
```

**State Space:** 6,912 states
```
state = (latency_bin, throughput_bin, jitter_bin,
         latency_trend, throughput_trend, jitter_trend,
         loss_bin)
```

- Uses metric bins (latency, throughput, jitter) from each connection
- Includes trend detection (improving/stable/worsening)
- Network condition awareness via loss_bin

### Andy's Agent (14-feature state)

```bash
uv run python -m main run --with-ml --ml-agent andy
```

**State Space:** ~11.6M theoretical states (sparse Q-table)
```
state = (lrf_v, lrf_f, lrf_c,    # loss_reduction_factor per connection
         cc_v,  cc_f,  cc_c,     # cubic_c per connection
         mw_v,  mw_f,  mw_c,     # minimum_window per connection
         pt_v,  pt_f,  pt_c,     # packet_threshold per connection
         tp_bin,                  # total throughput bin
         rtt_bin)                 # mean RTT bin
```

- Uses parameter step indices as state features
- Tracks exact position of each tunable parameter
- Network conditions via total throughput and RTT bins

## Dynamic Parameters

These 6 parameters can be modified mid-connection:

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `loss_reduction_factor` | 0.7 | 0.1-0.9 | cwnd reduction on packet loss (beta) |
| `cubic_c` | 0.4 | 0.1-1.0 | CUBIC growth aggressiveness |
| `minimum_window` | 2 | 1-10 | Minimum cwnd floor (packets) |
| `packet_threshold` | 3 | 1-10 | Packets before declaring loss |
| `time_threshold` | 1.125 | 1.0-2.0 | RTT multiplier for loss timeout |
| `cubic_max_idle_time` | 2.0 | 0.5-5.0 | Idle timeout before cwnd reset |

## Application Types

| Connection | Type | Traffic Pattern |
|------------|------|-----------------|
| 1 | Video Streaming | 30 fps, I-frames (50KB) + P-frames (5KB) |
| 2 | File Transfer | Continuous 64KB chunks |
| 3 | Conference Call | 320 bytes every 20ms |

## Browser Dashboard

When running with `--ui`, open http://localhost:8000 to access:

- **Network Scenario Config** - Displays bandwidth, RTT, loss rate, queue size, queue discipline
- **Real-time metrics** for each connection: throughput (Mbps), RTT (ms), latency (ms), jitter (ms), packet loss (%)
- **Total throughput** - Accumulated throughput across all 3 connections
- **Current parameter values** display
- **Manual parameter editor** (click "Edit Parameters")
- **Q-Learning Actions** - Shows parameter changes with before/after metrics comparison

### Network Config Display

The dashboard shows the current network scenario configuration:
- Bandwidth (Mbps)
- RTT (ms)
- Loss (%)
- Queue size (packets)
- Queue discipline (FIFO/RED/CoDel/PIE)
- Time varying (Yes/No with amplitude if applicable)

## Settling Time

After parameter changes, CUBIC congestion control needs time to adjust. The `--settling-time` option controls how long to wait before capturing metrics snapshots.

**Recommended settling times by scenario:**

| Scenario | RTT | `--settling-time` | Example |
|----------|-----|------------------|---------|
| Local loopback | 2-5ms | 2 (default) | `--settling-time 2` |
| Stable network | 20-50ms | 3-5 | `--settling-time 5` |
| Congested network | 50-100ms | 5-8 | `--settling-time 8` |
| Lossy/varying network | 50ms+ | 8-10 | `--settling-time 10` |

**Why settling time matters:**
- CUBIC needs multiple RTTs to adjust congestion window
- `loss_reduction_factor` only takes effect on next loss event
- Higher latency networks need more time for changes to propagate

**Example with network simulation:**
```bash
# For wireless_bottleneck with congested scenario
uv run python -m main run --ui --duration 120 --settling-time 8 --scenario congested_low
```

## Output Files

Results are saved to the output directory:

- `result_TIMESTAMP.json` - Final summary with fairness index and per-connection metrics
- `metrics_TIMESTAMP.json` - Time-series metrics history
- `epochs_TIMESTAMP.json` - Epoch-based metrics for ML analysis
- `qlearning_actions.json` - Q-learning parameter change history (if --with-ml)
- `q_table.json` - Learned Q-values (if --with-ml)
- `rewards.csv` - Reward history (if --with-ml)

## ML Callbacks

Create custom ML callbacks for automated parameter optimization:

```python
# my_callback.py
def my_optimizer(metrics: dict) -> dict:
    """
    Args:
        metrics: {conn_id: {"throughput": float, "rtt": float, "current_params": {...}}}

    Returns:
        {conn_id: {"param_name": new_value, ...}}
    """
    decisions = {}
    # Your optimization logic here
    return decisions
```

Run with: `uv run python -m main run --with-ml --ml-callback my_callback:my_optimizer`

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Main Process                              │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ ProcessOrchestrator│  │   MLController   │                │
│  └────────┬─────────┘  └────────┬─────────┘                 │
│           │                     │                            │
│     Barrier Sync          ML Callback                        │
│           │                     │                            │
├───────────┼─────────────────────┼────────────────────────────┤
│           ▼                     ▼                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │  Worker 1   │  │  Worker 2   │  │  Worker 3   │          │
│  │ (Video)     │  │ (File)      │  │ (Conference)│          │
│  │             │  │             │  │             │          │
│  │ aioquic     │  │ aioquic     │  │ aioquic     │          │
│  │ globals     │  │ globals     │  │ globals     │          │
│  │ (isolated)  │  │ (isolated)  │  │ (isolated)  │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
│     Process 1        Process 2        Process 3              │
└─────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
3_conn_code/
├── main.py                    # CLI entry point (run, server, clients, probe)
├── config/
│   ├── connection_config.py   # Per-connection configuration
│   └── multi_connection_config.py  # Multi-connection orchestration config
├── simulation/
│   ├── process_orchestrator.py  # Manages 3 worker processes
│   ├── server.py              # QUIC server implementation
│   ├── worker_process.py      # Worker process entry point
│   └── ml_controller.py       # ML controller for Q-learning integration
├── synthesizers/
│   ├── file_transfer.py       # File transfer traffic generator
│   ├── video_streaming.py     # Video streaming traffic generator
│   └── conference_call.py     # Conference call traffic generator
├── metrics/
│   ├── collector.py           # Metrics collection and aggregation
│   ├── calculator.py          # Metrics calculations
│   └── epoch.py               # Epoch-based metrics
├── ml_callbacks/
│   ├── q_learning_agent.py       # Default Q-learning agent (7-feature state)
│   └── q_learning_agent_andy.py  # Andy's Q-learning agent (14-feature state)
├── web/
│   ├── server.py              # FastAPI dashboard server
│   └── static/                # Dashboard HTML/CSS/JS
├── utils/
│   └── debug.py               # Debug utilities
├── certs/                     # SSL certificates (auto-generated)
└── output/                    # Results output directory
```

## Multi-Container Setup (Docker)

For distributed deployments with separate server and client containers:

```bash
# Using docker-compose (recommended)
cd /path/to/QUIC_3conn_implementation
SCENARIO=congested_low DURATION=60 docker compose up

# Manual setup:

# On server container:
uv run python -m main server --scenario congested_low --duration 120

# On client container:
uv run python -m main clients --server 192.168.200.10 --duration 60 --with-ml --ui

# With Andy's agent:
uv run python -m main clients --server 192.168.200.10 --duration 60 --with-ml --ml-agent andy --ui

# Optional: Run network probe sidecar
uv run python -m main probe --target 192.168.200.10 --duration 60
```

## Docker Troubleshooting

If Docker Desktop won't start:
```bash
# Kill all Docker processes and restart
killall Docker "Docker Desktop" com.docker.hyperkit com.docker.backend 2>/dev/null
sleep 2
open -a Docker
```

If containers fail to start:
```bash
# Clean up old containers
docker container prune -f

# Rebuild images
docker compose build --no-cache

# Run with fresh containers
docker compose up --force-recreate
```

## Requirements

- Python 3.12+
- aioquic >= 1.0.0
- fastapi >= 0.109.0
- uvicorn >= 0.27.0
- Docker (optional, for containerized runs)
