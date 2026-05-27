# QUIC 3-Connection Simulation with Wireless Bottleneck and Q-Learning

A multi-process QUIC simulation system that runs 3 concurrent connections competing through a shared wireless bottleneck, with optional Q-learning-based parameter optimization.

## What This Project Does

- Simulates **3 concurrent QUIC connections** with different traffic patterns:
  - Video streaming (optimize for low latency)
  - File transfer (optimize for high throughput)
  - Conference call (optimize for low jitter)

- Applies **realistic network constraints** using Linux traffic control (tc):
  - Bandwidth limiting
  - Latency/delay
  - Packet loss

- Optionally runs a **Q-learning agent** that dynamically tunes QUIC congestion control parameters to optimize performance across all connections

---

## Quick Start (5 minutes)

### Prerequisites

- **Docker Desktop** installed and running (download from https://www.docker.com/products/docker-desktop/)
- Docker Compose (included with Docker Desktop)
- ~2GB disk space for the Docker image

> **Note**: Make sure Docker Desktop is running before executing any `docker` commands. You should see the whale icon in your menu bar.

### Step 1: Build the Docker Image

```bash
cd QUIC_3conn_implementation
docker build -t quic-wireless -f Dockerfile .
```

### Step 2: Run the Simulation

```bash
docker-compose up
```

This runs:
- A QUIC server with 5 Mbps bandwidth limit, 30ms RTT, 2% packet loss
- 3 QUIC client connections competing for bandwidth
- Q-learning agent optimizing parameters in real-time
- Browser UI at **http://localhost:8000**
- Results saved to `./results/` directory

### Step 3: View the Live Dashboard

Open **http://localhost:8000** in your browser to see:
- Real-time throughput, RTT, jitter for all 3 connections
- Q-learning actions and parameter changes
- Live metrics graphs

### Step 4: View Results

After the run completes, results are saved in an organized structure:
```bash
ls results/
# congested_low/
#   └── run_Apr06_2026_1234PM/
#       ├── README.md              # Human-readable summary
#       ├── qlearning_actions.csv  # Parameter changes
#       ├── metrics_timeseries.csv # Metrics at every time step
#       ├── q_table.json           # Learned Q-values
#       └── ...
```

---

## Detailed Setup Guide

### Option A: Docker Setup (Recommended)

Docker is required for real bandwidth/loss enforcement. Without Docker, the Linux kernel bypasses traffic control rules.

#### 1. Build the Image

```bash
docker build -t quic-wireless -f Dockerfile .
```

#### 2. Run with Default Settings

```bash
# Default: congested_low scenario, 30 seconds, Q-learning ON, UI ON
docker-compose up

# Clean up when done
docker-compose down
```

#### 3. Run with Different Scenarios and Durations

```bash
# High bandwidth, low latency - 60 seconds
SCENARIO=stable_high DURATION=60 docker-compose up

# Variable bandwidth (oscillating) - 2 minutes
SCENARIO=varying DURATION=120 docker-compose up

# High packet loss - 90 seconds
SCENARIO=lossy DURATION=90 docker-compose up

# Asymmetric connection
SCENARIO=asymmetric DURATION=60 docker-compose up
```

#### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SCENARIO` | `congested_low` | Network scenario to use |
| `DURATION` | `30` | Simulation duration in seconds |

#### Available Scenarios

**Standard Scenarios:**

| Scenario | Bandwidth | RTT | Loss | Use Case |
|----------|-----------|-----|------|----------|
| `congested_low` | 5 Mbps | 30ms | 2% | Congested WiFi (default) |
| `stable_high` | 100 Mbps | 10ms | 0.1% | Good wired connection |
| `varying` | 12-28 Mbps | 20ms | 1% | Mobile network (bandwidth oscillates ±40%) |
| `lossy` | 10 Mbps | 40ms | 5% | Poor wireless (burst loss) |
| `asymmetric` | 50↓/10↑ Mbps | 25ms | 0.5% | Typical home internet |

**Packet Error Rate (PER) Scenarios** (for systematic loss testing):

| Scenario | Bandwidth | RTT | Loss | Use Case |
|----------|-----------|-----|------|----------|
| `per_ideal` | 50 Mbps | 20ms | 0% | Perfect channel (baseline) |
| `per_1` | 50 Mbps | 20ms | 1% | Light noise |
| `per_5` | 50 Mbps | 20ms | 5% | Moderate degradation |
| `per_10` | 50 Mbps | 20ms | 10% | Heavy degradation |
| `per_20` | 50 Mbps | 20ms | 20% | Severe degradation |

#### 4. Verify Bottleneck is Working

Check the server logs for:
```
quic-server | Successfully configured bottleneck: 5000 kbit/s, 15ms delay, 2.0% loss
```

Check results file:
```bash
cat results/bottleneck_summary_*.json | grep bottleneck_limiting
# "bottleneck_limiting_traffic": true   <-- Working!
```

---

### Option B: Local Setup (Limited - No Real Bottleneck)

For development/testing without Docker. Note: bandwidth limiting won't work on macOS/local loopback.

#### 1. Install Dependencies

```bash
cd 3_conn_code

# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

#### 2. Run Basic Simulation

```bash
uv run python -m main run --duration 30
```

#### 3. Run with Browser Dashboard

```bash
uv run python -m main run --ui --duration 60
# Open http://localhost:8000 in your browser
```

#### 4. Run with App-Level Bandwidth Cap

Since tc doesn't work locally, use the app-level bandwidth cap as a fallback:

```bash
uv run python -m main run --bandwidth-cap 30 --delay-ms 25 --loss-rate 0.02 --duration 60
```

---

## Running with Q-Learning

The Q-learning agent dynamically tunes QUIC parameters to optimize performance.

### In Docker (Default - Q-Learning is ON)

Q-learning and the browser UI are enabled by default in docker-compose.yml:

```bash
# Default: Q-learning ON, UI ON, 30 seconds
docker-compose up

# Longer run with varying network conditions
SCENARIO=varying DURATION=120 docker-compose up

# Access the live dashboard
open http://localhost:8000
```

### Docker Command Options

The docker-compose.yml clients command includes these flags:
```yaml
command: python -m main clients --server 192.168.200.10 --duration ${DURATION:-30} --scenario ${SCENARIO:-congested_low} --output-dir output --with-ml --ui
```

To run **without** Q-learning or UI, you can override:
```bash
# Without Q-learning (baseline run)
docker-compose run --rm clients python -m main clients --server 192.168.200.10 --duration 60 --scenario congested_low

# Without UI but with Q-learning
docker-compose run --rm clients python -m main clients --server 192.168.200.10 --duration 60 --with-ml
```

### Locally (Without Docker)

```bash
cd 3_conn_code

# Basic Q-learning run
uv run python -m main run --with-ml --duration 120

# With bandwidth cap (recommended for local testing)
uv run python -m main run --with-ml --bandwidth-cap 30 --duration 120

# With browser UI to watch in real-time
uv run python -m main run --with-ml --ui --duration 120

# All options combined
uv run python -m main run --with-ml --ui --scenario varying --duration 120 --settling-time 2
```

### What Q-Learning Optimizes

The agent tunes these CUBIC congestion control parameters:

| Parameter | Range | Effect |
|-----------|-------|--------|
| `loss_reduction_factor` | 0.3-0.7 | How much to reduce cwnd on packet loss |
| `cubic_c` | 0.2-0.4 | CUBIC growth aggressiveness |
| `minimum_window` | 2-4 | Minimum congestion window floor |
| `packet_threshold` | 3-4 | Packets before declaring loss |

### Q-Learning Output

Watch for agent decisions in the logs:
```
[QLAgent step=  10] state=(1, 2, 0, 1, 2, 1) action=file.cubic_c ↑
                    ε=0.285 lat=18.5ms tp=1.85Mbps jit=8.2ms avg_R=+0.542
```

The Q-table checkpoint is saved to `output/q_learning_checkpoint.json` and persists across runs. This includes:
- The learned Q-values (so the agent improves over multiple runs)
- The step count (continues incrementing across runs)
- The exploration rate epsilon (decays across runs)

**To start fresh** (reset step count to 0 and epsilon to 0.30):
```bash
rm -f output/q_learning_checkpoint.json
```

### Q-Learning Results Files

After each run, results are saved in an organized folder structure:

```
results/
└── {scenario}/
    └── run_{timestamp}/
        ├── README.md              # Human-readable summary
        ├── qlearning_actions.json # Parameter changes with before/after metrics
        ├── qlearning_actions.csv  # Same data for spreadsheets
        ├── q_table.json           # Learned Q-values (the trained "brain")
        ├── metrics_timeseries.csv # Metrics at every 0.1s interval
        ├── config.json            # Run configuration & hyperparameters
        ├── rewards.csv            # Reward at each Q-learning step
        └── metrics.json           # Final metrics per connection
```

---

## Project Structure

```
QUIC_3conn_implementation/
├── 3_conn_code/              # Main simulation code
│   ├── main.py               # Entry point
│   ├── simulation/           # Core engine
│   ├── synthesizers/         # Traffic generators
│   ├── metrics/              # Data collection
│   ├── ml_callbacks/         # Q-learning agent
│   └── web/                  # Browser dashboard
├── wireless_bottleneck/      # Network emulation (tc wrapper)
├── docker-compose.yml        # Multi-container setup
├── Dockerfile                # Container definition
├── FULL_report.md            # Detailed documentation
└── reward_functions.md       # Q-learning reward documentation
```

---

## Command Reference

### Docker Commands

```bash
# Build image
docker-compose build

# Run with defaults (congested_low, 30s, Q-learning ON, UI ON)
docker-compose up

# Run with specific scenario and duration
SCENARIO=varying DURATION=120 docker-compose up

# Run with all scenarios
SCENARIO=stable_high DURATION=60 docker-compose up
SCENARIO=congested_low DURATION=60 docker-compose up
SCENARIO=varying DURATION=120 docker-compose up
SCENARIO=lossy DURATION=60 docker-compose up
SCENARIO=asymmetric DURATION=60 docker-compose up

# Run in background
docker-compose up -d

# View logs
docker-compose logs -f
docker-compose logs -f clients  # Just client logs

# Stop and clean up
docker-compose down

# Rebuild after code changes
docker-compose build && docker-compose up

# Enter running container for debugging
docker exec -it quic-clients bash
docker exec -it quic-server bash
```

### Docker Run Without Q-Learning or UI

```bash
# Baseline run (no Q-learning, no UI)
docker-compose run --rm -p 8000:8000 clients \
    python -m main clients --server 192.168.200.10 --duration 60 --scenario varying

# Q-learning but no UI
docker-compose run --rm clients \
    python -m main clients --server 192.168.200.10 --duration 60 --with-ml --scenario varying

# UI but no Q-learning
docker-compose run --rm -p 8000:8000 clients \
    python -m main clients --server 192.168.200.10 --duration 60 --ui --scenario varying
```

### Local Commands (3_conn_code)

```bash
cd 3_conn_code

# Basic run (no bottleneck on macOS)
uv run python -m main run --duration 30

# With Q-learning
uv run python -m main run --with-ml --duration 120

# With browser UI
uv run python -m main run --ui --duration 60

# With Q-learning AND UI
uv run python -m main run --with-ml --ui --duration 120

# With app-level bandwidth cap (workaround for macOS)
uv run python -m main run --with-ml --bandwidth-cap 30 --delay-ms 25 --loss-rate 0.02 --duration 60

# Full options example
uv run python -m main run \
    --duration 120 \
    --scenario varying \
    --ui \
    --with-ml \
    --settling-time 2 \
    --output-dir output

# Server-only mode (for multi-machine setup)
uv run python -m main server --duration 60 --scenario congested_low

# Clients-only mode (connect to remote server)
uv run python -m main clients --server 192.168.1.100 --duration 30 --with-ml --ui
```

### All CLI Options

#### Common Options (all modes)

| Option | Default | Description |
|--------|---------|-------------|
| `--duration` | 30 | Simulation length in seconds |
| `--scenario` | congested_low | Network scenario name |
| `--output-dir` | output | Results directory |

#### Run Mode Options (`main run`)

| Option | Default | Description |
|--------|---------|-------------|
| `--ui` | off | Enable browser dashboard at http://localhost:8000 |
| `--port` | 8000 | Dashboard port |
| `--with-ml` | off | Enable Q-learning agent |
| `--settling-time` | 2.0 | Seconds to wait after parameter changes |
| `--bandwidth-cap` | none | App-level bandwidth limit in Mbps |
| `--loss-rate` | 0.0 | Simulated packet loss (0.0-1.0) |
| `--delay-ms` | 0.0 | Simulated delay in milliseconds |

#### Clients Mode Options (`main clients`)

| Option | Default | Description |
|--------|---------|-------------|
| `--server` | required | Server IP address to connect to |
| `--ui` | off | Enable browser dashboard |
| `--with-ml` | off | Enable Q-learning agent |

#### Server Mode Options (`main server`)

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | 0.0.0.0 | Interface to listen on |
| `--port` | 4433 | QUIC port |

---

## Output Files

After each run, results are saved in an organized hierarchical structure:

```
results/
├── {scenario}/                          # e.g., varying/, congested_low/
│   └── run_{timestamp}/                 # e.g., run_Apr06_2026_1234PM/
│       ├── README.md                    # Human-readable summary with tables
│       ├── qlearning_actions.json       # Parameter changes with before/after metrics
│       ├── qlearning_actions.csv        # Same data for Excel/Google Sheets
│       ├── q_table.json                 # Learned Q-values (the trained policy)
│       ├── metrics_timeseries.csv       # Metrics at every 0.1s interval
│       ├── config.json                  # Full run configuration
│       ├── rewards.csv                  # Reward at each Q-learning step
│       └── metrics.json                 # Final metrics per connection
├── server_metrics_latest.json           # Server-side throughput data
└── q_learning_checkpoint.json           # Persisted Q-table for warm starts
```

### File Descriptions

| File | Purpose | Use Case |
|------|---------|----------|
| `README.md` | Quick overview with summary tables | Read first to understand results |
| `qlearning_actions.csv` | What parameters changed and their effect | Import into Excel for analysis |
| `metrics_timeseries.csv` | Throughput/RTT/jitter over time | Plot graphs, analyze trends |
| `q_table.json` | The learned Q-values for each state | Study what the agent learned |
| `rewards.csv` | Reward progression over steps | Check if learning is improving |
| `config.json` | Hyperparameters and settings | Reproduce this exact run |

---

## Troubleshooting

### Docker Daemon Not Running

**Symptom**: Error message like:
```
ERROR: failed to connect to the docker API at unix:///Users/.../.docker/run/docker.sock
```

**Solutions**:

1. **Start Docker Desktop (GUI)**:
   - Open **Docker Desktop** from Applications or Spotlight (Cmd + Space, type "Docker")
   - Wait for the whale icon in the menu bar to stop animating
   - Retry the docker command

2. **Start from Terminal**:
   ```bash
   open -a Docker
   ```
   Wait ~30 seconds, then retry.

3. **Verify Docker is running**:
   ```bash
   docker info
   ```
   If running, you'll see system info. If not, you'll get the socket error.

**Don't have Docker installed?**

Download Docker Desktop for Mac: https://www.docker.com/products/docker-desktop/

---

### Bottleneck Not Working

**Symptom**: Throughput is 40+ Mbps instead of 5 Mbps

**Solutions**:
1. Make sure you're using Docker multi-container setup
2. Check server logs for "Successfully configured bottleneck"
3. Verify `bottleneck_applied: true` in results

### Connections Failing

**Symptom**: Clients can't connect to server

**Solutions**:
1. Wait for server to fully start before clients
2. Check both containers are on same network: `docker network ls`
3. Verify IPs: `docker inspect quic-server | grep IPAddress`

### Q-Learning Not Learning

**Symptom**: Agent always takes same actions, no improvement

**Solutions**:
1. Run longer (at least 120 seconds)
2. Use a constrained scenario (congested_low) so there's something to optimize
3. Check that metrics are being collected (non-zero throughput/latency)

### Q-Learning Steps Seem Off / Steps Not Starting at Zero

**Symptom**: Q-learning step count starts at a high number (e.g., step=50) instead of step=0, or steps don't match expected timing

**Cause**: The Q-learning agent persists its state (Q-table, step count, epsilon) to a checkpoint file (`output/q_learning_checkpoint.json`). When you run again, it continues from where it left off.

**Solutions**:

1. **Delete the checkpoint to start fresh**:
   ```bash
   # Local runs
   rm -f 3_conn_code/output/q_learning_checkpoint.json

   # Docker runs
   docker-compose down
   rm -f results/q_learning_checkpoint.json
   docker-compose up
   ```

2. **Note about logging frequency**: The agent only logs every 10 steps to reduce spam. In a 30-second run (~15 steps), you'll only see 1-2 log lines. This is normal.

### Permission Errors in Docker

**Symptom**: tc commands fail with permission denied

**Solution**: Ensure `--privileged` flag or `cap_add: NET_ADMIN` in docker-compose.yml

---

## How It Works

### Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        Docker Network (192.168.200.0/24)                  │
│                                                                           │
│  ┌─────────────────────┐                  ┌─────────────────────────┐    │
│  │  Server Container   │    tc qdisc      │  Clients Container      │    │
│  │  192.168.200.10     │◄────────────────►│  192.168.200.20         │    │
│  │                     │   (bottleneck)   │                         │    │
│  │  • QUIC Server      │                  │  • Worker 1 (Video)     │    │
│  │  • Bandwidth limit  │                  │  • Worker 2 (File)      │    │
│  │  • RTT/Loss shaping │                  │  • Worker 3 (Conference)│    │
│  │                     │                  │  • Q-Learning Agent     │    │
│  │                     │                  │  • Web UI (:8000)       │    │
│  └─────────────────────┘                  └─────────────────────────┘    │
│                                                      │                    │
│                                                      │ Port 8000          │
│                                                      ▼                    │
│                                           ┌─────────────────┐            │
│                                           │  Your Browser   │            │
│                                           │  localhost:8000 │            │
│                                           └─────────────────┘            │
└──────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Traffic Generation**: Each worker generates traffic matching its application type
2. **Network Constraint**: tc qdisc on server's eth0 limits bandwidth/adds delay/loss
3. **Metrics Collection**: Workers report throughput, latency, jitter every 0.1s
4. **Q-Learning Decision**: Agent observes metrics, picks parameter adjustment every 2s
5. **Parameter Update**: New parameters sent to workers via IPC
6. **CUBIC Adaptation**: aioquic adjusts congestion control with new parameters

---

## Additional Documentation

- [FULL_report.md](FULL_report.md) - Comprehensive technical documentation
- [reward_functions.md](reward_functions.md) - Q-learning reward function details
- [WIRELESS_BOTTLENECK_GUIDE.md](WIRELESS_BOTTLENECK_GUIDE.md) - Network emulation guide
- [3_conn_code/README.md](3_conn_code/README.md) - Simulation code documentation

---

## Requirements

- Python 3.12+
- Docker and Docker Compose (for real network emulation)
- Linux kernel with tc support (handled by Docker)

### Python Dependencies

- aioquic >= 1.0.0
- fastapi >= 0.109.0
- uvicorn >= 0.27.0
