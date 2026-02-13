# Component Relation Report

This document explains how all objects/classes in the codebase connect to each other and where in the pipeline each component operates.

---

## All Objects/Classes

### Configuration Objects

| Object | File | Purpose |
|--------|------|---------|
| `ConnectionConfig` | `config/connection_config.py` | Single connection's parameters |
| `MultiConnectionConfig` | `config/multi_connection_config.py` | All 3 connections + shared settings |

### Simulation Objects

| Object | File | Purpose |
|--------|------|---------|
| `ProcessOrchestrator` | `simulation/process_orchestrator.py` | Central coordinator |
| `ConnectionWorker` | `simulation/worker_process.py` | Runs QUIC client in isolated process |
| `QuicServer` | `simulation/server.py` | Receives data from clients |
| `ServerProtocol` | `simulation/server.py` | Handles QUIC events on server |
| `MLController` | `simulation/ml_controller.py` | Runs ML callback loop |
| `IPCMessage` | `simulation/ipc_messages.py` | Message format for IPC |
| `MessageType` | `simulation/ipc_messages.py` | Enum of message types |
| `ConnectionResult` | `simulation/result.py` | Single connection's results |
| `MultiConnectionResult` | `simulation/result.py` | All 3 connections' results |

### Synthesizer Objects

| Object | File | Purpose |
|--------|------|---------|
| `BaseSynthesizer` | `synthesizers/base.py` | Abstract base class |
| `DataPacket` | `synthesizers/base.py` | Single packet of data |
| `SynthesizerFactory` | `synthesizers/base.py` | Creates synthesizers by type |
| `VideoStreamingSynthesizer` | `synthesizers/video_streaming.py` | Generates video traffic |
| `FileTransferSynthesizer` | `synthesizers/file_transfer.py` | Generates file traffic |
| `ConferenceCallSynthesizer` | `synthesizers/conference_call.py` | Generates audio traffic |

### Metrics Objects

| Object | File | Purpose |
|--------|------|---------|
| `MetricsCollector` | `metrics/collector.py` | Records events during simulation |
| `MetricsCalculator` | `metrics/calculator.py` | Computes metrics from raw data |
| `MetricsResult` | `metrics/calculator.py` | Container for 6 metrics |
| `EpochManager` | `metrics/epoch.py` | Manages epoch-based collection |
| `Epoch` | `metrics/epoch.py` | Single stable parameter period |
| `EpochMetrics` | `metrics/epoch.py` | Aggregated metrics for epoch |
| `ParameterSnapshot` | `metrics/epoch.py` | Snapshot of all parameters |
| `ConnectionEpochHistory` | `metrics/epoch.py` | All epochs for one connection |
| `EpochConfig` | `metrics/epoch.py` | Epoch settings (settling time) |
| `MetricsExporter` | `metrics/exporter.py` | CSV export utilities |

### Web Objects

| Object | File | Purpose |
|--------|------|---------|
| `FastAPI app` | `web/server.py` | REST API + WebSocket server |
| `ConnectionManager` | `web/server.py` | Manages WebSocket connections |
| `ParameterUpdate` | `web/server.py` | Request model for param updates |

---

## Object Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CONFIGURATION                                   │
│                                                                              │
│  ┌─────────────────────────┐                                                │
│  │  MultiConnectionConfig  │                                                │
│  │  ─────────────────────  │                                                │
│  │  server_host            │                                                │
│  │  server_port            │                                                │
│  │  simulation_duration    │                                                │
│  │  shared_initial_cw      │                                                │
│  └───────────┬─────────────┘                                                │
│              │ contains 3x                                                  │
│              ▼                                                              │
│  ┌─────────────────────────┐                                                │
│  │    ConnectionConfig     │ ×3 (video, file, conference)                  │
│  │  ─────────────────────  │                                                │
│  │  connection_id          │                                                │
│  │  application_type       │                                                │
│  │  loss_reduction_factor  │                                                │
│  │  cubic_c                │                                                │
│  │  minimum_window         │                                                │
│  │  ...                    │                                                │
│  └─────────────────────────┘                                                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ passed to
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ORCHESTRATION                                   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      ProcessOrchestrator                             │   │
│  │  ───────────────────────────────────────────────────────────────    │   │
│  │                                                                      │   │
│  │  config: MultiConnectionConfig ◄────────────────────────────────────┼───┘
│  │  workers: Dict[int, Process]   ─────────────────────────────────────┼──┐
│  │  command_pipes: Dict[int, Pipe] ────────────────────────────────────┼──┤
│  │  metrics_queue: Queue ──────────────────────────────────────────────┼──┤
│  │  server: QuicServer ────────────────────────────────────────────────┼──┤
│  │  ml_controller: MLController ───────────────────────────────────────┼──┤
│  │                                                                      │  │
│  │  Methods:                                                            │  │
│  │  - setup()              → Creates server, barrier                   │  │
│  │  - _spawn_workers()     → Creates 3 worker processes                │  │
│  │  - run()                → Main simulation loop                      │  │
│  │  - update_parameter()   → Sends param update via pipe               │  │
│  │  - get_latest_metrics() → Returns metrics for UI                    │  │
│  │  - cleanup()            → Stops everything                          │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
         │              │                │              │              │
         │              │                │              │              │
         ▼              ▼                ▼              ▼              ▼
