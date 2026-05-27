# QUIC Parameter Grid Search

Find optimal QUIC congestion control parameters for each application type.

## Overview

This tool searches through combinations of CUBIC congestion control parameters to find the best configuration for each application type:

| Application Type | Optimization Target |
|------------------|---------------------|
| **File Transfer** | Maximize throughput |
| **Video Streaming** | Minimize latency |
| **Conference Call** | Minimize jitter |

## Parameters Searched

The grid search tests 6 **dynamic parameters** (values based on RFC 9438, RFC 9002):

| Parameter | Values | Description |
|-----------|--------|-------------|
| `loss_reduction_factor` | [0.5, 0.7, 0.9] | cwnd multiplier on packet loss |
| `cubic_c` | [0.2, 0.4, 0.6] | CUBIC aggressiveness constant |
| `minimum_window` | [2, 4, 6] | Minimum cwnd floor (packets) |
| `packet_threshold` | [2, 3, 4] | Dup ACKs for fast retransmit |
| `time_threshold` | [1.0, 1.125, 1.25] | RTT multiplier for loss detection |
| `cubic_max_idle_time` | [1.0, 2.0, 3.0] | Idle timeout before cwnd reset |

**Fixed parameters** (not searched):
- `initial_cw` = 14720 bytes (RFC 9002 Section 7.2)
- `max_ack_delay` = 0.025 seconds

## Combinations

| Mode | Parameters | Combinations | Time (1 worker) | Time (4 workers) |
|------|------------|--------------|-----------------|------------------|
| Reduced | 4 params | 243 total (81 per app) | ~2 hours | ~30 min |
| Full | 6 params | 2,187 total (729 per app) | ~18 hours | ~4.5 hours |

---

## Commands

### 1. `run` - Execute the grid search

```bash
# Basic run (reduced search, 243 combinations, ~30 min with 4 workers)
uv run python main.py run

# Preview without running (dry run)
uv run python main.py run --dry-run

# Run only one app type (81 combinations, ~10 min with 4 workers)
uv run python main.py run --app-type file_transfer
uv run python main.py run --app-type video_streaming
uv run python main.py run --app-type conference_call

# Full search with all 6 parameters (2,187 combinations, ~4.5 hours with 4 workers)
uv run python main.py run --full

# Change simulation duration (default is 30 seconds per combo)
uv run python main.py run --duration 60

# Change number of parallel workers (default: 4)
uv run python main.py run --workers 8

# Run sequentially (no parallelism)
uv run python main.py run --no-parallel

# Combine options
uv run python main.py run --app-type file_transfer --duration 15 --workers 2
```

#### Options

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview what would run without executing |
| `--full` | Search all 6 parameters (slow!) |
| `--app-type TYPE` | Run only for file_transfer, video_streaming, or conference_call |
| `--duration SECS` | Simulation duration per combination (default: 30) |
| `--output-dir DIR` | Output directory for results (default: output/measurements) |
| `--workers N` | Number of parallel workers (default: 4) |
| `--no-parallel` | Run sequentially instead of in parallel |

---

### 2. `status` - Check progress

```bash
uv run python main.py status
```

Shows completed/pending counts for each app type. Example output:

```
Grid Search Status
==================================================

Reduced Search (4 parameters, 243 combinations):
  Completed: 50/243
  Pending:   193
  Progress:  20.6%

By Application Type:
  file_transfer: 50/81 (62%)
  video_streaming: 0/81 (0%)
  conference_call: 0/81 (0%)
```

---

### 3. `analyze` - Find optimal parameters

```bash
# Basic analysis
uv run python main.py analyze

# Include statistics (min/max/mean/stdev)
uv run python main.py analyze --stats

# Export all results to single CSV
uv run python main.py analyze --export-all
```

#### Options

| Option | Description |
|--------|-------------|
| `--stats` | Show detailed statistics for each app type |
| `--export-all` | Export all results to a single CSV |
| `--measurements-dir DIR` | Directory containing measurement CSVs |
| `--output FILE` | Output file for optimal configs |

#### Output Files

- `output/analysis/optimal_configs.csv` - Best parameters per app type
- `output/analysis/optimal_configs.json` - Same in JSON format
- `output/analysis/all_results.csv` - All measurements (with `--export-all`)

---

### 4. `clear` - Delete all results

```bash
# With confirmation prompt
uv run python main.py clear

# Skip confirmation
uv run python main.py clear -y
```

---

## Resumability

The grid search is **fully resumable**. If interrupted (Ctrl+C, crash, etc.), simply run again:

```bash
# Start the search
uv run python main.py run

# ... interrupted at 50/243 ...

# Resume from where you stopped
uv run python main.py run

# Output:
# Progress: 50/243 completed
# Pending: 193
# [51/243] Testing: ...  <-- Continues from #51
```

Each completed combination saves to a unique CSV file. On restart, existing files are skipped.

---

## Quick Start

```bash
cd grid_search_code

# 1. Preview what will run
uv run python main.py run --dry-run

# 2. Run for one app type first (fastest)
uv run python main.py run --app-type file_transfer

# 3. Check progress
uv run python main.py status

# 4. Run remaining app types
uv run python main.py run --app-type video_streaming
uv run python main.py run --app-type conference_call

# 5. Analyze results
uv run python main.py analyze --stats
```

---

## Output Example

After running `uv run python main.py analyze`:

```
======================================================================
OPTIMAL CONFIGURATIONS FOUND
======================================================================

FILE TRANSFER
--------------------------------------------------
  Optimization target: Throughput = 45670000 bytes/sec (365.36 Mbps)

  Dynamic parameters (searched):
    loss_reduction_factor: 0.7
    cubic_c:               0.6
    minimum_window:        2
    packet_threshold:      3
    time_threshold:        1.125
    cubic_max_idle_time:   2.0

  Start-only parameters (fixed, not searched):
    initial_cw:            14720
    max_ack_delay:         0.025

VIDEO STREAMING
--------------------------------------------------
  Optimization target: Latency = 6.78 ms
  ...

CONFERENCE CALL
--------------------------------------------------
  Optimization target: Jitter = 0.87 ms
  ...
```

---

## Architecture

```
grid_search_code/
├── main.py                 # CLI entry point
├── config/
│   └── parameter_space.py  # Parameter definitions and combinations
├── runner/
│   ├── single_connection_runner.py  # Runs one connection in isolated process
│   └── executor.py         # Orchestrates all combinations
├── scheduler/
│   └── resumable_scheduler.py  # Tracks progress, enables resume
├── analysis/
│   └── results_analyzer.py # Finds optimal configs per app type
└── output/
    ├── measurements/       # Raw CSV per combination
    └── analysis/           # Optimal configs, summaries
```

---

## Synthesizers

The grid search uses the synthesizers from `3_conn_code/synthesizers/`:

| Synthesizer | Traffic Pattern |
|-------------|-----------------|
| **FileTransferSynthesizer** | 64KB chunks, no delay, fills bandwidth |
| **VideoStreamingSynthesizer** | 30fps, I-frames (50KB) + P-frames (5KB) |
| **ConferenceCallSynthesizer** | 320 bytes every 20ms (128kbps audio) |

Any changes to `3_conn_code/synthesizers/` will automatically apply to the grid search.

---

## References

Parameter values are based on:

- **RFC 9438** - CUBIC for Fast and Long-Distance Networks
- **RFC 9002** - QUIC Loss Detection and Congestion Control
- **RFC 8312** - CUBIC for Fast Long-Distance Networks
- **RFC 5681** - TCP Congestion Control

See `3_conn_code/param_ranges_report.md` for detailed citations.
