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

---

## 1. Executive Summary

This implementation plan describes a **standalone system** for running 3 concurrent QUIC connections, each representing a different application type, with the ability to modify congestion control parameters mid-connection.

**Key Features:**
- **3 Concurrent QUIC Connections** - Video streaming, file transfer, and conference call running simultaneously
- **Per-connection isolated parameters** - Achieved via multi-process architecture
- **Mid-connection parameter modification** - Dynamic tuning of CC parameters while connections are active
- **Shared network conditions** - All connections experience the same bandwidth/latency/loss from `wireless_bottleneck/`
- **ML controller integration** - Optional callback interface for dynamic parameter optimization

### Key Challenge Addressed

The aioquic library stores congestion control parameters as **module-level globals**:

```python
# aioquic/quic/congestion/cubic.py
K_CUBIC_LOSS_REDUCTION_FACTOR = 0.7  # Affects ALL connections in process
K_CUBIC_C = 0.4                       # Affects ALL connections in process
```

**Solution:** Multi-process architecture where each connection runs in a separate Python process with its own aioquic module instance.

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

### 4.1 Folder Structure

```
wireless_bottleneck/
├── apply_conditions.sh      # Script to apply tc/netem rules
├── remove_conditions.sh     # Script to remove tc/netem rules
├── profiles/
│   ├── lte_good.json        # LTE good conditions (15 Mbps, 30ms RTT, 0.5% loss)
│   ├── lte_poor.json        # LTE poor conditions (5 Mbps, 100ms RTT, 3% loss)
│   ├── wifi_congested.json  # WiFi congested (10 Mbps, 50ms RTT, 2% loss)
│   ├── wifi_good.json       # WiFi good (50 Mbps, 5ms RTT, 0.1% loss)
│   └── variable.json        # Time-varying conditions
└── README.md
```

### 4.2 Network Condition Parameters

| Parameter | Description | Example Values |
|-----------|-------------|----------------|
| `bandwidth` | Maximum throughput (shared bottleneck) | 5-50 Mbps |
| `latency` | Base one-way delay | 5-150 ms |
| `jitter` | Delay variation | ±5-30 ms |
| `loss_rate` | Random packet loss | 0.1-5% |

### 4.3 Example Profile (lte_good.json)

```json
{
  "name": "LTE Good Conditions",
  "bandwidth_mbps": 15,
  "latency_ms": 30,
  "jitter_ms": 5,
  "loss_percent": 0.5
}
```

### 4.4 Execution Flow with Network Conditions

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    EXECUTION WITH NETWORK CONDITIONS                             │
└─────────────────────────────────────────────────────────────────────────────────┘

Step 1: Apply network conditions
        $ ./wireless_bottleneck/apply_conditions.sh profiles/lte_good.json

        ┌─────────────────────────────────────────────────────────────────────┐
        │   tc qdisc add dev lo root handle 1: tbf rate 15mbit ...           │
        │   tc qdisc add dev lo parent 1:1 netem delay 30ms 5ms loss 0.5%    │
        └─────────────────────────────────────────────────────────────────────┘

Step 2: Run 3-connection simulation
        $ uv run main.py run --duration 30

        ┌─────────────────────────────────────────────────────────────────────┐
        │   All 3 connections compete for the 15 Mbps bottleneck             │
        │   ML controller can adjust dynamic params based on metrics         │
        └─────────────────────────────────────────────────────────────────────┘

Step 3: Remove network conditions
        $ ./wireless_bottleneck/remove_conditions.sh

        ┌─────────────────────────────────────────────────────────────────────┐
        │   tc qdisc del dev lo root                                          │
        └─────────────────────────────────────────────────────────────────────┘
