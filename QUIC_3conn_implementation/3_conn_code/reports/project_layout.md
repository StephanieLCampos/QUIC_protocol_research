# Project Layout Documentation

This document explains the complete project structure, module responsibilities, and runtime execution flow.

---

## Directory Structure

```
3_conn_code/
│
├── main.py                          # CLI entry point
│
├── config/                          # Configuration management
│   ├── __init__.py
│   ├── connection_config.py         # Single connection config (6 dynamic params)
│   └── multi_connection_config.py   # All 3 connections + shared params
│
├── simulation/                      # Core simulation engine
│   ├── __init__.py
│   ├── process_orchestrator.py      # Main coordinator (spawns workers)
│   ├── worker_process.py            # Isolated QUIC client process
│   ├── server.py                    # QUIC server (receives data)
│   ├── client.py                    # QUIC client utilities
│   ├── ml_controller.py             # ML callback loop
│   ├── ipc_messages.py              # IPC message definitions
│   ├── buffer_manager.py            # Buffer state tracking
│   └── result.py                    # Result data structures & export
│
├── synthesizers/                    # Traffic pattern generators
│   ├── __init__.py
│   ├── base.py                      # Abstract base class + factory
│   ├── video_streaming.py           # 30fps I/P-frame pattern
│   ├── file_transfer.py             # Continuous 64KB chunks
│   └── conference_call.py           # 320B every 20ms
│
├── metrics/                         # Metrics collection & calculation
│   ├── __init__.py
│   ├── collector.py                 # Real-time data collection
│   ├── calculator.py                # Metric computation functions
│   ├── epoch.py                     # Epoch-based metrics + settling
│   └── exporter.py                  # CSV export utilities
│
├── ml_callbacks/                    # ML optimization algorithms
│   └── __init__.py                  # (fairness_optimizer.py removed)
│
├── web/                             # Browser dashboard
│   ├── __init__.py
│   ├── server.py                    # FastAPI + WebSocket server
│   └── static/
│       ├── index.html               # Dashboard UI
│       ├── dashboard.js             # WebSocket client + snapshots
│       └── styles.css               # Dark theme styling
│
├── reports/                         # Documentation
│   ├── metrics.md                   # Metrics system documentation
│   └── project_layout.md            # This file
│
├── certs/                           # TLS certificates for QUIC
│   ├── cert.pem
│   └── key.pem
│
└── output/                          # Simulation results (generated)
    ├── result_TIMESTAMP.json
    ├── metrics_TIMESTAMP.json
    └── epochs_TIMESTAMP.json
```

---

## Module Responsibilities

### Entry Point

| Module | File | Responsibility |
|--------|------|----------------|
| **CLI** | `main.py` | Parse arguments, create orchestrator, run simulation |

### Configuration

| Module | File | Responsibility |
|--------|------|----------------|
| **ConnectionConfig** | `config/connection_config.py` | Single connection parameters (6 dynamic + 4 start-only) |
| **MultiConnectionConfig** | `config/multi_connection_config.py` | All 3 configs with shared start-only params |

### Simulation Engine

| Module | File | Responsibility |
|--------|------|----------------|
| **ProcessOrchestrator** | `simulation/process_orchestrator.py` | Spawn workers, manage IPC, collect metrics, handle UI |
| **ConnectionWorker** | `simulation/worker_process.py` | Run QUIC client in isolated process, apply CC params |
| **QuicServer** | `simulation/server.py` | Accept connections, receive synthesized data |
| **MLController** | `simulation/ml_controller.py` | Run ML callback loop, apply parameter decisions |
| **IPCMessage** | `simulation/ipc_messages.py` | Message format for inter-process communication |
| **Result** | `simulation/result.py` | Store and export simulation results |

### Traffic Generators

| Module | File | Traffic Pattern |
|--------|------|-----------------|
| **VideoStreamingSynthesizer** | `synthesizers/video_streaming.py` | I-frames (50KB) + P-frames (5KB) at 30fps |
| **FileTransferSynthesizer** | `synthesizers/file_transfer.py` | Continuous 64KB chunks |
| **ConferenceCallSynthesizer** | `synthesizers/conference_call.py` | 320B packets every 20ms |

### Metrics

| Module | File | Responsibility |
|--------|------|----------------|
| **MetricsCollector** | `metrics/collector.py` | Record events during simulation |
| **MetricsCalculator** | `metrics/calculator.py` | Compute 6 metrics from raw data |
| **EpochManager** | `metrics/epoch.py` | Track epochs with settling time |
| **MetricsExporter** | `metrics/exporter.py` | Export to CSV format |

### Web Dashboard

