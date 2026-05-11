# Implementation Plan: QUIC 3-Connection System with Mid-Connection Parameter Control

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Requirements](#2-system-requirements)
3. [Architecture Overview](#3-architecture-overview)
4. [Network Conditions from wireless_bottleneck](#4-network-conditions-from-wireless_bottleneck)
5. [Multi-Process Architecture](#5-multi-process-architecture)
6. [IPC Design](#6-ipc-design)
7. [Synchronization and Timing](#7-synchronization-and-timing)
8. [Mid-Connection Parameter Updates](#8-mid-connection-parameter-updates)
9. [File Structure](#9-file-structure)
10. [Detailed Component Specifications](#10-detailed-component-specifications)
11. [Implementation Phases](#11-implementation-phases)
12. [Testing Strategy](#12-testing-strategy)
13. [CLI Commands](#13-cli-commands)
14. [Configuration Files](#14-configuration-files)
15. [Synthesizer Implementation](#15-synthesizer-implementation) *(Full code matching `/code` directory)*
16. [QUIC Client/Server Implementation](#16-quic-clientserver-implementation) *(Full code matching `/code` directory)*
17. [Metrics Implementation](#17-metrics-implementation) *(Full code matching `/code` directory)*
    - 17.5 [Epoch-Based Metrics Collection](#175-epoch-based-metrics-collection-parameter-change-handling) *(Settling time, JSON export)*
18. [Real-Time Browser UI Dashboard](#18-real-time-browser-ui-dashboard) *(FastAPI + WebSocket, Chart.js, parameter control)*

---

## 1. Executive Summary

This implementation plan describes a **standalone system** for running 3 concurrent QUIC connections, each representing a different application type, with the ability to modify congestion control parameters mid-connection.

**Key Features:**
- **3 Concurrent QUIC Connections** - Video streaming, file transfer, and conference call running simultaneously
- **Per-connection isolated parameters** - Achieved via multi-process architecture
- **Mid-connection parameter modification** - Dynamic tuning of CC parameters while connections are active
- **Shared network conditions** - All connections experience the same bandwidth/latency/loss from `wireless_bottleneck/`
- **ML controller integration** - Optional callback interface for dynamic parameter optimization
- **Real-time UI Dashboard** - Browser-based interface (FastAPI + WebSocket) showing buffer states, live metrics, and manual parameter control

### Key Challenge Addressed

The aioquic library stores congestion control parameters as **module-level globals**. These are the 6 dynamic parameters you will tune:

```python
# aioquic/quic/congestion/cubic.py
K_CUBIC_LOSS_REDUCTION_FACTOR = 0.7  # cwnd reduction on packet loss (beta)
K_CUBIC_C = 0.4                       # CUBIC growth aggressiveness
K_MINIMUM_WINDOW = 2                  # Minimum cwnd floor (packets)
K_CUBIC_MAX_IDLE_TIME = 2.0           # Idle timeout before cwnd reset (seconds)

# aioquic/quic/recovery.py
K_PACKET_THRESHOLD = 3                # Packets before declaring loss
K_TIME_THRESHOLD = 1.125              # RTT multiplier for loss timeout
```

**Problem:** In a single process, changing these values affects ALL connections simultaneously. You cannot have different parameter values for different connections.

**Solution:** Multi-process architecture where each connection runs in a separate Python process with its own aioquic module instance, enabling true per-connection parameter isolation.

### Target Directory

This implementation will be built **from scratch** in a new directory:

```
QUIC_3conn_implementation/
└── 3_conn_code/          ← NEW standalone implementation
    ├── main.py
    ├── config/
    ├── simulation/
    ├── synthesizers/
    ├── metrics/
    └── ...
```

---

## 2. System Requirements

### 2.1 Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | Run 3 concurrent QUIC connections simultaneously | High |
| FR-2 | Each connection has isolated CC parameters | High |
| FR-3 | Modify dynamic parameters mid-connection | High |
| FR-4 | All connections share same network conditions from `wireless_bottleneck/` | High |
| FR-5 | Collect 6 metrics per connection (throughput, RTT, latency, jitter, packet loss, connection time) | High |
| FR-6 | Export results to JSON for analysis | High |
| FR-7 | ML callback interface for dynamic parameter control | Medium |
| FR-8 | Synchronized connection start for fair competition | Medium |
| FR-9 | Track parameter change history per connection | Medium |
| FR-10 | Real-time UI showing buffer state for each connection | High |
| FR-11 | Manual parameter modification for any connection via UI | High |
| FR-12 | Live metrics visualization in UI | Medium |

### 2.2 Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-1 | Metrics collection interval | 100ms |
| NFR-2 | Parameter update latency | < 10ms |
| NFR-3 | Memory per worker process | < 100MB |
| NFR-4 | Simulation duration range | 1-300 seconds |

### 2.3 Supported Parameters

#### Start-Only Parameters (CONSTANT across all connections)

These parameters are set **once before the simulation starts** and use the **same value for all 3 connections**. They cannot be changed mid-connection and cannot differ between connections.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `initial_cw` | int | 12000 | Initial congestion window (bytes) - same for all connections |
| `max_ack_delay` | float | 0.025 | Maximum ACK delay (seconds) - same for all connections |
| `max_data` | int | 1048576 | Max connection data (bytes) - same for all connections |
| `max_stream_data` | int | 1048576 | Max stream data (bytes) - same for all connections |

**Rationale:** These parameters establish identical initial conditions for all connections, ensuring fair comparison. The research focus is on how **dynamic parameters** (which CAN differ per-connection) affect performance when starting from identical baselines.

#### Dynamic Parameters (changeable mid-connection, per-connection isolated)

| Parameter | aioquic Constant | Default | Description |
|-----------|------------------|---------|-------------|
| `loss_reduction_factor` | `K_CUBIC_LOSS_REDUCTION_FACTOR` | 0.7 | cwnd reduction on loss (beta) |
| `cubic_c` | `K_CUBIC_C` | 0.4 | CUBIC growth aggressiveness |
| `minimum_window` | `K_MINIMUM_WINDOW` | 2 | Minimum cwnd floor (packets) |
| `packet_threshold` | `K_PACKET_THRESHOLD` | 3 | Packets before declaring loss |
| `time_threshold` | `K_TIME_THRESHOLD` | 1.125 | RTT multiplier for loss delay |
| `cubic_max_idle_time` | `K_CUBIC_MAX_IDLE_TIME` | 2.0 | Idle timeout before cwnd reset |

---

## 3. Architecture Overview

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              3_conn_code/main.py                                 │
│                                                                                  │
│                        Commands: run, status, analyze                            │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            ProcessOrchestrator                                   │
│                                                                                  │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                           Main Process                                   │   │
│   │                                                                          │   │
│   │   • QuicServer (handles all 3 client connections)                        │   │
│   │   • IPC Manager (pipes + queue)                                          │   │
│   │   • Barrier (synchronized start)                                         │   │
│   │   • MLController (optional, for dynamic parameter optimization)          │   │
│   │   • Result Collector                                                     │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                         │                                        │
│            ┌────────────────────────────┼────────────────────────────┐          │
│            │                            │                            │          │
│            ▼                            ▼                            ▼          │
│   ┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐   │
│   │ Worker Process 1│         │ Worker Process 2│         │ Worker Process 3│   │
│   │     (Video)     │         │     (File)      │         │  (Conference)   │   │
│   │                 │         │                 │         │                 │   │
│   │ aioquic globals │         │ aioquic globals │         │ aioquic globals │   │
│   │ ISOLATED        │         │ ISOLATED        │         │ ISOLATED        │   │
│   │                 │         │                 │         │                 │   │
│   │ • QuicClient    │         │ • QuicClient    │         │ • QuicClient    │   │
│   │ • Synthesizer   │         │ • Synthesizer   │         │ • Synthesizer   │   │
│   │ • Metrics       │         │ • Metrics       │         │ • Metrics       │   │
│   └────────┬────────┘         └────────┬────────┘         └────────┬────────┘   │
│            │                           │                           │            │
│            └───────────────────────────┼───────────────────────────┘            │
│                                        │                                        │
│                                        ▼                                        │
│                        ┌───────────────────────────────┐                        │
│                        │     Network Bottleneck        │                        │
│                        │   (tc/netem from             │                        │
│                        │    wireless_bottleneck/)      │                        │
│                        └───────────────────────────────┘                        │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Data Flow Overview

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                           COMPLETE DATA FLOW                                    │
└────────────────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────────────┐
                    │            User CLI Command              │
                    │                                          │
                    │  $ ./wireless_bottleneck/apply.sh        │
                    │  $ uv run main.py run --duration 30      │
                    └────────────────────┬────────────────────┘
                                         │
                                         ▼
                    ┌─────────────────────────────────────────┐
                    │       1. Load MultiConnectionConfig      │
                    │          (shared + per-connection)       │
                    └────────────────────┬────────────────────┘
                                         │
                                         ▼
                    ┌─────────────────────────────────────────┐
                    │       2. Start QuicServer in main       │
                    │          process (port 4433)            │
                    └────────────────────┬────────────────────┘
                                         │
                                         ▼
                    ┌─────────────────────────────────────────┐
                    │       3. Spawn 3 worker processes       │
                    │          (each with isolated aioquic)   │
                    └────────────────────┬────────────────────┘
                                         │
                                         ▼
                    ┌─────────────────────────────────────────┐
                    │       4. Barrier - synchronized start   │
                    │          (all workers + main wait)      │
                    └────────────────────┬────────────────────┘
                                         │
                                         ▼
                    ┌─────────────────────────────────────────┐
                    │       5. Control Loop (100ms interval)  │
                    │                                         │
                    │   ┌─────────────────────────────────┐   │
                    │   │ Collect metrics from workers    │   │
                    │   │ (via shared Queue)              │   │
                    │   └───────────────┬─────────────────┘   │
                    │                   │                     │
                    │   ┌───────────────▼─────────────────┐   │
                    │   │ ML callback decision            │   │
                    │   │ (optional)                      │   │
                    │   └───────────────┬─────────────────┘   │
                    │                   │                     │
                    │   ┌───────────────▼─────────────────┐   │
                    │   │ Send parameter updates          │   │
                    │   │ (via per-worker Pipes)          │   │
                    │   └─────────────────────────────────┘   │
                    │                                         │
                    └────────────────────┬────────────────────┘
                                         │
                                         ▼
                    ┌─────────────────────────────────────────┐
                    │       6. Collect final results          │
                    │          (join workers, build report)   │
                    └────────────────────┬────────────────────┘
                                         │
                                         ▼
                    ┌─────────────────────────────────────────┐
                    │       7. Export results                 │
                    │                                         │
                    │   output/                               │
                    │   ├── result.json                       │
                    │   └── metrics_history.json              │
                    └─────────────────────────────────────────┘
```

---

## 4. Network Conditions from wireless_bottleneck

Network conditions are applied from the `wireless_bottleneck/` folder using Linux Traffic Control (`tc`) and `netem`. This creates a realistic shared bottleneck that all 3 connections must compete for.

### 4.1 How the Bottleneck Works

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      TRAFFIC CONTROL STACK                                       │
└─────────────────────────────────────────────────────────────────────────────────┘

  3 QUIC Connections (Video, File, Conference)
          │
          │  All traffic on loopback interface (lo)
          ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│   Queue Discipline (qdisc) - FIFO/RED/CoDel/PIE                                  │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │  Packets → [ Queue (50-200 packets) ] → or DROPPED if full              │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                      │                                           │
│   netem (Network Emulator)           │                                           │
│   ┌──────────────────────────────────▼──────────────────────────────────────┐   │
│   │  • Adds DELAY (e.g., 15ms → 30ms RTT)                                   │   │
│   │  • Adds LOSS (e.g., 2% random)                                          │   │
│   │  • Adds JITTER (e.g., ±5ms)                                             │   │
│   └──────────────────────────────────┬──────────────────────────────────────┘   │
│                                      │                                           │
│   TBF (Token Bucket Filter)          │                                           │
│   ┌──────────────────────────────────▼──────────────────────────────────────┐   │
│   │  • Enforces BANDWIDTH (e.g., 5 Mbps shared by all 3 connections)        │   │
│   └──────────────────────────────────┬──────────────────────────────────────┘   │
│                                      │                                           │
└──────────────────────────────────────┼───────────────────────────────────────────┘
                                       ▼
                              Packets delivered
```

**Why Bottleneck Is Required:**

| Without Bottleneck (localhost) | With Bottleneck |
|-------------------------------|-----------------|
| Bandwidth: ~unlimited | Bandwidth: 5-50 Mbps (shared) |
| Latency: ~0.1ms | Latency: 10-100ms |
| Loss: 0% | Loss: 0.1-5% |
| **All CC params perform identically** | **CC params make real difference** |

### 4.2 Docker Requirement (macOS/Windows)

`tc` is Linux-only. On macOS/Windows, use Docker:

```bash
# Build the container
docker build -t quic-3conn -f 3_conn/Dockerfile .

# Run with browser UI (open http://localhost:8000)
docker run -it --privileged -p 8000:8000 --rm quic-3conn

# Run with specific scenario and UI
docker run -it --privileged -p 8000:8000 --rm quic-3conn \
    python -m main run --ui --scenario congested_low --duration 30

# Run headless (no UI)
docker run -it --privileged --rm quic-3conn \
    python -m main run --scenario congested_low --duration 30

# Validate tc setup
docker run --privileged --rm quic-3conn \
    python -m wireless_bottleneck.cli validate
```

**IMPORTANT:**
- The `--privileged` flag is REQUIRED for `tc` commands to work.
- The `-p 8000:8000` flag is needed to access the browser UI from your host machine.

### 4.3 Using docker-compose

```bash
# Run with browser UI (open http://localhost:8000)
docker-compose up quic-3conn-ui

# Run headless (no UI, just collect metrics)
docker-compose up quic-3conn-headless

# Run specific scenario with UI
SCENARIO=lossy DURATION=60 docker-compose up quic-3conn-ui

# Validate setup
docker-compose run --rm validate

# List available scenarios
docker-compose run --rm list-scenarios
```

**Note:** The `quic-3conn-ui` service automatically maps port 8000 for browser access.

### 4.4 Predefined Scenarios

| Scenario | Capacity | RTT | Loss | Queue | Use Case |
|----------|----------|-----|------|-------|----------|
| `stable_high` | 100 Mbps | 10ms | 0.1% | 200 (FIFO) | Baseline testing |
| `congested_low` | 5 Mbps | 30ms | 2% | 50 (RED) | **Recommended for testing CC** |
| `varying` | 20 Mbps ±40% | 20ms | 1% | 100 (CoDel) | Mobility/fading simulation |
| `lossy` | 10 Mbps | 40ms | 5% | 75 (FIFO) | Loss recovery testing |
| `asymmetric` | 50/10 Mbps | 25ms | 0.5% | 150 (FIFO) | Mobile/cellular simulation |

### 4.5 Network Condition Parameters

| Parameter | Description | Example Values |
|-----------|-------------|----------------|
| `bandwidth` | Maximum throughput (shared bottleneck) | 5-50 Mbps |
| `latency` | Base one-way delay | 5-150 ms |
| `jitter` | Delay variation | ±5-30 ms |
| `loss_rate` | Random packet loss | 0.1-5% |

### 4.6 Python API Integration

The `ProcessOrchestrator` integrates with the wireless bottleneck using a context manager:

```python
# In simulation/process_orchestrator.py

from wireless_bottleneck import WirelessBottleneck, get_scenario

class ProcessOrchestrator:
    async def run(self, duration: float, scenario_name: str = "congested_low"):
        """Run with wireless bottleneck applied."""

        # Get the scenario configuration
        scenario = get_scenario(scenario_name)

        # Apply bottleneck for entire simulation
        with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
            # All QUIC traffic now goes through the bottleneck

            await self.setup()
            self._spawn_workers(duration)

            for process in self.workers.values():
                process.start()

            self.start_barrier.wait()

            # Run control loop (ML or simple metrics collection)
            if self.ml_controller:
                await self.ml_controller.run_control_loop(duration)
            else:
                await self._collect_metrics_loop(duration)

            # Collect results
            self._collect_final_results()

            # Get bottleneck metrics
            bottleneck_metrics = bottleneck.get_metrics()

            return self._build_results(bottleneck_metrics)
```

### 4.7 Execution Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    EXECUTION WITH NETWORK CONDITIONS                             │
└─────────────────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────────────┐
                    │   $ docker run --privileged quic-3conn   │
                    │       run --scenario congested_low       │
                    └────────────────────┬────────────────────┘
                                         │
                                         ▼
Step 1: Apply bottleneck (automatic via Python context manager)
        ┌─────────────────────────────────────────────────────────────────────┐
        │   tc qdisc add dev lo root handle 1: tbf rate 5mbit ...            │
        │   tc qdisc add dev lo parent 1:1 netem delay 15ms loss 2%          │
        └─────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
Step 2: Run 3-connection simulation
        ┌─────────────────────────────────────────────────────────────────────┐
        │   All 3 connections compete for the 5 Mbps bottleneck              │
        │   Video, File Transfer, and Conference share bandwidth             │
        │   ML controller can adjust dynamic params based on metrics         │
        └─────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
Step 3: Remove bottleneck (automatic when context manager exits)
        ┌─────────────────────────────────────────────────────────────────────┐
        │   tc qdisc del dev lo root                                          │
        └─────────────────────────────────────────────────────────────────────┘
```

### 4.8 Why Network Conditions Are Required

Dynamic parameters only have meaningful effects when there is **congestion**:

| Parameter | When It's Triggered | Without Network Conditions |
|-----------|---------------------|---------------------------|
| `loss_reduction_factor` | On packet loss | No loss → never triggered |
| `cubic_c` | During cwnd regrowth after loss | No loss → never triggered |
| `minimum_window` | When cwnd drops to floor | cwnd never drops |
| `packet_threshold` | For loss detection | No reordering → never triggered |

**Result:** Without network conditions, all parameter combinations perform identically.

---

## 5. Multi-Process Architecture

### 5.1 Why Multi-Process?

The aioquic library uses **module-level globals** for congestion control parameters:

```python
# In aioquic/quic/congestion/cubic.py
K_CUBIC_LOSS_REDUCTION_FACTOR = 0.7  # Shared by ALL connections in same process
K_CUBIC_C = 0.4                       # Shared by ALL connections in same process
```

**Problem:** In a single process, changing these values affects ALL connections simultaneously.

**Solution:** Run each connection in a **separate Python process**. Each process has its own copy of the aioquic module, enabling true parameter isolation.

### 5.2 Process Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        MULTI-PROCESS ARCHITECTURE                                │
└─────────────────────────────────────────────────────────────────────────────────┘

                              ┌────────────────────────────┐
                              │        Main Process        │
                              │                            │
                              │  ┌──────────────────────┐  │
                              │  │  ProcessOrchestrator │  │
                              │  │                      │  │
                              │  │  • QuicServer        │  │
                              │  │  • IPC Manager       │  │
                              │  │  • Barrier           │  │
                              │  │  • Result Collector  │  │
                              │  └──────────┬───────────┘  │
                              │             │              │
                              │  ┌──────────▼───────────┐  │
                              │  │    MLController      │  │
                              │  │    (optional)        │  │
                              │  │                      │  │
                              │  │  • Collect metrics   │  │
                              │  │  • Run ML callback   │  │
                              │  │  • Send param updates│  │
                              │  └──────────────────────┘  │
                              └────────────┬───────────────┘
                                           │
            ┌──────────────────────────────┼──────────────────────────────┐
            │                              │                              │
            ▼                              ▼                              ▼
┌───────────────────────┐    ┌───────────────────────┐    ┌───────────────────────┐
│    Worker Process 1   │    │    Worker Process 2   │    │    Worker Process 3   │
│      (Video)          │    │      (File)           │    │    (Conference)       │
│                       │    │                       │    │                       │
│ ┌───────────────────┐ │    │ ┌───────────────────┐ │    │ ┌───────────────────┐ │
│ │ConnectionWorker   │ │    │ │ConnectionWorker   │ │    │ │ConnectionWorker   │ │
│ │                   │ │    │ │                   │ │    │ │                   │ │
│ │ aioquic globals:  │ │    │ │ aioquic globals:  │ │    │ │ aioquic globals:  │ │
│ │ • LRF = 0.6       │ │    │ │ • LRF = 0.7       │ │    │ │ • LRF = 0.5       │ │
│ │ • CUBIC_C = 0.4   │ │    │ │ • CUBIC_C = 0.5   │ │    │ │ • CUBIC_C = 0.3   │ │
│ │ • MIN_WIN = 4     │ │    │ │ • MIN_WIN = 2     │ │    │ │ • MIN_WIN = 6     │ │
│ │                   │ │    │ │                   │ │    │ │                   │ │
│ │ QuicClient        │ │    │ │ QuicClient        │ │    │ │ QuicClient        │ │
│ │ Synthesizer       │ │    │ │ Synthesizer       │ │    │ │ Synthesizer       │ │
│ │ MetricsCollector  │ │    │ │ MetricsCollector  │ │    │ │ MetricsCollector  │ │
│ └───────────────────┘ │    │ └───────────────────┘ │    │ └───────────────────┘ │
│                       │    │                       │    │                       │
│   ◄───── Pipe ─────►  │    │   ◄───── Pipe ─────►  │    │   ◄───── Pipe ─────►  │
│                       │    │                       │    │                       │
└───────────┬───────────┘    └───────────┬───────────┘    └───────────┬───────────┘
            │                            │                            │
            │                            │                            │
            └────────────────────────────┼────────────────────────────┘
                                         │
                                         ▼
                              ┌────────────────────────┐
                              │      QuicServer        │
                              │     localhost:4433     │
                              │                        │
                              │  Handles all 3 clients │
                              │  (runs in main process)│
                              └────────────────────────┘
```

---

## 6. IPC Design

### 6.1 Communication Channels

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        INTER-PROCESS COMMUNICATION                               │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Main Process                                        │
│                                                                                  │
│   ┌────────────────────────────────────────────────────────────────────────┐    │
│   │                           IPC Manager                                   │    │
│   │                                                                         │    │
│   │   command_pipes: Dict[int, Connection]  # Send commands TO workers      │    │
│   │   metrics_queue: Queue                   # Receive metrics FROM workers │    │
│   │   start_barrier: Barrier                 # Synchronized start           │    │
│   │                                                                         │    │
│   └────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│        ┌─────────────┐         ┌─────────────┐         ┌─────────────┐         │
│        │   Pipe 1    │         │   Pipe 2    │         │   Pipe 3    │         │
│        │ (commands)  │         │ (commands)  │         │ (commands)  │         │
│        │      ▼      │         │      ▼      │         │      ▼      │         │
│        └──────┼──────┘         └──────┼──────┘         └──────┼──────┘         │
│               │                       │                       │                 │
└───────────────┼───────────────────────┼───────────────────────┼─────────────────┘
                │                       │                       │
                ▼                       ▼                       ▼
┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────┐
│   Worker 1 (Video)    │ │   Worker 2 (File)     │ │ Worker 3 (Conference) │
│                       │ │                       │ │                       │
│  Receives: Commands   │ │  Receives: Commands   │ │  Receives: Commands   │
│  • UPDATE_PARAM       │ │  • UPDATE_PARAM       │ │  • UPDATE_PARAM       │
│  • STOP               │ │  • STOP               │ │  • STOP               │
│                       │ │                       │ │                       │
│  Sends: (to Queue)    │ │  Sends: (to Queue)    │ │  Sends: (to Queue)    │
│  • METRICS            │ │  • METRICS            │ │  • METRICS            │
│  • FINISHED           │ │  • FINISHED           │ │  • FINISHED           │
│  • ERROR              │ │  • ERROR              │ │  • ERROR              │
└───────────────────────┘ └───────────────────────┘ └───────────────────────┘
                │                       │                       │
                └───────────────────────┼───────────────────────┘
                                        │
                                        ▼
                          ┌─────────────────────────────┐
                          │       Shared Queue          │
                          │     (metrics/status)        │
                          │                             │
                          │  All workers send to same   │
                          │  queue, main process reads  │
                          └─────────────────────────────┘
```

### 6.2 Message Protocol

```python
# simulation/ipc_messages.py

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict

class MessageType(Enum):
    # Commands (Main → Worker)
    START = "start"
    STOP = "stop"
    UPDATE_PARAM = "update_param"
    UPDATE_MULTIPLE_PARAMS = "update_multiple_params"
    GET_METRICS = "get_metrics"
    GET_BUFFER_STATE = "get_buffer_state"      # Request current buffer state

    # Responses (Worker → Main)
    METRICS = "metrics"
    STATUS = "status"
    ACK = "ack"
    ERROR = "error"
    FINISHED = "finished"
    BUFFER_STATE = "buffer_state"              # Current buffer state report

@dataclass
class IPCMessage:
    """Standard message format for IPC."""
    msg_type: MessageType
    connection_id: int  # 1, 2, or 3
    timestamp: float
    payload: Dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "msg_type": self.msg_type.value,
            "connection_id": self.connection_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IPCMessage":
        return cls(
            msg_type=MessageType(data["msg_type"]),
            connection_id=data["connection_id"],
            timestamp=data["timestamp"],
            payload=data["payload"],
        )
```

### 6.3 Message Types

| Message | Direction | Purpose |
|---------|-----------|---------|
| `UPDATE_PARAM` | Main → Worker | Update single dynamic parameter |
| `UPDATE_MULTIPLE_PARAMS` | Main → Worker | Update multiple parameters at once |
| `STOP` | Main → Worker | Signal worker to stop and report final results |
| `GET_BUFFER_STATE` | Main → Worker | Request current buffer state |
| `METRICS` | Worker → Main | Periodic metrics report (every 100ms) |
| `BUFFER_STATE` | Worker → Main | Current send buffer state (queued packets, bytes) |
| `FINISHED` | Worker → Main | Final results with param history |
| `ERROR` | Worker → Main | Error notification |
| `ACK` | Worker → Main | Acknowledgment of command receipt |

---

## 7. Synchronization and Timing

### 7.1 Synchronization Timeline

```
Time    Main Process           Worker 1            Worker 2            Worker 3
─────┬─────────────────────┬──────────────────┬──────────────────┬──────────────────
  0  │ Start QuicServer    │                  │                  │
     │ Create Barrier(4)   │                  │                  │
     │ Spawn workers       │ Start            │ Start            │ Start
     │                     │ Apply params     │ Apply params     │ Apply params
     │                     │ Wait at barrier  │ Wait at barrier  │ Wait at barrier
     │ Wait at barrier     │         ▼        │         ▼        │         ▼
─────┤ ═══════════════════════ BARRIER RELEASE ══════════════════════════════════
  T  │ Start ML loop       │ Connect          │ Connect          │ Connect
     │                     │ Open streams     │ Open streams     │ Open streams
     │                     │ Start sending    │ Start sending    │ Start sending
     │                     │                  │                  │
     │ Collect metrics ◄───│ Report metrics ──┼──────────────────┼──────────────►
     │ ML decision         │ Check commands   │ Check commands   │ Check commands
     │ Send param update ─►│ Apply param      │                  │
     │                     │                  │                  │
     │ ... (100ms loop)    │ ... (continue)   │ ... (continue)   │ ... (continue)
     │                     │                  │                  │
─────┤
 T+D │ Send STOP ─────────►│ Stop sending     │ Stop sending     │ Stop sending
     │ Collect results ◄───│ Send FINISHED ───┼──────────────────┼──────────────►
     │ Join workers        │ Exit             │ Exit             │ Exit
     │ Build results       │                  │                  │
─────┴─────────────────────┴──────────────────┴──────────────────┴──────────────────
```

### 7.2 Barrier Purpose

The `Barrier(4)` ensures all 3 workers and the main process start at the **exact same time**:

1. **Workers spawn** and apply their initial parameters
2. **Each worker waits** at the barrier
3. **Main process waits** at the barrier
4. **All release simultaneously** when all 4 parties reach the barrier
5. **Fair competition** - no connection gets a head start

---

## 8. Mid-Connection Parameter Updates

### 8.1 Update Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     MID-CONNECTION PARAMETER UPDATE FLOW                         │
└─────────────────────────────────────────────────────────────────────────────────┘

Step 1: ML Controller receives metrics from all workers
        ┌─────────────────────────────────────────────────────────────────────────┐
        │   metrics = {                                                           │
        │       1: {"throughput": 5000000, "rtt": 0.052, "jitter": 0.008, ...},  │
        │       2: {"throughput": 8000000, "rtt": 0.065, "jitter": 0.012, ...},  │
        │       3: {"throughput": 1500000, "rtt": 0.048, "jitter": 0.020, ...},  │
        │   }                                                                     │
        └─────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
Step 2: ML callback makes decision
        ┌─────────────────────────────────────────────────────────────────────────┐
        │   def ml_callback(metrics):                                             │
        │       # Conference call (conn 3) has high jitter                        │
        │       # Decision: Reduce file transfer aggressiveness                   │
        │       return {                                                          │
        │           2: {"loss_reduction_factor": 0.8},  # More conservative       │
        │           3: {"loss_reduction_factor": 0.4},  # More aggressive         │
        │       }                                                                 │
        └─────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
Step 3: Send parameter update via Pipe
        ┌─────────────────────────────────────────────────────────────────────────┐
        │   msg = IPCMessage(                                                     │
        │       msg_type=MessageType.UPDATE_PARAM,                                │
        │       connection_id=2,                                                  │
        │       payload={"param_name": "loss_reduction_factor", "value": 0.8},   │
        │   )                                                                     │
        │   self.command_pipes[2].send(msg.to_dict())                            │
        └─────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
Step 4: Worker receives and applies parameter
        ┌─────────────────────────────────────────────────────────────────────────┐
        │   # In worker process (isolated aioquic module)                         │
        │   aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = 0.8                     │
        │                                                                         │
        │   # Track change in history                                             │
        │   param_history.append({                                                │
        │       "timestamp": time.time(),                                         │
        │       "param_name": "loss_reduction_factor",                            │
        │       "old_value": 0.7,                                                 │
        │       "new_value": 0.8,                                                 │
        │   })                                                                    │
        └─────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
Step 5: Effect on next congestion event
        ┌─────────────────────────────────────────────────────────────────────────┐
        │   # When next packet loss occurs in connection 2:                       │
        │   new_cwnd = cwnd * K_CUBIC_LOSS_REDUCTION_FACTOR  # Now uses 0.8      │
        │                                                                         │
        │   # Connection 2 reduces cwnd LESS aggressively                         │
        │   # This frees up bandwidth for connection 3 (conference)               │
        └─────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Parameter Update Validation

Only **dynamic parameters** can be updated mid-connection:

```python
DYNAMIC_PARAMETERS = [
    "loss_reduction_factor",
    "cubic_c",
    "minimum_window",
    "packet_threshold",
    "time_threshold",
    "cubic_max_idle_time",
]

def _update_parameter(self, param_name: str, value):
    if param_name not in DYNAMIC_PARAMETERS:
        self._send_error(f"Parameter '{param_name}' cannot be changed mid-connection")
        return
    # ... apply update
```

---

## 9. File Structure

### 9.1 Complete Directory Structure

```
QUIC_3conn_implementation/
└── 3_conn_code/                         # NEW standalone implementation
    │
    ├── main.py                          # CLI entry point
    ├── pyproject.toml                   # Dependencies (aioquic, fastapi, uvicorn, etc.)
    │
    ├── config/
    │   ├── __init__.py
    │   ├── settings.py                  # Global settings (host, port, paths)
    │   ├── connection_config.py         # Per-connection configuration
    │   └── multi_connection_config.py   # 3-connection configuration
    │
    ├── simulation/
    │   ├── __init__.py
    │   ├── server.py                    # QUIC server (runs in main process)
    │   ├── client.py                    # QUIC client protocol
    │   ├── worker_process.py            # ConnectionWorker class
    │   ├── process_orchestrator.py      # ProcessOrchestrator class
    │   ├── ipc_messages.py              # IPC message definitions
    │   ├── ml_controller.py             # ML controller for main process
    │   ├── buffer_manager.py            # Send buffer management for UI
    │   └── result.py                    # Result data structures
    │
    ├── synthesizers/
    │   ├── __init__.py
    │   ├── base.py                      # Abstract base synthesizer
    │   ├── video_streaming.py           # Video stream data generator
    │   ├── file_transfer.py             # File transfer data generator
    │   └── conference_call.py           # Conference call data generator
    │
    ├── metrics/
    │   ├── __init__.py
    │   ├── collector.py                 # Real-time metrics collection
    │   ├── calculator.py                # Metrics computation
    │   ├── epoch.py                     # Epoch data structures
    │   ├── epoch_manager.py             # Epoch-based collection with settling
    │   └── exporter.py                  # JSON export functionality
    │
    ├── web/                             # Browser-based UI Dashboard
    │   ├── __init__.py
    │   ├── server.py                    # FastAPI server with WebSocket
    │   └── static/
    │       ├── index.html               # Dashboard HTML
    │       ├── dashboard.js             # JavaScript with Chart.js
    │       └── styles.css               # CSS styles
    │
    ├── ml_callbacks/
    │   ├── __init__.py
    │   ├── fairness_optimizer.py        # Fairness-based parameter adjustment
    │   └── protect_conference.py        # Conference call protection callback
    │
    ├── certs/
    │   ├── cert.pem                     # TLS certificate
    │   └── key.pem                      # TLS private key
    │
    ├── wireless_bottleneck/             # Network condition simulation
    │   ├── apply_conditions.sh
    │   ├── remove_conditions.sh
    │   ├── profiles/
    │   │   ├── lte_good.json
    │   │   ├── lte_poor.json
    │   │   ├── wifi_congested.json
    │   │   └── wifi_good.json
    │   └── README.md
    │
    ├── tests/
    │   ├── __init__.py
    │   ├── test_config.py
    │   ├── test_ipc.py
    │   ├── test_parameter_isolation.py
    │   ├── test_web_ui.py               # Web UI and API tests
    │   └── test_integration.py
    │
    └── output/                          # Results output
        ├── result.json                  # Final summary
        ├── metrics_history.json         # Time-series metrics
        ├── conn_1_epochs.json           # Epoch history for connection 1
        ├── conn_2_epochs.json           # Epoch history for connection 2
        └── conn_3_epochs.json           # Epoch history for connection 3
```

### 9.2 File Descriptions

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point with `run`, `status` commands |
| `config/connection_config.py` | `ConnectionConfig` dataclass with start-only and dynamic params |
| `config/multi_connection_config.py` | `MultiConnectionConfig` with shared params |
| `simulation/worker_process.py` | `ConnectionWorker` class that runs in isolated process |
| `simulation/process_orchestrator.py` | `ProcessOrchestrator` that manages all workers |
| `simulation/ipc_messages.py` | `MessageType` enum and `IPCMessage` dataclass |
| `simulation/ml_controller.py` | `MLController` for running ML callbacks |
| `simulation/result.py` | `MultiConnectionResult`, `ConnectionResult` dataclasses |
| `synthesizers/*.py` | Application-specific data generators |
| `metrics/collector.py` | `MetricsCollector` for real-time data collection |

---

## 10. Detailed Component Specifications

### 10.1 ConnectionConfig

```python
# config/connection_config.py

from dataclasses import dataclass
from typing import Dict, Any, List

# Parameters that can be changed mid-connection (per-connection isolated)
DYNAMIC_PARAMETERS = [
    "loss_reduction_factor",
    "cubic_c",
    "minimum_window",
    "packet_threshold",
    "time_threshold",
    "cubic_max_idle_time",
]

# Parameters that are CONSTANT across all connections (set once before simulation)
START_ONLY_PARAMETERS = [
    "initial_cw",
    "max_ack_delay",
    "max_data",
    "max_stream_data",
]

@dataclass
class ConnectionConfig:
    """
    Configuration for a single QUIC connection.

    Start-only parameters use the SAME value for all 3 connections.
    Only dynamic parameters can differ between connections and be changed mid-connection.
    """

    # Connection identity
    connection_id: int
    application_type: str  # "video_streaming", "file_transfer", "conference_call"

    # Start-only parameters - CONSTANT across all connections
    initial_cw: int = 12000
    max_ack_delay: float = 0.025
    max_data: int = 1_048_576
    max_stream_data: int = 1_048_576
    max_datagram_size: int = 1200

    # Dynamic parameters (changeable mid-connection, per-connection isolated)
    loss_reduction_factor: float = 0.7
    cubic_c: float = 0.4
    minimum_window: int = 2
    packet_threshold: int = 3
    time_threshold: float = 1.125
    cubic_max_idle_time: float = 2.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for IPC serialization."""
        return {
            "connection_id": self.connection_id,
            "application_type": self.application_type,
            "initial_cw": self.initial_cw,
            "max_ack_delay": self.max_ack_delay,
            "max_data": self.max_data,
            "max_stream_data": self.max_stream_data,
            "max_datagram_size": self.max_datagram_size,
            "loss_reduction_factor": self.loss_reduction_factor,
            "cubic_c": self.cubic_c,
            "minimum_window": self.minimum_window,
            "packet_threshold": self.packet_threshold,
            "time_threshold": self.time_threshold,
            "cubic_max_idle_time": self.cubic_max_idle_time,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConnectionConfig":
        """Create from dictionary."""
        return cls(**data)
```

### 10.2 MultiConnectionConfig

```python
# config/multi_connection_config.py

from dataclasses import dataclass
from typing import List
from .connection_config import ConnectionConfig

@dataclass
class MultiConnectionConfig:
    """
    Configuration for 3 concurrent QUIC connections.

    IMPORTANT: Start-only parameters are SHARED across all connections.
    Only dynamic parameters can differ between connections.
    """

    # Server settings
    server_host: str = "localhost"
    server_port: int = 4433

    # Simulation settings
    simulation_duration: float = 30.0
    metrics_interval: float = 0.1  # 100ms

    # ═══════════════════════════════════════════════════════════════════════════
    # SHARED START-ONLY PARAMETERS (CONSTANT for all 3 connections)
    # ═══════════════════════════════════════════════════════════════════════════
    shared_initial_cw: int = 12000
    shared_max_ack_delay: float = 0.025
    shared_max_data: int = 1_048_576
    shared_max_stream_data: int = 1_048_576

    # Per-connection configs (only dynamic parameters differ)
    video_config: ConnectionConfig = None
    file_config: ConnectionConfig = None
    conference_config: ConnectionConfig = None

    def __post_init__(self):
        """Initialize connection configs with shared start-only parameters."""
        if self.video_config is None:
            self.video_config = ConnectionConfig(
                connection_id=1,
                application_type="video_streaming",
                loss_reduction_factor=0.6,
                cubic_c=0.4,
                minimum_window=4,
            )
        if self.file_config is None:
            self.file_config = ConnectionConfig(
                connection_id=2,
                application_type="file_transfer",
                loss_reduction_factor=0.7,
                cubic_c=0.5,
                minimum_window=2,
            )
        if self.conference_config is None:
            self.conference_config = ConnectionConfig(
                connection_id=3,
                application_type="conference_call",
                loss_reduction_factor=0.5,
                cubic_c=0.3,
                minimum_window=6,
                packet_threshold=2,
                time_threshold=1.0,
            )

        # Apply shared start-only parameters to all configs
        self._apply_shared_start_params()

    def _apply_shared_start_params(self):
        """Apply shared start-only parameters to all connection configs."""
        for config in self.get_all_configs():
            config.initial_cw = self.shared_initial_cw
            config.max_ack_delay = self.shared_max_ack_delay
            config.max_data = self.shared_max_data
            config.max_stream_data = self.shared_max_stream_data

    def get_all_configs(self) -> List[ConnectionConfig]:
        """Return list of all connection configs."""
        return [self.video_config, self.file_config, self.conference_config]

    def get_config(self, connection_id: int) -> ConnectionConfig:
        """Get config by connection ID."""
        configs = {1: self.video_config, 2: self.file_config, 3: self.conference_config}
        return configs.get(connection_id)

    @classmethod
    def from_json(cls, path: str) -> "MultiConnectionConfig":
        """Load configuration from JSON file."""
        import json
        with open(path) as f:
            data = json.load(f)
        return cls(**data)
```

### 10.3 ConnectionWorker

```python
# simulation/worker_process.py

import asyncio
import time
from multiprocessing import Queue
from multiprocessing.connection import Connection
from typing import Optional

from aioquic.quic.congestion import cubic as aioquic_cubic
from aioquic.quic import recovery as aioquic_recovery
from aioquic.quic.configuration import QuicConfiguration
from aioquic.asyncio import connect

from config.connection_config import ConnectionConfig, DYNAMIC_PARAMETERS
from metrics.collector import MetricsCollector
from metrics.epoch import ParameterSnapshot, EpochManager, EpochConfig
from synthesizers import SynthesizerFactory
from .ipc_messages import IPCMessage, MessageType


class ConnectionWorker:
    """
    Worker that runs a single QUIC connection in an isolated process.

    Each worker has its own copy of aioquic module globals, enabling
    true per-connection parameter isolation.
    """

    def __init__(
        self,
        config: ConnectionConfig,
        server_host: str,
        server_port: int,
        command_pipe: Connection,
        metrics_queue: Queue,
        start_barrier,
        network_scenario: str = "",
        network_config: dict = None,
    ):
        self.config = config
        self.server_host = server_host
        self.server_port = server_port
        self.command_pipe = command_pipe
        self.metrics_queue = metrics_queue
        self.start_barrier = start_barrier
        self.network_scenario = network_scenario
        self.network_config = network_config or {}

        self._running = False
        self._metrics_collector = MetricsCollector()
        self._param_history = []
        self._epoch_manager = None  # Initialized in run()

    def _apply_initial_parameters(self):
        """Apply initial CC parameters to aioquic globals (isolated to this process)."""
        initial_window_packets = self.config.initial_cw // self.config.max_datagram_size
        aioquic_cubic.K_INITIAL_WINDOW = initial_window_packets

        aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = self.config.loss_reduction_factor
        aioquic_cubic.K_CUBIC_C = self.config.cubic_c
        aioquic_cubic.K_MINIMUM_WINDOW = self.config.minimum_window
        aioquic_cubic.K_CUBIC_MAX_IDLE_TIME = self.config.cubic_max_idle_time
        aioquic_recovery.K_PACKET_THRESHOLD = self.config.packet_threshold
        aioquic_recovery.K_TIME_THRESHOLD = self.config.time_threshold

    def _update_parameter(self, param_name: str, value):
        """Update a single parameter mid-connection."""
        if param_name not in DYNAMIC_PARAMETERS:
            self._send_error(f"Parameter '{param_name}' cannot be changed mid-connection")
            return

        old_value = getattr(self.config, param_name)
        setattr(self.config, param_name, value)

        # Update aioquic globals
        if param_name == "loss_reduction_factor":
            aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = value
        elif param_name == "cubic_c":
            aioquic_cubic.K_CUBIC_C = value
        elif param_name == "minimum_window":
            aioquic_cubic.K_MINIMUM_WINDOW = value
        elif param_name == "packet_threshold":
            aioquic_recovery.K_PACKET_THRESHOLD = value
        elif param_name == "time_threshold":
            aioquic_recovery.K_TIME_THRESHOLD = value
        elif param_name == "cubic_max_idle_time":
            aioquic_cubic.K_CUBIC_MAX_IDLE_TIME = value

        self._param_history.append({
            "timestamp": time.time(),
            "param_name": param_name,
            "old_value": old_value,
            "new_value": value,
        })

        # Notify EpochManager of parameter change (starts new epoch after settling)
        if self._epoch_manager:
            new_params = ParameterSnapshot(
                loss_reduction_factor=self.config.loss_reduction_factor,
                cubic_c=self.config.cubic_c,
                minimum_window=self.config.minimum_window,
                packet_threshold=self.config.packet_threshold,
                time_threshold=self.config.time_threshold,
                cubic_max_idle_time=self.config.cubic_max_idle_time,
                initial_cw=self.config.initial_cw,
                max_ack_delay=self.config.max_ack_delay,
                max_data=self.config.max_data,
                max_stream_data=self.config.max_stream_data,
            )
            self._epoch_manager.on_parameter_change(new_params)

    def _check_commands(self):
        """Check for commands from main process (non-blocking)."""
        while self.command_pipe.poll():
            try:
                msg_dict = self.command_pipe.recv()
                msg = IPCMessage.from_dict(msg_dict)

                if msg.msg_type == MessageType.UPDATE_PARAM:
                    self._update_parameter(msg.payload["param_name"], msg.payload["value"])
                    self._send_ack(msg)
                elif msg.msg_type == MessageType.UPDATE_MULTIPLE_PARAMS:
                    for param_name, value in msg.payload["params"].items():
                        self._update_parameter(param_name, value)
                    self._send_ack(msg)
                elif msg.msg_type == MessageType.STOP:
                    self._running = False
            except Exception as e:
                self._send_error(str(e))

    def _send_metrics(self):
        """Send current metrics to main process."""
        metrics = self._metrics_collector.calculate_metrics()
        msg = IPCMessage(
            msg_type=MessageType.METRICS,
            connection_id=self.config.connection_id,
            timestamp=time.time(),
            payload={
                "throughput": metrics.throughput,
                "rtt": metrics.rtt,
                "latency": metrics.latency,
                "jitter": metrics.jitter,
                "packet_loss_rate": metrics.packet_loss_rate,
                "bytes_sent": self._metrics_collector.bytes_sent,
                "current_params": {
                    "loss_reduction_factor": self.config.loss_reduction_factor,
                    "cubic_c": self.config.cubic_c,
                    "minimum_window": self.config.minimum_window,
                },
            },
        )
        self.metrics_queue.put(msg)

    def _send_ack(self, original_msg: IPCMessage):
        """Send acknowledgment for received command."""
        msg = IPCMessage(
            msg_type=MessageType.ACK,
            connection_id=self.config.connection_id,
            timestamp=time.time(),
            payload={"original_timestamp": original_msg.timestamp},
        )
        self.metrics_queue.put(msg)

    def _send_error(self, error_msg: str):
        """Send error message to main process."""
        msg = IPCMessage(
            msg_type=MessageType.ERROR,
            connection_id=self.config.connection_id,
            timestamp=time.time(),
            payload={"error": error_msg},
        )
        self.metrics_queue.put(msg)

    def _send_finished(self, final_metrics: dict, epoch_history: dict = None):
        """Send finished message with final results including epoch history.

        Args:
            final_metrics: Final aggregated metrics as dict
            epoch_history: ConnectionEpochHistory.to_dict() result containing:
                - connection_id, application_type, total_epochs, valid_epochs
                - epochs: List of epoch dicts with parameters and metrics
        """
        msg = IPCMessage(
            msg_type=MessageType.FINISHED,
            connection_id=self.config.connection_id,
            timestamp=time.time(),
            payload={
                "final_metrics": final_metrics,
                "param_history": self._param_history,
                "epoch_history": epoch_history or {},
                "metrics_history": self._metrics_history,
                "success": True,
            },
        )
        self.metrics_queue.put(msg)

    async def run(self, duration: float):
        """Main worker loop with epoch-based metrics collection."""
        self._apply_initial_parameters()
        self._metrics_history = []

        # Create initial parameter snapshot (includes all parameters)
        initial_params = ParameterSnapshot(
            loss_reduction_factor=self.config.loss_reduction_factor,
            cubic_c=self.config.cubic_c,
            minimum_window=self.config.minimum_window,
            packet_threshold=self.config.packet_threshold,
            time_threshold=self.config.time_threshold,
            cubic_max_idle_time=self.config.cubic_max_idle_time,
            initial_cw=self.config.initial_cw,
            max_ack_delay=self.config.max_ack_delay,
            max_data=self.config.max_data,
            max_stream_data=self.config.max_stream_data,
        )

        # Initialize EpochManager with full context
        self._epoch_manager = EpochManager(
            connection_id=self.config.connection_id,
            application_type=self.config.application_type,
            network_scenario=self.network_scenario,
            network_config=self.network_config,
            initial_params=initial_params,
            config=EpochConfig(
                settling_time=2.0,  # 2 seconds settling time
                min_epoch_duration=2.0,
                sample_interval=0.1,
            ),
        )

        self.start_barrier.wait()

        self._running = True
        start_time = time.time()
        last_sample_time = start_time

        try:
            configuration = QuicConfiguration(is_client=True)
            configuration.verify_mode = False
            configuration.max_datagram_frame_size = 65536
            configuration.max_ack_delay = self.config.max_ack_delay

            async with connect(
                self.server_host,
                self.server_port,
                configuration=configuration,
            ) as protocol:
                self._metrics_collector.connection = protocol._quic
                self._metrics_collector.start()
                self._metrics_collector.record_connection_ready()

                # Connect epoch manager to metrics collector
                self._epoch_manager.set_metrics_collector(self._metrics_collector)
                self._epoch_manager.start()

                synthesizer = SynthesizerFactory.create(
                    self.config.application_type,
                    duration_seconds=duration,
                )

                stream_id = protocol._quic.get_next_available_stream_id()

                async for packet in synthesizer.generate():
                    if not self._running or (time.time() - start_time) >= duration:
                        break

                    protocol._quic.send_stream_data(stream_id, packet.data, end_stream=False)
                    self._metrics_collector.record_packet_sent(packet.size)

                    rtt = self._get_rtt(protocol)
                    if rtt and rtt > 0:
                        self._metrics_collector.record_rtt_sample(rtt)

                    self._check_commands()

                    # Collect epoch sample at interval (100ms)
                    now = time.time()
                    if now - last_sample_time >= 0.1:
                        # EpochManager collects sample (handles settling internally)
                        self._epoch_manager.collect_sample()

                        # Always record to metrics history for time-series export
                        metrics = self._metrics_collector.calculate_metrics()
                        self._metrics_history.append({
                            "timestamp": now - start_time,
                            **metrics.to_dict(),
                        })

                        # Only send metrics to UI if not settling
                        if not self._epoch_manager.is_settling():
                            self._send_metrics()

                        last_sample_time = now

                    await asyncio.sleep(0)

                self._metrics_collector.stop()

                # Finalize epoch collection and get history
                self._epoch_manager.finalize()
                epoch_history = self._epoch_manager.get_history()

                final_metrics = self._metrics_collector.calculate_metrics()

                # Send finished with epoch history converted to dict
                self._send_finished(final_metrics.to_dict(), epoch_history.to_dict())

        except Exception as e:
            self._send_error(f"Worker error: {str(e)}")
            raise

    def _get_rtt(self, protocol) -> Optional[float]:
        """Get current RTT from aioquic."""
        try:
            return protocol._quic._loss._rtt_smoothed
        except AttributeError:
            return None


def worker_process_entry(
    config_dict: dict,
    server_host: str,
    server_port: int,
    command_pipe: Connection,
    metrics_queue: Queue,
    start_barrier,
    duration: float,
    network_scenario: str = "",
    network_config: dict = None,
):
    """Entry point for worker process."""
    config = ConnectionConfig.from_dict(config_dict)
    worker = ConnectionWorker(
        config=config,
        server_host=server_host,
        server_port=server_port,
        command_pipe=command_pipe,
        metrics_queue=metrics_queue,
        start_barrier=start_barrier,
        network_scenario=network_scenario,
        network_config=network_config or {},
    )
    asyncio.run(worker.run(duration))
```

### 10.4 ProcessOrchestrator

```python
# simulation/process_orchestrator.py

import asyncio
import threading
import time
from multiprocessing import Process, Pipe, Queue, Barrier
from typing import Dict, List, Optional, Callable

from config.multi_connection_config import MultiConnectionConfig
from .worker_process import worker_process_entry
from .server import QuicServer
from .ml_controller import MLController
from .result import MultiConnectionResult, ConnectionResult
from .ipc_messages import MessageType


class ProcessOrchestrator:
    """Orchestrates multiple QUIC connection processes."""

    def __init__(
        self,
        config: MultiConnectionConfig,
        ml_callback: Optional[Callable] = None,
        metrics_interval: float = 0.1,
        network_scenario: str = "",
        network_config: dict = None,
    ):
        self.config = config
        self.ml_callback = ml_callback
        self.metrics_interval = metrics_interval
        self.network_scenario = network_scenario
        self.network_config = network_config or {}

        self.workers: Dict[int, Process] = {}
        self.command_pipes: Dict[int, Pipe] = {}
        self.metrics_queue: Queue = Queue(maxsize=10000)  # Prevent unbounded memory growth
        self.start_barrier: Optional[Barrier] = None
        self.server: Optional[QuicServer] = None
        self.ml_controller: Optional[MLController] = None
        self.metrics_history: List[Dict] = []
        self.final_results: Dict[int, dict] = {}
        self.epoch_histories: Dict[int, List[Dict]] = {}  # Per-connection epoch data

    async def setup(self):
        """Setup server and prepare for workers."""
        self.server = QuicServer(host=self.config.server_host, port=self.config.server_port)
        await self.server.start()
        self.start_barrier = Barrier(4)

        if self.ml_callback:
            self.ml_controller = MLController(
                decision_interval=self.metrics_interval,
                ml_callback=self.ml_callback,
            )

    def _spawn_workers(self, duration: float):
        """Spawn worker processes for each connection."""
        for conn_config in self.config.get_all_configs():
            main_pipe, worker_pipe = Pipe()
            self.command_pipes[conn_config.connection_id] = main_pipe

            process = Process(
                target=worker_process_entry,
                args=(
                    conn_config.to_dict(),
                    self.config.server_host,
                    self.config.server_port,
                    worker_pipe,
                    self.metrics_queue,
                    self.start_barrier,
                    duration,
                    self.network_scenario,
                    self.network_config,
                ),
                name=f"QUIC-{conn_config.application_type}",
            )
            self.workers[conn_config.connection_id] = process

    async def run(self, duration: Optional[float] = None) -> MultiConnectionResult:
        """Run all connections concurrently."""
        duration = duration or self.config.simulation_duration

        try:
            await self.setup()
            self._spawn_workers(duration)

            for process in self.workers.values():
                process.start()

            if self.ml_controller:
                self.ml_controller.set_ipc_channels(self.command_pipes, self.metrics_queue)

            # Wait for all workers to be ready (with timeout to prevent deadlock)
            try:
                self.start_barrier.wait(timeout=10.0)
            except threading.BrokenBarrierError:
                raise RuntimeError("Workers failed to start - barrier timeout after 10s")

            if self.ml_controller:
                await self.ml_controller.run_control_loop(duration)
                self.metrics_history = self.ml_controller.metrics_history
            else:
                await self._collect_metrics_loop(duration)

            for conn_id, process in self.workers.items():
                process.join(timeout=duration + 5)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=2)

            self._collect_final_results()
            return self._build_results()

        finally:
            await self.cleanup()

    async def _collect_metrics_loop(self, duration: float):
        """Simple metrics collection without ML."""
        start_time = time.time()

        while (time.time() - start_time) < duration:
            current_metrics = {}

            while not self.metrics_queue.empty():
                try:
                    msg = self.metrics_queue.get_nowait()
                    if msg.msg_type == MessageType.METRICS:
                        current_metrics[msg.connection_id] = msg.payload
                    elif msg.msg_type == MessageType.FINISHED:
                        self.final_results[msg.connection_id] = msg.payload
                except Exception:
                    break  # Queue empty or connection closed

            if current_metrics:
                self.metrics_history.append({
                    "timestamp": time.time() - start_time,
                    "metrics": current_metrics,
                })

            await asyncio.sleep(self.metrics_interval)

    def _collect_final_results(self):
        """Collect any remaining messages from queue."""
        while not self.metrics_queue.empty():
            try:
                msg = self.metrics_queue.get_nowait()
                if msg.msg_type == MessageType.FINISHED:
                    self.final_results[msg.connection_id] = msg.payload
                    # Extract epoch_history from finished payload
                    if "epoch_history" in msg.payload:
                        self.epoch_histories[msg.connection_id] = msg.payload["epoch_history"]
            except Exception:
                break  # Queue empty or connection closed

    def _build_results(self) -> MultiConnectionResult:
        """Build final result object from collected data."""
        connection_results = {}

        for conn_id in [1, 2, 3]:
            if conn_id in self.final_results:
                result_data = self.final_results[conn_id]

                # Extract epochs list from epoch_history dict
                # epoch_history is ConnectionEpochHistory.to_dict() with structure:
                # {"connection_id": int, "epochs": [...], "total_epochs": int, ...}
                epoch_history_data = self.epoch_histories.get(conn_id, {})
                epochs_list = epoch_history_data.get("epochs", []) if isinstance(epoch_history_data, dict) else []

                connection_results[conn_id] = ConnectionResult(
                    connection_id=conn_id,
                    application_type=self.config.get_config(conn_id).application_type,
                    final_metrics=result_data.get("final_metrics", {}),
                    param_history=result_data.get("param_history", []),
                    epoch_history=epochs_list,
                    metrics_history=result_data.get("metrics_history", []),
                    network_scenario=self.network_scenario,
                    network_config=self.network_config,
                    success=result_data.get("success", False),
                )

        all_success = (
            len(connection_results) == 3 and
            all(r.success for r in connection_results.values()) and
            all(p.exitcode == 0 for p in self.workers.values())
        )

        result = MultiConnectionResult(
            connection_results=connection_results,
            network_scenario=self.network_scenario,
            network_config=self.network_config,
            shared_params={
                "initial_cw": self.config.shared_initial_cw,
                "max_ack_delay": self.config.shared_max_ack_delay,
                "max_data": self.config.shared_max_data,
                "max_stream_data": self.config.shared_max_stream_data,
            },
            duration_seconds=self.config.simulation_duration,
        )
        result.finalize()
        return result

    async def cleanup(self):
        """Cleanup all resources."""
        # Terminate workers with force kill if needed to prevent zombies
        for process in self.workers.values():
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()  # Force kill if still alive
                    process.join(timeout=1)

        # Stop server with error protection
        if self.server:
            try:
                await self.server.stop()
            except Exception:
                pass  # Server may already be stopped

        # Close command pipes
        for pipe in self.command_pipes.values():
            try:
                pipe.close()
            except Exception:
                pass

        # Close metrics queue
        if self.metrics_queue:
            try:
                self.metrics_queue.close()
                self.metrics_queue.join_thread()
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════════════════════
    # UI SUPPORT METHODS (for Browser UI / WebSocket)
    # ═══════════════════════════════════════════════════════════════════════════

    def is_running(self) -> bool:
        """Check if simulation is currently running."""
        if not self.workers:
            return False
        return any(p.is_alive() for p in self.workers.values())

    def get_latest_metrics(self) -> Dict[int, dict]:
        """
        Get latest metrics for all connections.

        Returns:
            Dict mapping connection_id to latest metrics dict.
        """
        # Process any pending messages first
        self._process_pending_messages()

        if self.ml_controller:
            return self.ml_controller.latest_metrics.copy()
        return self._latest_metrics.copy() if hasattr(self, '_latest_metrics') else {}

    def get_buffer_states(self) -> Dict[int, dict]:
        """
        Get buffer states for all connections.

        Returns:
            Dict mapping connection_id to buffer state dict.
        """
        return self._buffer_states.copy() if hasattr(self, '_buffer_states') else {}

    def get_current_params(self) -> Dict[int, dict]:
        """
        Get current parameter values for all connections.

        Returns:
            Dict mapping connection_id to params dict.
        """
        params = {}
        for config in self.config.get_all_configs():
            params[config.connection_id] = {
                "loss_reduction_factor": config.loss_reduction_factor,
                "cubic_c": config.cubic_c,
                "minimum_window": config.minimum_window,
                "packet_threshold": config.packet_threshold,
                "time_threshold": config.time_threshold,
                "cubic_max_idle_time": config.cubic_max_idle_time,
            }
        return params

    # Parameter bounds for validation (dynamic parameters only)
    PARAM_BOUNDS = {
        "loss_reduction_factor": (0.1, 0.9),
        "cubic_c": (0.1, 1.0),
        "minimum_window": (1, 10),
        "packet_threshold": (1, 10),
        "time_threshold": (1.0, 2.0),
        "cubic_max_idle_time": (0.5, 5.0),
    }

    def update_parameter(self, connection_id: int, param_name: str, value: float) -> bool:
        """
        Update a parameter on a specific connection.

        Args:
            connection_id: Target connection (1, 2, or 3)
            param_name: Name of parameter to update
            value: New parameter value

        Returns:
            True if update was sent successfully, False otherwise.
        """
        pipe = self.command_pipes.get(connection_id)
        if not pipe:
            return False

        # Validate parameter bounds
        if param_name in self.PARAM_BOUNDS:
            min_val, max_val = self.PARAM_BOUNDS[param_name]
            if not (min_val <= value <= max_val):
                return False  # Reject out-of-bounds value

        try:
            msg = IPCMessage(
                msg_type=MessageType.UPDATE_PARAM,
                connection_id=connection_id,
                timestamp=time.time(),
                payload={"param_name": param_name, "value": value},
            )
            pipe.send(msg.to_dict())

            # Update local config copy
            config = self.config.get_config(connection_id)
            if config and hasattr(config, param_name):
                setattr(config, param_name, value)

            return True
        except Exception:
            return False

    def _process_pending_messages(self):
        """Process any pending messages from the metrics queue."""
        if not hasattr(self, '_latest_metrics'):
            self._latest_metrics = {}
        if not hasattr(self, '_buffer_states'):
            self._buffer_states = {}

        while not self.metrics_queue.empty():
            try:
                msg = self.metrics_queue.get_nowait()
                if msg.msg_type == MessageType.METRICS:
                    self._latest_metrics[msg.connection_id] = msg.payload
                elif msg.msg_type == MessageType.BUFFER_STATE:
                    self._buffer_states[msg.connection_id] = msg.payload
                elif msg.msg_type == MessageType.FINISHED:
                    self.final_results[msg.connection_id] = msg.payload
                    if "epoch_history" in msg.payload:
                        self.epoch_histories[msg.connection_id] = msg.payload["epoch_history"]
            except Exception:
                break  # Queue empty or connection closed
```

### 10.5 MLController

```python
# simulation/ml_controller.py

import time
import asyncio
from typing import Dict, List, Callable, Optional
from multiprocessing import Queue
from multiprocessing.connection import Connection

from .ipc_messages import IPCMessage, MessageType


class MLController:
    """Central ML controller that runs in the main process."""

    def __init__(
        self,
        decision_interval: float = 0.1,
        ml_callback: Optional[Callable] = None,
    ):
        self.decision_interval = decision_interval
        self.ml_callback = ml_callback or self._default_decision
        self.latest_metrics: Dict[int, dict] = {}
        self.metrics_history: List[Dict] = []
        self.command_pipes: Dict[int, Connection] = {}
        self.metrics_queue: Optional[Queue] = None

    def set_ipc_channels(self, command_pipes: Dict[int, Connection], metrics_queue: Queue):
        """Set IPC channels after process creation."""
        self.command_pipes = command_pipes
        self.metrics_queue = metrics_queue

    async def run_control_loop(self, duration: float):
        """Main control loop."""
        start_time = time.time()

        while (time.time() - start_time) < duration:
            loop_start = time.time()

            self._collect_metrics()

            if len(self.latest_metrics) == 3:
                # Execute ML callback with error protection
                try:
                    decisions = self.ml_callback(self.latest_metrics.copy())
                except Exception as e:
                    # Log error and continue with no parameter changes
                    print(f"ML callback error: {e}")
                    decisions = {}

                for conn_id, params in decisions.items():
                    if params:
                        self._send_param_update(conn_id, params)

            self.metrics_history.append({
                "timestamp": time.time() - start_time,
                "metrics": self.latest_metrics.copy(),
            })

            elapsed = time.time() - loop_start
            if elapsed < self.decision_interval:
                await asyncio.sleep(self.decision_interval - elapsed)

    def _collect_metrics(self):
        """Collect all available metrics from queue."""
        while not self.metrics_queue.empty():
            try:
                msg = self.metrics_queue.get_nowait()
                if msg.msg_type == MessageType.METRICS:
                    self.latest_metrics[msg.connection_id] = msg.payload
            except Exception:
                break  # Queue empty or connection closed

    def _send_param_update(self, conn_id: int, params: dict):
        """Send parameter update to specific worker."""
        pipe = self.command_pipes.get(conn_id)
        if pipe:
            if len(params) == 1:
                param_name, value = list(params.items())[0]
                msg = IPCMessage(
                    msg_type=MessageType.UPDATE_PARAM,
                    connection_id=conn_id,
                    timestamp=time.time(),
                    payload={"param_name": param_name, "value": value},
                )
            else:
                msg = IPCMessage(
                    msg_type=MessageType.UPDATE_MULTIPLE_PARAMS,
                    connection_id=conn_id,
                    timestamp=time.time(),
                    payload={"params": params},
                )
            pipe.send(msg.to_dict())

    def _default_decision(self, metrics: Dict[int, dict]) -> Dict[int, dict]:
        """Default ML decision (no changes)."""
        return {}

    def compute_fairness_index(self) -> float:
        """Compute Jain's fairness index for throughput."""
        throughputs = [m.get("throughput", 0) for m in self.latest_metrics.values()]
        if not throughputs or sum(throughputs) == 0:
            return 1.0

        n = len(throughputs)
        sum_x = sum(throughputs)
        sum_x_sq = sum(x ** 2 for x in throughputs)
        return (sum_x ** 2) / (n * sum_x_sq) if sum_x_sq > 0 else 1.0
```

### 10.6 Result Data Structures

```python
# simulation/result.py

import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path


@dataclass
class ConnectionResult:
    """
    Result from a single QUIC connection.

    Includes final metrics, parameter history, and epoch-based metrics
    for analyzing performance across parameter changes.
    """

    connection_id: int
    application_type: str

    # Final aggregated metrics
    final_metrics: Dict[str, float] = field(default_factory=dict)

    # Parameter history: list of {timestamp, param_name, old_value, new_value}
    param_history: List[Dict[str, Any]] = field(default_factory=list)

    # Epoch history from EpochManager (see Section 17.5)
    epoch_history: List[Dict[str, Any]] = field(default_factory=list)

    # Full metrics time series (100ms intervals)
    metrics_history: List[Dict[str, Any]] = field(default_factory=list)

    # Metadata
    start_time: float = 0.0
    end_time: float = 0.0
    success: bool = True
    error_message: Optional[str] = None

    # Network conditions this connection experienced
    network_scenario: str = ""
    network_config: Dict[str, Any] = field(default_factory=dict)

    def get_duration(self) -> float:
        """Get total connection duration in seconds."""
        return self.end_time - self.start_time

    def get_epoch_count(self) -> int:
        """Get number of completed epochs (parameter stable periods)."""
        return len(self.epoch_history)

    def get_final_epoch_metrics(self) -> Optional[Dict[str, Any]]:
        """Get metrics from the final (most recent) epoch."""
        if self.epoch_history:
            return self.epoch_history[-1]
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class MultiConnectionResult:
    """
    Combined result from all 3 QUIC connections.

    Provides methods to export results in various formats for analysis.
    """

    # Results per connection
    connection_results: Dict[int, ConnectionResult] = field(default_factory=dict)

    # Simulation metadata
    simulation_id: str = ""
    start_timestamp: str = ""
    end_timestamp: str = ""
    duration_seconds: float = 0.0

    # Network scenario used
    network_scenario: str = ""
    network_config: Dict[str, Any] = field(default_factory=dict)

    # Shared start-only parameters (constant for all connections)
    shared_params: Dict[str, Any] = field(default_factory=dict)

    # Aggregated fairness metrics
    fairness_index: float = 1.0
    total_throughput: float = 0.0

    def __post_init__(self):
        """Generate simulation ID if not provided."""
        if not self.simulation_id:
            self.simulation_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not self.start_timestamp:
            self.start_timestamp = datetime.now().isoformat()

    def add_connection_result(self, result: ConnectionResult):
        """Add a connection result."""
        self.connection_results[result.connection_id] = result

    def compute_fairness_index(self) -> float:
        """Compute Jain's fairness index across all connections."""
        throughputs = [
            r.final_metrics.get("throughput", 0)
            for r in self.connection_results.values()
        ]
        if not throughputs or sum(throughputs) == 0:
            return 1.0

        n = len(throughputs)
        sum_x = sum(throughputs)
        sum_x_sq = sum(x ** 2 for x in throughputs)
        self.fairness_index = (sum_x ** 2) / (n * sum_x_sq) if sum_x_sq > 0 else 1.0
        return self.fairness_index

    def compute_total_throughput(self) -> float:
        """Compute total throughput across all connections."""
        self.total_throughput = sum(
            r.final_metrics.get("throughput", 0)
            for r in self.connection_results.values()
        )
        return self.total_throughput

    def finalize(self):
        """Finalize results: compute aggregates, set end timestamp."""
        self.end_timestamp = datetime.now().isoformat()
        self.compute_fairness_index()
        self.compute_total_throughput()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "simulation_id": self.simulation_id,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "duration_seconds": self.duration_seconds,
            "network_scenario": self.network_scenario,
            "network_config": self.network_config,
            "shared_params": self.shared_params,
            "fairness_index": self.fairness_index,
            "total_throughput": self.total_throughput,
            "connections": {
                conn_id: result.to_dict()
                for conn_id, result in self.connection_results.items()
            },
        }

    def export_json(self, output_dir: str = "output") -> str:
        """
        Export complete results to JSON file.

        Returns the path to the exported file.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        filename = f"results_{self.simulation_id}.json"
        filepath = output_path / filename

        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

        return str(filepath)

    def export_metrics_history(self, output_dir: str = "output") -> str:
        """
        Export full metrics time series for all connections.

        This is a larger file with 100ms granularity data.
        Returns the path to the exported file.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        filename = f"metrics_history_{self.simulation_id}.json"
        filepath = output_path / filename

        history_data = {
            "simulation_id": self.simulation_id,
            "network_scenario": self.network_scenario,
            "connections": {
                conn_id: {
                    "application_type": result.application_type,
                    "metrics_history": result.metrics_history,
                }
                for conn_id, result in self.connection_results.items()
            },
        }

        with open(filepath, "w") as f:
            json.dump(history_data, f, indent=2)

        return str(filepath)

    def export_epoch_histories(self, output_dir: str = "output") -> str:
        """
        Export epoch-based metrics for all connections.

        This format is ideal for analyzing parameter effects with settling time.
        Each epoch represents a period where parameters were stable.

        Returns the path to the exported file.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        filename = f"epoch_history_{self.simulation_id}.json"
        filepath = output_path / filename

        epoch_data = {
            "simulation_id": self.simulation_id,
            "network_scenario": self.network_scenario,
            "network_config": self.network_config,
            "shared_params": self.shared_params,
            "connections": {},
        }

        for conn_id, result in self.connection_results.items():
            epoch_data["connections"][conn_id] = {
                "application_type": result.application_type,
                "epoch_count": result.get_epoch_count(),
                "epochs": result.epoch_history,
            }

        with open(filepath, "w") as f:
            json.dump(epoch_data, f, indent=2)

        return str(filepath)

    def get_epoch_comparison_summary(self) -> Dict[str, Any]:
        """
        Generate summary comparing metrics across epochs for each connection.

        Useful for seeing how parameter changes affected performance.
        """
        summary = {}

        for conn_id, result in self.connection_results.items():
            if not result.epoch_history:
                continue

            epochs = result.epoch_history
            summary[conn_id] = {
                "application_type": result.application_type,
                "total_epochs": len(epochs),
                "epoch_summaries": [],
            }

            for i, epoch in enumerate(epochs):
                epoch_summary = {
                    "epoch_number": epoch.get("epoch_number", i + 1),
                    "parameters": epoch.get("parameters", {}),
                    "duration_seconds": epoch.get("duration_seconds", 0),
                    "metrics": epoch.get("metrics", {}),
                }
                summary[conn_id]["epoch_summaries"].append(epoch_summary)

        return summary
```

### 10.7 Metrics Exporter (CSV and Additional Formats)

```python
# metrics/exporter.py

import csv
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime


class MetricsExporter:
    """
    Additional export utilities for metrics data.

    Complements the JSON exports in result.py with CSV and other formats
    for integration with analysis tools like pandas, Excel, etc.
    """

    @staticmethod
    def export_metrics_to_csv(
        metrics_history: List[Dict[str, Any]],
        output_path: str,
        connection_id: int,
    ) -> str:
        """
        Export metrics time series to CSV format.

        Args:
            metrics_history: List of metric snapshots
            output_path: Directory for output file
            connection_id: Connection identifier

        Returns:
            Path to the exported CSV file.
        """
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"metrics_conn_{connection_id}.csv"
        filepath = output_dir / filename

        if not metrics_history:
            return str(filepath)

        # Get all metric keys from first entry
        fieldnames = ["timestamp"]
        sample = metrics_history[0]
        for key in sample.keys():
            if key != "timestamp":
                fieldnames.append(key)

        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(metrics_history)

        return str(filepath)

    @staticmethod
    def export_epochs_to_csv(
        epoch_history: List[Dict[str, Any]],
        output_path: str,
        connection_id: int,
    ) -> str:
        """
        Export epoch-based metrics to CSV format.

        Flattens the epoch structure for easy analysis in spreadsheets.

        Args:
            epoch_history: List of epoch records
            output_path: Directory for output file
            connection_id: Connection identifier

        Returns:
            Path to the exported CSV file.
        """
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"epochs_conn_{connection_id}.csv"
        filepath = output_dir / filename

        if not epoch_history:
            return str(filepath)

        # Build flattened rows
        rows = []
        for epoch in epoch_history:
            row = {
                "epoch_number": epoch.get("epoch_number", 0),
                "start_time": epoch.get("start_time", 0),
                "end_time": epoch.get("end_time", 0),
                "duration_seconds": epoch.get("duration_seconds", 0),
                "settling_time": epoch.get("settling_time", 0),
            }

            # Flatten parameters
            params = epoch.get("parameters", {})
            for param_name, value in params.items():
                row[f"param_{param_name}"] = value

            # Flatten metrics
            metrics = epoch.get("metrics", {})
            for metric_name, value in metrics.items():
                row[f"metric_{metric_name}"] = value

            rows.append(row)

        if rows:
            fieldnames = list(rows[0].keys())
            with open(filepath, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

        return str(filepath)

    @staticmethod
    def export_comparison_csv(
        all_results: Dict[int, Dict[str, Any]],
        output_path: str,
        simulation_id: str,
    ) -> str:
        """
        Export a comparison CSV with all connections side-by-side.

        Creates a single CSV where each row is a timestamp and columns
        show metrics for each connection.

        Args:
            all_results: Dict mapping connection_id to result data
            output_path: Directory for output file
            simulation_id: Simulation identifier

        Returns:
            Path to the exported CSV file.
        """
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"comparison_{simulation_id}.csv"
        filepath = output_dir / filename

        # Build header with metrics for each connection
        metric_names = ["throughput", "rtt", "latency", "jitter", "packet_loss_rate"]
        fieldnames = ["timestamp"]
        for conn_id in sorted(all_results.keys()):
            app_type = all_results[conn_id].get("application_type", f"conn_{conn_id}")
            for metric in metric_names:
                fieldnames.append(f"{app_type}_{metric}")

        # Merge metrics histories by timestamp
        merged_data: Dict[float, Dict[str, Any]] = {}

        for conn_id, result in all_results.items():
            app_type = result.get("application_type", f"conn_{conn_id}")
            for entry in result.get("metrics_history", []):
                ts = entry.get("timestamp", 0)
                if ts not in merged_data:
                    merged_data[ts] = {"timestamp": ts}
                for metric in metric_names:
                    merged_data[ts][f"{app_type}_{metric}"] = entry.get(metric, "")

        # Sort by timestamp and write
        rows = [merged_data[ts] for ts in sorted(merged_data.keys())]

        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        return str(filepath)

    @staticmethod
    def export_summary_csv(
        results: Dict[str, Any],
        output_path: str,
    ) -> str:
        """
        Export a one-row summary CSV for batch analysis.

        Useful when running many simulations and wanting to compare
        final results across different configurations.

        Args:
            results: Full simulation result dictionary
            output_path: Directory for output file

        Returns:
            Path to the exported CSV file.
        """
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        simulation_id = results.get("simulation_id", "unknown")
        filename = f"summary_{simulation_id}.csv"
        filepath = output_dir / filename

        # Build summary row
        row = {
            "simulation_id": simulation_id,
            "network_scenario": results.get("network_scenario", ""),
            "duration_seconds": results.get("duration_seconds", 0),
            "fairness_index": results.get("fairness_index", 0),
            "total_throughput": results.get("total_throughput", 0),
        }

        # Add per-connection final metrics
        connections = results.get("connections", {})
        for conn_id, conn_result in connections.items():
            app_type = conn_result.get("application_type", f"conn_{conn_id}")
            final_metrics = conn_result.get("final_metrics", {})
            for metric_name, value in final_metrics.items():
                row[f"{app_type}_{metric_name}"] = value

        fieldnames = list(row.keys())
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(row)

        return str(filepath)
```

---

## 11. Implementation Phases

### Phase 1: Foundation

| Task | Files | Description |
|------|-------|-------------|
| 1.1 | `config/connection_config.py` | Create ConnectionConfig with all parameters |
| 1.2 | `config/multi_connection_config.py` | Create MultiConnectionConfig |
| 1.3 | `simulation/ipc_messages.py` | Define IPC message protocol |
| 1.4 | `config/settings.py` | Global settings (host, port, paths) |

### Phase 2: Core Infrastructure

| Task | Files | Description |
|------|-------|-------------|
| 2.1 | `simulation/server.py` | QUIC server implementation |
| 2.2 | `simulation/client.py` | QUIC client protocol |
| 2.3 | `metrics/collector.py` | Metrics collection |
| 2.4 | `metrics/calculator.py` | Metrics computation |

### Phase 3: Synthesizers

| Task | Files | Description |
|------|-------|-------------|
| 3.1 | `synthesizers/base.py` | Abstract base synthesizer |
| 3.2 | `synthesizers/video_streaming.py` | Video stream generator |
| 3.3 | `synthesizers/file_transfer.py` | File transfer generator |
| 3.4 | `synthesizers/conference_call.py` | Conference call generator |

**Full Synthesizer Implementation (matching `/code` directory logic):**

See [Section 15: Synthesizer Implementation](#15-synthesizer-implementation) for complete code.

### Phase 4: Multi-Process

| Task | Files | Description |
|------|-------|-------------|
| 4.1 | `simulation/worker_process.py` | ConnectionWorker class |
| 4.2 | `simulation/process_orchestrator.py` | ProcessOrchestrator class |
| 4.3 | `simulation/ml_controller.py` | MLController class |
| 4.4 | `simulation/result.py` | Result data structures |

### Phase 5: CLI and Network

| Task | Files | Description |
|------|-------|-------------|
| 5.1 | `main.py` | CLI entry point |
| 5.2 | `wireless_bottleneck/` | Network condition scripts |
| 5.3 | `ml_callbacks/` | Example ML callbacks |
| 5.4 | Tests | Integration tests |

---

## 12. Testing Strategy

### 12.1 Unit Tests

```python
# tests/test_config.py
def test_connection_config_creation():
    config = ConnectionConfig(connection_id=1, application_type="video_streaming")
    assert config.connection_id == 1
    assert config.loss_reduction_factor == 0.7  # default

def test_dynamic_parameters():
    from config.connection_config import DYNAMIC_PARAMETERS
    assert "loss_reduction_factor" in DYNAMIC_PARAMETERS
    assert "initial_cw" not in DYNAMIC_PARAMETERS

# tests/test_ipc.py
def test_message_serialization():
    msg = IPCMessage(
        msg_type=MessageType.UPDATE_PARAM,
        connection_id=1,
        timestamp=time.time(),
        payload={"param_name": "cubic_c", "value": 0.5},
    )
    restored = IPCMessage.from_dict(msg.to_dict())
    assert restored.msg_type == msg.msg_type
    assert restored.payload["value"] == 0.5
```

### 12.2 Parameter Isolation Test

```python
# tests/test_parameter_isolation.py
def test_parameter_isolation_across_processes():
    """Verify aioquic globals are isolated between processes."""
    from multiprocessing import Process, Queue

    results = Queue()

    def worker(lrf_value, queue):
        from aioquic.quic.congestion import cubic
        cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = lrf_value
        time.sleep(0.1)
        queue.put(cubic.K_CUBIC_LOSS_REDUCTION_FACTOR)

    p1 = Process(target=worker, args=(0.4, results))
    p2 = Process(target=worker, args=(0.8, results))

    p1.start(); p2.start()
    p1.join(); p2.join()

    values = [results.get(), results.get()]
    assert 0.4 in values
    assert 0.8 in values  # Both values exist = isolation works
```

### 12.3 Integration Test

```python
# tests/test_integration.py
@pytest.mark.asyncio
async def test_three_connections():
    """Test 3 concurrent connections run successfully."""
    config = MultiConnectionConfig()
    config.simulation_duration = 5.0  # Short test

    orchestrator = ProcessOrchestrator(config)
    result = await orchestrator.run()

    assert result.success
    assert len(result.connection_results) == 3

    for conn_result in result.connection_results.values():
        assert conn_result.success
        assert conn_result.final_metrics["throughput"] > 0
```

---

## 13. CLI Commands

### 13.1 Available Commands

```bash
# Run 3 concurrent connections
uv run main.py run

# Run with custom duration
uv run main.py run --duration 60

# Run with ML controller
uv run main.py run --with-ml

# Run with custom config file
uv run main.py run --config config.json

# Full options
uv run main.py run \
    --duration 30 \                    # Simulation duration (seconds)
    --metrics-interval 0.1 \           # Metrics collection interval
    --output-dir output/ \             # Output directory
    --with-ml \                        # Enable ML controller
    --ml-callback module:function      # Custom ML callback
```

### 13.2 Main.py Implementation

```python
# main.py

import argparse
import asyncio
from pathlib import Path

from config.multi_connection_config import MultiConnectionConfig
from simulation.process_orchestrator import ProcessOrchestrator
from wireless_bottleneck import WirelessBottleneck, get_scenario


def cmd_run(args):
    """Run 3 concurrent connections."""
    print("QUIC 3-Connection Simulation")
    print("=" * 50)

    # Load config
    if args.config:
        config = MultiConnectionConfig.from_json(args.config)
    else:
        config = MultiConnectionConfig()

    config.simulation_duration = args.duration

    # Validate duration is sufficient for epoch collection
    settling_time = 2.0  # Must match EpochConfig.settling_time
    min_epoch_duration = 2.0  # Minimum useful epoch
    min_duration = settling_time + min_epoch_duration
    if args.duration < min_duration:
        print(f"Warning: duration {args.duration}s < {min_duration}s (settling + min epoch)")
        print("No valid epochs will be collected. Consider increasing --duration.")
        print()

    # Setup network scenario
    scenario = get_scenario(args.scenario)
    network_config = scenario.config.to_dict() if scenario else {}

    # Setup ML callback
    ml_callback = None
    if args.with_ml:
        if args.ml_callback:
            module_name, func_name = args.ml_callback.split(":")
            module = __import__(module_name)
            ml_callback = getattr(module, func_name)
        else:
            from ml_callbacks.fairness_optimizer import fairness_optimizer
            ml_callback = fairness_optimizer

    # Run with network bottleneck
    with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
        orchestrator = ProcessOrchestrator(
            config=config,
            ml_callback=ml_callback,
            metrics_interval=args.metrics_interval,
            network_scenario=args.scenario,
            network_config=network_config,
        )

        result = asyncio.run(orchestrator.run())

    # Export results
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Export all formats
    result_file = result.export_json(str(output_path))
    print(f"Results saved to: {result_file}")

    metrics_file = result.export_metrics_history(str(output_path))
    print(f"Metrics history saved to: {metrics_file}")

    epoch_file = result.export_epoch_histories(str(output_path))
    print(f"Epoch histories saved to: {epoch_file}")

    # Summary
    print(f"\nSimulation Complete")
    print(f"Network Scenario: {args.scenario}")
    print(f"Duration: {args.duration}s")
    print(f"Fairness Index: {result.fairness_index:.3f}")
    print(f"Total Throughput: {result.total_throughput / 1e6:.2f} Mbps")
    print()

    for conn_id, conn_result in result.connection_results.items():
        print(f"  Connection {conn_id} ({conn_result.application_type}):")
        print(f"    Throughput: {conn_result.final_metrics.get('throughput', 0) / 1e6:.2f} Mbps")
        print(f"    RTT: {conn_result.final_metrics.get('rtt', 0) * 1000:.1f} ms")
        print(f"    Epochs: {conn_result.get_epoch_count()}")

    return 0


def main():
    parser = argparse.ArgumentParser(description="QUIC 3-Connection Simulation")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run simulation")
    run_parser.add_argument("--duration", type=float, default=30.0)
    run_parser.add_argument("--metrics-interval", type=float, default=0.1)
    run_parser.add_argument("--output-dir", default="output")
    run_parser.add_argument("--config", help="Path to JSON config file")
    run_parser.add_argument("--scenario", default="congested_low",
                           help="Network scenario (stable_high, congested_low, varying, lossy, asymmetric)")
    run_parser.add_argument("--with-ml", action="store_true")
    run_parser.add_argument("--ml-callback", help="module:function")
    run_parser.add_argument("--ui", action="store_true", help="Enable browser UI")
    run_parser.set_defaults(func=cmd_run)

    args = parser.parse_args()
    if hasattr(args, "func"):
        return args.func(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    exit(main())
```

---

## 14. Configuration Files

### 14.1 Default Config (JSON)

```json
{
  "server_host": "localhost",
  "server_port": 4433,
  "simulation_duration": 30.0,
  "metrics_interval": 0.1,

  "_comment": "SHARED START-ONLY PARAMETERS - CONSTANT for all 3 connections",
  "shared_initial_cw": 12000,
  "shared_max_ack_delay": 0.025,
  "shared_max_data": 1048576,
  "shared_max_stream_data": 1048576,

  "video_config": {
    "connection_id": 1,
    "application_type": "video_streaming",
    "loss_reduction_factor": 0.6,
    "cubic_c": 0.4,
    "minimum_window": 4,
    "packet_threshold": 3,
    "time_threshold": 1.125,
    "cubic_max_idle_time": 2.0
  },

  "file_config": {
    "connection_id": 2,
    "application_type": "file_transfer",
    "loss_reduction_factor": 0.7,
    "cubic_c": 0.5,
    "minimum_window": 2,
    "packet_threshold": 3,
    "time_threshold": 1.125,
    "cubic_max_idle_time": 2.0
  },

  "conference_config": {
    "connection_id": 3,
    "application_type": "conference_call",
    "loss_reduction_factor": 0.5,
    "cubic_c": 0.3,
    "minimum_window": 6,
    "packet_threshold": 2,
    "time_threshold": 1.0,
    "cubic_max_idle_time": 2.0
  }
}
```

### 14.2 Example ML Callback

```python
# ml_callbacks/fairness_optimizer.py

def fairness_optimizer(metrics: dict) -> dict:
    """Optimize for fairness across connections."""
    if len(metrics) < 3:
        return {}

    decisions = {}
    throughputs = [(k, m.get("throughput", 0)) for k, m in metrics.items()]

    # Jain's fairness index
    n = len(throughputs)
    sum_x = sum(t for _, t in throughputs)
    sum_x_sq = sum(t**2 for _, t in throughputs)
    fairness = (sum_x ** 2) / (n * sum_x_sq) if sum_x_sq > 0 else 1.0

    if fairness < 0.85:
        max_conn_id = max(throughputs, key=lambda x: x[1])[0]
        current_lrf = metrics[max_conn_id]["current_params"]["loss_reduction_factor"]
        decisions[max_conn_id] = {"loss_reduction_factor": min(0.9, current_lrf + 0.05)}

        min_conn_id = min(throughputs, key=lambda x: x[1])[0]
        current_lrf = metrics[min_conn_id]["current_params"]["loss_reduction_factor"]
        decisions[min_conn_id] = {"loss_reduction_factor": max(0.3, current_lrf - 0.05)}

    return decisions
```

---

## 15. Synthesizer Implementation

The synthesizers generate realistic traffic patterns for each application type. The following code matches the logic from the `/code` directory.

### 15.1 Base Synthesizer (`synthesizers/base.py`)

```python
"""
Base synthesizer module.

Provides abstract base class for all data synthesizers and a factory
for creating synthesizers by application type.
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional, Dict, Any


@dataclass
class DataPacket:
    """
    Represents a packet of synthesized data.

    Attributes:
        data: The raw bytes to transmit.
        size: Size of the data in bytes.
        timestamp: When the packet was generated.
        packet_type: Type identifier (e.g., "I-frame", "P-frame", "audio").
        sequence: Sequence number for ordering.
        metadata: Additional application-specific data.
    """

    data: bytes
    size: int
    timestamp: float
    packet_type: str = "data"
    sequence: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseSynthesizer(ABC):
    """
    Abstract base class for data synthesizers.

    Synthesizers generate realistic data patterns for different
    application types (video streaming, file transfer, conference calls).
    """

    def __init__(
        self,
        duration_seconds: float = 10.0,
        target_bitrate: Optional[int] = None,
    ):
        """
        Initialize the synthesizer.

        Args:
            duration_seconds: How long to generate data for.
            target_bitrate: Target bitrate in bits per second (optional).
        """
        self.duration_seconds = duration_seconds
        self.target_bitrate = target_bitrate
        self._sequence = 0

    @abstractmethod
    async def generate(self) -> AsyncIterator[DataPacket]:
        """
        Generate data packets.

        Yields:
            DataPacket objects at appropriate intervals.
        """
        pass

    def _next_sequence(self) -> int:
        """Get the next sequence number."""
        seq = self._sequence
        self._sequence += 1
        return seq

    @property
    @abstractmethod
    def application_type(self) -> str:
        """Return the application type identifier."""
        pass


class SynthesizerFactory:
    """Factory for creating synthesizers by application type."""

    _synthesizers: Dict[str, type] = {}

    @classmethod
    def register(cls, name: str, synthesizer_class: type):
        """Register a synthesizer class."""
        cls._synthesizers[name] = synthesizer_class

    @classmethod
    def create(
        cls,
        application_type: str,
        duration_seconds: float = 10.0,
        **kwargs,
    ) -> BaseSynthesizer:
        """
        Create a synthesizer instance.

        Args:
            application_type: Type of application (video_streaming, file_transfer, conference_call).
            duration_seconds: Duration to generate data for.
            **kwargs: Additional arguments for the synthesizer.

        Returns:
            A synthesizer instance.

        Raises:
            ValueError: If application_type is not registered.
        """
        if application_type not in cls._synthesizers:
            raise ValueError(
                f"Unknown application type: {application_type}. "
                f"Available: {list(cls._synthesizers.keys())}"
            )

        return cls._synthesizers[application_type](
            duration_seconds=duration_seconds, **kwargs
        )

    @classmethod
    def available_types(cls) -> list:
        """Return list of available application types."""
        return list(cls._synthesizers.keys())
```

### 15.2 Video Streaming Synthesizer (`synthesizers/video_streaming.py`)

```python
"""
Video streaming synthesizer.

Generates data patterns that mimic video streaming traffic with
I-frames and P-frames at realistic intervals.
"""

import asyncio
import time
from typing import AsyncIterator

from .base import BaseSynthesizer, DataPacket, SynthesizerFactory


class VideoStreamingSynthesizer(BaseSynthesizer):
    """
    Synthesizer for video streaming data.

    Generates I-frames (keyframes) and P-frames (delta frames) at
    realistic video streaming rates. Default configuration mimics
    720p video at 30fps with periodic keyframes.

    Traffic Pattern:
    - 30 fps (frames per second)
    - I-frames (keyframes): ~50KB every 60 frames (2 seconds)
    - P-frames (delta): ~5KB between I-frames
    - Total bitrate: approximately 5-6 Mbps
    """

    # Frame sizes in bytes
    I_FRAME_SIZE = 50_000  # ~50 KB for keyframes
    P_FRAME_SIZE = 5_000  # ~5 KB for delta frames

    # Timing
    FPS = 30
    FRAME_INTERVAL = 1.0 / FPS  # ~33ms between frames
    KEYFRAME_INTERVAL = 60  # I-frame every 60 frames (2 seconds)

    def __init__(
        self,
        duration_seconds: float = 10.0,
        fps: int = 30,
        i_frame_size: int = 50_000,
        p_frame_size: int = 5_000,
        keyframe_interval: int = 60,
    ):
        """
        Initialize video streaming synthesizer.

        Args:
            duration_seconds: Duration of the video stream.
            fps: Frames per second.
            i_frame_size: Size of I-frames (keyframes) in bytes.
            p_frame_size: Size of P-frames (delta frames) in bytes.
            keyframe_interval: Number of frames between keyframes.
        """
        super().__init__(duration_seconds=duration_seconds)
        self.fps = fps
        self.i_frame_size = i_frame_size
        self.p_frame_size = p_frame_size
        self.keyframe_interval = keyframe_interval
        self.frame_interval = 1.0 / fps

    async def generate(self) -> AsyncIterator[DataPacket]:
        """
        Generate video streaming packets.

        Yields I-frames at keyframe intervals and P-frames in between,
        maintaining consistent frame timing.
        """
        start_time = time.time()
        frame_count = 0

        while (time.time() - start_time) < self.duration_seconds:
            frame_start = time.time()

            # Determine frame type
            is_keyframe = (frame_count % self.keyframe_interval) == 0

            if is_keyframe:
                # I-frame (keyframe)
                frame_type = "I-frame"
                frame_size = self.i_frame_size
            else:
                # P-frame (delta)
                frame_type = "P-frame"
                frame_size = self.p_frame_size

            # Generate frame data
            data = bytes(frame_size)

            yield DataPacket(
                data=data,
                size=frame_size,
                timestamp=time.time(),
                packet_type=frame_type,
                sequence=self._next_sequence(),
                metadata={
                    "frame_number": frame_count,
                    "is_keyframe": is_keyframe,
                },
            )

            frame_count += 1

            # Wait for next frame timing
            elapsed = time.time() - frame_start
            sleep_time = max(0, self.frame_interval - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    @property
    def application_type(self) -> str:
        return "video_streaming"


# Register with factory
SynthesizerFactory.register("video_streaming", VideoStreamingSynthesizer)
```

### 15.3 File Transfer Synthesizer (`synthesizers/file_transfer.py`)

```python
"""
File transfer synthesizer.

Generates data patterns that mimic bulk file transfers,
sending data as fast as the congestion window allows.
"""

import asyncio
import time
from typing import AsyncIterator

from .base import BaseSynthesizer, DataPacket, SynthesizerFactory


class FileTransferSynthesizer(BaseSynthesizer):
    """
    Synthesizer for file transfer data.

    Generates continuous data chunks that simulate bulk file transfers.
    This pattern sends data as fast as possible, limited only by the
    QUIC congestion window.

    Traffic Pattern:
    - Large chunks (64KB default)
    - No timing delays between chunks
    - Simulates FTP/SFTP/HTTP file downloads
    - Throughput-hungry, fills available bandwidth
    """

    CHUNK_SIZE = 65_536  # 64 KB chunks

    def __init__(
        self,
        duration_seconds: float = 10.0,
        chunk_size: int = 65_536,
        total_size: int = 10_000_000,  # 10 MB default
    ):
        """
        Initialize file transfer synthesizer.

        Args:
            duration_seconds: Maximum duration (may complete earlier if total_size reached).
            chunk_size: Size of each data chunk in bytes.
            total_size: Total file size to transfer in bytes.
        """
        super().__init__(duration_seconds=duration_seconds)
        self.chunk_size = chunk_size
        self.total_size = total_size

    async def generate(self) -> AsyncIterator[DataPacket]:
        """
        Generate file transfer packets.

        Yields large chunks continuously without delays, simulating
        bulk data transfer that utilizes full bandwidth.
        """
        start_time = time.time()
        bytes_sent = 0
        chunk_number = 0

        while bytes_sent < self.total_size and (
            time.time() - start_time
        ) < self.duration_seconds:
            # Calculate chunk size (may be smaller for final chunk)
            remaining = self.total_size - bytes_sent
            current_chunk_size = min(self.chunk_size, remaining)

            # Generate chunk data
            data = bytes(current_chunk_size)

            yield DataPacket(
                data=data,
                size=current_chunk_size,
                timestamp=time.time(),
                packet_type="file_chunk",
                sequence=self._next_sequence(),
                metadata={
                    "chunk_number": chunk_number,
                    "bytes_sent": bytes_sent,
                    "total_size": self.total_size,
                    "progress": bytes_sent / self.total_size,
                },
            )

            bytes_sent += current_chunk_size
            chunk_number += 1

            # Yield control to event loop without delay
            # This allows sending as fast as congestion window permits
            await asyncio.sleep(0)

    @property
    def application_type(self) -> str:
        return "file_transfer"


# Register with factory
SynthesizerFactory.register("file_transfer", FileTransferSynthesizer)
```

### 15.4 Conference Call Synthesizer (`synthesizers/conference_call.py`)

```python
"""
Conference call synthesizer.

Generates data patterns that mimic real-time audio/video conferencing
with strict timing requirements.
"""

import asyncio
import time
from typing import AsyncIterator

from .base import BaseSynthesizer, DataPacket, SynthesizerFactory


class ConferenceCallSynthesizer(BaseSynthesizer):
    """
    Synthesizer for conference call data.

    Generates small, frequent packets that simulate real-time
    communication (WebRTC, Zoom, Teams). This traffic is sensitive
    to latency and jitter.

    Traffic Pattern:
    - Small packets (~320 bytes for 128kbps audio)
    - Strict timing: 20ms intervals (50 packets/sec)
    - Bidirectional (requires echo from server)
    - Low latency requirements
    - Jitter-sensitive

    Audio Codec Simulation:
    - 128 kbps audio = 16,000 bytes/sec
    - 50 packets/sec = 320 bytes/packet
    """

    # Audio packet parameters
    PACKET_SIZE = 320  # bytes (128kbps / 50pps)
    PACKET_INTERVAL = 0.020  # 20ms between packets

    def __init__(
        self,
        duration_seconds: float = 10.0,
        packet_size: int = 320,
        packet_interval: float = 0.020,
    ):
        """
        Initialize conference call synthesizer.

        Args:
            duration_seconds: Duration of the call.
            packet_size: Size of each audio packet in bytes.
            packet_interval: Time between packets in seconds.
        """
        super().__init__(duration_seconds=duration_seconds)
        self.packet_size = packet_size
        self.packet_interval = packet_interval

    async def generate(self) -> AsyncIterator[DataPacket]:
        """
        Generate conference call packets.

        Yields small audio packets at precise intervals,
        simulating real-time voice communication.
        """
        start_time = time.time()
        packet_count = 0

        while (time.time() - start_time) < self.duration_seconds:
            packet_start = time.time()

            # Generate audio packet
            data = bytes(self.packet_size)

            yield DataPacket(
                data=data,
                size=self.packet_size,
                timestamp=time.time(),
                packet_type="audio",
                sequence=self._next_sequence(),
                metadata={
                    "packet_number": packet_count,
                    "codec": "opus_128kbps",
                    "realtime": True,
                },
            )

            packet_count += 1

            # Precise timing is critical for conference calls
            # Calculate exact sleep time to maintain interval
            elapsed = time.time() - packet_start
            sleep_time = max(0, self.packet_interval - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    @property
    def application_type(self) -> str:
        return "conference_call"


# Register with factory
SynthesizerFactory.register("conference_call", ConferenceCallSynthesizer)
```

### 15.5 Synthesizer Package Init (`synthesizers/__init__.py`)

```python
"""
Synthesizers package.

Provides data generators for different application types:
- Video streaming: I-frames and P-frames at 30fps
- File transfer: Bulk data as fast as congestion allows
- Conference call: Small packets every 20ms
"""

from .base import BaseSynthesizer, DataPacket, SynthesizerFactory
from .video_streaming import VideoStreamingSynthesizer
from .file_transfer import FileTransferSynthesizer
from .conference_call import ConferenceCallSynthesizer

__all__ = [
    "BaseSynthesizer",
    "DataPacket",
    "SynthesizerFactory",
    "VideoStreamingSynthesizer",
    "FileTransferSynthesizer",
    "ConferenceCallSynthesizer",
]
```

---

## 16. QUIC Client/Server Implementation

The QUIC client and server implementations match the patterns from the `/code` directory.

### 16.1 Client Protocol (`simulation/client.py`)

```python
"""
QUIC client implementation for the research project.

The client connects to the server, opens 3 streams, and sends
synthesized data while collecting metrics.
"""

import asyncio
import time
from typing import Optional, List, AsyncIterator
from pathlib import Path

from aioquic.asyncio import connect, QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, HandshakeCompleted

from synthesizers.base import DataPacket
from metrics.collector import MetricsCollector


class ClientProtocol(QuicConnectionProtocol):
    """
    QUIC client protocol handler.

    Handles stream operations and tracks metrics during
    data transmission.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.handshake_complete = asyncio.Event()
        self.streams_opened: List[int] = []
        self.bytes_received = 0
        self.receive_timestamps: List[float] = []

    def quic_event_received(self, event):
        """Handle QUIC events."""
        if isinstance(event, HandshakeCompleted):
            self.handshake_complete.set()

        elif isinstance(event, StreamDataReceived):
            self.bytes_received += len(event.data)
            self.receive_timestamps.append(time.time())

    async def wait_handshake(self, timeout: float = 10.0):
        """Wait for handshake to complete."""
        await asyncio.wait_for(self.handshake_complete.wait(), timeout=timeout)

    def open_stream(self) -> int:
        """
        Open a new bidirectional stream.

        Returns:
            The stream ID.
        """
        stream_id = self._quic.get_next_available_stream_id()
        self.streams_opened.append(stream_id)
        return stream_id

    def send_data(self, stream_id: int, data: bytes, end_stream: bool = False):
        """
        Send data on a stream.

        Args:
            stream_id: The stream to send on.
            data: The data to send.
            end_stream: Whether to close the stream after sending.
        """
        self._quic.send_stream_data(stream_id, data, end_stream=end_stream)

    def get_rtt(self) -> Optional[float]:
        """Get the current smoothed RTT."""
        try:
            return self._quic._loss._rtt_smoothed
        except AttributeError:
            return None

    def get_connection_stats(self) -> dict:
        """Get connection statistics."""
        try:
            loss = self._quic._loss
            return {
                "rtt_smoothed": getattr(loss, "_rtt_smoothed", 0),
                "rtt_min": getattr(loss, "_rtt_min", 0),
                "congestion_window": getattr(loss, "congestion_window", 0),
                "bytes_in_flight": getattr(loss, "bytes_in_flight", 0),
            }
        except AttributeError:
            return {}


class QuicClient:
    """
    QUIC client for sending synthesized data.

    The client connects to a server, opens 3 streams as required,
    and sends data through one of them while collecting metrics.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 4433,
        max_ack_delay: float = 0.025,
        verify_cert: bool = False,
    ):
        """
        Initialize the QUIC client.

        Args:
            host: Server host to connect to.
            port: Server port.
            max_ack_delay: Maximum ACK delay in seconds.
            verify_cert: Whether to verify server certificate.
        """
        self.host = host
        self.port = port
        self.max_ack_delay = max_ack_delay
        self.verify_cert = verify_cert

        self._protocol: Optional[ClientProtocol] = None
        self._connection_cm = None
        self._metrics_collector: Optional[MetricsCollector] = None

    async def connect(self) -> ClientProtocol:
        """
        Connect to the QUIC server.

        Returns:
            The client protocol instance.
        """
        configuration = QuicConfiguration(
            is_client=True,
            max_datagram_frame_size=65536,
        )

        # Set max ACK delay
        configuration.max_ack_delay = self.max_ack_delay

        # Disable certificate verification for testing
        if not self.verify_cert:
            configuration.verify_mode = False

        # connect() returns an async context manager
        # Store it so we can properly close it later
        self._connection_cm = connect(
            self.host,
            self.port,
            configuration=configuration,
            create_protocol=ClientProtocol,
        )
        # Enter the context manager
        self._protocol = await self._connection_cm.__aenter__()

        # Wait for handshake
        await self._protocol.wait_handshake()

        return self._protocol

    async def open_streams(self, count: int = 3) -> List[int]:
        """
        Open multiple streams.

        Args:
            count: Number of streams to open.

        Returns:
            List of stream IDs.
        """
        if self._protocol is None:
            raise RuntimeError("Not connected. Call connect() first.")

        stream_ids = []
        for _ in range(count):
            stream_id = self._protocol.open_stream()
            stream_ids.append(stream_id)

        return stream_ids

    async def send_synthesized_data(
        self,
        stream_id: int,
        data_generator: AsyncIterator[DataPacket],
        metrics_collector: Optional[MetricsCollector] = None,
    ) -> int:
        """
        Send synthesized data through a stream.

        Args:
            stream_id: The stream to send on.
            data_generator: Async generator yielding DataPacket objects.
            metrics_collector: Optional metrics collector for recording.

        Returns:
            Total bytes sent.
        """
        if self._protocol is None:
            raise RuntimeError("Not connected. Call connect() first.")

        self._metrics_collector = metrics_collector
        total_bytes = 0

        async for packet in data_generator:
            # Send the packet
            self._protocol.send_data(stream_id, packet.data)
            total_bytes += packet.size

            # Record metrics
            if metrics_collector:
                metrics_collector.record_packet_sent(packet.size)

                # Sample RTT periodically
                rtt = self._protocol.get_rtt()
                if rtt is not None and rtt > 0:
                    metrics_collector.record_rtt_sample(rtt)

            # Allow event loop to process
            await asyncio.sleep(0)

        return total_bytes

    async def close(self):
        """Close the connection."""
        if self._connection_cm:
            try:
                await self._connection_cm.__aexit__(None, None, None)
            except Exception:
                pass  # Ignore errors during cleanup

    def get_protocol(self) -> Optional[ClientProtocol]:
        """Get the current protocol instance."""
        return self._protocol
```

### 16.2 Server Implementation (`simulation/server.py`)

```python
"""
QUIC server implementation for the research project.

The server accepts connections, opens 3 streams, and receives
synthesized data from clients for metric collection.
"""

import asyncio
from typing import Optional, Dict, Callable, Any
from pathlib import Path

from aioquic.asyncio import serve, QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, HandshakeCompleted, ConnectionTerminated


class ServerProtocol(QuicConnectionProtocol):
    """
    QUIC server protocol handler.

    Handles incoming connections and stream data, collecting
    metrics during data reception.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.streams: Dict[int, bytes] = {}
        self.total_bytes_received = 0
        self.handshake_complete = False
        self._data_received_callback: Optional[Callable] = None
        self._connection_callback: Optional[Callable] = None

    def set_data_received_callback(self, callback: Callable):
        """Set callback for when data is received."""
        self._data_received_callback = callback

    def set_connection_callback(self, callback: Callable):
        """Set callback for connection events."""
        self._connection_callback = callback

    def quic_event_received(self, event):
        """Handle QUIC events."""
        if isinstance(event, HandshakeCompleted):
            self.handshake_complete = True
            if self._connection_callback:
                self._connection_callback("handshake_complete")

        elif isinstance(event, StreamDataReceived):
            # Accumulate stream data
            stream_id = event.stream_id
            if stream_id not in self.streams:
                self.streams[stream_id] = b""
            self.streams[stream_id] += event.data
            self.total_bytes_received += len(event.data)

            # Notify callback
            if self._data_received_callback:
                self._data_received_callback(stream_id, len(event.data))

            # Echo back for bidirectional testing (conference calls)
            # Only echo on bidirectional streams (even stream IDs from client)
            if stream_id % 4 == 0:  # Client-initiated bidirectional
                # Send acknowledgment
                self._quic.send_stream_data(stream_id, b"ACK", end_stream=False)

        elif isinstance(event, ConnectionTerminated):
            if self._connection_callback:
                self._connection_callback("connection_terminated")


class QuicServer:
    """
    QUIC server for receiving synthesized data.

    The server listens for connections, receives data on streams,
    and optionally echoes data back for bidirectional testing.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 4433,
        cert_file: str = "certs/cert.pem",
        key_file: str = "certs/key.pem",
        max_ack_delay: float = 0.025,
    ):
        """
        Initialize the QUIC server.

        Args:
            host: Host to bind to.
            port: Port to listen on.
            cert_file: Path to TLS certificate file.
            key_file: Path to TLS private key file.
            max_ack_delay: Maximum ACK delay in seconds.
        """
        self.host = host
        self.port = port
        self.cert_file = Path(cert_file)
        self.key_file = Path(key_file)
        self.max_ack_delay = max_ack_delay

        self._server = None
        self._protocols: list = []
        self._running = False

    def _create_protocol(self, *args, **kwargs) -> ServerProtocol:
        """Create a new server protocol instance."""
        protocol = ServerProtocol(*args, **kwargs)
        self._protocols.append(protocol)
        return protocol

    async def start(self):
        """Start the QUIC server."""
        configuration = QuicConfiguration(
            is_client=False,
            max_datagram_frame_size=65536,
        )

        # Load certificates
        configuration.load_cert_chain(
            str(self.cert_file),
            str(self.key_file),
        )

        # Set max ACK delay
        configuration.max_ack_delay = self.max_ack_delay

        # serve() is a coroutine that returns a Server object
        self._server = await serve(
            self.host,
            self.port,
            configuration=configuration,
            create_protocol=self._create_protocol,
        )
        self._running = True

    async def stop(self):
        """Stop the QUIC server."""
        if self._server:
            self._server.close()
            self._running = False

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    def get_total_bytes_received(self) -> int:
        """Get total bytes received across all connections."""
        return sum(p.total_bytes_received for p in self._protocols)
```

---

## 17. Metrics Implementation

The metrics collection and calculation code matches the `/code` directory.

### 17.1 Metrics Calculator (`metrics/calculator.py`)

```python
"""
Metrics calculation utilities.

Provides functions for calculating the 6 key performance metrics
from raw measurement data.
"""

import statistics
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class MetricsResult:
    """Container for calculated metrics."""

    throughput: float  # bytes per second
    rtt: float  # round-trip time in seconds
    latency: float  # one-way latency in seconds (estimated as RTT / 2)
    jitter: float  # jitter in seconds
    packet_loss_rate: float  # percentage (0.0 to 1.0)
    connection_establishment_time: float  # seconds

    def to_dict(self) -> dict:
        """Convert to dictionary for export."""
        return {
            "throughput": self.throughput,
            "rtt": self.rtt,
            "latency": self.latency,
            "jitter": self.jitter,
            "packet_loss_rate": self.packet_loss_rate,
            "connection_establishment_time": self.connection_establishment_time,
        }


class MetricsCalculator:
    """
    Calculates performance metrics from raw data.

    The 6 metrics are:
    1. Throughput: Data transfer rate (bytes/second)
    2. RTT: Round-trip time (seconds)
    3. Latency: One-way latency estimated as RTT/2 (seconds)
    4. Jitter: Variation in packet delay (seconds)
    5. Packet Loss Rate: Percentage of lost packets
    6. Connection Establishment Time: Time for initial handshake
    """

    @staticmethod
    def calculate_throughput(
        total_bytes: int,
        duration_seconds: float,
    ) -> float:
        """
        Calculate throughput in bytes per second.

        Args:
            total_bytes: Total bytes transferred.
            duration_seconds: Duration of the transfer.

        Returns:
            Throughput in bytes per second.
        """
        if duration_seconds <= 0:
            return 0.0
        return total_bytes / duration_seconds

    @staticmethod
    def calculate_jitter(
        packet_timestamps: List[float],
        expected_interval: Optional[float] = None,
    ) -> float:
        """
        Calculate jitter (variation in inter-packet delay).

        Jitter is calculated as the standard deviation of the
        inter-packet delays. For applications like conference calls,
        low jitter is critical for quality.

        Args:
            packet_timestamps: List of packet receive timestamps.
            expected_interval: Optional expected interval between packets.

        Returns:
            Jitter in seconds (standard deviation of delays).
        """
        if len(packet_timestamps) < 2:
            return 0.0

        # Calculate inter-packet delays
        delays = []
        for i in range(1, len(packet_timestamps)):
            delay = packet_timestamps[i] - packet_timestamps[i - 1]
            delays.append(delay)

        if len(delays) < 2:
            return 0.0

        # Jitter is the standard deviation of delays
        try:
            return statistics.stdev(delays)
        except statistics.StatisticsError:
            return 0.0

    @staticmethod
    def calculate_packet_loss_rate(
        packets_sent: int,
        packets_received: int,
    ) -> float:
        """
        Calculate packet loss rate.

        Args:
            packets_sent: Number of packets sent.
            packets_received: Number of packets received (acknowledged).

        Returns:
            Packet loss rate as a fraction (0.0 to 1.0).
        """
        if packets_sent <= 0:
            return 0.0

        packets_lost = packets_sent - packets_received
        if packets_lost < 0:
            packets_lost = 0

        return packets_lost / packets_sent

    @staticmethod
    def calculate_latency(rtt: float) -> float:
        """
        Calculate estimated one-way latency from RTT.

        Latency is estimated as RTT / 2, assuming a symmetric network path.
        This is a reasonable approximation for localhost testing and symmetric
        networks. For asymmetric networks, actual one-way latency may differ.

        Note: This measures pure network/QUIC latency. Real-world application
        latency would include processing overhead (encoding, decoding, etc.)
        which is negligible with synthetic data but significant (~5-20ms) with
        real data.

        Args:
            rtt: Round-trip time in seconds.

        Returns:
            Estimated one-way latency in seconds.
        """
        if rtt <= 0:
            return 0.0
        return rtt / 2

    @staticmethod
    def calculate_all(
        total_bytes: int,
        duration_seconds: float,
        rtt_samples: List[float],
        packet_timestamps: List[float],
        packets_sent: int,
        packets_received: int,
        connection_time: float,
    ) -> MetricsResult:
        """
        Calculate all 6 metrics.

        Args:
            total_bytes: Total bytes transferred.
            duration_seconds: Duration of the transfer.
            rtt_samples: List of RTT measurements.
            packet_timestamps: List of packet receive timestamps.
            packets_sent: Number of packets sent.
            packets_received: Number of packets received.
            connection_time: Time to establish connection.

        Returns:
            MetricsResult with all calculated metrics.
        """
        # Calculate throughput
        throughput = MetricsCalculator.calculate_throughput(
            total_bytes, duration_seconds
        )

        # Calculate average RTT
        if rtt_samples:
            rtt = statistics.mean(rtt_samples)
        else:
            rtt = 0.0

        # Calculate latency (estimated as RTT / 2)
        latency = MetricsCalculator.calculate_latency(rtt)

        # Calculate jitter
        jitter = MetricsCalculator.calculate_jitter(packet_timestamps)

        # Calculate packet loss rate
        packet_loss_rate = MetricsCalculator.calculate_packet_loss_rate(
            packets_sent, packets_received
        )

        return MetricsResult(
            throughput=throughput,
            rtt=rtt,
            latency=latency,
            jitter=jitter,
            packet_loss_rate=packet_loss_rate,
            connection_establishment_time=connection_time,
        )
```

### 17.2 Metrics Collector (`metrics/collector.py`)

```python
"""
Metrics collector for real-time data collection during simulations.

Collects raw data during QUIC simulations and provides methods
to retrieve calculated metrics.
"""

import time
from typing import List, Optional, Any
from dataclasses import dataclass, field

from .calculator import MetricsCalculator, MetricsResult


@dataclass
class MetricsCollector:
    """
    Collects metrics during simulation execution.

    This class is used to record events during a QUIC simulation
    and then calculate the 6 performance metrics:
    - Throughput
    - RTT
    - Latency
    - Jitter
    - Packet Loss Rate
    - Connection Establishment Time
    """

    # Connection reference (for accessing internal metrics)
    connection: Any = None

    # Timing
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    connection_ready_time: Optional[float] = None

    # Byte counters
    bytes_sent: int = 0
    bytes_received: int = 0

    # Packet counters
    packets_sent: int = 0
    packets_received: int = 0
    packets_lost: int = 0

    # Timestamps for jitter calculation
    send_timestamps: List[float] = field(default_factory=list)
    receive_timestamps: List[float] = field(default_factory=list)

    # RTT samples
    rtt_samples: List[float] = field(default_factory=list)

    def start(self):
        """Mark the start of the simulation."""
        self.start_time = time.time()

    def stop(self):
        """Mark the end of the simulation."""
        self.end_time = time.time()

    def record_connection_ready(self):
        """Record when the connection is ready (handshake complete)."""
        self.connection_ready_time = time.time()

    def record_packet_sent(self, size: int):
        """
        Record a sent packet.

        Args:
            size: Size of the packet in bytes.
        """
        self.packets_sent += 1
        self.bytes_sent += size
        self.send_timestamps.append(time.time())

    def record_packet_received(self, size: int = 0):
        """
        Record a received packet (acknowledgment).

        Args:
            size: Size of the packet in bytes (optional).
        """
        self.packets_received += 1
        self.bytes_received += size
        self.receive_timestamps.append(time.time())

    def record_packet_lost(self):
        """Record a lost packet."""
        self.packets_lost += 1

    def record_rtt_sample(self, rtt: float):
        """
        Record an RTT measurement.

        Args:
            rtt: RTT value in seconds.
        """
        self.rtt_samples.append(rtt)

    def sample_connection_rtt(self):
        """
        Sample RTT from the QUIC connection if available.

        This accesses the internal RTT tracking in aioquic.
        """
        if self.connection is not None:
            try:
                # Access aioquic internal RTT metrics
                loss_handler = getattr(self.connection, "_loss", None)
                if loss_handler is not None:
                    rtt = getattr(loss_handler, "_rtt_smoothed", None)
                    if rtt is not None and rtt > 0:
                        self.rtt_samples.append(rtt)
            except (AttributeError, TypeError):
                pass  # Connection doesn't have RTT info

    @property
    def duration(self) -> float:
        """Get the simulation duration in seconds."""
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time else time.time()
        return end - self.start_time

    @property
    def connection_time(self) -> float:
        """Get the connection establishment time in seconds."""
        if self.start_time is None or self.connection_ready_time is None:
            return 0.0
        return self.connection_ready_time - self.start_time

    def calculate_metrics(self) -> MetricsResult:
        """
        Calculate all 6 metrics from collected data.

        Returns:
            MetricsResult with all calculated metrics.
        """
        # Get actual packet loss info from aioquic connection if available
        actual_packets_sent = self.packets_sent
        actual_packets_lost = 0

        if self.connection is not None:
            try:
                loss_handler = getattr(self.connection, "_loss", None)
                if loss_handler is not None:
                    # Get packets lost from aioquic's internal tracking
                    actual_packets_lost = getattr(loss_handler, "_packets_lost", 0)
                    # Use aioquic's sent count if available
                    sent_count = getattr(loss_handler, "_packets_sent", 0)
                    if sent_count > 0:
                        actual_packets_sent = sent_count
            except (AttributeError, TypeError):
                pass

        # Calculate packets_received as sent - lost
        actual_packets_received = max(0, actual_packets_sent - actual_packets_lost)

        return MetricsCalculator.calculate_all(
            total_bytes=self.bytes_sent,
            duration_seconds=self.duration,
            rtt_samples=self.rtt_samples,
            packet_timestamps=self.receive_timestamps or self.send_timestamps,
            packets_sent=actual_packets_sent,
            packets_received=actual_packets_received,
            connection_time=self.connection_time,
        )

    def reset(self):
        """Reset all collected data for a new simulation."""
        self.start_time = None
        self.end_time = None
        self.connection_ready_time = None
        self.bytes_sent = 0
        self.bytes_received = 0
        self.packets_sent = 0
        self.packets_received = 0
        self.packets_lost = 0
        self.send_timestamps = []
        self.receive_timestamps = []
        self.rtt_samples = []

    def get_summary(self) -> dict:
        """
        Get a summary of collected data.

        Returns:
            Dictionary with collection summary.
        """
        return {
            "duration_seconds": self.duration,
            "connection_time_seconds": self.connection_time,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "packets_sent": self.packets_sent,
            "packets_received": self.packets_received,
            "packets_lost": self.packets_lost,
            "rtt_samples_count": len(self.rtt_samples),
        }

    def get_current_metrics(self) -> dict:
        """
        Get current metrics as a raw dictionary for epoch sampling.

        Unlike calculate_metrics() which returns MetricsResult, this returns
        a simple dict suitable for epoch sample recording.

        Field names match what EpochManager._finalize_epoch() expects:
        - throughput_bps (not throughput) for consistency with EpochMetrics
        - rtt, jitter, packet_loss_rate match MetricsResult

        Returns:
            Dictionary with current metric values.
        """
        metrics = self.calculate_metrics()
        return {
            "throughput_bps": metrics.throughput,  # Renamed for EpochMetrics compatibility
            "rtt": metrics.rtt,
            "latency": metrics.latency,
            "jitter": metrics.jitter,
            "packet_loss_rate": metrics.packet_loss_rate,
            "bytes_sent": self.bytes_sent,
            "packets_sent": self.packets_sent,
        }

    def reset_for_new_epoch(self):
        """
        Soft reset for new epoch measurement.

        Unlike reset() which clears everything, this preserves the connection
        and timing info but resets counters for fresh epoch measurement.
        Used by EpochManager when starting a new measurement epoch.
        """
        # Store cumulative values before reset
        self._epoch_bytes_offset = self.bytes_sent
        self._epoch_packets_offset = self.packets_sent

        # Reset per-epoch tracking (but keep cumulative counters)
        # RTT samples are cleared since we want fresh RTT measurements per epoch
        self.rtt_samples = []

        # Keep send/receive timestamps for jitter calculation fresh
        self.send_timestamps = self.send_timestamps[-10:] if self.send_timestamps else []
        self.receive_timestamps = self.receive_timestamps[-10:] if self.receive_timestamps else []
```

### 17.3 Metrics Package Init (`metrics/__init__.py`)

```python
"""
Metrics package.

Provides real-time metrics collection and calculation for QUIC simulations.
"""

from .calculator import MetricsCalculator, MetricsResult
from .collector import MetricsCollector

__all__ = [
    "MetricsCalculator",
    "MetricsResult",
    "MetricsCollector",
]
```

### 17.5 Epoch-Based Metrics Collection (Parameter Change Handling)

When parameters change mid-connection, we need to capture metrics in **epochs** (stable periods) rather than just continuous time series. This ensures:

1. Metrics are measured AFTER the system settles (congestion control adapts)
2. Each epoch links metrics to specific parameter configurations
3. Results are meaningful for comparing parameter effectiveness

#### 17.5.1 The Problem with Continuous Metrics

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    WHY SETTLING TIME MATTERS                                     │
└─────────────────────────────────────────────────────────────────────────────────┘

  Parameter Change at t=10s
         │
         ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │                                                                               │
  │  Throughput                                                                   │
  │  (Mbps)                                                                       │
  │     │                                                                         │
  │  10 ┤     ╭───────╮                       ╭───────────────────────────────    │
  │     │    ╱         ╲         ╭───────────╯                                    │
  │   5 ┤   ╱           ╲       ╱                                                 │
  │     │  ╱             ╲─────╯                                                  │
  │   0 ┼──┴───────┬──────────────────────────────────────────────► Time         │
  │        Epoch 1 │  Settling   │         Epoch 2                               │
  │                │   Period    │                                                │
  │              (DO NOT         (MEASURE HERE)                                   │
  │               MEASURE)                                                        │
  └──────────────────────────────────────────────────────────────────────────────┘

  After parameter change:
  - CC algorithm needs time to adapt (typically 2-5 RTTs)
  - Queues need to drain/fill to new steady state
  - Measuring during transition gives INVALID data
```

#### 17.5.2 Epoch Data Structure

```python
# metrics/epoch.py

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time
import json


@dataclass
class ParameterSnapshot:
    """Snapshot of all parameters at a point in time."""
    loss_reduction_factor: float
    cubic_c: float
    minimum_window: int
    packet_threshold: int
    time_threshold: float
    cubic_max_idle_time: float

    # Start-only parameters (for reference)
    initial_cw: int
    max_ack_delay: float
    max_data: int
    max_stream_data: int

    def to_dict(self) -> dict:
        return {
            "dynamic": {
                "loss_reduction_factor": self.loss_reduction_factor,
                "cubic_c": self.cubic_c,
                "minimum_window": self.minimum_window,
                "packet_threshold": self.packet_threshold,
                "time_threshold": self.time_threshold,
                "cubic_max_idle_time": self.cubic_max_idle_time,
            },
            "start_only": {
                "initial_cw": self.initial_cw,
                "max_ack_delay": self.max_ack_delay,
                "max_data": self.max_data,
                "max_stream_data": self.max_stream_data,
            },
        }


@dataclass
class EpochMetrics:
    """Metrics collected during a stable parameter epoch."""
    throughput_bps: float
    avg_rtt_seconds: float
    min_rtt_seconds: float
    max_rtt_seconds: float
    jitter_seconds: float
    packet_loss_rate: float
    bytes_sent: int
    bytes_received: int
    packets_sent: int
    packets_lost: int

    def to_dict(self) -> dict:
        return {
            "throughput_bps": self.throughput_bps,
            "throughput_mbps": self.throughput_bps / 1_000_000,
            "avg_rtt_ms": self.avg_rtt_seconds * 1000,
            "min_rtt_ms": self.min_rtt_seconds * 1000,
            "max_rtt_ms": self.max_rtt_seconds * 1000,
            "jitter_ms": self.jitter_seconds * 1000,
            "packet_loss_rate": self.packet_loss_rate,
            "packet_loss_percent": self.packet_loss_rate * 100,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "packets_sent": self.packets_sent,
            "packets_lost": self.packets_lost,
        }


@dataclass
class Epoch:
    """
    A single epoch representing a stable period with fixed parameters.

    An epoch starts when:
    - Connection begins (epoch 0)
    - Parameters change (epoch N, after settling)

    An epoch ends when:
    - Parameters change again
    - Connection ends
    """
    epoch_id: int
    connection_id: int
    application_type: str

    # Timing
    start_time: float  # Epoch start (after settling if not first)
    end_time: Optional[float] = None
    settling_start: Optional[float] = None  # When param change occurred
    settling_duration: float = 0.0  # How long we waited

    # Parameters for this epoch
    parameters: Optional[ParameterSnapshot] = None

    # Network conditions
    network_scenario: str = ""
    network_config: Dict = field(default_factory=dict)

    # Metrics (calculated after epoch ends)
    metrics: Optional[EpochMetrics] = None

    # Raw samples collected during this epoch (for detailed analysis)
    raw_samples: List[Dict] = field(default_factory=list)

    @property
    def duration(self) -> float:
        """Duration of this epoch (excluding settling time)."""
        if self.end_time is None:
            return time.time() - self.start_time
        return self.end_time - self.start_time

    @property
    def is_valid(self) -> bool:
        """Epoch is valid if it has enough measurement time."""
        MIN_MEASUREMENT_TIME = 2.0  # At least 2 seconds of data
        return self.duration >= MIN_MEASUREMENT_TIME

    def to_dict(self) -> dict:
        return {
            "epoch_id": self.epoch_id,
            "connection_id": self.connection_id,
            "application_type": self.application_type,
            "timing": {
                "start_time": self.start_time,
                "end_time": self.end_time,
                "duration_seconds": self.duration,
                "settling_start": self.settling_start,
                "settling_duration_seconds": self.settling_duration,
            },
            "parameters": self.parameters.to_dict() if self.parameters else None,
            "network": {
                "scenario": self.network_scenario,
                "config": self.network_config,
            },
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "is_valid": self.is_valid,
            "sample_count": len(self.raw_samples),
        }


@dataclass
class ConnectionEpochHistory:
    """Complete epoch history for a single connection."""
    connection_id: int
    application_type: str
    epochs: List[Epoch] = field(default_factory=list)

    def add_epoch(self, epoch: Epoch):
        self.epochs.append(epoch)

    def get_valid_epochs(self) -> List[Epoch]:
        """Return only epochs with sufficient measurement time."""
        return [e for e in self.epochs if e.is_valid]

    def to_dict(self) -> dict:
        return {
            "connection_id": self.connection_id,
            "application_type": self.application_type,
            "total_epochs": len(self.epochs),
            "valid_epochs": len(self.get_valid_epochs()),
            "epochs": [e.to_dict() for e in self.epochs],
        }

    def export_json(self, path: str):
        """Export to JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
```

#### 17.5.3 Epoch Manager

```python
# metrics/epoch_manager.py

import time
from typing import Dict, Optional, Callable
from dataclasses import dataclass

from .epoch import Epoch, EpochMetrics, ParameterSnapshot, ConnectionEpochHistory
from .collector import MetricsCollector


@dataclass
class EpochConfig:
    """Configuration for epoch management."""
    settling_time: float = 2.0  # Seconds to wait after param change
    min_epoch_duration: float = 2.0  # Minimum measurement time
    sample_interval: float = 0.1  # How often to collect samples


class EpochManager:
    """
    Manages epoch-based metrics collection for a connection.

    Handles:
    - Detecting parameter changes
    - Waiting for settling time
    - Collecting metrics during stable periods
    - Finalizing epochs when parameters change or connection ends
    """

    def __init__(
        self,
        connection_id: int,
        application_type: str,
        network_scenario: str,
        network_config: dict,
        initial_params: ParameterSnapshot,
        config: EpochConfig = None,
    ):
        self.connection_id = connection_id
        self.application_type = application_type
        self.network_scenario = network_scenario
        self.network_config = network_config
        self.config = config or EpochConfig()

        self.history = ConnectionEpochHistory(
            connection_id=connection_id,
            application_type=application_type,
        )

        self._current_epoch: Optional[Epoch] = None
        self._current_params = initial_params
        self._metrics_collector: Optional[MetricsCollector] = None
        self._settling = False
        self._settling_end_time: float = 0

    def set_metrics_collector(self, collector: MetricsCollector):
        """Set the metrics collector to sample from."""
        self._metrics_collector = collector

    def start(self):
        """Start the first epoch."""
        self._current_epoch = Epoch(
            epoch_id=0,
            connection_id=self.connection_id,
            application_type=self.application_type,
            start_time=time.time(),
            parameters=self._current_params,
            network_scenario=self.network_scenario,
            network_config=self.network_config,
        )

    def on_parameter_change(self, new_params: ParameterSnapshot):
        """
        Called when parameters change.

        1. Finalize current epoch (calculate metrics from samples)
        2. Enter settling period
        3. Start new epoch after settling
        """
        now = time.time()

        # Finalize current epoch
        if self._current_epoch:
            self._current_epoch.end_time = now
            self._finalize_epoch(self._current_epoch)
            self.history.add_epoch(self._current_epoch)

        # Enter settling period
        self._settling = True
        self._settling_end_time = now + self.config.settling_time
        self._current_params = new_params

        # Prepare next epoch (will start after settling)
        next_epoch_id = len(self.history.epochs)
        self._current_epoch = Epoch(
            epoch_id=next_epoch_id,
            connection_id=self.connection_id,
            application_type=self.application_type,
            settling_start=now,
            settling_duration=self.config.settling_time,
            start_time=self._settling_end_time,  # Will start after settling
            parameters=new_params,
            network_scenario=self.network_scenario,
            network_config=self.network_config,
        )

    def collect_sample(self):
        """
        Collect a metric sample if not in settling period.
        Called periodically (e.g., every 100ms).
        """
        now = time.time()

        # Check if settling period ended
        if self._settling and now >= self._settling_end_time:
            self._settling = False
            # Reset metrics collector for fresh epoch data
            if self._metrics_collector:
                self._metrics_collector.reset_for_new_epoch()

        # Don't collect during settling
        if self._settling:
            return

        # Collect sample
        if self._current_epoch and self._metrics_collector:
            metrics = self._metrics_collector.get_current_metrics()
            self._current_epoch.raw_samples.append({
                "timestamp": now,
                "elapsed": now - self._current_epoch.start_time,
                **metrics,
            })

    def is_settling(self) -> bool:
        """Return True if currently in settling period."""
        return self._settling

    def finalize(self):
        """Finalize the current epoch when connection ends."""
        if self._current_epoch:
            self._current_epoch.end_time = time.time()
            self._finalize_epoch(self._current_epoch)
            self.history.add_epoch(self._current_epoch)
            self._current_epoch = None

    def _finalize_epoch(self, epoch: Epoch):
        """Calculate final metrics for an epoch from its samples."""
        if not epoch.raw_samples:
            return

        # Calculate aggregated metrics from samples
        samples = epoch.raw_samples

        throughputs = [s.get("throughput_bps", 0) for s in samples]
        rtts = [s.get("rtt", 0) for s in samples if s.get("rtt", 0) > 0]
        jitters = [s.get("jitter", 0) for s in samples]

        # Use last sample for cumulative values
        last_sample = samples[-1]
        first_sample = samples[0]

        epoch.metrics = EpochMetrics(
            throughput_bps=sum(throughputs) / len(throughputs) if throughputs else 0,
            avg_rtt_seconds=sum(rtts) / len(rtts) if rtts else 0,
            min_rtt_seconds=min(rtts) if rtts else 0,
            max_rtt_seconds=max(rtts) if rtts else 0,
            jitter_seconds=sum(jitters) / len(jitters) if jitters else 0,
            packet_loss_rate=last_sample.get("packet_loss_rate", 0),
            bytes_sent=last_sample.get("bytes_sent", 0) - first_sample.get("bytes_sent", 0),
            bytes_received=last_sample.get("bytes_received", 0) - first_sample.get("bytes_received", 0),
            packets_sent=last_sample.get("packets_sent", 0) - first_sample.get("packets_sent", 0),
            packets_lost=last_sample.get("packets_lost", 0) - first_sample.get("packets_lost", 0),
        )

    def get_history(self) -> ConnectionEpochHistory:
        """Get the complete epoch history."""
        return self.history
```

#### 17.5.4 Example JSON Output

When epochs are exported, the JSON structure looks like:

```json
{
  "connection_id": 1,
  "application_type": "video_streaming",
  "total_epochs": 3,
  "valid_epochs": 3,
  "epochs": [
    {
      "epoch_id": 0,
      "connection_id": 1,
      "application_type": "video_streaming",
      "timing": {
        "start_time": 1706745600.0,
        "end_time": 1706745610.0,
        "duration_seconds": 10.0,
        "settling_start": null,
        "settling_duration_seconds": 0.0
      },
      "parameters": {
        "dynamic": {
          "loss_reduction_factor": 0.5,
          "cubic_c": 0.4,
          "minimum_window": 2,
          "packet_threshold": 3,
          "time_threshold": 1.125,
          "cubic_max_idle_time": 2.0
        },
        "start_only": {
          "initial_cw": 12000,
          "max_ack_delay": 0.025,
          "max_data": 1048576,
          "max_stream_data": 1048576
        }
      },
      "network": {
        "scenario": "congested_low",
        "config": {
          "bandwidth_mbps": 5,
          "rtt_ms": 30,
          "loss_percent": 2
        }
      },
      "metrics": {
        "throughput_bps": 4250000,
        "throughput_mbps": 4.25,
        "avg_rtt_ms": 32.5,
        "min_rtt_ms": 30.1,
        "max_rtt_ms": 45.2,
        "jitter_ms": 3.2,
        "packet_loss_rate": 0.021,
        "packet_loss_percent": 2.1,
        "bytes_sent": 5312500,
        "bytes_received": 5200000,
        "packets_sent": 4250,
        "packets_lost": 89
      },
      "is_valid": true,
      "sample_count": 100
    },
    {
      "epoch_id": 1,
      "connection_id": 1,
      "application_type": "video_streaming",
      "timing": {
        "start_time": 1706745612.0,
        "end_time": 1706745622.0,
        "duration_seconds": 10.0,
        "settling_start": 1706745610.0,
        "settling_duration_seconds": 2.0
      },
      "parameters": {
        "dynamic": {
          "loss_reduction_factor": 0.7,
          "cubic_c": 0.4,
          "minimum_window": 2,
          "packet_threshold": 3,
          "time_threshold": 1.125,
          "cubic_max_idle_time": 2.0
        },
        "start_only": { "..." : "..." }
      },
      "network": { "..." : "..." },
      "metrics": {
        "throughput_bps": 3800000,
        "throughput_mbps": 3.80,
        "avg_rtt_ms": 35.1,
        "..." : "..."
      },
      "is_valid": true,
      "sample_count": 100
    }
  ]
}
```

#### 17.5.5 Integration with ConnectionWorker

```python
# Updated sections of simulation/worker_process.py

class ConnectionWorker:
    """Worker with epoch-based metrics collection."""

    def __init__(self, ...):
        # ... existing init ...

        # Create initial parameter snapshot
        initial_params = ParameterSnapshot(
            loss_reduction_factor=self.config.loss_reduction_factor,
            cubic_c=self.config.cubic_c,
            minimum_window=self.config.minimum_window,
            packet_threshold=self.config.packet_threshold,
            time_threshold=self.config.time_threshold,
            cubic_max_idle_time=self.config.cubic_max_idle_time,
            initial_cw=self.config.initial_cw,
            max_ack_delay=self.config.max_ack_delay,
            max_data=self.config.max_data,
            max_stream_data=self.config.max_stream_data,
        )

        # Initialize epoch manager
        self._epoch_manager = EpochManager(
            connection_id=self.config.connection_id,
            application_type=self.config.application_type,
            network_scenario=self.network_scenario,
            network_config=self.network_config,
            initial_params=initial_params,
            config=EpochConfig(
                settling_time=2.0,  # 2 second settling time
                min_epoch_duration=2.0,
                sample_interval=0.1,
            ),
        )

    def _update_parameter(self, param_name: str, value):
        """Update parameter and notify epoch manager."""
        # ... existing parameter update code ...

        # Create new parameter snapshot
        new_params = ParameterSnapshot(
            loss_reduction_factor=aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR,
            cubic_c=aioquic_cubic.K_CUBIC_C,
            minimum_window=aioquic_cubic.K_MINIMUM_WINDOW,
            packet_threshold=aioquic_recovery.K_PACKET_THRESHOLD,
            time_threshold=aioquic_recovery.K_TIME_THRESHOLD,
            cubic_max_idle_time=aioquic_cubic.K_CUBIC_MAX_IDLE_TIME,
            initial_cw=self.config.initial_cw,
            max_ack_delay=self.config.max_ack_delay,
            max_data=self.config.max_data,
            max_stream_data=self.config.max_stream_data,
        )

        # Notify epoch manager of parameter change
        self._epoch_manager.on_parameter_change(new_params)

    async def run(self, duration: float):
        """Main worker loop with epoch tracking."""
        self._apply_initial_parameters()
        self._epoch_manager.set_metrics_collector(self._metrics_collector)
        self._epoch_manager.start()

        self.start_barrier.wait()

        self._running = True
        start_time = time.time()
        last_sample_time = start_time

        try:
            # ... connection setup ...

            while self._running and (time.time() - start_time) < duration:
                # ... existing loop code ...

                # Collect epoch sample
                now = time.time()
                if now - last_sample_time >= 0.1:  # Every 100ms
                    self._epoch_manager.collect_sample()
                    last_sample_time = now

                    # Only send metrics to UI if not settling
                    if not self._epoch_manager.is_settling():
                        self._send_metrics()

                await asyncio.sleep(0)

        finally:
            # Finalize epochs
            self._epoch_manager.finalize()

            # Send epoch history with final results
            self._send_finished_with_epochs()

    def _send_finished_with_epochs(self):
        """Send finished message including epoch history."""
        final_metrics = self._metrics_collector.calculate_metrics()
        epoch_history = self._epoch_manager.get_history()

        msg = IPCMessage(
            msg_type=MessageType.FINISHED,
            connection_id=self.config.connection_id,
            timestamp=time.time(),
            payload={
                "final_metrics": final_metrics.to_dict(),
                "param_history": self._param_history,
                "epoch_history": epoch_history.to_dict(),
                "success": True,
            },
        )
        self.metrics_queue.put(msg)
```

#### 17.5.6 Timeline Visualization

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      EPOCH-BASED METRICS COLLECTION                              │
└─────────────────────────────────────────────────────────────────────────────────┘

Timeline: Connection with 2 parameter changes
═══════════════════════════════════════════════════════════════════════════════════

  t=0s                t=10s              t=12s              t=25s              t=30s
   │                    │                  │                   │                  │
   ▼                    ▼                  ▼                   ▼                  ▼
   ├────────────────────┼──────────────────┼───────────────────┼──────────────────┤
   │                    │                  │                   │                  │
   │      EPOCH 0       │    SETTLING     │      EPOCH 1      │ SETTLING │ EP. 2 │
   │   Initial params   │   (2 seconds)    │   LRF changed     │(2 seconds)│      │
   │                    │                  │   to 0.7          │          │      │
   │   ✓ Collecting     │   ✗ No samples  │   ✓ Collecting    │✗ No samp │✓ Coll│
   │                    │                  │                   │          │      │
   └────────────────────┴──────────────────┴───────────────────┴──────────┴──────┘
           │                                        │                        │
           ▼                                        ▼                        ▼
   ┌───────────────┐                      ┌───────────────┐          ┌───────────────┐
   │ epoch_0.json  │                      │ epoch_1.json  │          │ epoch_2.json  │
   │               │                      │               │          │               │
   │ params: {...} │                      │ params: {...} │          │ params: {...} │
   │ metrics: {    │                      │ metrics: {    │          │ metrics: {    │
   │   tp: 4.2Mbps │                      │   tp: 3.8Mbps │          │   tp: 4.5Mbps │
   │   rtt: 32ms   │                      │   rtt: 35ms   │          │   rtt: 31ms   │
   │ }             │                      │ }             │          │ }             │
   └───────────────┘                      └───────────────┘          └───────────────┘

Key:
  ✓ = Samples collected (valid measurement period)
  ✗ = No samples (settling period - CC adapting)
```

#### 17.5.7 Configuration Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `settling_time` | 2.0s | Time to wait after parameter change before measuring |
| `min_epoch_duration` | 2.0s | Minimum measurement time for valid epoch |
| `sample_interval` | 0.1s | How often to collect metric samples |

**Settling Time Recommendations:**

| Network Condition | Recommended Settling Time |
|-------------------|--------------------------|
| Low latency (<20ms RTT) | 1.0 - 1.5 seconds |
| Medium latency (20-50ms RTT) | 2.0 - 3.0 seconds |
| High latency (>50ms RTT) | 3.0 - 5.0 seconds |
| High loss (>3%) | 3.0 - 5.0 seconds |

The settling time should be at least **5-10 RTTs** to allow CUBIC to adapt.

#### 17.5.8 Alternative Approaches

**Option A: Epoch-Based (Recommended - Described Above)**
- Pros: Clean segmentation, accurate metrics per configuration
- Cons: Lost measurement time during settling

**Option B: Sliding Window with Tags**
- Collect continuous metrics but tag samples with current params
- Post-process to filter out transition periods
- Pros: No lost measurement time, flexible analysis
- Cons: More complex post-processing

**Option C: Event-Triggered Snapshots**
- Take snapshots at specific events (start, param change + settling, end)
- Pros: Simple, minimal data
- Cons: Misses time-series patterns

```python
# Option B: Sliding Window Implementation
class SlidingWindowCollector:
    """Alternative: continuous collection with parameter tags."""

    def collect_sample(self):
        sample = {
            "timestamp": time.time(),
            "metrics": self._metrics_collector.get_current_metrics(),
            "params": self._get_current_params(),
            "settling": self._is_settling,
            "epoch_id": self._current_epoch_id,
        }
        self._all_samples.append(sample)

    def get_stable_samples(self, epoch_id: int) -> List[dict]:
        """Get samples from a specific epoch, excluding settling."""
        return [
            s for s in self._all_samples
            if s["epoch_id"] == epoch_id and not s["settling"]
        ]
```

---

## 18. Real-Time Browser UI Dashboard

The UI Dashboard provides a **browser-based interface** for monitoring and controlling the 3 QUIC connections in real-time. Built using **FastAPI** with **WebSocket** for real-time updates, it enables:

- **Buffer Visualization** - See queued packets for each connection (read-only)
- **Parameter Control** - Modify dynamic CC parameters mid-connection
- **Live Metrics** - Real-time throughput, RTT, jitter, and loss display with charts
- **Cross-Platform** - Works on any device with a web browser

### 18.1 UI Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          BROWSER UI ARCHITECTURE                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

                                   ┌─────────────────────────────────────┐
                                   │           Web Browser               │
                                   │                                     │
                                   │  ┌─────────────────────────────┐   │
                                   │  │     JavaScript Frontend     │   │
                                   │  │                             │   │
                                   │  │  • Chart.js for metrics     │   │
                                   │  │  • WebSocket client         │   │
                                   │  │  • Parameter controls       │   │
                                   │  └─────────────┬───────────────┘   │
                                   │                │                    │
                                   └────────────────┼────────────────────┘
                                                    │
                                        WebSocket (ws://localhost:8000/ws)
                                                    │
┌───────────────────────────────────────────────────┼─────────────────────────────┐
│  Docker Container                                 │                              │
│                                                   ▼                              │
│                          ┌─────────────────────────────────────────┐            │
│                          │           FastAPI Server                 │            │
│                          │                                          │            │
│                          │  Routes:                                 │            │
│                          │  • GET  /           → Dashboard HTML     │            │
│                          │  • GET  /api/status → Current state      │            │
│                          │  • POST /api/params → Update params      │            │
│                          │  • WS   /ws         → Real-time stream   │            │
│                          └───────────────┬──────────────────────────┘            │
│                                          │                                       │
│                                          ▼                                       │
│                          ┌─────────────────────────────────────────┐            │
│                          │        ProcessOrchestrator              │            │
│                          │                                          │            │
│                          │  command_pipes → Workers                 │            │
│                          │  metrics_queue ← Workers                 │            │
│                          └─────────────────────────────────────────┘            │
│                                          │                                       │
│                    ┌─────────────────────┼─────────────────────┐                │
│                    ▼                     ▼                     ▼                │
│            ┌──────────────┐      ┌──────────────┐      ┌──────────────┐         │
│            │   Worker 1   │      │   Worker 2   │      │   Worker 3   │         │
│            │   (Video)    │      │   (File)     │      │ (Conference) │         │
│            └──────────────┘      └──────────────┘      └──────────────┘         │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘

Data Flow:
  1. Workers → metrics_queue → Orchestrator → WebSocket → Browser (every 100ms)
  2. Browser → HTTP POST → FastAPI → command_pipe → Worker (on user action)
```

### 18.1.1 Why Browser UI?

| Feature | Terminal (Textual) | Browser (FastAPI) |
|---------|-------------------|-------------------|
| **Charts/Graphs** | Limited ASCII | Full Chart.js support |
| **Remote Access** | SSH required | Any device with browser |
| **Docker Support** | Requires TTY | Works with port mapping |
| **Mobile Viewing** | Not practical | Responsive design |
| **Data Export** | Manual | Download buttons |

### 18.2 Buffer Visualization

Each worker process maintains a **send buffer** that the UI can monitor (read-only). The buffer shows packets generated by the synthesizer waiting to be sent.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         BUFFER VISUALIZATION                                     │
└─────────────────────────────────────────────────────────────────────────────────┘

     Synthesizer                                    Send Buffer
  ┌─────────────────┐                         ┌─────────────────┐
  │ Video: I-frame  │ ───────────────────────►│ [I] [P] [P] [P] │
  │ Video: P-frame  │ (adds at its own pace)  │ [P] [P] [I] ... │ ──► QUIC sends
  │ Video: P-frame  │                         │                 │     (FIFO order)
  └─────────────────┘                         └─────────────────┘
                                                      │
                                                      ▼
                                              UI displays queue
                                              state (read-only)

  [I] = I-frame from synthesizer
  [P] = P-frame from synthesizer
```

**Why Read-Only?**

The synthesizer traffic pattern IS the application simulation:
- **Conference call** = 320 bytes every 20ms
- **Video streaming** = I/P frames at 30fps
- **File transfer** = Max-rate chunks

Injecting packets would change the traffic pattern, meaning you'd no longer be measuring that application's performance. To fairly compare CC parameters, the traffic pattern must stay constant—only the CC parameters should change.

```python
# simulation/buffer_manager.py

from dataclasses import dataclass, field
from typing import List, Optional
from collections import deque
import threading
import time


@dataclass
class BufferPacket:
    """A packet in the send buffer."""
    data: bytes
    size: int
    packet_type: str
    timestamp: float = field(default_factory=time.time)


class SendBuffer:
    """
    Thread-safe send buffer for a QUIC connection.

    The buffer holds packets waiting to be sent. The synthesizer adds
    packets automatically. The UI can observe the buffer state (read-only).
    """

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._buffer: deque[BufferPacket] = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._total_sent = 0

    def add_packet(self, packet: BufferPacket):
        """Add a packet to the buffer (from synthesizer)."""
        with self._lock:
            self._buffer.append(packet)

    def get_next(self) -> Optional[BufferPacket]:
        """Get and remove the next packet to send."""
        with self._lock:
            if self._buffer:
                self._total_sent += 1
                return self._buffer.popleft()
            return None

    def peek(self, count: int = 10) -> List[BufferPacket]:
        """Peek at the next N packets without removing them."""
        with self._lock:
            return list(self._buffer)[:count]

    def get_state(self) -> dict:
        """Get current buffer state for UI display (read-only)."""
        with self._lock:
            return {
                "queue_length": len(self._buffer),
                "max_size": self.max_size,
                "total_bytes": sum(p.size for p in self._buffer),
                "utilization": len(self._buffer) / self.max_size if self.max_size > 0 else 0,
                "total_sent": self._total_sent,
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)
```

### 18.3 Updated ConnectionWorker with Buffer Support

```python
# Updated sections of simulation/worker_process.py

class ConnectionWorker:
    """Worker with send buffer support for UI interaction."""

    def __init__(self, ...):
        # ... existing init ...
        self._send_buffer = SendBuffer(max_size=1000)
        self._buffer_report_interval = 0.05  # 50ms buffer state reports

    def _check_commands(self):
        """Check for commands including packet injection."""
        while self.command_pipe.poll():
            try:
                msg_dict = self.command_pipe.recv()
                msg = IPCMessage.from_dict(msg_dict)

                if msg.msg_type == MessageType.UPDATE_PARAM:
                    self._update_parameter(msg.payload["param_name"], msg.payload["value"])
                    self._send_ack(msg)

                elif msg.msg_type == MessageType.GET_BUFFER_STATE:
                    self._send_buffer_state()

                elif msg.msg_type == MessageType.STOP:
                    self._running = False

            except Exception as e:
                self._send_error(str(e))

    def _send_buffer_state(self):
        """Send current buffer state to main process."""
        msg = IPCMessage(
            msg_type=MessageType.BUFFER_STATE,
            connection_id=self.config.connection_id,
            timestamp=time.time(),
            payload=self._send_buffer.get_state(),
        )
        self.metrics_queue.put(msg)

    async def run(self, duration: float):
        """Main worker loop with buffer integration."""
        self._apply_initial_parameters()
        self.start_barrier.wait()

        self._running = True
        start_time = time.time()
        last_buffer_report = time.time()

        try:
            # ... connection setup ...

            synthesizer = SynthesizerFactory.create(
                self.config.application_type,
                duration_seconds=duration,
            )

            stream_id = protocol._quic.get_next_available_stream_id()

            # Run synthesizer and buffer consumer concurrently
            async for packet in synthesizer.generate():
                if not self._running or (time.time() - start_time) >= duration:
                    break

                # Add to buffer instead of sending directly
                self._send_buffer.add_packet(BufferPacket(
                    data=packet.data,
                    size=packet.size,
                    packet_type=packet.packet_type,
                ))

                # Send packets from buffer
                while True:
                    buf_packet = self._send_buffer.get_next()
                    if buf_packet is None:
                        break

                    protocol._quic.send_stream_data(stream_id, buf_packet.data)
                    self._metrics_collector.record_packet_sent(buf_packet.size)

                # Check commands (including packet injection)
                self._check_commands()

                # Report buffer state periodically
                if time.time() - last_buffer_report >= self._buffer_report_interval:
                    self._send_buffer_state()
                    last_buffer_report = time.time()

                await asyncio.sleep(0)
```

### 18.4 Web UI Components

#### 18.4.1 FastAPI Server (`web/server.py`)

```python
"""
FastAPI server for the QUIC 3-Connection Dashboard.
Provides REST API and WebSocket for real-time updates.
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, List, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


class ParameterUpdate(BaseModel):
    """Request model for parameter updates."""
    connection_id: int
    param_name: str
    value: float


class ConnectionManager:
    """Manages WebSocket connections for broadcasting updates."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        """Send message to all connected clients."""
        if not self.active_connections:
            return
        data = json.dumps(message)
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(data)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.active_connections.discard(conn)


def create_app(orchestrator) -> FastAPI:
    """Create FastAPI application with orchestrator reference."""

    app = FastAPI(title="QUIC 3-Connection Dashboard")
    manager = ConnectionManager()

    # Store orchestrator reference
    app.state.orchestrator = orchestrator
    app.state.manager = manager

    # Serve static files (HTML, CSS, JS)
    static_path = Path(__file__).parent / "static"
    if static_path.exists():
        app.mount("/static", StaticFiles(directory=static_path), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def get_dashboard():
        """Serve the main dashboard HTML."""
        html_path = Path(__file__).parent / "static" / "index.html"
        return html_path.read_text()

    @app.get("/api/status")
    async def get_status():
        """Get current status of all connections."""
        return {
            "metrics": orchestrator.get_latest_metrics(),
            "buffers": orchestrator.get_buffer_states(),
            "params": orchestrator.get_current_params(),
            "running": orchestrator.is_running(),
        }

    @app.post("/api/params")
    async def update_params(update: ParameterUpdate):
        """Update a parameter for a specific connection."""
        success = orchestrator.update_parameter(
            update.connection_id,
            update.param_name,
            update.value
        )
        return {"success": success, "connection_id": update.connection_id}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time updates."""
        await manager.connect(websocket)
        try:
            while True:
                # Send updates every 100ms
                await asyncio.sleep(0.1)
                data = {
                    "type": "update",
                    "metrics": orchestrator.get_latest_metrics(),
                    "buffers": orchestrator.get_buffer_states(),
                    "params": orchestrator.get_current_params(),
                }
                await websocket.send_json(data)
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    return app


async def run_server(orchestrator, host: str = "0.0.0.0", port: int = 8000):
    """Run the FastAPI server."""
    import uvicorn

    app = create_app(orchestrator)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
```

#### 18.4.2 Dashboard HTML (`web/static/index.html`)

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QUIC 3-Connection Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
    <header>
        <h1>QUIC 3-Connection Dashboard</h1>
        <div id="status-bar">
            <span id="duration">Duration: 0.0s</span>
            <span id="total-tx">Total TX: 0 MB</span>
            <span id="fairness">Fairness: --</span>
        </div>
    </header>

    <main id="dashboard">
        <!-- Connection 1: Video Streaming -->
        <div class="connection-panel" id="conn-1">
            <h2>Connection 1: Video Streaming</h2>

            <div class="section buffer-section">
                <h3>Send Buffer</h3>
                <div class="buffer-bar">
                    <div class="buffer-fill" id="buffer-1"></div>
                </div>
                <p class="buffer-stats" id="buffer-stats-1">Queued: 0 pkts | 0 bytes</p>
            </div>

            <div class="section metrics-section">
                <h3>Live Metrics</h3>
                <canvas id="chart-1" width="300" height="150"></canvas>
                <div class="metrics-values">
                    <p>Throughput: <span id="tp-1">0</span> Mbps</p>
                    <p>RTT: <span id="rtt-1">0</span> ms</p>
                    <p>Loss: <span id="loss-1">0</span>%</p>
                </div>
            </div>

            <div class="section params-section">
                <h3>Dynamic Parameters</h3>
                <div class="params-grid" id="params-1"></div>
                <button class="edit-btn" onclick="openParamEditor(1)">Edit Parameters</button>
            </div>
        </div>

        <!-- Connection 2: File Transfer -->
        <div class="connection-panel" id="conn-2">
            <h2>Connection 2: File Transfer</h2>

            <div class="section buffer-section">
                <h3>Send Buffer</h3>
                <div class="buffer-bar">
                    <div class="buffer-fill" id="buffer-2"></div>
                </div>
                <p class="buffer-stats" id="buffer-stats-2">Queued: 0 pkts | 0 bytes</p>
            </div>

            <div class="section metrics-section">
                <h3>Live Metrics</h3>
                <canvas id="chart-2" width="300" height="150"></canvas>
                <div class="metrics-values">
                    <p>Throughput: <span id="tp-2">0</span> Mbps</p>
                    <p>RTT: <span id="rtt-2">0</span> ms</p>
                    <p>Loss: <span id="loss-2">0</span>%</p>
                </div>
            </div>

            <div class="section params-section">
                <h3>Dynamic Parameters</h3>
                <div class="params-grid" id="params-2"></div>
                <button class="edit-btn" onclick="openParamEditor(2)">Edit Parameters</button>
            </div>
        </div>

        <!-- Connection 3: Conference Call -->
        <div class="connection-panel" id="conn-3">
            <h2>Connection 3: Conference Call</h2>

            <div class="section buffer-section">
                <h3>Send Buffer</h3>
                <div class="buffer-bar">
                    <div class="buffer-fill" id="buffer-3"></div>
                </div>
                <p class="buffer-stats" id="buffer-stats-3">Queued: 0 pkts | 0 bytes</p>
            </div>

            <div class="section metrics-section">
                <h3>Live Metrics</h3>
                <canvas id="chart-3" width="300" height="150"></canvas>
                <div class="metrics-values">
                    <p>Throughput: <span id="tp-3">0</span> Mbps</p>
                    <p>RTT: <span id="rtt-3">0</span> ms</p>
                    <p>Loss: <span id="loss-3">0</span>%</p>
                </div>
            </div>

            <div class="section params-section">
                <h3>Dynamic Parameters</h3>
                <div class="params-grid" id="params-3"></div>
                <button class="edit-btn" onclick="openParamEditor(3)">Edit Parameters</button>
            </div>
        </div>
    </main>

    <!-- Parameter Editor Modal -->
    <div id="param-modal" class="modal hidden">
        <div class="modal-content">
            <h2>Edit Parameters - Connection <span id="modal-conn-id">1</span></h2>
            <form id="param-form">
                <div class="param-row">
                    <label for="loss_reduction_factor">loss_reduction_factor (0.1-0.9)</label>
                    <input type="number" id="loss_reduction_factor" step="0.1" min="0.1" max="0.9">
                </div>
                <div class="param-row">
                    <label for="cubic_c">cubic_c (0.1-1.0)</label>
                    <input type="number" id="cubic_c" step="0.1" min="0.1" max="1.0">
                </div>
                <div class="param-row">
                    <label for="minimum_window">minimum_window (1-10)</label>
                    <input type="number" id="minimum_window" step="1" min="1" max="10">
                </div>
                <div class="param-row">
                    <label for="packet_threshold">packet_threshold (1-5)</label>
                    <input type="number" id="packet_threshold" step="1" min="1" max="5">
                </div>
                <div class="param-row">
                    <label for="time_threshold">time_threshold (1.0-2.0)</label>
                    <input type="number" id="time_threshold" step="0.125" min="1.0" max="2.0">
                </div>
                <div class="param-row">
                    <label for="cubic_max_idle_time">cubic_max_idle_time (0.5-5.0)</label>
                    <input type="number" id="cubic_max_idle_time" step="0.5" min="0.5" max="5.0">
                </div>
                <div class="modal-buttons">
                    <button type="submit" class="apply-btn">Apply</button>
                    <button type="button" class="cancel-btn" onclick="closeParamEditor()">Cancel</button>
                </div>
            </form>
        </div>
    </div>

    <script src="/static/dashboard.js"></script>
</body>
</html>
```

#### 18.4.3 Dashboard JavaScript (`web/static/dashboard.js`)

```javascript
/**
 * QUIC 3-Connection Dashboard - Real-time WebSocket client
 */

// WebSocket connection
let ws = null;
let charts = {};
let startTime = Date.now();
let currentConnId = 1;

// Chart configuration
const CHART_MAX_POINTS = 60;  // 60 seconds of history

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    connectWebSocket();
    setupFormHandler();
});

function initCharts() {
    for (let i = 1; i <= 3; i++) {
        const ctx = document.getElementById(`chart-${i}`).getContext('2d');
        charts[i] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Throughput (Mbps)',
                    data: [],
                    borderColor: '#4CAF50',
                    tension: 0.1,
                    fill: false
                }, {
                    label: 'RTT (ms)',
                    data: [],
                    borderColor: '#2196F3',
                    tension: 0.1,
                    fill: false,
                    yAxisID: 'rtt'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                scales: {
                    x: { display: false },
                    y: {
                        type: 'linear',
                        position: 'left',
                        title: { display: true, text: 'Mbps' }
                    },
                    rtt: {
                        type: 'linear',
                        position: 'right',
                        title: { display: true, text: 'ms' },
                        grid: { drawOnChartArea: false }
                    }
                },
                plugins: {
                    legend: { display: true, position: 'bottom' }
                }
            }
        });
    }
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
        console.log('WebSocket connected');
        document.getElementById('status-bar').classList.remove('disconnected');
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected, reconnecting...');
        document.getElementById('status-bar').classList.add('disconnected');
        setTimeout(connectWebSocket, 2000);
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'update') {
            updateDashboard(data);
        }
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

function updateDashboard(data) {
    const elapsed = (Date.now() - startTime) / 1000;
    document.getElementById('duration').textContent = `Duration: ${elapsed.toFixed(1)}s`;

    let totalTx = 0;

    for (let connId = 1; connId <= 3; connId++) {
        const metrics = data.metrics[connId] || {};
        const buffer = data.buffers[connId] || {};
        const params = data.params[connId] || {};

        // Update buffer visualization
        const utilization = (buffer.utilization || 0) * 100;
        document.getElementById(`buffer-${connId}`).style.width = `${utilization}%`;
        document.getElementById(`buffer-stats-${connId}`).textContent =
            `Queued: ${buffer.queue_length || 0} pkts | ${formatBytes(buffer.total_bytes || 0)}`;

        // Update metrics
        // Field names match MetricsCollector.get_current_metrics():
        // - throughput_bps (bytes/sec), rtt (seconds), packet_loss_rate (0-1.0)
        const throughput = (metrics.throughput_bps || 0) / 1_000_000;
        const rtt = (metrics.rtt || 0) * 1000;  // Convert seconds to ms
        const loss = (metrics.packet_loss_rate || 0) * 100;  // Convert to percentage

        document.getElementById(`tp-${connId}`).textContent = throughput.toFixed(2);
        document.getElementById(`rtt-${connId}`).textContent = rtt.toFixed(1);
        document.getElementById(`loss-${connId}`).textContent = loss.toFixed(1);

        totalTx += metrics.bytes_sent || 0;

        // Update chart
        const chart = charts[connId];
        const now = new Date().toLocaleTimeString();
        chart.data.labels.push(now);
        chart.data.datasets[0].data.push(throughput);
        chart.data.datasets[1].data.push(rtt);

        // Keep only last N points
        if (chart.data.labels.length > CHART_MAX_POINTS) {
            chart.data.labels.shift();
            chart.data.datasets[0].data.shift();
            chart.data.datasets[1].data.shift();
        }
        chart.update('none');

        // Update parameters display
        updateParamsDisplay(connId, params);
    }

    document.getElementById('total-tx').textContent = `Total TX: ${formatBytes(totalTx)}`;
}

function updateParamsDisplay(connId, params) {
    const container = document.getElementById(`params-${connId}`);
    container.innerHTML = Object.entries(params)
        .map(([key, value]) => `<div class="param-item"><span>${key}:</span> <span>${
            typeof value === 'number' ? value.toFixed(3) : value
        }</span></div>`)
        .join('');
}

function openParamEditor(connId) {
    currentConnId = connId;
    document.getElementById('modal-conn-id').textContent = connId;

    // Fetch current params
    fetch('/api/status')
        .then(res => res.json())
        .then(data => {
            const params = data.params[connId] || {};
            document.getElementById('loss_reduction_factor').value = params.loss_reduction_factor || 0.5;
            document.getElementById('cubic_c').value = params.cubic_c || 0.4;
            document.getElementById('minimum_window').value = params.minimum_window || 2;
            document.getElementById('packet_threshold').value = params.packet_threshold || 3;
            document.getElementById('time_threshold').value = params.time_threshold || 1.125;
            document.getElementById('cubic_max_idle_time').value = params.cubic_max_idle_time || 2.0;
        });

    document.getElementById('param-modal').classList.remove('hidden');
}

function closeParamEditor() {
    document.getElementById('param-modal').classList.add('hidden');
}

function setupFormHandler() {
    document.getElementById('param-form').addEventListener('submit', async (e) => {
        e.preventDefault();

        const params = [
            'loss_reduction_factor', 'cubic_c', 'minimum_window',
            'packet_threshold', 'time_threshold', 'cubic_max_idle_time'
        ];

        for (const paramName of params) {
            const value = parseFloat(document.getElementById(paramName).value);
            if (!isNaN(value)) {
                await fetch('/api/params', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        connection_id: currentConnId,
                        param_name: paramName,
                        value: value
                    })
                });
            }
        }

        closeParamEditor();
    });
}

function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}
```

#### 18.4.4 Dashboard Styles (`web/static/styles.css`)

```css
/* QUIC 3-Connection Dashboard Styles */

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #1a1a2e;
    color: #eee;
    min-height: 100vh;
}

header {
    background: #16213e;
    padding: 1rem 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 2px solid #0f3460;
}

header h1 {
    font-size: 1.5rem;
    color: #4CAF50;
}

#status-bar {
    display: flex;
    gap: 2rem;
    font-size: 0.9rem;
    color: #aaa;
}

#status-bar.disconnected {
    color: #f44336;
}

#dashboard {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1rem;
    padding: 1rem;
}

@media (max-width: 1200px) {
    #dashboard {
        grid-template-columns: repeat(2, 1fr);
    }
}

@media (max-width: 768px) {
    #dashboard {
        grid-template-columns: 1fr;
    }
}

.connection-panel {
    background: #16213e;
    border-radius: 8px;
    padding: 1rem;
    border: 1px solid #0f3460;
}

.connection-panel h2 {
    text-align: center;
    margin-bottom: 1rem;
    color: #4CAF50;
    font-size: 1.1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid #0f3460;
}

.section {
    margin-bottom: 1rem;
    padding: 0.75rem;
    background: #1a1a2e;
    border-radius: 4px;
}

.section h3 {
    font-size: 0.9rem;
    color: #888;
    margin-bottom: 0.5rem;
}

/* Buffer visualization */
.buffer-bar {
    height: 24px;
    background: #333;
    border-radius: 4px;
    overflow: hidden;
    margin-bottom: 0.5rem;
}

.buffer-fill {
    height: 100%;
    background: linear-gradient(90deg, #4CAF50, #8BC34A);
    width: 0%;
    transition: width 0.2s ease;
}

.buffer-stats {
    font-size: 0.8rem;
    color: #888;
}

/* Metrics */
.metrics-values {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.5rem;
    margin-top: 0.5rem;
    font-size: 0.85rem;
}

.metrics-values p {
    text-align: center;
}

.metrics-values span {
    color: #4CAF50;
    font-weight: bold;
}

/* Parameters */
.params-grid {
    display: grid;
    gap: 0.25rem;
    font-size: 0.8rem;
    margin-bottom: 0.5rem;
}

.param-item {
    display: flex;
    justify-content: space-between;
    padding: 0.25rem 0;
    border-bottom: 1px solid #333;
}

.edit-btn {
    width: 100%;
    padding: 0.5rem;
    background: #0f3460;
    color: #fff;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.2s;
}

.edit-btn:hover {
    background: #1a4a7a;
}

/* Modal */
.modal {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.8);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 1000;
}

.modal.hidden {
    display: none;
}

.modal-content {
    background: #16213e;
    padding: 2rem;
    border-radius: 8px;
    width: 400px;
    max-width: 90%;
}

.modal-content h2 {
    margin-bottom: 1.5rem;
    color: #4CAF50;
}

.param-row {
    margin-bottom: 1rem;
}

.param-row label {
    display: block;
    margin-bottom: 0.25rem;
    font-size: 0.9rem;
    color: #aaa;
}

.param-row input {
    width: 100%;
    padding: 0.5rem;
    background: #1a1a2e;
    border: 1px solid #0f3460;
    border-radius: 4px;
    color: #fff;
}

.modal-buttons {
    display: flex;
    gap: 1rem;
    margin-top: 1.5rem;
}

.apply-btn, .cancel-btn {
    flex: 1;
    padding: 0.75rem;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-weight: bold;
}

.apply-btn {
    background: #4CAF50;
    color: #fff;
}

.cancel-btn {
    background: #f44336;
    color: #fff;
}
```

### 18.5 CLI Integration

```bash
# Run with browser UI dashboard (opens http://localhost:8000)
uv run main.py run --ui

# Run with UI and ML controller
uv run main.py run --ui --with-ml

# Run without UI (headless)
uv run main.py run --duration 30

# Run in Docker with web UI accessible from host
docker run -it --privileged -p 8000:8000 --rm quic-3conn \
    python -m main run --ui --scenario congested_low --duration 60
```

**Accessing the Dashboard:**

1. Start the simulation with `--ui` flag
2. Open browser to `http://localhost:8000`
3. If running in Docker, ensure port 8000 is mapped with `-p 8000:8000`

### 18.6 Updated ProcessOrchestrator for UI Support

```python
# Additional methods in simulation/process_orchestrator.py

class ProcessOrchestrator:
    """Orchestrator with UI support methods."""

    def __init__(self, ...):
        # ... existing init ...
        self._latest_metrics = {1: {}, 2: {}, 3: {}}
        self._buffer_states = {1: {}, 2: {}, 3: {}}
        self._current_params = {1: {}, 2: {}, 3: {}}

    def get_latest_metrics(self) -> dict:
        """Get latest metrics for all connections (for UI)."""
        return self._latest_metrics.copy()

    def get_buffer_states(self) -> dict:
        """Get current buffer states for all connections (for UI)."""
        return self._buffer_states.copy()

    def get_current_params(self) -> dict:
        """Get current parameters for all connections (for UI)."""
        return self._current_params.copy()

    # Parameter bounds for validation (dynamic parameters only)
    PARAM_BOUNDS = {
        "loss_reduction_factor": (0.1, 0.9),
        "cubic_c": (0.1, 1.0),
        "minimum_window": (1, 10),
        "packet_threshold": (1, 10),
        "time_threshold": (1.0, 2.0),
        "cubic_max_idle_time": (0.5, 5.0),
    }

    def update_parameter(self, connection_id: int, param_name: str, value) -> bool:
        """Update a parameter for a specific connection (from UI)."""
        # Validate parameter bounds
        if param_name in self.PARAM_BOUNDS:
            min_val, max_val = self.PARAM_BOUNDS[param_name]
            if not (min_val <= value <= max_val):
                return False  # Reject out-of-bounds value

        pipe = self.command_pipes.get(connection_id)
        if pipe:
            msg = IPCMessage(
                msg_type=MessageType.UPDATE_PARAM,
                connection_id=connection_id,
                timestamp=time.time(),
                payload={"param_name": param_name, "value": value},
            )
            pipe.send(msg.to_dict())
            return True
        return False

    def _process_metrics_queue(self):
        """Process metrics queue and update internal state for UI."""
        while not self.metrics_queue.empty():
            try:
                msg = self.metrics_queue.get_nowait()

                if msg.msg_type == MessageType.METRICS:
                    self._latest_metrics[msg.connection_id] = msg.payload
                    # Extract current params from metrics
                    if "current_params" in msg.payload:
                        self._current_params[msg.connection_id] = msg.payload["current_params"]

                elif msg.msg_type == MessageType.BUFFER_STATE:
                    self._buffer_states[msg.connection_id] = msg.payload

                elif msg.msg_type == MessageType.FINISHED:
                    self.final_results[msg.connection_id] = msg.payload

            except Exception:
                break  # Queue empty or connection closed
```

### 18.7 Interaction Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      BROWSER UI INTERACTION FLOW                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

USER ACTION                     BROWSER                      SYSTEM
─────────────────────────────────────────────────────────────────────────────────

1. Open browser to        →    WebSocket connects       →  FastAPI accepts
   http://localhost:8000       to /ws endpoint              connection

2. View buffer state      ←    JavaScript updates       ←  WebSocket pushes data
   (automatic, 100ms)          progress bars & stats        from orchestrator

3. View live metrics      ←    Chart.js updates         ←  WebSocket pushes data
   (automatic, 100ms)          graphs with new points       every 100ms

4. Click "Edit Params"    →    Opens modal dialog       →  GET /api/status to
   button                      with current values          fetch current params

5. Adjust parameter       →    Form validation          →  (waiting for submit)
   values in modal

6. Click "Apply"          →    POST /api/params         →  FastAPI calls
                               for each changed param       orchestrator.update_parameter()

7. (automatic)            ←    Next WebSocket update    ←  Worker applies change,
                               shows new values             sends updated METRICS
```

### 18.8 Browser UI Screenshot Preview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  QUIC 3-Connection Dashboard          Duration: 15.3s | TX: 45.2 MB | Fair: 0.87│
├─────────────────────────┬─────────────────────────┬─────────────────────────────┤
│  Connection 1: Video    │  Connection 2: File     │  Connection 3: Conference   │
├─────────────────────────┼─────────────────────────┼─────────────────────────────┤
│  Send Buffer            │  Send Buffer            │  Send Buffer                │
│  [████████░░░░░░] 45%   │  [██████████████] 85%   │  [██░░░░░░░░░░░░] 12%       │
│  45 pkts | 58.5 KB      │  120 pkts | 7.5 MB      │  12 pkts | 3.8 KB           │
├─────────────────────────┼─────────────────────────┼─────────────────────────────┤
│  Live Metrics           │  Live Metrics           │  Live Metrics               │
│  ╭────────────────────╮ │  ╭────────────────────╮ │  ╭────────────────────────╮ │
│  │    📈 Throughput   │ │  │    📈 Throughput   │ │  │      📈 Throughput     │ │
│  │   ╱╲  ╱╲           │ │  │      ╱╲            │ │  │   ────────────────     │ │
│  │  ╱  ╲╱  ╲  ╱       │ │  │   ╱╱  ╲╲          │ │  │                        │ │
│  │ ╱        ╲╱        │ │  │  ╱      ╲         │ │  │   (stable 128 Kbps)    │ │
│  ╰────────────────────╯ │  ╰────────────────────╯ │  ╰────────────────────────╯ │
│  TP: 5.2 Mbps           │  TP: 8.1 Mbps           │  TP: 128 Kbps               │
│  RTT: 52ms | Loss: 1%   │  RTT: 65ms | Loss: 2%   │  RTT: 48ms | Loss: 0%       │
├─────────────────────────┼─────────────────────────┼─────────────────────────────┤
│  Parameters             │  Parameters             │  Parameters                 │
│  loss_reduction: 0.600  │  loss_reduction: 0.700  │  loss_reduction: 0.500      │
│  cubic_c: 0.400         │  cubic_c: 0.500         │  cubic_c: 0.300             │
│  minimum_window: 2      │  minimum_window: 2      │  minimum_window: 2          │
│  [ Edit Parameters ]    │  [ Edit Parameters ]    │  [ Edit Parameters ]        │
└─────────────────────────┴─────────────────────────┴─────────────────────────────┘
```

---

## Summary

This implementation plan provides a **standalone system** for running 3 concurrent QUIC connections with:

1. **Multi-process architecture** - Each connection runs in a separate Python process with isolated aioquic globals

2. **Network conditions from `wireless_bottleneck/`** - Realistic shared bottleneck using tc/netem

3. **Mid-connection parameter modification** - Dynamic parameters can be changed while connections are active

4. **ML controller integration** - Optional callback interface for intelligent parameter optimization

5. **Complete metrics collection** - Throughput, RTT, latency, jitter, packet loss per connection

6. **Parameter history tracking** - All parameter changes are recorded with timestamps

7. **Epoch-based metrics collection** - Metrics saved in segments with:
    - **Settling time** - Wait 2+ seconds after parameter change before measuring
    - **Per-epoch JSON** - Each stable period saved with params, network config, and metrics
    - **Application context** - Each epoch tagged with connection type and network scenario

8. **Synthesizers matching `/code` directory** - Video streaming (30fps I/P frames), file transfer (64KB chunks), conference call (20ms intervals)

9. **QUIC client/server matching `/code` directory** - Same `ClientProtocol`, `QuicClient`, `ServerProtocol`, `QuicServer` patterns

10. **Metrics collection matching `/code` directory** - Same `MetricsCollector` and `MetricsCalculator` with 6 metrics

11. **Real-time Browser UI Dashboard** - Web-based interface (FastAPI + WebSocket) providing:
    - **Buffer visualization** - See queued packets for each connection (read-only)
    - **Parameter control** - Edit dynamic CC parameters mid-connection via browser
    - **Live metrics** - Real-time throughput, RTT, jitter, and loss display with Chart.js graphs
    - **Cross-platform access** - Works on any device with a web browser (including mobile)

**Target Location:** `QUIC_3conn_implementation/3_conn_code/`

**Key Distinction from draft_IMP_3CONN.md:**
- This implementation is **standalone** (not integrated with existing `/code` directory)
- No grid search functionality - focuses solely on 3-connection mode
- Built from scratch in a new directory
- Uses the same synthesizer, client/server, and metrics logic as the original `/code` directory
- Includes real-time browser UI for manual control and monitoring (no ML required)
- Docker-friendly: web UI accessible via port mapping (`-p 8000:8000`)
