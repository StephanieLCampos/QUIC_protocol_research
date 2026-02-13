# Main.py Report

This document explains what `main.py` does and how it interacts with the metrics module and worker processes.

---

## What main.py Does

`main.py` is the **entry point** - it:

1. Parses command-line arguments
2. Creates configuration
3. Creates the orchestrator
4. Runs the simulation
5. Exports results

It does NOT directly measure metrics or run QUIC connections - it delegates to other modules.

---

## main.py Structure

```python
main.py
│
├── cmd_run(args)           # Main command handler
├── run_headless()          # Run without UI
├── run_with_ui()           # Run with browser dashboard
├── export_results()        # Save JSON files
└── main()                  # CLI argument parser
```

---

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              main.py                                         │
│                                                                              │
│  STEP 1: PARSE ARGUMENTS                                                    │
│  ────────────────────────                                                   │
│  $ uv run python -m main run --ui --duration 30                            │
│                                                                              │
│  args.duration = 30                                                         │
│  args.ui = True                                                             │
│  args.scenario = "congested_low"                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 2: CREATE CONFIGURATION                                               │
│  ────────────────────────────                                               │
│                                                                              │
│  config = MultiConnectionConfig()                                           │
│      │                                                                       │
│      ├── video_config (ConnectionConfig for connection 1)                   │
│      ├── file_config (ConnectionConfig for connection 2)                    │
│      └── conference_config (ConnectionConfig for connection 3)              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 3: CREATE ORCHESTRATOR                                                │
│  ───────────────────────────                                                │
│                                                                              │
│  orchestrator = ProcessOrchestrator(                                        │
│      config=config,                                                         │
│      ml_callback=None,                                                      │
│      metrics_interval=0.1,                                                  │
│      network_scenario="congested_low",                                      │
│  )                                                                          │
│                                                                              │
│  At this point: Nothing is running yet, just configured                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 4: RUN SIMULATION                                                     │
│  ──────────────────────                                                     │
│                                                                              │
│  if args.ui:                                                                │
│      asyncio.run(run_with_ui(orchestrator, args))                          │
│  else:                                                                      │
│      asyncio.run(run_headless(orchestrator, args))                         │
│                                                                              │
│  Inside run_with_ui():                                                      │
│      server_task = run_server(orchestrator)  ──► Web UI on port 8000       │
│      sim_task = orchestrator.run()           ──► Actual simulation         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ orchestrator.run() triggers everything
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  WHAT HAPPENS INSIDE orchestrator.run()                                     │
│  ──────────────────────────────────────                                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  1. setup()                                                          │   │
│  │     └─► Start QuicServer on port 4433                               │   │
│  │     └─► Create Barrier(4)                                           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                          │                                                  │
│                          ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  2. _spawn_workers()                                                 │   │
│  │     └─► Create 3 worker processes                                   │   │
│  │     └─► Each gets: config, pipe, queue                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                          │                                                  │
│                          ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  3. process.start() for each worker                                  │   │
│  │     └─► Workers begin running in parallel                           │   │
│  │     └─► Each worker: connects to server, sends data, records metrics│   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                          │                                                  │
│                          ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  4. _collect_metrics_loop(duration)                                  │   │
│  │     └─► Main process reads from metrics_queue                       │   │
│  │     └─► Stores metrics for UI and history                           │   │
│  │     └─► Runs for 'duration' seconds                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                          │                                                  │
│                          ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  5. _build_results()                                                 │   │
│  │     └─► Creates MultiConnectionResult from collected data           │   │
│  │     └─► Computes fairness_index                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                          │                                                  │
│                          ▼                                                  │
│  Returns: MultiConnectionResult                                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 5: EXPORT RESULTS                                                     │
│  ──────────────────────                                                     │
│                                                                              │
│  export_results(result, args)                                               │
│      │                                                                       │
│      ├─► result.export_json()           → output/results_*.json            │
│      ├─► result.export_metrics_history() → output/metrics_*.json           │
│      └─► result.export_epoch_histories() → output/epochs_*.json            │
│                                                                              │
│  Print summary to console                                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## How main.py Interacts with Metrics Module

**main.py does NOT directly use the metrics module.**

The interaction is indirect through the orchestrator:

```
main.py
    │
    │ creates
    ▼
ProcessOrchestrator
    │
    │ spawns
    ▼
ConnectionWorker (in separate process)
    │
    │ creates and uses
    ▼
┌────────────────────────────────────────┐
│           METRICS MODULE               │
│                                        │
│  MetricsCollector                      │
│      └─► records raw data              │
│                                        │
│  MetricsCalculator                     │
│      └─► computes 6 metrics            │
│                                        │
│  EpochManager                          │
│      └─► groups metrics by params      │
│                                        │
└────────────────────────────────────────┘
    │
    │ sends via Queue
    ▼
ProcessOrchestrator
    │
    │ builds results
    ▼
MultiConnectionResult
    │
    │ returned to
    ▼
main.py
    │
    │ calls export methods
    ▼
JSON files
```

---

## How main.py Interacts with Worker Processes