┌─────────────┐  ┌─────────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐
│ QuicServer  │  │ MLController│  │  Worker   │  │  Worker   │  │  Worker   │
│             │  │             │  │  Process  │  │  Process  │  │  Process  │
│ (port 4433) │  │ (optional)  │  │    #1     │  │    #2     │  │    #3     │
└─────────────┘  └─────────────┘  └───────────┘  └───────────┘  └───────────┘
```

---

## Inside Each Worker Process

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           WORKER PROCESS                                     │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                      ConnectionWorker                                 │  │
│  │  ────────────────────────────────────────────────────────────────    │  │
│  │                                                                       │  │
│  │  config: ConnectionConfig ◄─── Parameters for this connection        │  │
│  │  command_pipe: Connection ◄─── Receives commands from orchestrator   │  │
│  │  metrics_queue: Queue     ◄─── Sends metrics to orchestrator         │  │
│  │                                                                       │  │
│  │  _metrics_collector: MetricsCollector ◄─── Records raw data          │  │
│  │  _epoch_manager: EpochManager         ◄─── Manages epochs            │  │
│  │                                                                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│         │                    │                      │                       │
│         │ creates            │ uses                 │ uses                  │
│         ▼                    ▼                      ▼                       │
│  ┌─────────────┐     ┌─────────────────┐    ┌─────────────────┐            │
│  │ Synthesizer │     │ MetricsCollector│    │  EpochManager   │            │
│  │ (Video/     │     │                 │    │                 │            │
│  │  File/Conf) │     │ bytes_sent      │    │ current_epoch   │            │
│  │             │     │ rtt_samples[]   │    │ epochs[]        │            │
│  │ generate()  │     │ packets_sent    │    │ settling_time   │            │
│  └──────┬──────┘     └────────┬────────┘    └────────┬────────┘            │
│         │                     │                      │                      │
│         │ yields              │ provides             │ uses                 │
│         ▼                     ▼                      ▼                      │
│  ┌─────────────┐     ┌─────────────────┐    ┌─────────────────┐            │
│  │ DataPacket  │     │ MetricsResult   │    │     Epoch       │            │
│  │             │     │                 │    │                 │            │
│  │ data        │     │ throughput      │    │ parameters      │            │
│  │ size        │     │ rtt             │    │ metrics         │            │
│  │ timestamp   │     │ jitter          │    │ raw_samples[]   │            │
│  │ packet_type │     │ packet_loss     │    │ start/end_time  │            │
│  └─────────────┘     └─────────────────┘    └─────────────────┘            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Metrics Pipeline

This shows exactly **where and when** metrics are measured:

```
TIME ─────────────────────────────────────────────────────────────────────────►

STEP 1: PACKET GENERATION
┌─────────────────────────────────────────┐
│  Synthesizer.generate()                 │
│  └─► yields DataPacket                  │
│      - data: bytes                      │
│      - size: 64KB / 50KB / 320B         │
│      - timestamp: time.time()           │
└─────────────────────────────────────────┘
                    │
                    ▼
STEP 2: SEND OVER QUIC
┌─────────────────────────────────────────┐
│  protocol._quic.send_stream_data()      │
│  protocol.transmit()                    │
│                                         │
│  └─► Packet goes to server via QUIC     │
│      (congestion control applied here)  │
└─────────────────────────────────────────┘
                    │
                    ▼
