# QUIC 3-Connection Simulation

A multi-process QUIC simulation system that runs 3 concurrent connections with isolated congestion control parameters and mid-connection parameter modification.

## Features

- **3 Concurrent QUIC Connections** - Video streaming, file transfer, and conference call
- **Per-connection parameter isolation** - Each connection runs in a separate process with its own aioquic globals
- **Mid-connection parameter modification** - Dynamically tune 6 CC parameters while connections are active
- **Real-time browser dashboard** - Monitor metrics, buffer states, and manually adjust parameters
- **ML controller integration** - Optional callback interface for automated parameter optimization
- **Epoch-based metrics** - Collect stable metrics with settling time after parameter changes

## Installation

```bash
cd 3_conn_code

# Install dependencies with uv
uv sync

# Or with pip
pip install -e .
```

## Quick Start

```bash
# Run basic simulation (30 seconds)
uv run python -m main run

# Run with browser UI dashboard at http://localhost:8000
uv run python -m main run --ui

# Run with custom port
uv run python -m main run --ui --port 8080

# Run with ML-based fairness optimizer
uv run python -m main run --with-ml

# Run for 60 seconds with a specific network scenario
uv run python -m main run --duration 60 --scenario congested_low

# Run with longer settling time for network simulation
uv run python -m main run --ui --duration 120 --settling-time 5 --scenario congested_low
```

## Command Line Options

```
uv run python -m main run [OPTIONS]

Options:
  --duration FLOAT        Simulation duration in seconds (default: 30)
  --metrics-interval FLOAT  Metrics collection interval in seconds (default: 0.1)
  --output-dir PATH       Output directory for results (default: output)
  --config PATH           Path to JSON config file
  --scenario NAME         Network scenario: stable_high, congested_low, varying,
                          lossy, asymmetric (default: congested_low)
  --with-ml               Enable ML controller for automatic parameter tuning
  --ml-callback MODULE:FUNC  Custom ML callback (e.g., my_module:my_callback)
  --ui                    Enable browser UI dashboard
  --port INT              Port for browser UI (default: 8000)
  --settling-time FLOAT   Settling time in seconds after parameter changes (default: 2.0)
```

## Dynamic Parameters

These 6 parameters can be modified mid-connection:

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `loss_reduction_factor` | 0.7 | 0.1-0.9 | cwnd reduction on packet loss (beta) |
| `cubic_c` | 0.4 | 0.1-1.0 | CUBIC growth aggressiveness |
| `minimum_window` | 2 | 1-10 | Minimum cwnd floor (packets) |
| `packet_threshold` | 3 | 1-10 | Packets before declaring loss |
| `time_threshold` | 1.125 | 1.0-2.0 | RTT multiplier for loss timeout |
| `cubic_max_idle_time` | 2.0 | 0.5-5.0 | Idle timeout before cwnd reset |

## Application Types

| Connection | Type | Traffic Pattern |
|------------|------|-----------------|
| 1 | Video Streaming | 30 fps, I-frames (50KB) + P-frames (5KB) |
| 2 | File Transfer | Continuous 64KB chunks |
| 3 | Conference Call | 320 bytes every 20ms |

## Browser Dashboard

When running with `--ui`, open http://localhost:8000 to access:

- Real-time metrics for each connection: throughput (Mbps), RTT (ms), packet loss (%)
- Current parameter values display
- Manual parameter editor (click "Edit Parameters")
- **Parameter Snapshots**: Automatically captured baseline and post-change metrics

### Parameter Snapshots

The dashboard captures metrics snapshots at key moments:
- **Baseline**: Captured after initial settling time when simulation starts
- **Change #N**: Captured after settling time following each parameter modification

This allows you to compare metrics before and after parameter changes.

## Settling Time

After parameter changes, CUBIC congestion control needs time to adjust. The `--settling-time` option controls how long to wait before capturing metrics snapshots.

**Recommended settling times by scenario:**

| Scenario | RTT | `--settling-time` | Example |
|----------|-----|------------------|---------|
| Local loopback | 2-5ms | 2 (default) | `--settling-time 2` |
| Stable network | 20-50ms | 3-5 | `--settling-time 5` |
| Congested network | 50-100ms | 5-8 | `--settling-time 8` |
| Lossy/varying network | 50ms+ | 8-10 | `--settling-time 10` |

**Why settling time matters:**
- CUBIC needs multiple RTTs to adjust congestion window
- `loss_reduction_factor` only takes effect on next loss event
- Higher latency networks need more time for changes to propagate

**Example with network simulation:**
```bash
# For wireless_bottleneck with congested scenario
uv run python -m main run --ui --duration 120 --settling-time 8 --scenario congested_low
```

## Output Files

Results are saved to the output directory:

- `result_TIMESTAMP.json` - Final summary with fairness index and per-connection metrics
- `metrics_TIMESTAMP.json` - Time-series metrics history
- `epochs_TIMESTAMP.json` - Epoch-based metrics for ML analysis

## ML Callbacks

Create custom ML callbacks for automated parameter optimization:

```python
# my_callback.py
def my_optimizer(metrics: dict) -> dict:
    """
    Args:
        metrics: {conn_id: {"throughput": float, "rtt": float, "current_params": {...}}}

    Returns:
        {conn_id: {"param_name": new_value, ...}}
    """
    decisions = {}
    # Your optimization logic here
    return decisions
```

Run with: `uv run python -m main run --with-ml --ml-callback my_callback:my_optimizer`

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Main Process                              │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ ProcessOrchestrator│  │   MLController   │                │
│  └────────┬─────────┘  └────────┬─────────┘                 │
│           │                     │                            │
│     Barrier Sync          ML Callback                        │
│           │                     │                            │
├───────────┼─────────────────────┼────────────────────────────┤
│           ▼                     ▼                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │  Worker 1   │  │  Worker 2   │  │  Worker 3   │          │
│  │ (Video)     │  │ (File)      │  │ (Conference)│          │
│  │             │  │             │  │             │          │
│  │ aioquic     │  │ aioquic     │  │ aioquic     │          │
│  │ globals     │  │ globals     │  │ globals     │          │
│  │ (isolated)  │  │ (isolated)  │  │ (isolated)  │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
│     Process 1        Process 2        Process 3              │
└─────────────────────────────────────────────────────────────┘
```

## Requirements

- Python 3.12+
- aioquic >= 1.0.0
- fastapi >= 0.109.0
- uvicorn >= 0.27.0