| Module | File | Responsibility |
|--------|------|----------------|
| **FastAPI Server** | `web/server.py` | REST API + WebSocket for real-time updates |
| **Dashboard UI** | `web/static/` | Browser interface for monitoring |

---

## Runtime Execution Flow

### Phase 1: Initialization

```
User runs: uv run python -m main run --ui --duration 30

┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                  │
│                                                                  │
│  1. Parse CLI arguments (--ui, --duration, --scenario, etc.)    │
│  2. Create MultiConnectionConfig (3 connection configs)         │
│  3. Create ProcessOrchestrator                                  │
│  4. Call asyncio.run(run_with_ui()) or run_headless()          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Phase 2: Setup

```
┌─────────────────────────────────────────────────────────────────┐
│                   ProcessOrchestrator.setup()                    │
│                                                                  │
│  1. Create QuicServer (binds to localhost:4433)                 │
│  2. Start server (await server.start())                         │
│  3. Create Barrier(4) for synchronized start                    │
│  4. If --with-ml: Create MLController                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   ProcessOrchestrator._spawn_workers()           │
│                                                                  │
│  For each connection (1, 2, 3):                                 │
│    1. Create Pipe() for commands (main ↔ worker)                │
│    2. Create Process(target=worker_process_entry)               │
│    3. Store in self.workers dict                                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Start Worker Processes                         │
│                                                                  │
│  for process in self.workers.values():                          │
│      process.start()  # Each runs in isolated memory space      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Phase 3: Barrier Synchronization

```
┌────────────────┐  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│  Main Process  │  │   Worker 1     │  │   Worker 2     │  │   Worker 3     │
│                │  │ (Video)        │  │ (File)         │  │ (Conference)   │
└───────┬────────┘  └───────┬────────┘  └───────┬────────┘  └───────┬────────┘
        │                   │                   │                   │
        │  ┌────────────────┴───────────────────┴───────────────────┤
        │  │         Each Worker Process Initializes:               │
        │  │                                                        │
        │  │  1. Apply CC params to aioquic globals                │
        │  │  2. Create EpochManager                                │
        │  │  3. Wait at barrier.wait()  ◄──────────────────────────┤
        │  └────────────────────────────────────────────────────────┘
        │
        ▼
   barrier.wait()  ◄─── Main process waits here too
        │
        │  ═══════════════════════════════════════════════════════
        │         ALL 4 PROCESSES RELEASE SIMULTANEOUSLY
        │  ═══════════════════════════════════════════════════════
        ▼
```

### Phase 4: Active Simulation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MAIN PROCESS                                    │
│                                                                              │
│  ┌─────────────────────┐      ┌─────────────────────┐                       │
│  │ _collect_metrics_loop│      │   Web Server        │                       │
│  │                     │      │   (if --ui)         │                       │
│  │  while running:     │      │                     │                       │
│  │    read Queue ──────┼──────┼─► store metrics     │                       │
│  │    store metrics    │      │    broadcast WS     │                       │
│  │    sleep 100ms      │      │                     │                       │
│  └─────────────────────┘      └─────────────────────┘                       │
│           ▲                                                                  │
│           │ Metrics Queue (multiprocessing.Queue)                           │
│           │                                                                  │
└───────────┼──────────────────────────────────────────────────────────────────┘
            │
            │  ┌──────────────────────────────────────────────────────────────┐
            │  │                                                              │
            │  │                   WORKER PROCESSES                           │
            │  │                                                              │
            │  │  ┌──────────────────────────────────────────────────────┐   │
            │  │  │                   Worker Loop                         │   │
            │  │  │                                                       │   │
            │  │  │  async for packet in synthesizer.generate():         │   │
            │  │  │      │                                                │   │
            │  │  │      ├─► Send data over QUIC stream                  │   │
            │  │  │      │   protocol._quic.send_stream_data()           │   │
            │  │  │      │   protocol.transmit()                         │   │
            │  │  │      │                                                │   │
            │  │  │      ├─► Record metrics                              │   │
            │  │  │      │   collector.record_packet_sent(size)          │   │
            │  │  │      │   collector.record_rtt_sample(rtt)            │   │
            │  │  │      │                                                │   │
            │  │  │      ├─► Check command pipe (non-blocking)           │   │
            │  │  │      │   if UPDATE_PARAM: update aioquic globals     │   │
            │  │  │      │                                                │   │
            │  │  │      ├─► Every 100ms: send metrics to Queue ─────────┼───┘
            │  │  │      │   epoch_manager.collect_sample()              │
            │  │  │      │                                                │
            │  │  │      └─► await asyncio.sleep(0.001)                  │
            │  │  │                                                       │
            │  │  └──────────────────────────────────────────────────────┘   │
            │  │                                                              │
            │  └──────────────────────────────────────────────────────────────┘
            │