```
┌────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  main.py                           WORKER PROCESSES                         │
│  ────────                          ─────────────────                        │
│                                                                             │
│  Creates orchestrator               (not running yet)                       │
│         │                                                                   │
│         ▼                                                                   │
│  orchestrator.run()                                                         │
│         │                                                                   │
│         ├─► _spawn_workers() ────────────────────────► Worker 1 created    │
│         │                    ────────────────────────► Worker 2 created    │
│         │                    ────────────────────────► Worker 3 created    │
│         │                                                                   │
│         ├─► process.start() ─────────────────────────► Workers START       │
│         │                                                    │              │
│         │                                                    │              │
│         │   ┌────────────────────────────────────────────────┘              │
│         │   │                                                               │
│         │   ▼                                                               │
│         │   Workers run independently:                                      │
│         │   - Connect to QUIC server                                        │
│         │   - Generate and send data                                        │
│         │   - Record metrics                                                │
│         │   - Send metrics via Queue ──────────────────┐                   │
│         │                                              │                   │
│         ├─► _collect_metrics_loop() ◄──────────────────┘                   │
│         │       │                                                           │
│         │       └─► Reads from Queue                                       │
│         │       └─► Stores in metrics_history                              │
│         │                                                                   │
│         │   Workers finish, send FINISHED ─────────────┐                   │
│         │                                              │                   │
│         ├─► _collect_final_results() ◄─────────────────┘                   │
│         │                                                                   │
│         ├─► _build_results()                                               │
│         │       └─► Returns MultiConnectionResult                          │
│         │                                                                   │
│  result = orchestrator.run() ◄─────────────────────────                    │
│         │                                                                   │
│         ▼                                                                   │
│  export_results(result)                                                     │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## What main.py Knows vs What Workers Know

| | main.py | Worker Process |
|--|---------|----------------|
| Configuration | ✓ Creates it | ✓ Receives copy |
| QUIC connection | ✗ Never touches | ✓ Runs it |
| Metrics collection | ✗ Never touches | ✓ Does it |
| Metrics calculation | ✗ Never touches | ✓ Does it |
| Epoch management | ✗ Never touches | ✓ Does it |
| Parameter updates | ✓ Sends via pipe | ✓ Applies them |
| Final results | ✓ Receives them | ✓ Sends them |
| JSON export | ✓ Does it | ✗ Never touches |

---

## Code Walkthrough

### 1. Entry Point (lines 195-229)

```python
def main():
    parser = argparse.ArgumentParser(description="QUIC 3-Connection Simulation")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run simulation")
    run_parser.add_argument("--duration", type=float, default=30.0)
    run_parser.add_argument("--ui", action="store_true")
    run_parser.add_argument("--port", type=int, default=8000)
    # ... more arguments

    args = parser.parse_args()
    if hasattr(args, "func"):
        return args.func(args)  # Calls cmd_run(args)
```

### 2. Command Handler (lines 33-97)

```python
def cmd_run(args):
    # Load or create config
    if args.config:
        config = MultiConnectionConfig.from_json(args.config)
    else:
        config = MultiConnectionConfig()

    config.simulation_duration = args.duration

    # Create orchestrator (doesn't start yet)
    orchestrator = ProcessOrchestrator(
        config=config,
        ml_callback=ml_callback,
        metrics_interval=args.metrics_interval,
        network_scenario=scenario_name,
    )

    # Run with or without UI
    if args.ui:
        asyncio.run(run_with_ui(orchestrator, args))
    else:
        asyncio.run(run_headless(orchestrator, args, scenario))
```

### 3. Run with UI (lines 116-163)

```python
async def run_with_ui(orchestrator, args):
    # Start web server and simulation concurrently
    server_task = asyncio.create_task(run_server(orchestrator, port=port))
    sim_task = asyncio.create_task(orchestrator.run())  # ◄── This does everything

    # Wait for simulation to complete
    result = await sim_task
    export_results(result, args)

    # Cleanup
    server_task.cancel()
```

### 4. Export Results (lines 165-192)

```python
def export_results(result, args):
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # These methods are on MultiConnectionResult
    result_file = result.export_json(str(output_path))
    metrics_file = result.export_metrics_history(str(output_path))
    epoch_file = result.export_epoch_histories(str(output_path))

    # Print summary
    print(f"Fairness Index: {result.fairness_index:.3f}")
    print(f"Total Throughput: {result.total_throughput / 1e6:.2f} Mbps")
```

---

## Summary

| Role | Who Does It |
|------|-------------|
| Parse CLI arguments | main.py |
| Create configuration | main.py |
| Create orchestrator | main.py |
| Start simulation | main.py (calls `orchestrator.run()`) |
| Start QUIC server | ProcessOrchestrator |
| Spawn worker processes | ProcessOrchestrator |
| Run QUIC client | ConnectionWorker |
| Generate traffic | Synthesizer |
| Record raw metrics | MetricsCollector |
| Calculate metrics | MetricsCalculator |
| Manage epochs | EpochManager |
| Collect metrics from workers | ProcessOrchestrator |
| Build final results | ProcessOrchestrator |
| Export to JSON | main.py (calls result methods) |

**main.py is the coordinator** - it sets things up, triggers the simulation, and handles the output. The actual work happens in the orchestrator and worker processes.
