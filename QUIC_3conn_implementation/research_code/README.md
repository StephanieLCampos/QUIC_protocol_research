# Research Code: Uniform Configuration Experiments

This directory contains tools to run comparative experiments using uniform QUIC configurations across all 3 application types.

## Overview

The experiment applies the **same congestion control parameters** to all 3 connections simultaneously, measuring how each application type performs under each configuration.

| Configuration | Optimizes For | Source |
|---------------|---------------|--------|
| `ft_friendly` | Throughput (File Transfer) | Grid search optimal |
| `vc_friendly` | Jitter (Video Call) | Grid search optimal |
| `mm_friendly` | Latency (Multimedia) | Grid search optimal |

This produces **27 measurements**: 3 configs × 3 apps × 3 metrics (throughput, latency, jitter).

---

## Installation

No separate installation needed - this module uses the `3_conn_code` virtual environment.

---

## Running Experiments

**Important:** Run from the `3_conn_code` directory (where certificates and dependencies are located).

```bash
cd 3_conn_code
```

### List Available Presets

```bash
uv run python ../research_code/experiment_runner.py --list
```

### Run All 3 Experiments

Runs all configurations sequentially to collect all 27 metric values:

```bash
uv run python ../research_code/experiment_runner.py --all --duration 60
```

### Run Single Configuration

```bash
uv run python ../research_code/experiment_runner.py --config ft_friendly --duration 60
uv run python ../research_code/experiment_runner.py --config vc_friendly --duration 60
uv run python ../research_code/experiment_runner.py --config mm_friendly --duration 60
```

---

## Extracting Results

After running experiments, extract and compare the 27 values:

```bash
uv run python ../research_code/results_extractor.py --output-dir ../research_code/output
```

This produces:
- `output/all_27_values.csv` - All measurements
- `output/metric_ranges.csv` - Min/max ranges per metric
- `output/comparison_results.json` - Full data in JSON format

---

## Commands

### experiment_runner.py

```bash
uv run python ../research_code/experiment_runner.py [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--config NAME` | - | Run single config (ft_friendly, vc_friendly, mm_friendly) |
| `--all` | - | Run all 3 configs sequentially |
| `--duration SECS` | 60 | Simulation duration per config |
| `--output-dir DIR` | output | Output directory for results |
| `--list` | - | List available presets and exit |

### results_extractor.py

```bash
uv run python ../research_code/results_extractor.py [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--output-dir DIR` | output | Directory containing results |
| `--format FORMAT` | both | Output format: table, csv, or both |

---

## Current Preset Values

Values from grid search (243 combinations tested):

### ft_friendly (Maximize Throughput)

Optimal throughput: **326.88 Mbps**

| Parameter | Value |
|-----------|-------|
| `loss_reduction_factor` | 0.3 |
| `cubic_c` | 0.2 |
| `minimum_window` | 4 |
| `packet_threshold` | 3 |
| `time_threshold` | 1.125 |
| `cubic_max_idle_time` | 2.0 |

### vc_friendly (Minimize Jitter)

Optimal jitter: **0.06 ms**

| Parameter | Value |
|-----------|-------|
| `loss_reduction_factor` | 0.5 |
| `cubic_c` | 0.2 |
| `minimum_window` | 4 |
| `packet_threshold` | 3 |
| `time_threshold` | 1.125 |
| `cubic_max_idle_time` | 2.0 |

### mm_friendly (Minimize Latency)

Optimal latency: **1.60 ms**

| Parameter | Value |
|-----------|-------|
| `loss_reduction_factor` | 0.7 |
| `cubic_c` | 0.4 |
| `minimum_window` | 2 |
| `packet_threshold` | 4 |
| `time_threshold` | 1.125 |
| `cubic_max_idle_time` | 2.0 |

**Source:** `config/uniform_presets.py` (values from `grid_search_code/output/analysis/optimal_configs.json`)

---

## Directory Structure

```
research_code/
├── README.md                 # This file
├── experiment_runner.py      # Main experiment CLI
├── results_extractor.py      # Extract and compare results
├── config/
│   ├── __init__.py
│   └── uniform_presets.py    # Preset configurations
└── output/                   # Results (created after running)
    ├── ft_friendly/
    ├── vc_friendly/
    └── mm_friendly/
```

---

## Quick Start

```bash
# 1. Navigate to 3_conn_code (required for dependencies)
cd 3_conn_code

# 2. List available presets
uv run python ../research_code/experiment_runner.py --list

# 3. Run all experiments (collects all 27 values)
uv run python ../research_code/experiment_runner.py --all --duration 60

# 4. Extract and compare results
uv run python ../research_code/results_extractor.py --output-dir ../research_code/output
```

---

## Updating Presets

To update with new grid search results:

```bash
# 1. Run grid search
cd ../grid_search_code
uv run python main.py run

# 2. Analyze results
uv run python main.py analyze

# 3. Copy values from output/analysis/optimal_configs.json
# 4. Update config/uniform_presets.py
```
