# Multi-Process Implementation Plan for Per-Connection Parameter Isolation

This document provides an in-depth implementation plan for running 3 QUIC connections in separate processes to achieve true per-connection parameter isolation while sharing the same network conditions.

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Solution Overview](#solution-overview)
3. [Architecture](#architecture)
4. [Network Simulation Integration](#network-simulation-integration)
5. [Inter-Process Communication Design](#inter-process-communication-design)
6. [ML Controller Integration](#ml-controller-integration)
7. [Implementation Steps](#implementation-steps)
8. [File Structure](#file-structure)
9. [Code Examples](#code-examples)
10. [Synchronization and Timing](#synchronization-and-timing)
11. [Error Handling](#error-handling)
12. [Testing Strategy](#testing-strategy)
13. [Performance Considerations](#performance-considerations)
14. [Migration from Single-Process](#migration-from-single-process)

---

## Problem Statement

### Current Limitation

The aioquic library stores congestion control parameters as **module-level global constants**:

```python
# aioquic/quic/congestion/cubic.py
K_CUBIC_LOSS_REDUCTION_FACTOR = 0.7  # Affects ALL connections
K_CUBIC_C = 0.4                       # Affects ALL connections
K_MINIMUM_WINDOW = 2                  # Affects ALL connections
```

In a single Python process, changing any of these values affects **every active QUIC connection simultaneously**, making true per-connection ML optimization impossible.

### Goal

Run 3 QUIC connections with:
- **Isolated CC parameters** - Each connection has its own `K_CUBIC_LOSS_REDUCTION_FACTOR`, `K_CUBIC_C`, etc.
- **Same network conditions** - All connections experience identical bandwidth, latency, loss, and jitter
- **ML integration** - Central controller can monitor metrics and update parameters mid-connection
- **Concurrent execution** - All connections run simultaneously and compete for bandwidth

---

## Solution Overview

### Multi-Process Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              KERNEL LEVEL                                   │
│                                                                             │
│    tc qdisc (netem): 15Mbps, 50ms delay, 1% loss, 10ms jitter              │
│    Applied to: lo interface (or specified interface)                       │
│                                                                             │
│    ─────────────────────────────────────────────────────────────────────    │
│                          All traffic passes through                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │
┌─────────────────────────────────────┼───────────────────────────────────────┐
│                              USER SPACE                                     │
│                                      │                                      │
│  ┌───────────────────────────────────┼───────────────────────────────────┐  │
│  │                         Main Process                                  │  │
│  │                      (ML Controller / Orchestrator)                   │  │
│  │                                                                       │  │
│  │   ┌─────────────────────────────────────────────────────────────┐    │  │
│  │   │                    Process Manager                           │    │  │
│  │   │  • Spawns worker processes                                   │    │  │
│  │   │  • Manages IPC channels                                      │    │  │
│  │   │  • Collects metrics from all connections                     │    │  │
│  │   │  • Sends parameter updates to workers                        │    │  │
│  │   └─────────────────────────────────────────────────────────────┘    │  │
│  │                                                                       │  │
│  │   ┌─────────────────────────────────────────────────────────────┐    │  │
│  │   │                    ML Decision Engine                        │    │  │
│  │   │  • Receives aggregated metrics                               │    │  │
│  │   │  • Computes optimal parameters per connection                │    │  │
│  │   │  • Sends parameter updates via IPC                           │    │  │
│  │   └─────────────────────────────────────────────────────────────┘    │  │
│  │                                                                       │  │
│  │   ┌─────────────────────────────────────────────────────────────┐    │  │
│  │   │                    QUIC Server                               │    │  │
│  │   │  • Single shared server on localhost:4433                    │    │  │
│  │   │  • Handles all 3 client connections                          │    │  │
│  │   └─────────────────────────────────────────────────────────────┘    │  │
│  │                                                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                      │                                      │
│            ┌─────────────────────────┼─────────────────────────┐            │
│            │                         │                         │            │
│            ▼                         ▼                         ▼            │
│  ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐     │
│  │   Process 1     │      │   Process 2     │      │   Process 3     │     │
│  │   (Video)       │      │   (File)        │      │  (Conference)   │     │
│  │                 │      │                 │      │                 │     │
│  │ ┌─────────────┐ │      │ ┌─────────────┐ │      │ ┌─────────────┐ │     │
│  │ │  aioquic    │ │      │ │  aioquic    │ │      │ │  aioquic    │ │     │
│  │ │  globals:   │ │      │ │  globals:   │ │      │ │  globals:   │ │     │
│  │ │             │ │      │ │             │ │      │ │             │ │     │
│  │ │ LRF = 0.5   │ │      │ │ LRF = 0.7   │ │      │ │ LRF = 0.3   │ │     │
│  │ │ C   = 0.4   │ │      │ │ C   = 0.5   │ │      │ │ C   = 0.3   │ │     │
│  │ │ MIN = 4     │ │      │ │ MIN = 2     │ │      │ │ MIN = 6     │ │     │
│  │ └─────────────┘ │      │ └─────────────┘ │      │ └─────────────┘ │     │
│  │                 │      │                 │      │                 │     │
│  │ ┌─────────────┐ │      │ ┌─────────────┐ │      │ ┌─────────────┐ │     │
│  │ │   Metrics   │ │      │ │   Metrics   │ │      │ │   Metrics   │ │     │
│  │ │  Collector  │ │      │ │  Collector  │ │      │ │  Collector  │ │     │
│  │ └─────────────┘ │      │ └─────────────┘ │      │ └─────────────┘ │     │
│  │                 │      │                 │      │                 │     │
│  │ ◄────Pipe────►  │      │ ◄────Pipe────►  │      │ ◄────Pipe────►  │     │
│  └────────┬────────┘      └────────┬────────┘      └────────┬────────┘     │
│           │                        │                        │              │
│           └────────────────────────┼────────────────────────┘              │
│                                    │                                        │
│                                    ▼                                        │
│                           QUIC Server (4433)                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Benefits

| Aspect | Single Process | Multi-Process |
|--------|---------------|---------------|
| Parameter isolation | Shared globals | **True isolation** |
| Same network conditions | Yes | **Yes** (tc/netem at kernel level) |
| ML integration | Direct calls | IPC (Pipes/Queues) |
| Memory overhead | Lower | Higher (3x Python interpreters) |
| Debugging | Easier | More complex |
| Bandwidth competition | Natural | **Natural** (shared interface) |

---

## Network Simulation Integration

### Why tc/netem Works Across Processes

`tc` (traffic control) and `netem` operate at the **Linux kernel level**, affecting all traffic on the specified interface regardless of which process generates it.

```
┌─────────────────────────────────────────────────────────────────┐
│                    Linux Kernel Network Stack                    │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │                    tc qdisc (netem)                       │  │
│   │                                                          │  │
│   │   Parameters applied to ALL packets on interface:        │  │
│   │   • rate 15mbit        (bandwidth limit)                 │  │
│   │   • delay 50ms 10ms    (latency + jitter)               │  │
│   │   • loss 1%            (packet loss)                     │  │
│   │                                                          │  │
│   └──────────────────────────────────────────────────────────┘  │
│                              │                                   │
│         ┌────────────────────┼────────────────────┐             │
│         │                    │                    │             │
│         ▼                    ▼                    ▼             │
│   ┌──────────┐        ┌──────────┐        ┌──────────┐         │
│   │ Process 1│        │ Process 2│        │ Process 3│         │
│   │  Packets │        │  Packets │        │  Packets │         │
│   └──────────┘        └──────────┘        └──────────┘         │
│                                                                  │
│   All processes experience IDENTICAL network conditions         │
│   All processes COMPETE for the same 15Mbps bandwidth           │
└─────────────────────────────────────────────────────────────────┘
```

### Network Setup Commands

```bash
# Setup network simulation BEFORE starting processes
# This is done once by the main orchestrator

# Option 1: Apply to loopback (for localhost testing)
sudo tc qdisc add dev lo root netem \
    delay 50ms 10ms distribution normal \
    loss 1% \
    rate 15mbit

# Option 2: Apply to specific interface
sudo tc qdisc add dev eth0 root netem \
    delay 50ms 10ms distribution normal \
    loss 1% \
    rate 15mbit

# Cleanup after test
sudo tc qdisc del dev lo root
```

### Integration with Existing wireless_bottleneck Module

```python
# In main orchestrator process
from wireless_bottleneck import WirelessBottleneck, get_scenario

class MultiProcessOrchestrator:
    def __init__(self, scenario_name: str = "moderate_congestion"):
        self.scenario = get_scenario(scenario_name)
        self.bottleneck = None

    async def run_with_network_simulation(self):
        """Run all processes under simulated network conditions."""

        # Apply network conditions (affects all processes)
        with WirelessBottleneck(self.scenario.config, interface="lo") as self.bottleneck:
            # Now spawn worker processes - they all experience these conditions
            await self._run_worker_processes()

            # Collect results
            return self._aggregate_results()
```

### Bandwidth Competition Behavior

When 3 processes share a 15Mbps bottleneck:

```
Time 0s:    All 3 connections start
            Each tries to grow cwnd (CUBIC slow start)

Time 1-2s:  Connections compete for bandwidth
            Total demand > 15Mbps
            Packet loss occurs (buffer overflow or netem loss)

Time 2-5s:  CC algorithms respond to loss
            - Connection with LRF=0.3 reduces less aggressively
            - Connection with LRF=0.7 reduces more aggressively
            Bandwidth allocation shifts based on CC parameters

Time 5-30s: Steady state competition
            ML controller can observe and adjust parameters
            Each adjustment affects only ONE connection's behavior
```

---

## Inter-Process Communication Design

### IPC Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Main Process (Orchestrator)                        │
│                                                                              │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                        IPC Manager                                    │  │
│   │                                                                       │  │
│   │   metrics_queues: Dict[int, Queue]    # Metrics FROM workers         │  │
│   │   command_pipes: Dict[int, Pipe]      # Commands TO workers          │  │
│   │   status_queue: Queue                 # Status FROM all workers      │  │
│   │                                                                       │  │
│   └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│        │                      │                      │                       │
│        │ Pipe (bidirectional) │ Pipe                 │ Pipe                  │
│        │                      │                      │                       │
│        ▼                      ▼                      ▼                       │
│   ┌─────────────┐       ┌─────────────┐       ┌─────────────┐               │
│   │  Worker 1   │       │  Worker 2   │       │  Worker 3   │               │
│   │  (Video)    │       │  (File)     │       │ (Conference)│               │
│   │             │       │             │       │             │               │
│   │ Receives:   │       │ Receives:   │       │ Receives:   │               │
│   │ • Params    │       │ • Params    │       │ • Params    │               │
│   │ • Commands  │       │ • Commands  │       │ • Commands  │               │
│   │             │       │             │       │             │               │
│   │ Sends:      │       │ Sends:      │       │ Sends:      │               │
│   │ • Metrics   │       │ • Metrics   │       │ • Metrics   │               │
│   │ • Status    │       │ • Status    │       │ • Status    │               │
│   └─────────────┘       └─────────────┘       └─────────────┘               │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Message Types

```python
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

class MessageType(Enum):
    # Commands (Main → Worker)
    START = "start"
    STOP = "stop"
    UPDATE_PARAM = "update_param"
    GET_METRICS = "get_metrics"

    # Responses (Worker → Main)
    METRICS = "metrics"
    STATUS = "status"
    ACK = "ack"
    ERROR = "error"
    FINISHED = "finished"

@dataclass
class IPCMessage:
    """Message format for inter-process communication."""
    msg_type: MessageType
    connection_id: int
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

# Example messages
param_update = IPCMessage(
    msg_type=MessageType.UPDATE_PARAM,
    connection_id=1,
    timestamp=time.time(),
    payload={
        "param_name": "loss_reduction_factor",
        "value": 0.5,
    }
)

metrics_report = IPCMessage(
    msg_type=MessageType.METRICS,
    connection_id=1,
    timestamp=time.time(),
    payload={
        "throughput": 5_000_000,
        "rtt": 0.052,
        "jitter": 0.008,
        "packet_loss_rate": 0.012,
        "cwnd": 45000,
        "bytes_sent": 15_000_000,
    }
)
```

### Pipe vs Queue Selection

| Use Case | Recommended | Reason |
|----------|-------------|--------|
| Commands to worker | `Pipe` | Bidirectional, low latency |
| Metrics from worker | `Queue` | Thread-safe, buffered |
| Status updates | Shared `Queue` | Aggregate from all workers |
| Synchronization | `Event` / `Barrier` | Start all at same time |

---

## ML Controller Integration

### Controller Architecture

```python
from multiprocessing import Process, Pipe, Queue, Event, Barrier
from typing import Dict, List, Callable, Optional
import asyncio

class MLController:
    """
    Central ML controller that runs in the main process.

    Responsibilities:
    - Collect metrics from all worker processes
    - Run ML decision algorithm
    - Send parameter updates to workers
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
        self.metrics_history: List[Dict[int, dict]] = []

        # IPC channels (set by orchestrator)
        self.command_pipes: Dict[int, Pipe] = {}
        self.metrics_queue: Queue = None

    def set_ipc_channels(
        self,
        command_pipes: Dict[int, Pipe],
        metrics_queue: Queue,
    ):
        """Set IPC channels after process creation."""
        self.command_pipes = command_pipes
        self.metrics_queue = metrics_queue

    async def run_control_loop(self, duration: float):
        """
        Main control loop that runs for specified duration.

        1. Collect metrics from all workers
        2. Run ML decision algorithm
        3. Send parameter updates if needed
        """
        start_time = time.time()

        while (time.time() - start_time) < duration:
            # Collect latest metrics from all workers
            self._collect_metrics()

            # Run ML decision
            if len(self.latest_metrics) == 3:  # All workers reporting
                decisions = self.ml_callback(self.latest_metrics)

                # Send parameter updates
                for conn_id, params in decisions.items():
                    if params:  # Only if changes needed
                        self._send_param_update(conn_id, params)

            # Record history
            self.metrics_history.append(self.latest_metrics.copy())

            # Wait for next decision interval
            await asyncio.sleep(self.decision_interval)

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
            for param_name, value in params.items():
                msg = IPCMessage(
                    msg_type=MessageType.UPDATE_PARAM,
                    connection_id=conn_id,
                    timestamp=time.time(),
                    payload={"param_name": param_name, "value": value},
                )
                pipe.send(msg.to_dict())

    def _default_decision(self, metrics: Dict[int, dict]) -> Dict[int, dict]:
        """
        Default ML decision algorithm.

        Override this with actual ML model.

        Returns:
            Dict mapping connection_id to parameter updates
        """
        decisions = {}

        # Example: Protect conference call if experiencing high loss
        conference_metrics = metrics.get(3)
        if conference_metrics and conference_metrics.get("packet_loss_rate", 0) > 0.02:
            # Reduce file transfer aggressiveness to free bandwidth
            decisions[2] = {"loss_reduction_factor": 0.8}  # More aggressive reduction
            # Make conference more aggressive
            decisions[3] = {"loss_reduction_factor": 0.4}  # Less aggressive reduction

        return decisions
```

### ML Callback Interface

```python
def my_ml_model(metrics: Dict[int, dict]) -> Dict[int, dict]:
    """
    Custom ML decision function.

    Args:
        metrics: Dict mapping connection_id to current metrics
            {
                1: {"throughput": 5000000, "rtt": 0.05, "jitter": 0.008, ...},
                2: {"throughput": 8000000, "rtt": 0.06, "jitter": 0.012, ...},
                3: {"throughput": 2000000, "rtt": 0.04, "jitter": 0.005, ...},
            }

    Returns:
        Dict mapping connection_id to parameter updates
            {
                1: {"loss_reduction_factor": 0.5},  # Change for video
                2: {},                               # No change for file
                3: {"cubic_c": 0.3},                # Change for conference
            }
    """
    # Your ML model logic here
    # Could use:
    # - Reinforcement learning (PPO, DQN, etc.)
    # - Bayesian optimization
    # - Neural network predictions
    # - Rule-based heuristics

    return decisions

# Usage
controller = MLController(
    decision_interval=0.1,
    ml_callback=my_ml_model,
)
```

---

## Implementation Steps

### Step 1: Create Worker Process Module

**File:** `simulation/worker_process.py`

```python
"""
Worker process for running a single QUIC connection.

Each worker runs in its own process with isolated aioquic globals.
Communicates with main process via IPC.
"""

import asyncio
import time
from multiprocessing import Process, Pipe, Queue
from multiprocessing.connection import Connection
from typing import Optional

from aioquic.quic.congestion import cubic as aioquic_cubic
from aioquic.quic import recovery as aioquic_recovery
from aioquic.quic.configuration import QuicConfiguration
from aioquic.asyncio import connect

from config.connection_config import ConnectionConfig
from metrics.collector import MetricsCollector
from synthesizers import SynthesizerFactory


class ConnectionWorker:
    """
    Worker that runs a single QUIC connection in an isolated process.

    Has its own copy of aioquic module globals.
    """

    def __init__(
        self,
        config: ConnectionConfig,
        server_host: str,
        server_port: int,
        command_pipe: Connection,
        metrics_queue: Queue,
        start_barrier,  # Barrier for synchronized start
    ):
        self.config = config
        self.server_host = server_host
        self.server_port = server_port
        self.command_pipe = command_pipe
        self.metrics_queue = metrics_queue
        self.start_barrier = start_barrier

        self._running = False
        self._metrics_collector = MetricsCollector()
        self._client = None

    def _apply_parameters(self):
        """
        Apply CC parameters to aioquic globals.

        These are ISOLATED to this process only.
        """
        aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = self.config.loss_reduction_factor
        aioquic_cubic.K_CUBIC_C = self.config.cubic_c
        aioquic_cubic.K_MINIMUM_WINDOW = self.config.minimum_window
        aioquic_recovery.K_PACKET_THRESHOLD = self.config.packet_threshold
        aioquic_recovery.K_TIME_THRESHOLD = self.config.time_threshold

        # Initial window (only affects this process)
        max_datagram_size = self.config.max_datagram_size
        initial_window_packets = self.config.initial_cw // max_datagram_size
        aioquic_cubic.K_INITIAL_WINDOW = initial_window_packets

    def _update_parameter(self, param_name: str, value):
        """Update a single parameter mid-connection."""
        setattr(self.config, param_name, value)

        # Apply to aioquic globals (isolated to this process)
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
                    # Send ACK
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
                "jitter": metrics.jitter,
                "packet_loss_rate": metrics.packet_loss_rate,
                "bytes_sent": self._metrics_collector.bytes_sent,
                "packets_sent": self._metrics_collector.packets_sent,
                # Include current parameters for tracking
                "current_params": {
                    "loss_reduction_factor": self.config.loss_reduction_factor,
                    "cubic_c": self.config.cubic_c,
                    "minimum_window": self.config.minimum_window,
                },
            },
        )
        self.metrics_queue.put(msg)

    async def run(self, duration: float):
        """
        Main worker loop.

        1. Wait for synchronized start
        2. Connect to server
        3. Send data while checking for commands
        4. Report metrics periodically
        """
        # Apply initial parameters
        self._apply_parameters()

        # Wait for all workers to be ready
        self.start_barrier.wait()

        self._running = True
        start_time = time.time()

        try:
            # Connect
            configuration = QuicConfiguration(
                is_client=True,
                max_datagram_frame_size=65536,
            )
            configuration.verify_mode = False

            async with connect(
                self.server_host,
                self.server_port,
                configuration=configuration,
            ) as protocol:
                self._metrics_collector.connection = protocol._quic
                self._metrics_collector.start()

                # Create synthesizer
                synthesizer = SynthesizerFactory.create(
                    self.config.application_type,
                    duration_seconds=duration,
                )

                # Send data with periodic command checks and metrics reports
                last_metrics_time = time.time()
                metrics_interval = 0.1  # 100ms

                for chunk in synthesizer.generate():
                    if not self._running:
                        break

                    # Send data
                    stream_id = protocol._quic.get_next_available_stream_id()
                    protocol._quic.send_stream_data(stream_id, chunk, end_stream=False)
                    self._metrics_collector.record_data_sent(len(chunk))

                    # Check for commands
                    self._check_commands()

                    # Report metrics periodically
                    if time.time() - last_metrics_time >= metrics_interval:
                        self._send_metrics()
                        last_metrics_time = time.time()

                    # Small yield to allow other async tasks
                    await asyncio.sleep(0.001)

                # Final metrics
                self._metrics_collector.stop()
                self._send_metrics()

                # Send finished message
                self._send_finished()

        except Exception as e:
            self._send_error(str(e))
            raise


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
    # Reconstruct config from dict (can't pickle dataclass directly sometimes)
    config = ConnectionConfig(**config_dict)

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

### Step 2: Create Process Orchestrator

**File:** `simulation/process_orchestrator.py`

```python
"""
Orchestrator for managing multiple QUIC connection processes.

Spawns worker processes, manages IPC, and coordinates ML controller.
"""

import asyncio
import time
from multiprocessing import Process, Pipe, Queue, Barrier
from typing import Dict, List, Optional, Callable

from config.multi_connection_config import MultiConnectionConfig
from simulation.worker_process import worker_process_entry
from simulation.server import QuicServer
from simulation.ml_controller import MLController
from simulation.multi_connection_result import MultiConnectionResult


class ProcessOrchestrator:
    """
    Orchestrates multiple QUIC connection processes.

    Manages:
    - Spawning worker processes
    - IPC channels
    - Network simulation setup
    - ML controller integration
    - Result collection
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
        self.start_barrier: Barrier = None

        # Server
        self.server: Optional[QuicServer] = None

        # ML Controller
        self.ml_controller: Optional[MLController] = None

        # Results
        self.all_metrics: List[Dict[int, dict]] = []

    async def setup(self):
        """Setup server and prepare for workers."""
        # Start QUIC server
        self.server = QuicServer(
            host=self.config.server_host,
            port=self.config.server_port,
        )
        await self.server.start()

        # Create barrier for synchronized start (3 workers + 1 main)
        self.start_barrier = Barrier(4)

        # Setup ML controller
        if self.ml_callback:
            self.ml_controller = MLController(
                decision_interval=self.metrics_interval,
                ml_callback=self.ml_callback,
            )

    def _spawn_workers(self, duration: float):
        """Spawn worker processes for each connection."""
        for conn_config in self.config.get_all_configs():
            # Create pipe for commands
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

            # Setup ML controller IPC
            if self.ml_controller:
                self.ml_controller.set_ipc_channels(
                    self.command_pipes,
                    self.metrics_queue,
                )

            # Wait at barrier to synchronize start
            self.start_barrier.wait()

            # Run ML control loop (or just collect metrics)
            if self.ml_controller:
                await self.ml_controller.run_control_loop(duration)
            else:
                await self._collect_metrics_loop(duration)

            # Wait for all workers to finish
            for process in self.workers.values():
                process.join(timeout=5)

            # Collect final results
            return self._build_results()

        finally:
            await self.cleanup()

    async def _collect_metrics_loop(self, duration: float):
        """Simple metrics collection without ML."""
        start_time = time.time()

        while (time.time() - start_time) < duration:
            # Collect metrics
            current_metrics = {}
            while not self.metrics_queue.empty():
                try:
                    msg = self.metrics_queue.get_nowait()
                    if msg.msg_type == MessageType.METRICS:
                        current_metrics[msg.connection_id] = msg.payload
                except:
                    break

            if current_metrics:
                self.all_metrics.append(current_metrics)

            await asyncio.sleep(self.metrics_interval)

    def _build_results(self) -> MultiConnectionResult:
        """Build final results from collected metrics."""
        # Get final metrics for each connection
        final_metrics = {}
        for conn_id in [1, 2, 3]:
            # Find last metrics for this connection
            for metrics_snapshot in reversed(self.all_metrics):
                if conn_id in metrics_snapshot:
                    final_metrics[conn_id] = metrics_snapshot[conn_id]
                    break

        # Build result object
        return MultiConnectionResult(
            config=self.config,
            connection_results=final_metrics,
            metrics_history=self.all_metrics,
            success=all(p.exitcode == 0 for p in self.workers.values()),
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

### Step 3: Create Main Entry Point

**File:** `main.py` (add new command)

```python
@app.command()
def run_multi_isolated(
    duration: float = typer.Option(30.0, help="Simulation duration"),
    scenario: str = typer.Option("moderate_congestion", help="Network scenario"),
    output_dir: str = typer.Option("output/multi_isolated", help="Output directory"),
    with_ml: bool = typer.Option(False, help="Enable ML controller"),
):
    """
    Run 3 QUIC connections in separate processes with isolated parameters.

    Each connection has its own CC parameters (LRF, Cubic C, etc.)
    while all share the same network conditions.
    """
    from wireless_bottleneck import WirelessBottleneck, get_scenario
    from simulation.process_orchestrator import ProcessOrchestrator

    config = MultiConnectionConfig.create_default()
    config.simulation_duration = duration

    # Set different parameters for each connection
    config.video_config.loss_reduction_factor = 0.5
    config.video_config.cubic_c = 0.4

    config.file_config.loss_reduction_factor = 0.7
    config.file_config.cubic_c = 0.5

    config.conference_config.loss_reduction_factor = 0.3
    config.conference_config.cubic_c = 0.3

    # ML callback if enabled
    ml_callback = my_ml_model if with_ml else None

    # Create orchestrator
    orchestrator = ProcessOrchestrator(
        config=config,
        ml_callback=ml_callback,
    )

    # Run with network simulation
    network_scenario = get_scenario(scenario)

    with WirelessBottleneck(network_scenario.config, interface="lo"):
        result = asyncio.run(orchestrator.run(duration))

    # Export results
    result.export_csv(f"{output_dir}/results.csv")
    result.export_metrics_history(f"{output_dir}/metrics_history.json")

    # Print summary
    print_multi_connection_summary(result)
```

---

## File Structure

```
code/
├── config/
│   ├── __init__.py
│   ├── settings.py
│   ├── parameters.py
│   ├── connection_config.py          # Per-connection config
│   └── multi_connection_config.py    # Multi-connection config
│
├── simulation/
│   ├── __init__.py
│   ├── runner.py                     # Single-process runner (existing)
│   ├── server.py
│   ├── client.py
│   ├── connection_handler.py         # Single-process handler (existing)
│   ├── multi_connection_runner.py    # Single-process multi-conn (existing)
│   │
│   │   # NEW: Multi-process implementation
│   ├── worker_process.py             # Worker process for isolated connection
│   ├── process_orchestrator.py       # Manages worker processes
│   ├── ipc_messages.py               # IPC message definitions
│   └── ml_controller.py              # ML controller for main process
│
├── metrics/
│   ├── __init__.py
│   ├── collector.py
│   ├── calculator.py
│   ├── exporter.py
│   └── aggregated_metrics.py
│
├── synthesizers/
│   └── ...
│
├── wireless_bottleneck/
│   └── ...
│
└── main.py                           # Add run_multi_isolated command
```

---

## Code Examples

### Running the Multi-Process Implementation

```bash
# Run with default parameters
uv run main.py run-multi-isolated --duration 30

# Run with specific network scenario
uv run main.py run-multi-isolated --scenario high_congestion --duration 60

# Run with ML controller enabled
uv run main.py run-multi-isolated --with-ml --duration 30
```

### Custom ML Callback Example

```python
def bandwidth_fairness_ml(metrics: Dict[int, dict]) -> Dict[int, dict]:
    """
    ML model that tries to achieve fair bandwidth allocation.

    Uses Jain's fairness index as optimization target.
    """
    decisions = {}

    if len(metrics) < 3:
        return decisions

    # Calculate current throughputs
    throughputs = [m.get("throughput", 0) for m in metrics.values()]

    # Calculate Jain's fairness index
    n = len(throughputs)
    sum_x = sum(throughputs)
    sum_x_sq = sum(x**2 for x in throughputs)
    fairness = (sum_x ** 2) / (n * sum_x_sq) if sum_x_sq > 0 else 1.0

    # If fairness is low, adjust parameters
    if fairness < 0.9:
        # Find connection with highest throughput
        max_conn = max(metrics.items(), key=lambda x: x[1].get("throughput", 0))
        max_conn_id = max_conn[0]

        # Make it less aggressive
        current_lrf = max_conn[1]["current_params"]["loss_reduction_factor"]
        decisions[max_conn_id] = {
            "loss_reduction_factor": min(0.9, current_lrf + 0.1)
        }

        # Find connection with lowest throughput
        min_conn = min(metrics.items(), key=lambda x: x[1].get("throughput", 0))
        min_conn_id = min_conn[0]

        # Make it more aggressive
        current_lrf = min_conn[1]["current_params"]["loss_reduction_factor"]
        decisions[min_conn_id] = {
            "loss_reduction_factor": max(0.3, current_lrf - 0.1)
        }

    return decisions
```

### Accessing Results

```python
# After running
result = asyncio.run(orchestrator.run(30))

# Per-connection final metrics
for conn_id, metrics in result.connection_results.items():
    print(f"Connection {conn_id}:")
    print(f"  Throughput: {metrics['throughput'] / 1_000_000:.2f} Mbps")
    print(f"  RTT: {metrics['rtt'] * 1000:.1f} ms")
    print(f"  Jitter: {metrics['jitter'] * 1000:.1f} ms")
    print(f"  Loss Rate: {metrics['packet_loss_rate'] * 100:.2f}%")

# Metrics history (for plotting)
import pandas as pd
import matplotlib.pyplot as plt

# Convert to DataFrame
df_list = []
for i, snapshot in enumerate(result.metrics_history):
    for conn_id, m in snapshot.items():
        df_list.append({
            "time_index": i,
            "connection_id": conn_id,
            "throughput": m["throughput"],
            "rtt": m["rtt"],
        })
df = pd.DataFrame(df_list)

# Plot throughput over time
for conn_id in [1, 2, 3]:
    conn_df = df[df["connection_id"] == conn_id]
    plt.plot(conn_df["time_index"], conn_df["throughput"], label=f"Conn {conn_id}")
plt.legend()
plt.xlabel("Time (100ms intervals)")
plt.ylabel("Throughput (bytes/s)")
plt.title("Per-Connection Throughput Over Time")
plt.show()
```

---

## Synchronization and Timing

### Synchronized Start

All workers start sending data at the same time using a `Barrier`:

```python
from multiprocessing import Barrier

# Main process
start_barrier = Barrier(4)  # 3 workers + 1 main

# In each worker
start_barrier.wait()  # All workers block here
# ... then all proceed simultaneously

# In main process
start_barrier.wait()  # Main also waits
# All 4 processes now proceed
```

### Timing Diagram

```
Time    Main Process           Worker 1            Worker 2            Worker 3
─────┬─────────────────────┬──────────────────┬──────────────────┬──────────────────
  0  │ Setup server        │                  │                  │
     │ Spawn workers       │ Start            │ Start            │ Start
     │                     │ Apply params     │ Apply params     │ Apply params
     │                     │ Wait at barrier  │ Wait at barrier  │ Wait at barrier
     │ Wait at barrier     │         ▼        │         ▼        │         ▼
─────┤ ═══════════════════════ BARRIER RELEASE ══════════════════════════════════
  T  │ Start ML loop       │ Connect          │ Connect          │ Connect
     │                     │ Send data        │ Send data        │ Send data
     │ Collect metrics     │ Report metrics   │ Report metrics   │ Report metrics
     │ ML decision         │ Check commands   │ Check commands   │ Check commands
     │ Send params         │ Apply params     │                  │ Apply params
     │ ...                 │ ...              │ ...              │ ...
─────┤
 T+D │ Stop loop           │ Finish           │ Finish           │ Finish
     │ Join workers        │ Send final       │ Send final       │ Send final
     │ Collect results     │ Exit             │ Exit             │ Exit
─────┴─────────────────────┴──────────────────┴──────────────────┴──────────────────
```

---

## Error Handling

### Worker Process Errors

```python
class ConnectionWorker:
    def _send_error(self, error_msg: str):
        """Report error to main process."""
        msg = IPCMessage(
            msg_type=MessageType.ERROR,
            connection_id=self.config.connection_id,
            timestamp=time.time(),
            payload={"error": error_msg},
        )
        self.metrics_queue.put(msg)

    async def run(self, duration: float):
        try:
            # ... run logic
        except ConnectionError as e:
            self._send_error(f"Connection failed: {e}")
        except Exception as e:
            self._send_error(f"Unexpected error: {e}")
            raise  # Re-raise to set non-zero exit code

class ProcessOrchestrator:
    def _check_worker_health(self):
        """Check for errors from workers."""
        while not self.metrics_queue.empty():
            msg = self.metrics_queue.get_nowait()
            if msg.msg_type == MessageType.ERROR:
                print(f"Worker {msg.connection_id} error: {msg.payload['error']}")
                # Optionally terminate all workers
```

### Timeout Handling

```python
class ProcessOrchestrator:
    async def run(self, duration: float, timeout_margin: float = 5.0):
        # ... spawn workers and run

        # Wait for workers with timeout
        total_timeout = duration + timeout_margin
        for conn_id, process in self.workers.items():
            process.join(timeout=total_timeout)
            if process.is_alive():
                print(f"Worker {conn_id} timed out, terminating")
                process.terminate()
                process.join(timeout=2)
```

---

## Testing Strategy

### Unit Tests

```python
# test_worker_process.py

def test_parameter_isolation():
    """Verify parameters are isolated between processes."""
    from multiprocessing import Process, Queue

    results = Queue()

    def worker(lrf_value, results_queue):
        from aioquic.quic.congestion import cubic
        cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = lrf_value
        time.sleep(0.1)
        results_queue.put(cubic.K_CUBIC_LOSS_REDUCTION_FACTOR)

    # Start two workers with different values
    p1 = Process(target=worker, args=(0.5, results))
    p2 = Process(target=worker, args=(0.8, results))

    p1.start()
    p2.start()
    p1.join()
    p2.join()

    # Both should have their own values
    values = [results.get(), results.get()]
    assert 0.5 in values
    assert 0.8 in values

def test_ipc_communication():
    """Test IPC message passing."""
    from multiprocessing import Pipe

    main_pipe, worker_pipe = Pipe()

    # Send command
    msg = IPCMessage(
        msg_type=MessageType.UPDATE_PARAM,
        connection_id=1,
        timestamp=time.time(),
        payload={"param_name": "loss_reduction_factor", "value": 0.6},
    )
    main_pipe.send(msg.to_dict())

    # Receive in worker
    received = IPCMessage.from_dict(worker_pipe.recv())
    assert received.msg_type == MessageType.UPDATE_PARAM
    assert received.payload["value"] == 0.6
```

### Integration Tests

```python
# test_multi_process_integration.py

@pytest.mark.asyncio
async def test_three_connections_different_params():
    """Test 3 connections with different parameters."""
    config = MultiConnectionConfig.create_default()
    config.video_config.loss_reduction_factor = 0.4
    config.file_config.loss_reduction_factor = 0.7
    config.conference_config.loss_reduction_factor = 0.5

    orchestrator = ProcessOrchestrator(config)
    result = await orchestrator.run(duration=10)

    assert result.success
    assert len(result.connection_results) == 3

    # Verify each connection ran with its own parameters
    # (Check metrics history for parameter values)

@pytest.mark.asyncio
async def test_ml_parameter_updates():
    """Test ML controller can update parameters mid-connection."""
    updates_made = []

    def test_ml_callback(metrics):
        if len(metrics) == 3:
            # Make an update at 5 seconds
            updates_made.append(time.time())
            return {1: {"loss_reduction_factor": 0.6}}
        return {}

    orchestrator = ProcessOrchestrator(
        config=MultiConnectionConfig.create_default(),
        ml_callback=test_ml_callback,
    )
    result = await orchestrator.run(duration=10)

    assert len(updates_made) > 0
    # Verify parameter was actually updated (check metrics history)
```

---

## Performance Considerations

### Memory Overhead

Each worker process creates a new Python interpreter:
- Base Python: ~30 MB
- aioquic + dependencies: ~20 MB
- Metrics/data: ~10 MB
- **Total per worker: ~60 MB**
- **3 workers + main: ~240 MB**

### IPC Latency

| Operation | Typical Latency |
|-----------|-----------------|
| Pipe send/recv | < 1 ms |
| Queue put/get | < 1 ms |
| Barrier wait | < 1 ms |

For 100ms decision intervals, IPC latency is negligible.

### CPU Usage

- Each worker: ~5-10% during active sending
- Main process: ~5% for ML + coordination
- Total: ~25-40% on a 4-core system

---

## Migration from Single-Process

### Compatibility

The multi-process implementation can coexist with the single-process version:

| Mode | Use Case |
|------|----------|
| Single-process (`run_multi`) | Quick tests, debugging, shared parameter research |
| Multi-process (`run_multi_isolated`) | Per-connection parameter research, ML optimization |

### Code Reuse

The following components are reused:
- `ConnectionConfig` - Per-connection configuration
- `MultiConnectionConfig` - Multi-connection setup
- `MetricsCollector` - Metrics collection (instantiated per worker)
- `SynthesizerFactory` - Data generation
- `WirelessBottleneck` - Network simulation

### New Components

| Component | Purpose |
|-----------|---------|
| `worker_process.py` | Runs single connection in isolated process |
| `process_orchestrator.py` | Manages worker processes |
| `ipc_messages.py` | Message definitions for IPC |
| `ml_controller.py` | ML integration in main process |

---

## Summary

This multi-process implementation provides:

1. **True parameter isolation** - Each connection has its own aioquic globals
2. **Same network conditions** - All processes share tc/netem configuration
3. **ML integration** - Central controller with IPC for real-time optimization
4. **Synchronized execution** - Barrier-based start for fair competition
5. **Comprehensive metrics** - Per-connection and aggregated metrics with history

The approach trades some complexity for the ability to truly test per-connection parameter optimization, which is essential for meaningful ML research on QUIC congestion control.
