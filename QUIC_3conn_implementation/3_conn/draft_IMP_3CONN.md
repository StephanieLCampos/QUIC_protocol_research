# Implementation Plan: QUIC 3-Connection System with Grid Search and Mid-Connection Parameter Control

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Requirements](#2-system-requirements)
3. [Architecture Overview](#3-architecture-overview)
4. [Mode 1: Single Connection Grid Search](#4-mode-1-single-connection-grid-search)
5. [Mode 2: Three Concurrent Connections](#5-mode-2-three-concurrent-connections)
6. [File Structure and New Modules](#6-file-structure-and-new-modules)
7. [Detailed Component Specifications](#7-detailed-component-specifications)
8. [Implementation Phases](#8-implementation-phases)
9. [Integration with Existing Code](#9-integration-with-existing-code)
10. [Testing Strategy](#10-testing-strategy)
11. [CLI Commands](#11-cli-commands)
12. [Configuration Files](#12-configuration-files)

---

## 1. Executive Summary

This implementation plan describes how to extend the existing QUIC Multi-Stream Research Project to support:

1. **Single Connection Grid Search** - Run parameter sweeps on a single QUIC connection for a specific application type (video streaming, file transfer, or conference call)

2. **Three Concurrent Connections** - Run 3 independent QUIC connections simultaneously, each representing a different application type, with:
   - **Per-connection isolated parameters** (achieved via multi-process architecture)
   - **Mid-connection parameter modification** capability
   - **Shared network conditions** (all connections experience same bandwidth/latency/loss)
   - **ML controller integration** for dynamic parameter optimization

### Key Challenge Addressed

The aioquic library stores congestion control parameters as **module-level globals**:

```python
# aioquic/quic/congestion/cubic.py
K_CUBIC_LOSS_REDUCTION_FACTOR = 0.7  # Affects ALL connections in process
K_CUBIC_C = 0.4                       # Affects ALL connections in process
```

**Solution:** Multi-process architecture where each connection runs in a separate Python process with its own aioquic module instance.

---

## 2. System Requirements

### 2.1 Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | Run grid search on single QUIC connection for any application type | High |
| FR-2 | Run 3 concurrent QUIC connections simultaneously | High |
| FR-3 | Each connection has isolated CC parameters | High |
| FR-4 | Modify parameters mid-connection | High |
| FR-5 | All connections share same network conditions | High |
| FR-6 | Collect 6 metrics per connection (throughput, RTT, latency, jitter, packet loss, connection time) | High |
| FR-7 | Export results to CSV/JSON for analysis | Medium |
| FR-8 | ML callback interface for dynamic parameter control | Medium |
| FR-9 | Synchronized connection start for fair competition | Medium |
| FR-10 | Resume interrupted grid search | Low |

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

**Rationale:** These parameters are applied at connection establishment time via `QuicConfiguration`. Since aioquic uses module-level globals for congestion control, these "start-only" parameters establish the baseline network behavior that all connections share. The research focus is on how **dynamic parameters** (which CAN differ per-connection) affect performance when starting from identical initial conditions.

#### Dynamic Parameters (changeable mid-connection, per-connection isolated)
| Parameter | aioquic Constant | Default | Description |
|-----------|------------------|---------|-------------|
| `loss_reduction_factor` | `K_CUBIC_LOSS_REDUCTION_FACTOR` | 0.7 | cwnd reduction on loss |
| `cubic_c` | `K_CUBIC_C` | 0.4 | CUBIC growth aggressiveness |
| `minimum_window` | `K_MINIMUM_WINDOW` | 2 | Minimum cwnd floor (packets) |
| `packet_threshold` | `K_PACKET_THRESHOLD` | 3 | Packets before declaring loss |
| `time_threshold` | `K_TIME_THRESHOLD` | 1.125 | RTT multiplier for loss delay |
| `cubic_max_idle_time` | `K_CUBIC_MAX_IDLE_TIME` | 2.0 | Idle timeout before cwnd reset |

---

## 3. Architecture Overview

### 3.1 High-Level Architecture

```
                    ┌──────────────────────────────────────────────────────────┐
                    │                      main.py                              │
                    │                                                           │
                    │   Commands: run, run-single, run-3conn, status, analyze   │
                    └───────────────────────────┬──────────────────────────────┘
                                                │
                    ┌───────────────────────────┴──────────────────────────┐
                    │                                                      │
                    ▼                                                      ▼
     ┌─────────────────────────────────┐           ┌─────────────────────────────────┐
     │        MODE 1: Single           │           │       MODE 2: Three             │
     │    Connection Grid Search       │           │   Concurrent Connections        │
     │                                 │           │                                 │
     │   ┌─────────────────────────┐   │           │   ┌─────────────────────────┐   │
     │   │ SingleConnectionRunner  │   │           │   │  ProcessOrchestrator    │   │
     │   │                         │   │           │   │                         │   │
     │   │ • Grid search executor  │   │           │   │ • Spawns 3 workers      │   │
     │   │ • Single process        │   │           │   │ • Manages IPC           │   │
     │   │ • Parameter patching    │   │           │   │ • ML controller host    │   │
     │   └─────────────────────────┘   │           │   └───────────┬─────────────┘   │
     │                                 │           │               │                 │
     │   ┌─────────────────────────┐   │           │   ┌───────────┴──────────┐      │
     │   │   SimulationRunner      │   │           │   │                      │      │
     │   │   (existing)            │   │           │   ▼                      ▼      │
     │   └─────────────────────────┘   │           │ ┌────────┐ ┌────────┐ ┌────────┐│
     │                                 │           │ │Worker 1│ │Worker 2│ │Worker 3││
     └─────────────────────────────────┘           │ │ Video  │ │ File   │ │ Conf   ││
                                                   │ │        │ │        │ │        ││
                                                   │ │aioquic │ │aioquic │ │aioquic ││
                                                   │ │globals │ │globals │ │globals ││
                                                   │ │isolated│ │isolated│ │isolated││
                                                   │ └───┬────┘ └───┬────┘ └───┬────┘│
                                                   │     │          │          │     │
                                                   │     └──────────┼──────────┘     │
                                                   │                ▼                │
                                                   │   ┌─────────────────────────┐   │
                                                   │   │     QuicServer          │   │
                                                   │   │     (shared)            │   │
                                                   │   └─────────────────────────┘   │
                                                   └─────────────────────────────────┘
```

### 3.2 Data Flow Overview

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                           COMPLETE DATA FLOW                                    │
└────────────────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────────────┐
                    │            User CLI Command              │
                    │                                          │
                    │  uv run main.py run-single --app video   │
                    │  uv run main.py run-3conn --duration 30  │
                    └────────────────────┬────────────────────┘
                                         │
              ┌──────────────────────────┴──────────────────────────┐
              │                                                      │
              ▼                                                      ▼
┌─────────────────────────────┐                    ┌─────────────────────────────┐
│   Single Connection Mode    │                    │   Three Connection Mode     │
│                             │                    │                             │
│ 1. Load ConnectionConfig    │                    │ 1. Load MultiConnectionConfig│
│ 2. For each param combo:    │                    │ 2. Start shared QuicServer  │
│    a. Apply params          │                    │ 3. Spawn 3 worker processes │
│    b. Run simulation        │                    │ 4. Wait at Barrier          │
│    c. Collect metrics       │                    │ 5. Run control loop:        │
│    d. Export CSV            │                    │    - Collect metrics (IPC)  │
│ 3. Analyze results          │                    │    - ML decision            │
│                             │                    │    - Send param updates     │
│                             │                    │ 6. Collect final results    │
└─────────────────────────────┘                    └─────────────────────────────┘
              │                                                      │
              └──────────────────────────┬───────────────────────────┘
                                         │
                                         ▼
                    ┌─────────────────────────────────────────┐
                    │              Results Export              │
                    │                                          │
                    │  output/measurements/                    │
                    │  ├── single_video_*.csv                  │
                    │  ├── single_file_*.csv                   │
                    │  ├── multi_3conn_*.json                  │
                    │  └── multi_3conn_metrics_history.json    │
                    └─────────────────────────────────────────┘
```

---

## 4. Mode 1: Single Connection Grid Search

### 4.1 Purpose

Run a grid search over QUIC parameters for a **single application type**. This allows finding optimal parameters for video streaming, file transfer, or conference call independently.

### 4.2 Architecture (Single Process)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     SINGLE CONNECTION GRID SEARCH                            │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                  SingleConnectionGridSearch                          │   │
│   │                                                                      │   │
│   │   application_type: str      # "video_streaming" | "file_transfer"  │   │
│   │   param_space: GridSearchParams                                      │   │
│   │   output_dir: Path                                                   │   │
│   │                                                                      │   │
│   │   Methods:                                                           │   │
│   │   - execute() → Dict[str, Any]                                       │   │
│   │   - execute_dry_run() → List[ParameterCombination]                   │   │
│   │   - get_status() → Dict[str, Any]                                    │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                         │                                    │
│                                         │ For each parameter combination     │
│                                         ▼                                    │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                      SimulationRunner (existing)                     │   │
│   │                                                                      │   │
│   │   1. _apply_recovery_parameters()                                    │   │
│   │      - Patch aioquic.K_INITIAL_WINDOW                               │   │
│   │      - Patch aioquic.K_CUBIC_LOSS_REDUCTION_FACTOR                  │   │
│   │                                                                      │   │
│   │   2. Start QuicServer                                                │   │
│   │   3. Connect QuicClient                                              │   │
│   │   4. Open streams, select by app_type                                │   │
│   │   5. Send synthesized data                                           │   │
│   │   6. Collect metrics                                                 │   │
│   │   7. _restore_recovery_parameters()                                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                         │                                    │
│                                         ▼                                    │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                          CSV Export                                  │   │
│   │                                                                      │   │
│   │   Filename: single_{app}_{icw}_{ack}_{lrf}.csv                       │   │
│   │   Example:  single_video_streaming_36000_0.025_0.5.csv               │   │
│   │                                                                      │   │
│   │   Columns: initial_cw, max_ack_delay, loss_reduction_factor,         │   │
│   │            throughput, rtt, latency, jitter, packet_loss_rate,       │   │
│   │            connection_establishment_time                             │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Parameter Space for Single Connection

```python
# Default grid search for single application
class SingleAppGridSearchParams:
    """Parameter values for single-application grid search."""

    # Initial Congestion Window (bytes)
    initial_cw_values: List[int] = [12000, 36000, 72000, 120000]

    # Max ACK Delay (seconds)
    max_ack_delay_values: List[float] = [0.002, 0.010, 0.025, 0.050]

    # Loss Reduction Factor
    loss_factor_values: List[float] = [0.4, 0.5, 0.6, 0.7]

    # Extended parameters (optional)
    cubic_c_values: List[float] = [0.3, 0.4, 0.5]
    minimum_window_values: List[int] = [2, 4, 6]

    # Total combinations per app: 4 × 4 × 4 = 64 (basic)
    # Extended: 4 × 4 × 4 × 3 × 3 = 576
```

### 4.4 Code Location

| Component | File | Status |
|-----------|------|--------|
| Grid Search Executor | `grid_search/single_app_executor.py` | **New** |
| Parameter Space | `grid_search/parameter_space.py` | Extend existing |
| Simulation Runner | `simulation/runner.py` | Existing |
| CSV Exporter | `metrics/exporter.py` | Extend existing |

---

## 5. Mode 2: Three Concurrent Connections

### 5.1 Purpose

Run 3 QUIC connections simultaneously, each for a different application:
- **Connection 1:** Video Streaming
- **Connection 2:** File Transfer
- **Connection 3:** Conference Call

Each connection has **isolated dynamic parameters** that can be modified mid-connection.

### 5.2 Network Conditions from `wireless_bottleneck`

Network conditions are applied from the `wireless_bottleneck/` folder using Linux Traffic Control (`tc`) and `netem`. This creates a realistic shared bottleneck that all 3 connections must compete for.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        NETWORK CONDITION APPLICATION                             │
│                                                                                  │
│   wireless_bottleneck/                                                           │
│   ├── apply_conditions.sh      # Script to apply tc/netem rules                 │
│   ├── remove_conditions.sh     # Script to remove tc/netem rules                │
│   ├── profiles/                                                                  │
│   │   ├── lte_good.json        # LTE good conditions (15 Mbps, 30ms RTT)       │
│   │   ├── lte_poor.json        # LTE poor conditions (5 Mbps, 100ms RTT)       │
│   │   ├── wifi_congested.json  # WiFi congested (10 Mbps, 50ms, 2% loss)       │
│   │   └── variable.json        # Time-varying conditions                        │
│   └── README.md                                                                  │
│                                                                                  │
│   Network conditions include:                                                    │
│   • Bandwidth limit (e.g., 15 Mbps shared bottleneck)                           │
│   • Base RTT / latency (e.g., 30ms)                                             │
│   • Packet loss rate (e.g., 1%)                                                 │
│   • Jitter / delay variation (e.g., ±10ms)                                      │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Execution Flow:**

```
1. Apply network conditions    →  tc/netem rules from wireless_bottleneck/
2. Start 3 QUIC connections    →  All share the constrained network
3. ML controller loop:
   ├─ Collect metrics          →  Observe throughput, RTT, jitter per connection
   ├─ Make decision            →  Determine optimal parameter adjustments
   └─ Update dynamic params    →  Modify loss_reduction_factor, cubic_c, etc.
4. Connections compete         →  Dynamic params affect how each adapts
5. Remove network conditions   →  Cleanup tc/netem rules
```

**Key Point:** Once network conditions are applied, the ML controller can alter **dynamic parameters mid-connection** to optimize how each application responds to the constrained network. This enables research into:
- How different CC parameter combinations affect bandwidth sharing
- Whether ML can learn to protect latency-sensitive apps (conference) while still allowing throughput for bulk transfers (file)
- Real-time adaptation to changing network conditions

### 5.3 Multi-Process Architecture (Parameter Isolation)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        THREE CONCURRENT CONNECTIONS                              │
│                          Multi-Process Architecture                              │
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
│ │ • LRF = 0.5       │ │    │ │ • LRF = 0.7       │ │    │ │ • LRF = 0.5       │ │
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

### 5.4 IPC Design

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
│   │   status_queue: Queue                    # Receive status FROM workers  │    │
│   │   start_barrier: Barrier                 # Synchronized start           │    │
│   │                                                                         │    │
│   └────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│        ┌─────────────┐         ┌─────────────┐         ┌─────────────┐         │
│        │   Pipe 1    │         │   Pipe 2    │         │   Pipe 3    │         │
│        │ (cmd only)  │         │ (cmd only)  │         │ (cmd only)  │         │
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
│  • STATUS             │ │  • STATUS             │ │  • STATUS             │
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

### 5.5 Message Protocol

```python
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

    # Responses (Worker → Main)
    METRICS = "metrics"
    STATUS = "status"
    ACK = "ack"
    ERROR = "error"
    FINISHED = "finished"

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

### 5.6 Synchronization Timeline

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

### 5.7 Mid-Connection Parameter Update Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     MID-CONNECTION PARAMETER UPDATE FLOW                         │
└─────────────────────────────────────────────────────────────────────────────────┘

Step 1: ML Controller receives metrics from all workers
        ┌─────────────────────────────────────────────────────────────────────────┐
        │   MLController.run_control_loop()                                       │
        │                                                                         │
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
        │       # Decision: Reduce file transfer (conn 2) aggressiveness          │
        │                                                                         │
        │       return {                                                          │
        │           2: {"loss_reduction_factor": 0.8},  # More conservative       │
        │           3: {"loss_reduction_factor": 0.4},  # More aggressive         │
        │       }                                                                 │
        └─────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
Step 3: Send parameter update via IPC
        ┌─────────────────────────────────────────────────────────────────────────┐
        │   MLController._send_param_update(conn_id=2, params={...})              │
        │                                                                         │
        │   msg = IPCMessage(                                                     │
        │       msg_type=MessageType.UPDATE_PARAM,                                │
        │       connection_id=2,                                                  │
        │       timestamp=time.time(),                                            │
        │       payload={"param_name": "loss_reduction_factor", "value": 0.8},   │
        │   )                                                                     │
        │   self.command_pipes[2].send(msg.to_dict())                            │
        └─────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼ (via Pipe)
Step 4: Worker receives and applies parameter
        ┌─────────────────────────────────────────────────────────────────────────┐
        │   ConnectionWorker._check_commands()                                    │
        │                                                                         │
        │   if msg.msg_type == MessageType.UPDATE_PARAM:                          │
        │       self._update_parameter(                                           │
        │           msg.payload["param_name"],  # "loss_reduction_factor"        │
        │           msg.payload["value"],       # 0.8                             │
        │       )                                                                 │
        │                                                                         │
        │   def _update_parameter(self, param_name, value):                       │
        │       if param_name == "loss_reduction_factor":                         │
        │           aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = value           │
        │       elif param_name == "cubic_c":                                     │
        │           aioquic_cubic.K_CUBIC_C = value                              │
        │       # ... etc                                                         │
        └─────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
Step 5: Effect on next CC event
        ┌─────────────────────────────────────────────────────────────────────────┐
        │   aioquic/quic/congestion/cubic.py                                      │
        │                                                                         │
        │   def on_packets_lost(self, ...):                                       │
        │       new_ssthresh = max(                                               │
        │           int(flight_size * K_CUBIC_LOSS_REDUCTION_FACTOR),  # Now 0.8 │
        │           K_MINIMUM_WINDOW * self._max_datagram_size,                   │
        │       )                                                                 │
        │       # Connection 2 now reduces cwnd less aggressively on loss         │
        └─────────────────────────────────────────────────────────────────────────┘
```

---

## 6. File Structure and New Modules

### 6.1 Complete File Structure

```
code/
├── main.py                              # CLI entry point (EXTEND)
├── pyproject.toml                       # Dependencies
│
├── config/
│   ├── __init__.py
│   ├── settings.py                      # Global settings (existing)
│   ├── parameters.py                    # Grid search params (EXTEND)
│   ├── connection_config.py             # Per-connection config (NEW)
│   └── multi_connection_config.py       # 3-connection config (NEW)
│
├── simulation/
│   ├── __init__.py
│   ├── runner.py                        # Single simulation (existing)
│   ├── client.py                        # QUIC client (existing)
│   ├── server.py                        # QUIC server (existing)
│   │
│   │   # NEW: Single-app grid search
│   ├── single_app_runner.py             # Single-app grid search orchestrator
│   │
│   │   # NEW: Multi-process implementation
│   ├── worker_process.py                # Worker process for isolated connection
│   ├── process_orchestrator.py          # Manages worker processes
│   ├── ipc_messages.py                  # IPC message definitions
│   ├── ml_controller.py                 # ML controller for main process
│   └── multi_connection_result.py       # Result data structures
│
├── synthesizers/
│   ├── __init__.py
│   ├── base.py                          # Abstract base (existing)
│   ├── video_streaming.py               # Video synthesizer (existing)
│   ├── file_transfer.py                 # File synthesizer (existing)
│   └── conference_call.py               # Conference synthesizer (existing)
│
├── metrics/
│   ├── __init__.py
│   ├── collector.py                     # Metrics collection (existing)
│   ├── calculator.py                    # Metrics calculation (existing)
│   ├── exporter.py                      # CSV export (EXTEND)
│   └── aggregated_metrics.py            # Multi-connection aggregation (NEW)
│
├── grid_search/
│   ├── __init__.py
│   ├── parameter_space.py               # Parameter combinations (EXTEND)
│   ├── scheduler.py                     # Resumable scheduler (existing)
│   ├── executor.py                      # Grid search executor (existing)
│   └── single_app_executor.py           # Single-app executor (NEW)
│
├── results/
│   ├── __init__.py
│   ├── analyzer.py                      # Results analysis (EXTEND)
│   └── report_generator.py              # Report generation (EXTEND)
│
├── certs/                               # TLS certificates
│
└── output/
    ├── measurements/                    # Grid search results
    │   ├── single_video_*.csv           # Single-app results
    │   ├── single_file_*.csv
    │   └── multi_3conn_*.json           # 3-connection results
    └── reports/                         # Generated reports
```

### 6.2 New Files Summary

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `config/connection_config.py` | Per-connection configuration | `ConnectionConfig`, `DYNAMIC_PARAMETERS` |
| `config/multi_connection_config.py` | 3-connection configuration | `MultiConnectionConfig` |
| `simulation/single_app_runner.py` | Single-app grid search | `SingleAppGridSearchRunner` |
| `simulation/worker_process.py` | Worker process | `ConnectionWorker`, `worker_process_entry()` |
| `simulation/process_orchestrator.py` | Process management | `ProcessOrchestrator` |
| `simulation/ipc_messages.py` | IPC protocol | `MessageType`, `IPCMessage` |
| `simulation/ml_controller.py` | ML integration | `MLController` |
| `simulation/multi_connection_result.py` | Result structures | `MultiConnectionResult`, `ConnectionResult` |
| `metrics/aggregated_metrics.py` | Multi-conn metrics | `AggregatedMetrics` |
| `grid_search/single_app_executor.py` | Single-app executor | `SingleAppGridSearchExecutor` |

---

## 7. Detailed Component Specifications

### 7.1 ConnectionConfig

```python
# config/connection_config.py

from dataclasses import dataclass, field
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
# These use the SAME value for all 3 connections - they cannot differ per-connection
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

    NOTE: Start-only parameters (initial_cw, max_ack_delay, max_data, max_stream_data)
    are CONSTANT across all connections. They are stored here for convenience but
    the MultiConnectionConfig ensures all connections use the same values.

    Only DYNAMIC_PARAMETERS can differ between connections and be changed mid-connection.
    """

    # Connection identity
    connection_id: int
    application_type: str  # "video_streaming", "file_transfer", "conference_call"

    # Start-only parameters - CONSTANT across all connections (same value for all 3)
    # These establish identical initial conditions for fair comparison
    initial_cw: int = 12000           # Same for all connections
    max_ack_delay: float = 0.025      # Same for all connections
    max_data: int = 1_048_576         # Same for all connections
    max_stream_data: int = 1_048_576  # Same for all connections
    max_datagram_size: int = 1200     # Same for all connections

    # Dynamic parameters (changeable mid-connection, per-connection isolated)
    # These CAN differ between connections and are the focus of ML optimization
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

    @classmethod
    def create_for_video(cls, connection_id: int = 1) -> "ConnectionConfig":
        """Create config optimized for video streaming."""
        return cls(
            connection_id=connection_id,
            application_type="video_streaming",
            initial_cw=72000,
            max_ack_delay=0.002,
            max_data=2_000_000,
            max_stream_data=1_000_000,
            loss_reduction_factor=0.6,
            cubic_c=0.4,
            minimum_window=4,
        )

    @classmethod
    def create_for_file_transfer(cls, connection_id: int = 2) -> "ConnectionConfig":
        """Create config optimized for file transfer."""
        return cls(
            connection_id=connection_id,
            application_type="file_transfer",
            initial_cw=120000,
            max_ack_delay=0.025,
            max_data=10_000_000,
            max_stream_data=5_000_000,
            loss_reduction_factor=0.7,
            cubic_c=0.5,
            minimum_window=2,
        )

    @classmethod
    def create_for_conference(cls, connection_id: int = 3) -> "ConnectionConfig":
        """Create config optimized for conference call."""
        return cls(
            connection_id=connection_id,
            application_type="conference_call",
            initial_cw=12000,
            max_ack_delay=0.002,
            max_data=500_000,
            max_stream_data=100_000,
            loss_reduction_factor=0.5,
            cubic_c=0.3,
            minimum_window=6,
            packet_threshold=2,
            time_threshold=1.0,
        )
```

### 7.2 MultiConnectionConfig

```python
# config/multi_connection_config.py

from dataclasses import dataclass
from typing import List
from .connection_config import ConnectionConfig, START_ONLY_PARAMETERS

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
    # These establish identical initial conditions for fair comparison
    # ═══════════════════════════════════════════════════════════════════════════
    shared_initial_cw: int = 12000           # Initial congestion window (bytes)
    shared_max_ack_delay: float = 0.025      # Maximum ACK delay (seconds)
    shared_max_data: int = 1_048_576         # Max connection data (bytes)
    shared_max_stream_data: int = 1_048_576  # Max stream data (bytes)

    # Per-connection configs (only dynamic parameters differ)
    video_config: ConnectionConfig = None
    file_config: ConnectionConfig = None
    conference_config: ConnectionConfig = None

    def __post_init__(self):
        """Initialize connection configs with shared start-only parameters."""
        if self.video_config is None:
            self.video_config = self._create_video_config()
        if self.file_config is None:
            self.file_config = self._create_file_config()
        if self.conference_config is None:
            self.conference_config = self._create_conference_config()

        # Ensure all connections use the same start-only parameters
        self._apply_shared_start_params()

    def _apply_shared_start_params(self):
        """Apply shared start-only parameters to all connection configs."""
        for config in self.get_all_configs():
            config.initial_cw = self.shared_initial_cw
            config.max_ack_delay = self.shared_max_ack_delay
            config.max_data = self.shared_max_data
            config.max_stream_data = self.shared_max_stream_data

    def _create_video_config(self) -> ConnectionConfig:
        """Create video config with default dynamic parameters."""
        return ConnectionConfig(
            connection_id=1,
            application_type="video_streaming",
            # Dynamic parameters (can differ per-connection)
            loss_reduction_factor=0.6,
            cubic_c=0.4,
            minimum_window=4,
        )

    def _create_file_config(self) -> ConnectionConfig:
        """Create file transfer config with default dynamic parameters."""
        return ConnectionConfig(
            connection_id=2,
            application_type="file_transfer",
            # Dynamic parameters (can differ per-connection)
            loss_reduction_factor=0.7,
            cubic_c=0.5,
            minimum_window=2,
        )

    def _create_conference_config(self) -> ConnectionConfig:
        """Create conference config with default dynamic parameters."""
        return ConnectionConfig(
            connection_id=3,
            application_type="conference_call",
            # Dynamic parameters (can differ per-connection)
            loss_reduction_factor=0.5,
            cubic_c=0.3,
            minimum_window=6,
            packet_threshold=2,
            time_threshold=1.0,
        )

    def get_all_configs(self) -> List[ConnectionConfig]:
        """Return list of all connection configs."""
        return [self.video_config, self.file_config, self.conference_config]

    def get_config(self, connection_id: int) -> ConnectionConfig:
        """Get config by connection ID."""
        configs = {
            1: self.video_config,
            2: self.file_config,
            3: self.conference_config,
        }
        return configs.get(connection_id)

    @classmethod
    def create_default(cls) -> "MultiConnectionConfig":
        """Create default optimized configuration."""
        return cls()

    @classmethod
    def create_baseline(cls) -> "MultiConnectionConfig":
        """Create baseline configuration (all same params)."""
        base = ConnectionConfig(
            connection_id=0,
            application_type="",
            initial_cw=12000,
            max_ack_delay=0.025,
            loss_reduction_factor=0.5,
        )
        return cls(
            video_config=ConnectionConfig(
                connection_id=1, application_type="video_streaming", **{
                    k: v for k, v in base.to_dict().items()
                    if k not in ["connection_id", "application_type"]
                }
            ),
            file_config=ConnectionConfig(
                connection_id=2, application_type="file_transfer", **{
                    k: v for k, v in base.to_dict().items()
                    if k not in ["connection_id", "application_type"]
                }
            ),
            conference_config=ConnectionConfig(
                connection_id=3, application_type="conference_call", **{
                    k: v for k, v in base.to_dict().items()
                    if k not in ["connection_id", "application_type"]
                }
            ),
        )
```

### 7.3 ConnectionWorker

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
    ):
        self.config = config
        self.server_host = server_host
        self.server_port = server_port
        self.command_pipe = command_pipe
        self.metrics_queue = metrics_queue
        self.start_barrier = start_barrier

        self._running = False
        self._metrics_collector = MetricsCollector()
        self._protocol = None
        self._param_history = []  # Track parameter changes

    def _apply_initial_parameters(self):
        """Apply initial CC parameters to aioquic globals (isolated to this process)."""
        # Initial window (packets)
        initial_window_packets = self.config.initial_cw // self.config.max_datagram_size
        aioquic_cubic.K_INITIAL_WINDOW = initial_window_packets

        # Dynamic parameters
        aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = self.config.loss_reduction_factor
        aioquic_cubic.K_CUBIC_C = self.config.cubic_c
        aioquic_cubic.K_MINIMUM_WINDOW = self.config.minimum_window
        aioquic_cubic.K_CUBIC_MAX_IDLE_TIME = self.config.cubic_max_idle_time
        aioquic_recovery.K_PACKET_THRESHOLD = self.config.packet_threshold
        aioquic_recovery.K_TIME_THRESHOLD = self.config.time_threshold

    def _update_parameter(self, param_name: str, value):
        """
        Update a single parameter mid-connection.

        The parameter is updated in:
        1. Local config (for tracking)
        2. aioquic module globals (for immediate effect)
        """
        if param_name not in DYNAMIC_PARAMETERS:
            self._send_error(f"Parameter '{param_name}' cannot be changed mid-connection")
            return

        # Update local config
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

        # Track change
        self._param_history.append({
            "timestamp": time.time(),
            "param_name": param_name,
            "old_value": old_value,
            "new_value": value,
        })

    def _check_commands(self):
        """Check for commands from main process (non-blocking)."""
        while self.command_pipe.poll():
            try:
                msg_dict = self.command_pipe.recv()
                msg = IPCMessage.from_dict(msg_dict)

                if msg.msg_type == MessageType.UPDATE_PARAM:
                    self._update_parameter(
                        msg.payload["param_name"],
                        msg.payload["value"],
                    )
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
                "packets_sent": self._metrics_collector.packets_sent,
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

    def _send_finished(self, final_metrics: dict):
        """Send finished message with final results."""
        msg = IPCMessage(
            msg_type=MessageType.FINISHED,
            connection_id=self.config.connection_id,
            timestamp=time.time(),
            payload={
                "final_metrics": final_metrics,
                "param_history": self._param_history,
                "success": True,
            },
        )
        self.metrics_queue.put(msg)

    async def run(self, duration: float):
        """
        Main worker loop.

        1. Apply initial parameters
        2. Wait at barrier for synchronized start
        3. Connect to server
        4. Send data while checking for commands
        5. Report metrics periodically
        6. Send final results
        """
        # Apply initial parameters (isolated to this process)
        self._apply_initial_parameters()

        # Wait for all workers to be ready
        self.start_barrier.wait()

        self._running = True
        start_time = time.time()

        try:
            # Create QUIC configuration
            configuration = QuicConfiguration(is_client=True)
            configuration.verify_mode = False
            configuration.max_datagram_frame_size = 65536
            configuration.max_ack_delay = self.config.max_ack_delay

            # Connect to server
            async with connect(
                self.server_host,
                self.server_port,
                configuration=configuration,
            ) as protocol:
                self._protocol = protocol
                self._metrics_collector.connection = protocol._quic
                self._metrics_collector.start()
                self._metrics_collector.record_connection_ready()

                # Create synthesizer for this application type
                synthesizer = SynthesizerFactory.create(
                    self.config.application_type,
                    duration_seconds=duration,
                )

                # Get stream ID
                stream_id = protocol._quic.get_next_available_stream_id()

                # Send data with periodic command checks and metrics reports
                last_metrics_time = time.time()
                metrics_interval = 0.1  # 100ms

                async for packet in synthesizer.generate():
                    if not self._running:
                        break

                    # Check elapsed time
                    if (time.time() - start_time) >= duration:
                        break

                    # Send data
                    protocol._quic.send_stream_data(stream_id, packet.data, end_stream=False)
                    self._metrics_collector.record_packet_sent(packet.size)

                    # Sample RTT
                    rtt = self._get_rtt(protocol)
                    if rtt and rtt > 0:
                        self._metrics_collector.record_rtt_sample(rtt)

                    # Check for commands from main process
                    self._check_commands()

                    # Report metrics periodically
                    if time.time() - last_metrics_time >= metrics_interval:
                        self._send_metrics()
                        last_metrics_time = time.time()

                    # Small yield to allow other async tasks
                    await asyncio.sleep(0)

                # Stop metrics collection
                self._metrics_collector.stop()

                # Calculate and send final metrics
                final_metrics = self._metrics_collector.calculate_metrics()
                self._send_finished(final_metrics.to_dict())

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
):
    """
    Entry point for worker process.

    Called by multiprocessing.Process.
    """
    # Reconstruct config from dict
    config = ConnectionConfig.from_dict(config_dict)

    # Create worker
    worker = ConnectionWorker(
        config=config,
        server_host=server_host,
        server_port=server_port,
        command_pipe=command_pipe,
        metrics_queue=metrics_queue,
        start_barrier=start_barrier,
    )

    # Run async loop
    asyncio.run(worker.run(duration))
```

### 7.4 ProcessOrchestrator

```python
# simulation/process_orchestrator.py

import asyncio
import time
from multiprocessing import Process, Pipe, Queue, Barrier
from typing import Dict, List, Optional, Callable

from config.multi_connection_config import MultiConnectionConfig
from simulation.worker_process import worker_process_entry
from simulation.server import QuicServer
from simulation.ml_controller import MLController
from simulation.multi_connection_result import MultiConnectionResult, ConnectionResult
from simulation.ipc_messages import MessageType


class ProcessOrchestrator:
    """
    Orchestrates multiple QUIC connection processes.

    Manages:
    - Spawning worker processes (one per connection)
    - IPC channels (pipes for commands, queue for metrics)
    - Synchronized start via Barrier
    - ML controller integration
    - Result collection and aggregation
    """

    def __init__(
        self,
        config: MultiConnectionConfig,
        ml_callback: Optional[Callable] = None,
        metrics_interval: float = 0.1,
    ):
        self.config = config
        self.ml_callback = ml_callback
        self.metrics_interval = metrics_interval

        # Process management
        self.workers: Dict[int, Process] = {}
        self.command_pipes: Dict[int, Pipe] = {}  # Main's end of pipes
        self.metrics_queue: Queue = Queue()
        self.start_barrier: Optional[Barrier] = None

        # Server
        self.server: Optional[QuicServer] = None

        # ML Controller
        self.ml_controller: Optional[MLController] = None

        # Results
        self.metrics_history: List[Dict[int, dict]] = []
        self.final_results: Dict[int, dict] = {}

    async def setup(self):
        """Setup server and prepare for workers."""
        # Start QUIC server in main process
        self.server = QuicServer(
            host=self.config.server_host,
            port=self.config.server_port,
        )
        await self.server.start()

        # Create barrier for synchronized start (3 workers + 1 main)
        self.start_barrier = Barrier(4)

        # Setup ML controller if callback provided
        if self.ml_callback:
            self.ml_controller = MLController(
                decision_interval=self.metrics_interval,
                ml_callback=self.ml_callback,
            )

    def _spawn_workers(self, duration: float):
        """Spawn worker processes for each connection."""
        for conn_config in self.config.get_all_configs():
            # Create pipe for commands (bidirectional)
            main_pipe, worker_pipe = Pipe()
            self.command_pipes[conn_config.connection_id] = main_pipe

            # Create process
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
                ),
                name=f"QUIC-{conn_config.application_type}",
            )
            self.workers[conn_config.connection_id] = process

    async def run(self, duration: Optional[float] = None) -> MultiConnectionResult:
        """
        Run all connections concurrently.

        Returns:
            MultiConnectionResult with per-connection and aggregated metrics.
        """
        duration = duration or self.config.simulation_duration

        try:
            await self.setup()

            # Spawn worker processes
            self._spawn_workers(duration)

            # Start all workers
            for process in self.workers.values():
                process.start()

            # Setup ML controller IPC if enabled
            if self.ml_controller:
                self.ml_controller.set_ipc_channels(
                    self.command_pipes,
                    self.metrics_queue,
                )

            # Wait at barrier to synchronize start with workers
            self.start_barrier.wait()

            # Run control loop
            if self.ml_controller:
                await self.ml_controller.run_control_loop(duration)
                self.metrics_history = self.ml_controller.metrics_history
            else:
                await self._collect_metrics_loop(duration)

            # Wait for all workers to finish
            for conn_id, process in self.workers.items():
                process.join(timeout=duration + 5)
                if process.is_alive():
                    print(f"Worker {conn_id} timed out, terminating")
                    process.terminate()
                    process.join(timeout=2)

            # Collect final results from queue
            self._collect_final_results()

            # Build and return result object
            return self._build_results()

        finally:
            await self.cleanup()

    async def _collect_metrics_loop(self, duration: float):
        """Simple metrics collection without ML (when no callback provided)."""
        start_time = time.time()

        while (time.time() - start_time) < duration:
            current_metrics = {}

            # Drain metrics queue
            while not self.metrics_queue.empty():
                try:
                    msg = self.metrics_queue.get_nowait()
                    if msg.msg_type == MessageType.METRICS:
                        current_metrics[msg.connection_id] = msg.payload
                    elif msg.msg_type == MessageType.FINISHED:
                        self.final_results[msg.connection_id] = msg.payload
                except:
                    break

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
            except:
                break

    def _build_results(self) -> MultiConnectionResult:
        """Build final result object from collected data."""
        connection_results = {}

        for conn_id in [1, 2, 3]:
            if conn_id in self.final_results:
                result_data = self.final_results[conn_id]
                connection_results[conn_id] = ConnectionResult(
                    connection_id=conn_id,
                    application_type=self.config.get_config(conn_id).application_type,
                    final_metrics=result_data.get("final_metrics", {}),
                    param_history=result_data.get("param_history", []),
                    success=result_data.get("success", False),
                )

        # Check if all workers succeeded
        all_success = (
            len(connection_results) == 3 and
            all(r.success for r in connection_results.values()) and
            all(p.exitcode == 0 for p in self.workers.values())
        )

        return MultiConnectionResult(
            config=self.config,
            connection_results=connection_results,
            metrics_history=self.metrics_history,
            success=all_success,
        )

    async def cleanup(self):
        """Cleanup all resources."""
        # Terminate any remaining workers
        for process in self.workers.values():
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)

        # Stop server
        if self.server:
            await self.server.stop()

        # Close pipes
        for pipe in self.command_pipes.values():
            pipe.close()
```

### 7.5 MLController

```python
# simulation/ml_controller.py

import time
from typing import Dict, List, Callable, Optional
from multiprocessing import Queue
from multiprocessing.connection import Connection

from .ipc_messages import IPCMessage, MessageType


class MLController:
    """
    Central ML controller that runs in the main process.

    Responsibilities:
    - Collect metrics from all worker processes
    - Run ML decision callback
    - Send parameter updates to workers
    - Track metrics history
    """

    def __init__(
        self,
        decision_interval: float = 0.1,  # 100ms
        ml_callback: Optional[Callable] = None,
    ):
        self.decision_interval = decision_interval
        self.ml_callback = ml_callback or self._default_decision

        # Metrics storage
        self.latest_metrics: Dict[int, dict] = {}
        self.metrics_history: List[Dict] = []

        # IPC channels (set by orchestrator)
        self.command_pipes: Dict[int, Connection] = {}
        self.metrics_queue: Optional[Queue] = None

    def set_ipc_channels(
        self,
        command_pipes: Dict[int, Connection],
        metrics_queue: Queue,
    ):
        """Set IPC channels after process creation."""
        self.command_pipes = command_pipes
        self.metrics_queue = metrics_queue

    async def run_control_loop(self, duration: float):
        """
        Main control loop.

        1. Collect metrics from all workers
        2. Run ML decision callback
        3. Send parameter updates if needed
        4. Record metrics history
        """
        import asyncio

        start_time = time.time()

        while (time.time() - start_time) < duration:
            loop_start = time.time()

            # Collect latest metrics from all workers
            self._collect_metrics()

            # Run ML decision if we have metrics from all 3 connections
            if len(self.latest_metrics) == 3:
                decisions = self.ml_callback(self.latest_metrics.copy())

                # Send parameter updates
                for conn_id, params in decisions.items():
                    if params:  # Only if changes needed
                        self._send_param_update(conn_id, params)

            # Record history
            self.metrics_history.append({
                "timestamp": time.time() - start_time,
                "metrics": self.latest_metrics.copy(),
            })

            # Wait for next decision interval
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
            except:
                break

    def _send_param_update(self, conn_id: int, params: dict):
        """Send parameter update to specific worker."""
        pipe = self.command_pipes.get(conn_id)
        if pipe:
            if len(params) == 1:
                # Single parameter update
                param_name, value = list(params.items())[0]
                msg = IPCMessage(
                    msg_type=MessageType.UPDATE_PARAM,
                    connection_id=conn_id,
                    timestamp=time.time(),
                    payload={"param_name": param_name, "value": value},
                )
            else:
                # Multiple parameters
                msg = IPCMessage(
                    msg_type=MessageType.UPDATE_MULTIPLE_PARAMS,
                    connection_id=conn_id,
                    timestamp=time.time(),
                    payload={"params": params},
                )
            pipe.send(msg.to_dict())

    def _default_decision(self, metrics: Dict[int, dict]) -> Dict[int, dict]:
        """
        Default ML decision (no changes).

        Override with actual ML model by passing ml_callback to constructor.
        """
        return {}

    # Utility methods for ML callbacks
    def get_parameter(self, conn_id: int, param_name: str):
        """Get current parameter value for a connection."""
        metrics = self.latest_metrics.get(conn_id, {})
        return metrics.get("current_params", {}).get(param_name)

    def get_throughput(self, conn_id: int) -> float:
        """Get current throughput for a connection."""
        return self.latest_metrics.get(conn_id, {}).get("throughput", 0)

    def get_total_throughput(self) -> float:
        """Get total throughput across all connections."""
        return sum(m.get("throughput", 0) for m in self.latest_metrics.values())

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

---

## 8. Implementation Phases

### Phase 1: Foundation (Week 1)

| Task | Files | Description |
|------|-------|-------------|
| 1.1 | `config/connection_config.py` | Create ConnectionConfig with all parameters |
| 1.2 | `config/multi_connection_config.py` | Create MultiConnectionConfig |
| 1.3 | `simulation/ipc_messages.py` | Define IPC message protocol |
| 1.4 | `metrics/aggregated_metrics.py` | Create aggregation utilities |

### Phase 2: Single Connection Grid Search (Week 2)

| Task | Files | Description |
|------|-------|-------------|
| 2.1 | `grid_search/single_app_executor.py` | Single-app grid search executor |
| 2.2 | `grid_search/parameter_space.py` | Extend for single-app mode |
| 2.3 | `metrics/exporter.py` | Extend for single-app naming |
| 2.4 | `main.py` | Add `run-single` command |

### Phase 3: Worker Process (Week 3)

| Task | Files | Description |
|------|-------|-------------|
| 3.1 | `simulation/worker_process.py` | ConnectionWorker class |
| 3.2 | Integration tests | Test parameter isolation |
| 3.3 | `simulation/worker_process.py` | Add mid-connection parameter updates |

### Phase 4: Process Orchestrator (Week 4)

| Task | Files | Description |
|------|-------|-------------|
| 4.1 | `simulation/process_orchestrator.py` | ProcessOrchestrator class |
| 4.2 | `simulation/ml_controller.py` | MLController class |
| 4.3 | `simulation/multi_connection_result.py` | Result data structures |

### Phase 5: CLI and Integration (Week 5)

| Task | Files | Description |
|------|-------|-------------|
| 5.1 | `main.py` | Add `run-3conn` command |
| 5.2 | Integration tests | Full system tests |
| 5.3 | Documentation | Update README, add examples |

---

## 9. Integration with Existing Code

### 9.1 Files to Modify

| File | Changes |
|------|---------|
| `main.py` | Add new CLI commands: `run-single`, `run-3conn`, `status-3conn` |
| `config/parameters.py` | Add `SingleAppGridSearchParams`, extend parameter ranges |
| `grid_search/parameter_space.py` | Add `generate_for_single_app()` method |
| `metrics/exporter.py` | Add `export_single_app()`, `export_multi_connection()` |
| `results/analyzer.py` | Add methods for analyzing single-app and multi-conn results |

### 9.2 Code Reuse

| Component | Reuse Strategy |
|-----------|----------------|
| `SimulationRunner` | Used directly for single-app grid search |
| `QuicServer` | Used in main process for 3-conn mode |
| `QuicClient` | Base for worker process connections |
| `MetricsCollector` | Instantiated in each worker process |
| `SynthesizerFactory` | Used in each worker for data generation |
| `MetricsCalculator` | Used for computing final metrics |

### 9.3 Backwards Compatibility

The existing `run` command continues to work exactly as before. New commands are added alongside:

```bash
# Existing (unchanged)
uv run main.py run              # Full grid search (all apps, all params)
uv run main.py status           # Grid search status
uv run main.py analyze          # Analyze results

# New commands
uv run main.py run-single       # Single-app grid search
uv run main.py run-3conn        # 3 concurrent connections
uv run main.py status-3conn     # 3-conn status
```

---

## 10. Testing Strategy

### 10.1 Unit Tests

```python
# tests/test_connection_config.py
def test_connection_config_creation():
    config = ConnectionConfig.create_for_video(1)
    assert config.connection_id == 1
    assert config.application_type == "video_streaming"
    assert config.initial_cw == 72000

def test_dynamic_parameters():
    assert "loss_reduction_factor" in DYNAMIC_PARAMETERS
    assert "initial_cw" not in DYNAMIC_PARAMETERS

# tests/test_ipc_messages.py
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
    assert 0.8 in values
```

### 10.2 Integration Tests

```python
# tests/test_single_app_grid_search.py
@pytest.mark.asyncio
async def test_single_app_grid_search():
    """Test single-app grid search completes successfully."""
    executor = SingleAppGridSearchExecutor(
        application_type="video_streaming",
        output_dir="output/test_single",
    )
    # Use minimal parameter space for testing
    executor.param_space = SingleAppGridSearchParams(
        initial_cw_values=[12000],
        max_ack_delay_values=[0.025],
        loss_factor_values=[0.5],
    )

    result = await executor.execute()
    assert result["status"] == "complete"
    assert result["completed"] == 1

# tests/test_three_connections.py
@pytest.mark.asyncio
async def test_three_connections():
    """Test 3 concurrent connections run successfully."""
    config = MultiConnectionConfig.create_baseline()
    config.simulation_duration = 5.0  # Short test

    orchestrator = ProcessOrchestrator(config)
    result = await orchestrator.run()

    assert result.success
    assert len(result.connection_results) == 3

    for conn_result in result.connection_results.values():
        assert conn_result.success
        assert conn_result.final_metrics["throughput"] > 0

# tests/test_mid_connection_update.py
@pytest.mark.asyncio
async def test_mid_connection_parameter_update():
    """Test parameter can be updated mid-connection."""
    updates_made = []

    def test_ml_callback(metrics):
        if len(metrics) == 3 and len(updates_made) == 0:
            updates_made.append(time.time())
            return {1: {"loss_reduction_factor": 0.6}}
        return {}

    config = MultiConnectionConfig.create_baseline()
    config.simulation_duration = 10.0

    orchestrator = ProcessOrchestrator(config, ml_callback=test_ml_callback)
    result = await orchestrator.run()

    assert len(updates_made) > 0
    # Verify parameter was tracked in history
    conn1_result = result.connection_results[1]
    assert len(conn1_result.param_history) > 0
    assert conn1_result.param_history[0]["param_name"] == "loss_reduction_factor"
```

---

## 11. CLI Commands

### 11.1 Single Connection Grid Search

```bash
# Run grid search for a single application type
uv run main.py run-single --app video_streaming
uv run main.py run-single --app file_transfer
uv run main.py run-single --app conference_call

# Options
uv run main.py run-single --app video_streaming \
    --duration 10 \              # Per-simulation duration (seconds)
    --output-dir output/video \  # Output directory
    --dry-run                    # Show what would run

# Check status
uv run main.py status-single --app video_streaming

# Analyze results
uv run main.py analyze-single --app video_streaming
```

### 11.2 Three Concurrent Connections

```bash
# Run 3 concurrent connections with default config
uv run main.py run-3conn

# Run with custom duration
uv run main.py run-3conn --duration 60

# Run with ML controller enabled
uv run main.py run-3conn --with-ml

# Run with custom config file
uv run main.py run-3conn --config configs/custom_3conn.json

# Options
uv run main.py run-3conn \
    --duration 30 \                    # Simulation duration (seconds)
    --metrics-interval 0.1 \           # Metrics collection interval
    --output-dir output/3conn \        # Output directory
    --with-ml \                        # Enable ML controller
    --ml-callback my_module:callback   # Custom ML callback

# Check status
uv run main.py status-3conn

# Analyze results
uv run main.py analyze-3conn --output-dir output/3conn
```

### 11.3 Implementation in main.py

```python
# main.py additions

def cmd_run_single(args):
    """Run single-application grid search."""
    from grid_search.single_app_executor import SingleAppGridSearchExecutor

    print(f"Single Application Grid Search: {args.app}")
    print("=" * 50)

    executor = SingleAppGridSearchExecutor(
        application_type=args.app,
        output_dir=args.output_dir,
    )

    result = asyncio.run(executor.execute(dry_run=args.dry_run))

    print(f"\nCompleted: {result['completed']}/{result['total']}")
    return 0


def cmd_run_3conn(args):
    """Run 3 concurrent connections."""
    from config.multi_connection_config import MultiConnectionConfig
    from simulation.process_orchestrator import ProcessOrchestrator

    print("QUIC 3-Connection Mode")
    print("=" * 50)

    # Load or create config
    if args.config:
        config = MultiConnectionConfig.from_json(args.config)
    else:
        config = MultiConnectionConfig.create_default()

    config.simulation_duration = args.duration

    # Setup ML callback if enabled
    ml_callback = None
    if args.with_ml:
        if args.ml_callback:
            # Load custom callback
            module_name, func_name = args.ml_callback.split(":")
            module = __import__(module_name)
            ml_callback = getattr(module, func_name)
        else:
            # Use default callback
            from simulation.ml_controller import default_fairness_callback
            ml_callback = default_fairness_callback

    # Create orchestrator and run
    orchestrator = ProcessOrchestrator(
        config=config,
        ml_callback=ml_callback,
        metrics_interval=args.metrics_interval,
    )

    result = asyncio.run(orchestrator.run())

    # Export results
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    result.export_json(output_path / "result.json")
    result.export_metrics_history(output_path / "metrics_history.json")

    # Print summary
    print_3conn_summary(result)

    return 0 if result.success else 1


# Add argument parsers
def main():
    # ... existing code ...

    # Single-app command
    single_parser = subparsers.add_parser("run-single", help="Run single-app grid search")
    single_parser.add_argument(
        "--app", required=True,
        choices=["video_streaming", "file_transfer", "conference_call"],
        help="Application type to test",
    )
    single_parser.add_argument("--duration", type=float, default=10.0)
    single_parser.add_argument("--output-dir", default="output/single")
    single_parser.add_argument("--dry-run", action="store_true")
    single_parser.set_defaults(func=cmd_run_single)

    # 3-conn command
    conn3_parser = subparsers.add_parser("run-3conn", help="Run 3 concurrent connections")
    conn3_parser.add_argument("--duration", type=float, default=30.0)
    conn3_parser.add_argument("--metrics-interval", type=float, default=0.1)
    conn3_parser.add_argument("--output-dir", default="output/3conn")
    conn3_parser.add_argument("--config", help="Path to JSON config file")
    conn3_parser.add_argument("--with-ml", action="store_true")
    conn3_parser.add_argument("--ml-callback", help="module:function for ML callback")
    conn3_parser.set_defaults(func=cmd_run_3conn)
```

---

## 12. Configuration Files

### 12.1 Default 3-Connection Config (JSON)

```json
{
  "server_host": "localhost",
  "server_port": 4433,
  "simulation_duration": 30.0,
  "metrics_interval": 0.1,

  "_comment_shared": "START-ONLY PARAMETERS - CONSTANT for all 3 connections",
  "shared_initial_cw": 12000,
  "shared_max_ack_delay": 0.025,
  "shared_max_data": 1048576,
  "shared_max_stream_data": 1048576,

  "_comment_video": "DYNAMIC PARAMETERS ONLY - these can differ per-connection",
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

**Note:** The `shared_*` parameters are applied identically to all 3 connections. Only the dynamic parameters (`loss_reduction_factor`, `cubic_c`, `minimum_window`, `packet_threshold`, `time_threshold`, `cubic_max_idle_time`) can differ between connections and be modified mid-connection.

### 12.2 Example ML Callback

```python
# ml_callbacks/fairness_optimizer.py

def fairness_optimizer(metrics: dict) -> dict:
    """
    ML callback that optimizes for fairness across connections.

    Uses Jain's fairness index and adjusts loss_reduction_factor
    to achieve more equal throughput distribution.

    Args:
        metrics: Dict mapping connection_id to current metrics
            {
                1: {"throughput": 5000000, "rtt": 0.05, "jitter": 0.008,
                    "current_params": {"loss_reduction_factor": 0.6, ...}},
                2: {"throughput": 8000000, ...},
                3: {"throughput": 2000000, ...},
            }

    Returns:
        Dict mapping connection_id to parameter updates
            {1: {}, 2: {"loss_reduction_factor": 0.8}, 3: {"loss_reduction_factor": 0.4}}
    """
    if len(metrics) < 3:
        return {}

    decisions = {}

    # Calculate current throughputs
    throughputs = [(k, m.get("throughput", 0)) for k, m in metrics.items()]

    # Calculate Jain's fairness index
    n = len(throughputs)
    sum_x = sum(t for _, t in throughputs)
    sum_x_sq = sum(t**2 for _, t in throughputs)
    fairness = (sum_x ** 2) / (n * sum_x_sq) if sum_x_sq > 0 else 1.0

    # If fairness is low, adjust parameters
    if fairness < 0.85:
        # Find connection with highest throughput
        max_conn_id = max(throughputs, key=lambda x: x[1])[0]
        current_lrf = metrics[max_conn_id]["current_params"]["loss_reduction_factor"]

        # Make it more conservative (reduce cwnd more on loss)
        decisions[max_conn_id] = {
            "loss_reduction_factor": min(0.9, current_lrf + 0.05)
        }

        # Find connection with lowest throughput
        min_conn_id = min(throughputs, key=lambda x: x[1])[0]
        current_lrf = metrics[min_conn_id]["current_params"]["loss_reduction_factor"]

        # Make it more aggressive (reduce cwnd less on loss)
        decisions[min_conn_id] = {
            "loss_reduction_factor": max(0.3, current_lrf - 0.05)
        }

    return decisions


def protect_conference_call(metrics: dict) -> dict:
    """
    ML callback that prioritizes conference call quality.

    If conference call jitter exceeds threshold, reduces
    other connections' aggressiveness.
    """
    if len(metrics) < 3:
        return {}

    decisions = {}

    # Check conference call (connection 3) jitter
    conf_metrics = metrics.get(3, {})
    conf_jitter = conf_metrics.get("jitter", 0)

    JITTER_THRESHOLD = 0.015  # 15ms

    if conf_jitter > JITTER_THRESHOLD:
        # Conference call has high jitter - reduce others' bandwidth

        # Make file transfer (conn 2) more conservative
        file_lrf = metrics.get(2, {}).get("current_params", {}).get("loss_reduction_factor", 0.7)
        decisions[2] = {
            "loss_reduction_factor": min(0.9, file_lrf + 0.1),
            "cubic_c": 0.3,  # Slower growth
        }

        # Make conference call more aggressive
        conf_lrf = conf_metrics.get("current_params", {}).get("loss_reduction_factor", 0.5)
        decisions[3] = {
            "loss_reduction_factor": max(0.3, conf_lrf - 0.05),
            "minimum_window": 8,  # Higher floor
        }

    return decisions
```

---

## Summary

This implementation plan provides:

1. **Single Connection Grid Search** - Systematic parameter exploration for individual applications using the existing `SimulationRunner` in a single process

2. **Three Concurrent Connections** - Multi-process architecture where:
   - Each connection runs in a separate Python process
   - aioquic module globals are naturally isolated per process
   - IPC (Pipes + Queue) enables parameter updates and metrics collection
   - ML controller can modify parameters mid-connection
   - Synchronized start ensures fair bandwidth competition

3. **Complete Parameter Control**:
   - **Start-only parameters (CONSTANT for all connections)**: `initial_cw`, `max_ack_delay`, `max_data`, `max_stream_data` - these use the same value for all 3 connections to ensure fair initial conditions
   - **Dynamic parameters (per-connection isolated)**: `loss_reduction_factor`, `cubic_c`, `minimum_window`, `packet_threshold`, `time_threshold`, `cubic_max_idle_time` - these CAN differ between connections and are the focus of ML optimization

4. **Integration with Existing Code**:
   - Reuses existing `SimulationRunner`, synthesizers, metrics collection
   - New commands coexist with existing CLI
   - Backwards compatible with current grid search

The multi-process approach elegantly solves the aioquic global parameter limitation while maintaining the ability to share network conditions across all connections for realistic bandwidth competition testing.