STEP 3: RECORD RAW DATA ◄─────────────────── METRICS MEASUREMENT STARTS HERE
┌─────────────────────────────────────────┐
│  MetricsCollector.record_packet_sent()  │  ◄── worker_process.py:286
│  └─► bytes_sent += size                 │
│  └─► packets_sent += 1                  │
│  └─► send_timestamps.append(now)        │
│                                         │
│  MetricsCollector.record_rtt_sample()   │  ◄── worker_process.py:288-290
│  └─► rtt_samples.append(rtt)            │
│      (rtt from aioquic._rtt_smoothed)   │
└─────────────────────────────────────────┘
                    │
                    ▼
STEP 4: CALCULATE METRICS (every 100ms)
┌─────────────────────────────────────────┐
│  MetricsCollector.calculate_metrics()   │  ◄── worker_process.py:301
│  └─► calls MetricsCalculator            │
│                                         │
│  MetricsCalculator.calculate_all()      │  ◄── calculator.py:147-200
│  └─► throughput = bytes / duration      │
│  └─► rtt = mean(rtt_samples)            │
│  └─► latency = rtt / 2                  │
│  └─► jitter = stdev(delays)             │
│  └─► loss = (sent - received) / sent    │
│  └─► returns MetricsResult              │
└─────────────────────────────────────────┘
                    │
                    ▼
STEP 5: EPOCH SAMPLING (if not settling)
┌─────────────────────────────────────────┐
│  EpochManager.collect_sample()          │  ◄── worker_process.py:298
│  └─► if not settling:                   │
│      └─► current_epoch.raw_samples.     │
│          append(metrics)                │
└─────────────────────────────────────────┘
                    │
                    ▼
STEP 6: SEND TO MAIN PROCESS
┌─────────────────────────────────────────┐
│  ConnectionWorker._send_metrics()       │  ◄── worker_process.py:308
│  └─► IPCMessage(METRICS, payload)       │
│  └─► metrics_queue.put(msg)             │
└─────────────────────────────────────────┘
                    │
                    │ IPC Queue
                    ▼
STEP 7: ORCHESTRATOR RECEIVES
┌─────────────────────────────────────────┐
│  ProcessOrchestrator._collect_metrics() │  ◄── process_orchestrator.py:135-162
│  └─► msg = metrics_queue.get()          │
│  └─► _latest_metrics[conn_id] = msg     │
│  └─► metrics_history.append(msg)        │
└─────────────────────────────────────────┘
                    │
                    ▼
STEP 8: UI UPDATE (if --ui)
┌─────────────────────────────────────────┐
│  WebSocket broadcast                    │  ◄── web/server.py:104-110
│  └─► get_latest_metrics()               │
│  └─► send to browser                    │
└─────────────────────────────────────────┘
```

---

## Object Interactions by Phase

### Phase 1: Initialization

```
main.py
    │
    ├─► MultiConnectionConfig()
    │       └─► Creates 3× ConnectionConfig
    │
    └─► ProcessOrchestrator(config)
            └─► Stores config
            └─► Creates empty Queue, dicts
```

### Phase 2: Setup

```
ProcessOrchestrator.setup()
    │
    ├─► QuicServer(host, port)
    │       └─► QuicServer.start()
    │               └─► aioquic.serve()
    │
    ├─► Barrier(4)
    │
    └─► MLController(callback)  [if --with-ml]
```

### Phase 3: Worker Creation

```
ProcessOrchestrator._spawn_workers()
    │
    └─► For each ConnectionConfig:
            │
            ├─► Pipe()  → command_pipe
            │
            └─► Process(target=worker_process_entry)
                    │
                    └─► ConnectionWorker(config, pipe, queue)
                            │
                            ├─► MetricsCollector()
                            │
                            └─► EpochManager(initial_params)
                                    └─► Epoch(epoch_id=0)
