# High-Level Architecture

This document describes the architecture of the QUIC Multi-Stream Research Project.

## Project Overview

This research project investigates how QUIC protocol parameters affect performance metrics for different types of data transmission. The project performs a systematic grid search over parameter combinations and analyzes the results to find optimal configurations.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                           main.py                                   │
│                    (CLI Entry Point)                                │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   grid_search   │  │   simulation    │  │     results     │
│                 │  │                 │  │                 │
│ - executor      │  │ - runner        │  │ - analyzer      │
│ - scheduler     │  │ - client        │  │ - report_gen    │
│ - param_space   │  │ - server        │  │                 │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         │           ┌────────┴────────┐           │
         │           │                 │           │
         │           ▼                 ▼           │
         │  ┌─────────────────┐ ┌─────────────┐   │
         │  │  synthesizers   │ │   metrics   │   │
         │  │                 │ │             │   │
         │  │ - video         │ │ - collector │   │
         │  │ - file          │ │ - calculator│   │
         │  │ - conference    │ │ - exporter  │◄──┘
         │  └─────────────────┘ └─────────────┘
         │                              │
         │                              ▼
         │                      ┌─────────────┐
         └─────────────────────►│   config    │
                                │             │
                                │ - settings  │
                                │ - parameters│
                                └─────────────┘
```

## Module Descriptions

### config/

Configuration and settings management.

| File | Purpose |
|------|---------|
| `settings.py` | Global settings (paths, timeouts, defaults) |
| `parameters.py` | Parameter presets and validation |

### synthesizers/

Synthetic data generators for each application type.

| File | Purpose |
|------|---------|
| `base.py` | Abstract base class and factory |
| `video_streaming.py` | Video traffic patterns (I/P frames at 30fps) |
| `file_transfer.py` | Bulk transfer patterns (64KB chunks) |
| `conference_call.py` | Real-time patterns (20ms intervals) |

### simulation/

QUIC client/server implementation using aioquic.

| File | Purpose |
|------|---------|
| `server.py` | QUIC server receiving synthetic data |
| `client.py` | QUIC client sending synthetic streams |
| `runner.py` | Orchestrates single simulation run |

### metrics/

Performance measurement and export.

| File | Purpose |
|------|---------|
| `collector.py` | Real-time metric collection during simulation |
| `calculator.py` | Metric calculations (throughput, RTT, jitter, etc.) |
| `exporter.py` | CSV export with standardized naming |

### grid_search/

Systematic parameter sweep execution.

| File | Purpose |
|------|---------|
| `parameter_space.py` | Defines all parameter values (4×4×4×3 = 192) |
| `scheduler.py` | Resumable scheduling via CSV file detection |
| `executor.py` | Runs simulations for pending combinations |

### results/

Analysis and reporting.

| File | Purpose |
|------|---------|
| `analyzer.py` | Load data, find optimal parameters, analyze trends |
| `report_generator.py` | Generate human-readable reports |

## Data Flow

### 1. Grid Search Execution

```
GridSearchExecutor
    │
    ├─► ResumableScheduler.get_pending_combinations()
    │       └─► Check existing CSV files
    │
    └─► For each pending combination:
            │
            ├─► SimulationRunner.run()
            │       │
            │       ├─► Start QuicServer
            │       ├─► Create Synthesizer (video/file/conference)
            │       ├─► Start QuicClient with Synthesizer
            │       ├─► MetricsCollector gathers measurements
            │       └─► Return SimulationResult
            │
            └─► MetricsExporter.export()
                    └─► Save CSV file
```

### 2. Results Analysis

```
ResultsAnalyzer
    │
    ├─► load_data()
    │       └─► Parse all CSV files into DataFrame
    │
    ├─► find_optimal_parameters(app_type)
    │       └─► Minimize RTT (video), Maximize throughput (file), Minimize jitter (conference)
    │
    └─► ReportGenerator.generate_summary_report()
            └─► Format findings as text report
```

## Parameter Space

The grid search explores these parameter combinations:

| Parameter | Values | Description |
|-----------|--------|-------------|
| Initial Congestion Window | 12000, 36000, 72000, 120000 bytes | How much data to send initially |
| Max ACK Delay | 2, 10, 25, 50 ms | Maximum delay before ACK |
| Loss Reduction Factor | 0.4, 0.5, 0.6, 0.7 | Congestion window reduction on loss |

Applied to 3 application types:
- `video_streaming`: Optimized for low latency
- `file_transfer`: Optimized for high throughput
- `conference_call`: Optimized for low jitter

**Total combinations: 4 × 4 × 4 × 3 = 192**

## Key Design Decisions

### Resumability

The scheduler determines completion by checking for existing CSV files. This simple approach:
- Requires no database or state files
- Survives crashes and restarts
- Is idempotent (re-running completed simulations is harmless)

### Synthetic Data

Real application data isn't needed because:
- QUIC protocol behavior depends on byte patterns, not content
- Timing and size patterns are what matter
- Synthesized data provides consistent, reproducible results

### Optimization Targets

Each application type has a different optimization goal:
- **Video streaming** → Minimize RTT (for responsive playback)
- **File transfer** → Maximize throughput (for fast downloads)
- **Conference call** → Minimize jitter (for smooth audio/video)

## File Output Structure

```
output/
└── measurements/
    ├── video_streaming_12000_0.002_0.4.csv
    ├── video_streaming_12000_0.002_0.5.csv
    ├── ...
    ├── file_transfer_120000_0.05_0.7.csv
    └── conference_call_72000_0.025_0.5.csv
```

Each CSV contains timestamped metrics:
- `timestamp`: When measurement was taken
- `throughput`: Bytes/second
- `rtt`: Round-trip time in seconds
- `jitter`: RTT variance in seconds
- `loss_rate`: Packet loss ratio (0-1)
- `goodput`: Effective throughput (excluding retransmissions)
