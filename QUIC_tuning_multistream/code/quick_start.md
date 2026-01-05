# Quick Start Guide

This guide will help you get the QUIC Multi-Stream Research Project running.

## Prerequisites

- Python 3.10 or higher
- [uv](https://github.com/astral-sh/uv) package manager

## Installation

1. Navigate to the code directory:

```bash
cd code
```

2. Install dependencies with uv:

```bash
uv sync
```

This will create a virtual environment and install all required packages.

## Running the Grid Search

### Check Status

Before running, check the current status:

```bash
uv run main.py status
```

This shows:
- Current progress (completed/total)
- Parameter space summary
- Next pending simulation

### Dry Run

To see what simulations would run without executing them:

```bash
uv run main.py run --dry-run
```

### Execute Grid Search

Run the full parameter sweep:

```bash
uv run main.py run
```

The grid search will:
- Execute 192 parameter combinations (4 ICW × 4 ACK delay × 4 loss factor × 3 app types)
- Save results to `output/measurements/` as CSV files
- Resume automatically from where it stopped if interrupted

### Resumability

If the process crashes or is interrupted:
- Simply run `uv run main.py run` again
- Completed simulations are detected by existing CSV files
- Only remaining simulations will execute

## Analyzing Results

After simulations complete, analyze the data:

```bash
uv run main.py analyze
```

This displays:
- Optimal parameters for each application type
- Key metrics at optimal configurations

## Generating Reports

### Summary Report

Generate a full summary report:

```bash
uv run main.py report
```

Save to file:

```bash
uv run main.py report -o output/summary_report.txt
```

### Detailed Report (per app type)

Generate detailed analysis for a specific application:

```bash
uv run main.py report --app-type video_streaming
uv run main.py report --app-type file_transfer
uv run main.py report --app-type conference_call
```

## Other Commands

### Clear Results

Start fresh by clearing all result files:

```bash
uv run main.py clear
```

Use `-f` to skip confirmation:

```bash
uv run main.py clear -f
```

### Custom Output Directory

Specify a different output directory:

```bash
uv run main.py --output-dir /path/to/results run
```

## Output Files

Results are stored in `output/measurements/` with naming convention:

```
<app_type>_<initial_cw>_<max_ack_delay>_<loss_factor>.csv
```

Example: `video_streaming_36000_0.025_0.5.csv`

Each CSV contains metrics collected during the simulation:
- `timestamp`: Measurement time
- `throughput`: Bytes per second
- `rtt`: Round-trip time (seconds)
- `jitter`: RTT variance (seconds)
- `loss_rate`: Packet loss percentage
- `goodput`: Effective throughput

## Troubleshooting

### "No CSV files found"

Run the grid search first to generate results:

```bash
uv run main.py run
```

### Connection errors

Ensure no other QUIC servers are running on the default ports (4433).

### Partial completion

Use `uv run main.py status` to check progress and re-run to complete.
