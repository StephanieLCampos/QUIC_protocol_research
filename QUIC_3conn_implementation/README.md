# QUIC 3-Connection Simulation with Wireless Bottleneck and Q-Learning

A multi-process QUIC simulation that runs 3 concurrent connections competing
through a shared wireless bottleneck, with Q-learning agents that tune each
connection's congestion-control parameters live.

This is the second of the two generations in this repository. The first,
[`QUIC_tuning_multistream`](../QUIC_tuning_multistream), measured one connection
at a time with fixed parameters. This one asks the harder question: when three
connections with conflicting goals share one constrained link, can a
reinforcement-learning agent tune them better than any fixed configuration?

Part of a team project with three contributors: Stephanie Campos, Sean Lai and
Derek Chui. One Q-learning agent variant carries an in-source author credit to
Andy Li.

---

## What This Project Does

- Simulates **3 concurrent QUIC connections** with different traffic patterns:
  - Video streaming (optimize for low latency)
  - File transfer (optimize for high throughput)
  - Conference call (optimize for low jitter)

- Applies **realistic network constraints** using Linux traffic control (tc):
  - Bandwidth limiting
  - Latency/delay
  - Packet loss

- Optionally runs a **Q-learning agent** that dynamically tunes QUIC congestion
  control parameters to optimize performance across all connections

The three connections genuinely compete: they share one bottleneck, one
bandwidth budget, and start simultaneously behind a barrier so no connection
gets a head start.

---

## The Central Design Constraint

One library detail shaped this entire architecture, and is the most useful
thing to understand before reading the code.

**aioquic stores its congestion-control tuning in module-level globals.**
`K_CUBIC_C`, `K_CUBIC_LOSS_REDUCTION_FACTOR`, `K_PACKET_THRESHOLD` and the rest
are module attributes, not per-connection configuration. There is no supported
way to give two connections in the same process different parameters.

Generation 1 lived with this by measuring one connection at a time. This
project cannot: its entire premise is three connections holding *different*
parameters at once.

The resolution is to give each connection **its own OS process**, and therefore
its own copy of the aioquic modules. That single decision explains why the
system needs:

| Mechanism | Why it exists |
|---|---|
| One process per connection | Independent aioquic globals |
| Command pipe per worker | Parameter updates must cross a process boundary |
| Shared metrics queue | Telemetry must come back across that boundary |
| Start barrier | Otherwise process startup skew gives one connection a head start |
| Shared token bucket | A bandwidth budget must be enforced across processes |
| Config passed as dicts | Arguments must be picklable under `spawn` |

Everything that looks like unnecessary machinery follows from that one
constraint.

---

## Architecture

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
│  │  • Control :9001    │                  │  • Q-Learning Agent     │    │
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

**Why three containers rather than one.** A container can only shape its own
egress, so a single container would force upload and download to share one
constraint. Splitting server from clients lets each shape its own direction. A
third `prober` container runs an independent ICMP probe of the same path, giving
an outside view of RTT that is not distorted by the connections' own queueing.

Because the dashboard runs alongside the clients but a slider change must reach
both bottlenecks, the server container exposes a small internal control
endpoint on `:9001` that the clients container posts to.

### Inside the clients container

```
                    ProcessOrchestrator (main process)
                                 │
    ┌────────────────────────────┼────────────────────────────┐
    │                            │                            │
QuicServer                 MLController                 start barrier
(shared endpoint)      (Q-learning control loop)    (synchronised start)
    │                            │
    │                 parameters │  ▲ metrics
    │                     (pipe) ▼  │ (shared queue)
    │          ┌─────────────────────────────────────┐
    │          │  worker 1  │  worker 2  │  worker 3 │  separate processes
    └──────────│   video    │    file    │ conference│  one aioquic each
               └─────────────────────────────────────┘
                                 │
                      WirelessBottleneck (Linux tc)
                                 │
                                 ▼
              MultiConnectionResult → JSON / CSV exports
```

### Run sequence

1. Apply the wireless bottleneck (interface chosen by deployment mode)
2. Start the shared QUIC server
3. Spawn three worker processes
4. Release the start barrier so all three begin together
5. Drive either the Q-learning control loop or a plain metrics loop
6. Signal STOP, drain results, join and terminate stragglers
7. Read `tc` counters, await the RTT probe, export Q-learning history
8. Build and return the combined result

Shutdown is deliberately concurrent: results are drained on a daemon thread
*while* workers exit, because a worker terminated mid-write can leave a partial
pipe write that would block a reader indefinitely.