```

### Phase 5: Parameter Updates (Optional)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PARAMETER UPDATE FLOW                                 │
│                                                                              │
│   Browser UI                Main Process              Worker Process         │
│       │                         │                          │                 │
│       │  POST /api/params       │                          │                 │
│       │  {conn: 1,              │                          │                 │
│       │   param: "cubic_c",     │                          │                 │
│       │   value: 0.6}           │                          │                 │
│       ├────────────────────────►│                          │                 │
│       │                         │                          │                 │
│       │                         │  IPCMessage              │                 │
│       │                         │  (UPDATE_PARAM)          │                 │
│       │                         │  via command_pipe        │                 │
│       │                         ├─────────────────────────►│                 │
│       │                         │                          │                 │
│       │                         │                          │  1. Update config│
│       │                         │                          │  2. Update aioquic│
│       │                         │                          │     globals      │
│       │                         │                          │  3. Notify epoch │
│       │                         │                          │     manager      │
│       │                         │                          │  4. Start settling│
│       │                         │                          │     period       │
│       │                         │                          │                 │
│       │                         │◄─────────────────────────┤  ACK            │
│       │◄────────────────────────┤  {success: true}         │                 │
│       │                         │                          │                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Phase 6: Shutdown & Results

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SHUTDOWN SEQUENCE                                  │
│                                                                              │
│  1. Duration expires (time.time() - start_time >= duration)                 │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      Each Worker Process:                              │  │
│  │                                                                        │  │
│  │  a. Exit synthesizer loop                                             │  │
│  │  b. collector.stop()                                                  │  │
│  │  c. epoch_manager.finalize()                                          │  │
│  │  d. Send FINISHED message with:                                       │  │
│  │     - final_metrics                                                   │  │
│  │     - param_history                                                   │  │
│  │     - epoch_history                                                   │  │
│  │  e. Process exits                                                     │  │
│  │                                                                        │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  2. Main process collects FINISHED messages                                 │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                   ProcessOrchestrator:                                 │  │
│  │                                                                        │  │
│  │  a. process.join(timeout) for each worker                            │  │
│  │  b. _collect_final_results() - drain queue                           │  │
│  │  c. _build_results() - create MultiConnectionResult                  │  │
│  │  d. cleanup() - terminate workers, stop server, close pipes          │  │
│  │                                                                        │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  3. Export results                                                          │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      export_results():                                 │  │
│  │                                                                        │  │
│  │  a. result.export_json() → output/result_TIMESTAMP.json              │  │
│  │  b. result.export_metrics_history() → output/metrics_TIMESTAMP.json  │  │
│  │  c. result.export_epoch_histories() → output/epochs_TIMESTAMP.json   │  │
│  │                                                                        │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  4. Print summary to console                                                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Complete Sequence Diagram

```
     Time
       │
       │  ┌─────────┐
       │  │ main.py │
       │  └────┬────┘
       │       │
       │       │ parse args, create config
       │       │
       │       ▼
       │  ┌─────────────────────┐
       │  │ ProcessOrchestrator │
       │  └──────────┬──────────┘
       │             │
       │             │ setup()
       │             │
       │             ▼
       │  ┌─────────────────────┐
       │  │    QuicServer       │ ◄─── Listening on :4433
       │  └─────────────────────┘
       │             │
       │             │ _spawn_workers()
       │             │
       │  ┌──────────┼──────────┬──────────────────┐
       │  │          │          │                  │
       │  ▼          ▼          ▼                  ▼
       │  ┌────┐   ┌────┐    ┌────┐          ┌──────────┐
       │  │ W1 │   │ W2 │    │ W3 │          │ WebServer│ (if --ui)
       │  └──┬─┘   └──┬─┘    └──┬─┘          └────┬─────┘
       │     │        │         │                 │
       │     │ apply CC params to aioquic         │
       │     │        │         │                 │
       │  ═══╪════════╪═════════╪═════════════════╪═══ BARRIER
       │     │        │         │                 │
       │     │ connect to QuicServer              │
       │     │        │         │                 │
       │     ▼        ▼         ▼                 │
       │  ┌──────────────────────────┐            │
       │  │   Synthesizer.generate() │            │
       │  │   (Video/File/Conf)      │            │
       │  └────────────┬─────────────┘            │
       │               │                          │
       │     ┌─────────┴─────────┐                │
       │     │                   │                │
       │     ▼                   ▼                │
       │  send data         record metrics        │
       │  over QUIC         to collector          │
       │     │                   │                │
       │     │                   │ every 100ms    │
       │     │                   ▼                │
       │     │            ┌──────────────┐        │
       │     │            │ Metrics Queue│────────┼──► WebSocket
       │     │            └──────────────┘        │    broadcast
       │     │                   │                │
       │     │    ◄──────────────┼────────────────┤
       │     │    param updates  │                │ POST /api/params
       │     │    via Pipe       │                │
       │     │                   │                │
       │  ═══╪═══════════════════╪════════════════╪═══ DURATION EXPIRES
       │     │                   │                │
       │     ▼                   │                │
       │  finalize epoch         │                │
       │  send FINISHED          │                │
       │     │                   │                │
       │     └───────────────────┼────────────────┘
       │                         │
       │                         ▼
       │                  ┌─────────────┐
       │                  │ Build Result│
       │                  └──────┬──────┘
       │                         │
       │                         ▼
       │                  ┌─────────────┐
       │                  │ Export JSON │
       │                  └──────┬──────┘
       │                         │
       │                         ▼
       │                  ┌─────────────┐
       │                  │ Print Stats │
       │                  └─────────────┘
       │
       ▼