```

### Phase 4: Simulation Loop

```
ConnectionWorker.run()
    │
    ├─► SynthesizerFactory.create(application_type)
    │       └─► VideoStreamingSynthesizer / FileTransfer / ConferenceCall
    │
    └─► async for packet in synthesizer.generate():
            │
            ├─► protocol.send_stream_data(packet.data)
            │
            ├─► MetricsCollector.record_packet_sent(size)
            │
            ├─► MetricsCollector.record_rtt_sample(rtt)
            │
            ├─► Every 100ms:
            │       ├─► MetricsCollector.calculate_metrics()
            │       │       └─► MetricsCalculator.calculate_all()
            │       │               └─► Returns MetricsResult
            │       │
            │       ├─► EpochManager.collect_sample()
            │       │       └─► Epoch.raw_samples.append()
            │       │
            │       └─► _send_metrics()
            │               └─► IPCMessage → Queue
            │
            └─► _check_commands()
                    └─► If UPDATE_PARAM:
                            ├─► _update_parameter()
                            │       └─► aioquic globals updated
                            │
                            └─► EpochManager.on_parameter_change()
                                    ├─► Finalize current Epoch
                                    └─► Start new Epoch (after settling)
```

### Phase 5: Results Collection

```
ConnectionWorker (at end)
    │
    ├─► MetricsCollector.calculate_metrics()
    │       └─► final MetricsResult
    │
    ├─► EpochManager.finalize()
    │       └─► Finalize last Epoch
    │       └─► Returns ConnectionEpochHistory
    │
    └─► _send_finished(final_metrics, epoch_history)
            └─► IPCMessage(FINISHED) → Queue

ProcessOrchestrator
    │
    ├─► _collect_final_results()
    │       └─► Receives FINISHED messages
    │
    └─► _build_results()
            │
            ├─► ConnectionResult(final_metrics, epoch_history, ...)
            │
            └─► MultiConnectionResult(connection_results)
                    ├─► compute_fairness_index()
                    └─► compute_total_throughput()
```

### Phase 6: Export

```
main.py: export_results()
    │
    └─► MultiConnectionResult
            ├─► export_json()           → results_*.json
            ├─► export_metrics_history() → metrics_*.json
            └─► export_epoch_histories() → epochs_*.json
```

---

## Key Object Connections Summary

| Object A | Connects To | How |
|----------|-------------|-----|
| `MultiConnectionConfig` | `ConnectionConfig` | Contains 3 instances |
| `ProcessOrchestrator` | `MultiConnectionConfig` | Stores as `self.config` |
| `ProcessOrchestrator` | `QuicServer` | Creates and starts |
| `ProcessOrchestrator` | `ConnectionWorker` | Spawns via `multiprocessing.Process` |
| `ProcessOrchestrator` | `MLController` | Creates if `--with-ml` |
| `ConnectionWorker` | `ConnectionConfig` | Receives copy via IPC |
| `ConnectionWorker` | `MetricsCollector` | Creates and uses |
| `ConnectionWorker` | `EpochManager` | Creates and uses |
| `ConnectionWorker` | `Synthesizer` | Creates via factory |
| `MetricsCollector` | `MetricsCalculator` | Calls static methods |
| `MetricsCollector` | `MetricsResult` | Returns from `calculate_metrics()` |
| `EpochManager` | `Epoch` | Creates and manages multiple |
| `EpochManager` | `MetricsCollector` | Reads metrics via `get_current_metrics()` |
| `Epoch` | `EpochMetrics` | Contains aggregated metrics |
| `Epoch` | `ParameterSnapshot` | Contains parameter state |
| `Synthesizer` | `DataPacket` | Yields from `generate()` |
| `MultiConnectionResult` | `ConnectionResult` | Contains 3 instances |

---

## Where Each Metric Is Born

| Metric | Created In | Method | Line |
|--------|------------|--------|------|
| `bytes_sent` | `MetricsCollector` | `record_packet_sent()` | `collector.py:78` |
| `packets_sent` | `MetricsCollector` | `record_packet_sent()` | `collector.py:77` |
| `rtt_samples` | `MetricsCollector` | `record_rtt_sample()` | `collector.py:103` |
| `throughput` | `MetricsCalculator` | `calculate_throughput()` | `calculator.py:49-66` |
| `rtt` (avg) | `MetricsCalculator` | `calculate_all()` | `calculator.py:177-180` |
| `latency` | `MetricsCalculator` | `calculate_latency()` | `calculator.py:129-144` |
| `jitter` | `MetricsCalculator` | `calculate_jitter()` | `calculator.py:68-103` |
| `packet_loss_rate` | `MetricsCalculator` | `calculate_packet_loss_rate()` | `calculator.py:105-127` |
| `fairness_index` | `MultiConnectionResult` | `compute_fairness_index()` | `result.py:107-120` |