---

## Project Structure

```
QUIC_3conn_implementation/
├── 3_conn_code/                    Main simulation
│   ├── main.py                     CLI: run / server / clients / probe
│   ├── config/
│   │   ├── connection_config.py    One connection's parameters
│   │   └── multi_connection_config.py
│   ├── simulation/
│   │   ├── process_orchestrator.py Control centre (largest file)
│   │   ├── worker_process.py       One connection, one process
│   │   ├── ml_controller.py        Q-learning control loop
│   │   ├── server.py               Shared QUIC endpoint
│   │   ├── token_bucket.py         Cross-process bandwidth cap
│   │   ├── ipc_messages.py         Message types
│   │   └── result.py               Aggregation and exports
│   ├── ml_callbacks/               Three Q-learning agents
│   ├── metrics/                    Collection, calculation, epochs
│   ├── synthesizers/               Three traffic models
│   ├── web/                        FastAPI dashboard + static front end
│   └── certs/                      TLS certificates
├── grid_search_code/               Sweep over the 6 dynamic parameters
├── research_code/                  Uniform-config comparison (27 values)
├── wireless_bottleneck/            tc emulation (HTB, live control)
├── train_agents.sh                 Train all three agents
├── train_hybrid.sh                 Train the hybrid agent only
├── train_q_learning.sh             Batch train across all scenarios
├── setup_veth.sh                   veth pair for single-container mode
├── docker-compose.yml              Three-container setup
└── Dockerfile                      Container definition
```

### How the sub-projects relate

```
grid_search_code          research_code              3_conn_code
─────────────────         ──────────────             ───────────
Sweep 6 dynamic      →    Apply one config       →   3 connections, each
parameters, one           uniformly to all 3;        tuned independently
connection at a time      27 measurements            and live by an agent
       │                         │                          │
  optimal params          what does sharing          can learning beat
  per app type            one config cost?           any fixed config?
```

`grid_search_code` produces the tuning ranges the agents search within.
`research_code` quantifies the cost of a single shared configuration, which is
the argument for per-connection tuning in the first place.

---

## Quick Start (5 minutes)

### Prerequisites