```

---

## Inter-Process Communication

### Communication Channels

| Channel | Type | Direction | Purpose |
|---------|------|-----------|---------|
| **Command Pipe** | `multiprocessing.Pipe` | Main → Worker | Send parameter updates |
| **Metrics Queue** | `multiprocessing.Queue` | Worker → Main | Send metrics, status, results |
| **Barrier** | `multiprocessing.Barrier` | Bidirectional | Synchronized start |

### Message Types

```python
class MessageType(Enum):
    # Main → Worker
    START = "start"
    STOP = "stop"
    UPDATE_PARAM = "update_param"
    UPDATE_MULTIPLE_PARAMS = "update_multiple_params"

    # Worker → Main
    METRICS = "metrics"           # Periodic metrics update
    ACK = "ack"                   # Command acknowledgment
    ERROR = "error"               # Error report
    FINISHED = "finished"         # Final results
    BUFFER_STATE = "buffer_state" # Buffer status
```

---

## Process Memory Isolation

Each worker process has its own copy of Python's memory space:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MAIN PROCESS                                    │
│                                                                              │
│  aioquic globals: (not used directly)                                       │
│  ProcessOrchestrator, MultiConnectionConfig, WebServer                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────┐  ┌───────────────────────┐  ┌───────────────────────┐
│     WORKER 1          │  │     WORKER 2          │  │     WORKER 3          │
│                       │  │                       │  │                       │
│  aioquic globals:     │  │  aioquic globals:     │  │  aioquic globals:     │
│  K_CUBIC_C = 0.4      │  │  K_CUBIC_C = 0.5      │  │  K_CUBIC_C = 0.3      │
│  K_LOSS_FACTOR = 0.6  │  │  K_LOSS_FACTOR = 0.7  │  │  K_LOSS_FACTOR = 0.5  │
│  K_MIN_WINDOW = 4     │  │  K_MIN_WINDOW = 2     │  │  K_MIN_WINDOW = 6     │
│                       │  │                       │  │                       │
│  ConnectionConfig     │  │  ConnectionConfig     │  │  ConnectionConfig     │
│  MetricsCollector     │  │  MetricsCollector     │  │  MetricsCollector     │
│  EpochManager         │  │  EpochManager         │  │  EpochManager         │
│  VideoSynthesizer     │  │  FileSynthesizer      │  │  ConferenceSynthesizer│
│                       │  │                       │  │                       │
└───────────────────────┘  └───────────────────────┘  └───────────────────────┘

         │                          │                          │
         └──────────────────────────┴──────────────────────────┘
                                    │
                                    ▼
                          ┌─────────────────────┐
                          │     QuicServer      │
                          │  (shared endpoint)  │
                          │   localhost:4433    │
                          └─────────────────────┘
```

This isolation is why we use separate processes instead of threads - each process can have different values for aioquic's module-level congestion control constants.

---

## Key File References

| Component | File | Key Lines |
|-----------|------|-----------|
| CLI entry | `main.py` | `cmd_run()` at line 33 |
| Orchestrator setup | `simulation/process_orchestrator.py` | `setup()` at line 62 |
| Worker spawn | `simulation/process_orchestrator.py` | `_spawn_workers()` at line 74 |
| Worker main loop | `simulation/worker_process.py` | `run()` at line 195 |
| CC param application | `simulation/worker_process.py` | `_apply_initial_parameters()` at line 59 |
| Metrics collection | `simulation/worker_process.py` | lines 286-310 |
| Parameter update | `simulation/worker_process.py` | `_update_parameter()` at line 71 |
| WebSocket broadcast | `web/server.py` | `websocket_endpoint()` at line 96 |
| Result export | `simulation/result.py` | `export_json()` method |