```

### 4.5 Why Network Conditions Are Required

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

### 6.3 Message Types

| Message | Direction | Purpose |
|---------|-----------|---------|
| `UPDATE_PARAM` | Main → Worker | Update single dynamic parameter |
| `UPDATE_MULTIPLE_PARAMS` | Main → Worker | Update multiple parameters at once |
| `STOP` | Main → Worker | Signal worker to stop and report final results |
| `METRICS` | Worker → Main | Periodic metrics report (every 100ms) |
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
    ├── pyproject.toml                   # Dependencies (aioquic, etc.)
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
    │   └── exporter.py                  # JSON export functionality
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
    │   └── test_integration.py
    │
    └── output/                          # Results output
        ├── result.json
        └── metrics_history.json
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
        self._param_history = []

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
        """Main worker loop."""
        self._apply_initial_parameters()
        self.start_barrier.wait()

        self._running = True
        start_time = time.time()

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

                synthesizer = SynthesizerFactory.create(
                    self.config.application_type,
                    duration_seconds=duration,
                )

                stream_id = protocol._quic.get_next_available_stream_id()
                last_metrics_time = time.time()
                metrics_interval = 0.1

                async for packet in synthesizer.generate():
                    if not self._running or (time.time() - start_time) >= duration:
                        break

                    protocol._quic.send_stream_data(stream_id, packet.data, end_stream=False)
                    self._metrics_collector.record_packet_sent(packet.size)

                    rtt = self._get_rtt(protocol)
                    if rtt and rtt > 0:
                        self._metrics_collector.record_rtt_sample(rtt)

                    self._check_commands()

                    if time.time() - last_metrics_time >= metrics_interval:
                        self._send_metrics()
                        last_metrics_time = time.time()

                    await asyncio.sleep(0)

                self._metrics_collector.stop()
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
    """Entry point for worker process."""
    config = ConnectionConfig.from_dict(config_dict)
    worker = ConnectionWorker(
        config=config,
        server_host=server_host,
        server_port=server_port,
        command_pipe=command_pipe,
        metrics_queue=metrics_queue,
        start_barrier=start_barrier,
    )
    asyncio.run(worker.run(duration))
```

### 10.4 ProcessOrchestrator

```python
# simulation/process_orchestrator.py

import asyncio
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
    ):
        self.config = config
        self.ml_callback = ml_callback
        self.metrics_interval = metrics_interval

        self.workers: Dict[int, Process] = {}
        self.command_pipes: Dict[int, Pipe] = {}
        self.metrics_queue: Queue = Queue()
        self.start_barrier: Optional[Barrier] = None
        self.server: Optional[QuicServer] = None
        self.ml_controller: Optional[MLController] = None
        self.metrics_history: List[Dict] = []
        self.final_results: Dict[int, dict] = {}

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

            self.start_barrier.wait()

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
        for process in self.workers.values():
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)

        if self.server:
            await self.server.stop()

        for pipe in self.command_pipes.values():
            pipe.close()
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
                decisions = self.ml_callback(self.latest_metrics.copy())
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
            except:
                break

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

    # Run
    orchestrator = ProcessOrchestrator(
        config=config,
        ml_callback=ml_callback,
        metrics_interval=args.metrics_interval,
    )

    result = asyncio.run(orchestrator.run())

    # Export
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    result.export_json(output_path / "result.json")
    result.export_metrics_history(output_path / "metrics_history.json")

    # Summary
    print(f"\nSuccess: {result.success}")
    for conn_id, conn_result in result.connection_results.items():
        print(f"  Connection {conn_id} ({conn_result.application_type}):")
        print(f"    Throughput: {conn_result.final_metrics.get('throughput', 0) / 1e6:.2f} Mbps")
        print(f"    RTT: {conn_result.final_metrics.get('rtt', 0) * 1000:.1f} ms")

    return 0 if result.success else 1


def main():
    parser = argparse.ArgumentParser(description="QUIC 3-Connection Simulation")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run simulation")
    run_parser.add_argument("--duration", type=float, default=30.0)
    run_parser.add_argument("--metrics-interval", type=float, default=0.1)
    run_parser.add_argument("--output-dir", default="output")
    run_parser.add_argument("--config", help="Path to JSON config file")
    run_parser.add_argument("--with-ml", action="store_true")
    run_parser.add_argument("--ml-callback", help="module:function")
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

---

## Summary

This implementation plan provides a **standalone system** for running 3 concurrent QUIC connections with:

1. **Multi-process architecture** - Each connection runs in a separate Python process with isolated aioquic globals

2. **Network conditions from `wireless_bottleneck/`** - Realistic shared bottleneck using tc/netem

3. **Mid-connection parameter modification** - Dynamic parameters can be changed while connections are active

4. **ML controller integration** - Optional callback interface for intelligent parameter optimization

5. **Complete metrics collection** - Throughput, RTT, latency, jitter, packet loss per connection

6. **Parameter history tracking** - All parameter changes are recorded with timestamps

7. **Synthesizers matching `/code` directory** - Video streaming (30fps I/P frames), file transfer (64KB chunks), conference call (20ms intervals)

8. **QUIC client/server matching `/code` directory** - Same `ClientProtocol`, `QuicClient`, `ServerProtocol`, `QuicServer` patterns

9. **Metrics collection matching `/code` directory** - Same `MetricsCollector` and `MetricsCalculator` with 6 metrics

**Target Location:** `QUIC_3conn_implementation/3_conn_code/`

**Key Distinction from draft_IMP_3CONN.md:**
- This implementation is **standalone** (not integrated with existing `/code` directory)
- No grid search functionality - focuses solely on 3-connection mode
- Built from scratch in a new directory
- Uses the same synthesizer, client/server, and metrics logic as the original `/code` directory