- **Docker Desktop** installed and running (download from https://www.docker.com/products/docker-desktop/)
- Docker Compose (included with Docker Desktop)
- ~2GB disk space for the Docker image

> **Note**: Make sure Docker Desktop is running before executing any `docker`
> commands. You should see the whale icon in your menu bar.

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

Docker is required for real bandwidth/loss enforcement. Without Docker, the
Linux kernel bypasses traffic control rules.

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
| `ML_AGENT` | `default` | Q-learning agent: `default`, `andy` or `hybrid` |
| `CLEAR_QTABLE` | unset | Set to `1` to discard the persisted Q-table |

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

The `varying` scenario's period is 6 seconds rather than Generation 1's 2
seconds. This is deliberate: the agent acts every 2 seconds, so a 2-second
network period gave it no chance to observe the consequence of an action before
conditions changed again. Three decisions per network state makes cause and
effect learnable.

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

For development/testing without Docker. Note: bandwidth limiting won't work on
macOS/local loopback.

#### 1. Install Dependencies

```bash
cd 3_conn_code

# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

#### 1b. Generate TLS Certificates

Local runs need a certificate and key, which are generated on demand rather
than committed:

```bash
cd ..            # QUIC_3conn_implementation
cd ..            # repository root
./generate_certs.sh
```

This is **not** needed for `docker-compose up`: the image generates its own
certificates at build time.

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

This is the shared token bucket rather than kernel shaping. It creates genuine
contention between the three connections, which is what the agent needs, but it
is not a substitute for `tc` when measuring absolute performance.

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

# Choose an agent
ML_AGENT=andy SCENARIO=varying DURATION=120 docker-compose up

# Clear the Q-table and train from scratch
CLEAR_QTABLE=1 ML_AGENT=andy SCENARIO=varying DURATION=600 docker-compose up

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

# Select a specific agent
uv run python -m main run --with-ml --ml-agent andy --scenario congested_low --duration 60
uv run python -m main run --with-ml --ml-agent hybrid --scenario varying --duration 600

# All options combined
uv run python -m main run --with-ml --ui --scenario varying --duration 120 --settling-time 2
```

### Batch training

```bash
./train_agents.sh            # all three agents, across scenarios
./train_agents.sh --clear    # discard prior learning first
./train_hybrid.sh            # hybrid agent only
DURATION=600 SESSIONS=5 ./train_q_learning.sh
```

These re-invoke themselves inside `tmux`, so a multi-hour training run survives
the terminal closing. `train_agents.sh` and `train_hybrid.sh` preserve Q-tables
between scenarios so learning accumulates; `train_q_learning.sh` clears the
checkpoint at the start, which is required whenever the state representation has
changed, because a Q-table keyed by the old layout is meaningless under a new one.

---

## The Three Q-Learning Agents

All three share an identical action space and reward function, and differ
**only** in how they represent state. That makes the comparison between them a
clean experiment in state design.

| Agent | Features | State space | Design idea |
|---|---|---|---|
| `default` | 8 | ~27,600 | Performance bins plus trends |
| `hybrid` | 10 | ~995,000 | Default, plus compressed boundary and dominance signals |
| `andy` | 14 | ~11.6M | Exact parameter step indices, so boundaries are visible |

The trade-off is generalisation against precision. Andy's agent can tell that a
parameter is already pinned at its limit and that pushing further is wasted; the
default agent, seeing only outcomes, cannot. But with ~11.6M possible states and
only a few hundred visited per run, its Q-table is far sparser and generalises
much less. The hybrid keeps the boundary signal while compressing it into a
single feature.

### What Q-Learning Optimizes

The agent tunes these CUBIC congestion control parameters:

| Parameter | Range | Effect |
|-----------|-------|--------|
| `loss_reduction_factor` | 0.3-0.7 | How much to reduce cwnd on packet loss |
| `cubic_c` | 0.2-0.4 | CUBIC growth aggressiveness |
| `minimum_window` | 2-4 | Minimum congestion window floor |
| `packet_threshold` | 3-4 | Packets before declaring loss |

Ranges come from `grid_search_code`. Only one parameter on one connection moves
per step, so each reward is attributable to a single change.

### Reward function

```
R = mean(U_video, U_file, U_conf)
    − stability penalty    (μ = 0.05, discourages needless churn)
    − starvation penalty   (0.2 per connection below 500 KB/s)
    − suffering penalty    (0.15 per connection with utility below 0.4)

U_video = 0.7 · U_latency + 0.3 · U_throughput
U_file  = 1.0 · U_throughput
U_conf  = 0.7 · U_jitter  + 0.3 · U_throughput
```

Fairness is enforced by **absolute floors rather than by penalising
inequality**. This is deliberate: file transfer is expected to take a larger
share, since throughput is its entire utility while the other two weight it at
only 30%. Penalising that imbalance directly would fight the intended priority.
What must be prevented is starvation, not inequality.

> Note: earlier documentation described a variance-based fairness term
> (`λ · std` of the three utilities). That term is not present in the current
> implementation; the threshold-based penalties above replaced it.

### Timing: why the agent acts every 2 seconds

The control loop runs every 100ms, but the agent throttles itself to act every
2 seconds. A congestion window does not respond instantly, so acting faster
would attribute the previous configuration's behaviour to the new one and
poison the learning signal. Each action is held with its "before" metrics and
completed only after a 1.5s settling window, at which point the "after" metrics
are attached.

### Q-Learning Output

Watch for agent decisions in the logs:
```
[QLAgent step=  10] state=(1, 2, 0, 1, 2, 1) action=file.cubic_c ↑
                    ε=0.285 lat=18.5ms tp=1.85Mbps jit=8.2ms avg_R=+0.542
```

The Q-table checkpoint is saved to `output/q_learning_checkpoint.json` and
persists across runs. This includes:
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

## Measurement Design

**Epoch-based metrics.** When parameters change mid-run, the congestion window
takes time to react. Metrics are grouped into *epochs* — periods of constant
configuration — separated by a settling delay during which nothing is sampled.
Without this, averaging would blend every configuration tried into one
meaningless number. See `3_conn_code/metrics/epoch.py`.

**Three throughput figures**, because each is misleading alone:

| Figure | Meaning |
|---|---|
| `throughput` | Bytes the application offered to the transport |
| `throughput_acked_delta` | Bytes confirmed delivered in this epoch |
| `throughput_cwnd` | cwnd/RTT — the transport's own ceiling |

Under a bottleneck these diverge sharply, since offered data can sit in buffers
or be dropped. The agents use the delta figure, as it responds to recent change.

**Receiver-side measurement.** The server records what actually arrived, which
under a bottleneck is very different from what was sent. Because the server sees
three anonymous QUIC connections, the pairing back to applications is
reconstructed heuristically from byte volumes and rank ordering
(`_match_server_to_client_connections`).

**Robust statistics.** Summaries use trimmed medians, so one startup transient
cannot dominate a reported figure. Fairness is Jain's index over per-connection
throughput.

### Known caveats

- **Packet loss is estimated, not observed.** aioquic exposes no loss counter,
  so loss is inferred from ssthresh reductions, cwnd drops and PTO counts with
  heuristic multipliers. Treat it as a relative indicator, not an exact count;
  the `tc` counters are authoritative where precision matters.
- **Latency is RTT/2**, assuming a symmetric path — untrue under `asymmetric`.
- **Flow-control windows are capped at 128KB**, down from the 1MB default. At
  30 Mbps the larger window produced ~1500ms RTTs dominated by self-inflicted
  bufferbloat, which masked the effect of the parameters under study.
- **Loopback does not shape.** Local macOS runs are for development, not
  measurement.

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
| `--ml-agent` | default | Agent to use: `default`, `andy` or `hybrid` |
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

Without real contention there is nothing to optimise — on an unconstrained
loopback link, file transfer reaches 100+ Mbps and no parameter change matters.
Either use Docker or pass `--bandwidth-cap`.

### Q-Learning Steps Seem Off / Steps Not Starting at Zero

**Symptom**: Q-learning step count starts at a high number (e.g., step=50)
instead of step=0, or steps don't match expected timing

**Cause**: The Q-learning agent persists its state (Q-table, step count,
epsilon) to a checkpoint file (`output/q_learning_checkpoint.json`). When you
run again, it continues from where it left off.

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

2. **Note about logging frequency**: The agent only logs every 10 steps to
   reduce spam. In a 30-second run (~15 steps), you'll only see 1-2 log lines.
   This is normal.

### Permission Errors in Docker

**Symptom**: tc commands fail with permission denied

**Solution**: Ensure `--privileged` flag or `cap_add: NET_ADMIN` in docker-compose.yml

---

## How It Works

### Data Flow

1. **Traffic Generation**: Each worker generates traffic matching its application type
2. **Network Constraint**: tc qdisc on server's eth0 limits bandwidth/adds delay/loss
3. **Metrics Collection**: Workers report throughput, latency, jitter every 0.1s
4. **Q-Learning Decision**: Agent observes metrics, picks parameter adjustment every 2s
5. **Parameter Update**: New parameters sent to workers via IPC
6. **CUBIC Adaptation**: aioquic adjusts congestion control with new parameters

### Where to look first

| To understand | Read |
|---|---|
| Why the architecture is multi-process | `3_conn_code/simulation/worker_process.py` |
| How the three connections are coordinated | `3_conn_code/simulation/process_orchestrator.py` |
| How parameter changes are attributed to outcomes | `3_conn_code/metrics/epoch.py` |
| The learning policy and reward design | `3_conn_code/ml_callbacks/q_learning_agent.py` |
| How the network constraint is applied | `wireless_bottleneck/bottleneck.py` |
| Cross-process bandwidth contention | `3_conn_code/simulation/token_bucket.py` |

Every source file carries a header describing what it does and which modules it
connects to.

---

## Additional Documentation

- [3_conn_code/README.md](3_conn_code/README.md) — simulation code documentation
- [grid_search_code/README.md](grid_search_code/README.md) — parameter sweep
- [research_code/README.md](research_code/README.md) — uniform-configuration experiments
- [wireless_bottleneck/README.md](wireless_bottleneck/README.md) — network emulation
- [final_reports_old/FULL_report.md](final_reports_old/FULL_report.md) — comprehensive technical documentation
- [final_reports_old/reward_functions.md](final_reports_old/reward_functions.md) — Q-learning reward function details
- [final_reports_old/WIRELESS_BOTTLENECK_GUIDE.md](final_reports_old/WIRELESS_BOTTLENECK_GUIDE.md) — network emulation guide
- [final_reports_may/](final_reports_may/) — most recent written findings
- [3_conn_code/final_reports_3conn/](3_conn_code/final_reports_3conn/) — Q-learning and measurement notes
- [grid_search_code/final_reports_grid/](grid_search_code/final_reports_grid/) — optimal parameter analysis

---

## Requirements

- Python 3.12+
- Docker and Docker Compose (for real network emulation)
- Linux kernel with tc support (handled by Docker)

### Python Dependencies

- aioquic >= 1.0.0
- fastapi >= 0.109.0
- uvicorn >= 0.27.0
