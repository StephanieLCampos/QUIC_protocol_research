# Recommended Output Files for Q-Learning QUIC Simulation

This document outlines additional data that could be valuable to capture after each Q-learning session, beyond the current outputs.

---

## Current Outputs

The simulation currently generates:

| File | Description |
|------|-------------|
| `README.md` | Human-readable summary with tables |
| `qlearning_actions.json` | Q-learning action history with before/after metrics |
| `qlearning_actions.csv` | Same data in CSV format for spreadsheets |
| `metrics.json` | Final metrics for each connection |

---

## High Value - Strongly Recommend

| File | Description | Why It's Valuable |
|------|-------------|-------------------|
| **q_table.json** | The learned Q-values for all visited states | This IS the trained "brain" - lets you analyze what the agent learned, compare across scenarios, and potentially warm-start future runs |
| **metrics_timeseries.csv** | Throughput, RTT, jitter, loss for each connection at every time step | Currently you only save final metrics - time-series lets you plot graphs, see how metrics evolved, correlate with Q-learning actions |
| **config.json** | Full run configuration (QUIC params, Q-learning hyperparams, scenario settings) | Essential for reproducibility - know exactly what settings produced these results |
| **rewards.csv** | Reward value at each Q-learning step | Shows if agent is improving over time, helps diagnose reward function issues |

### q_table.json

```json
{
  "export_timestamp": "2026-04-06T12:34:56",
  "total_states": 127,
  "q_values": {
    "(0, 2, 1, 1, 2, 1)": [0.234, 0.156, -0.089, ...],
    "(1, 3, 0, 2, 1, 0)": [0.412, 0.089, 0.234, ...]
  },
  "state_visit_counts": {
    "(0, 2, 1, 1, 2, 1)": 15,
    "(1, 3, 0, 2, 1, 0)": 8
  }
}
```

### metrics_timeseries.csv

```csv
timestamp,conn_1_throughput,conn_1_rtt,conn_1_jitter,conn_1_loss,conn_2_throughput,conn_2_rtt,...
0.0,0.00,0.00,0.00,0.00,0.00,0.00,...
0.1,1.25,32.5,2.1,0.01,2.45,28.3,...
0.2,1.31,31.2,1.8,0.00,2.52,27.9,...
```

### config.json

```json
{
  "scenario": "varying",
  "duration_seconds": 120,
  "network": {
    "capacity_bps": 20000000,
    "propagation_delay": 0.01,
    "loss_rate": 0.01,
    "time_varying": true,
    "variation_period": 2.0,
    "variation_amplitude": 0.4
  },
  "qlearning": {
    "alpha": 0.10,
    "gamma": 0.90,
    "epsilon_start": 0.30,
    "epsilon_min": 0.05,
    "epsilon_decay": 0.995,
    "control_interval": 2.0
  },
  "connections": {
    "video_streaming": {
      "loss_reduction_factor": 0.6,
      "cubic_c": 0.4,
      "minimum_window": 4
    },
    "file_transfer": {
      "loss_reduction_factor": 0.7,
      "cubic_c": 0.5,
      "minimum_window": 2
    },
    "conference_call": {
      "loss_reduction_factor": 0.5,
      "cubic_c": 0.3,
      "minimum_window": 6
    }
  }
}
```

### rewards.csv

```csv
step,timestamp,reward,epsilon,action,state
1,2.0,0.342,0.300,video.cubic_c.increase,"(0,2,1,1,2,1)"
2,4.0,0.289,0.299,file.loss_reduction_factor.decrease,"(1,2,1,1,2,1)"
3,6.0,0.401,0.297,no-op,"(1,3,1,2,2,1)"
```

---

## Medium Value - Recommended

| File | Description | Why It's Valuable |
|------|-------------|-------------------|
| **parameter_history.csv** | Time-series of all CUBIC parameters per connection | See the trajectory of parameter tuning - did they stabilize or oscillate? |
| **performance_summary.json** | Aggregated stats: avg/min/max/p95 for each metric, Jain's fairness index, bandwidth utilization | Quick high-level "how well did this run perform?" |
| **state_transitions.json** | Full (state, action, reward, next_state) log | The fundamental Q-learning data - can replay/analyze learning offline |
| **convergence_metrics.json** | Q-value change rate, exploration ratio over time, action distribution | Assess if Q-learning is actually converging or still exploring |

### parameter_history.csv

```csv
timestamp,conn_1_loss_reduction,conn_1_cubic_c,conn_1_min_window,conn_2_loss_reduction,...
0.0,0.6,0.4,4,0.7,...
2.0,0.6,0.5,4,0.7,...
4.0,0.6,0.5,4,0.6,...
```

### performance_summary.json

```json
{
  "scenario": "varying",
  "duration_seconds": 120,
  "aggregate_metrics": {
    "video_streaming": {
      "throughput_mbps": {"avg": 1.82, "min": 0.45, "max": 2.91, "std": 0.52},
      "rtt_ms": {"avg": 34.2, "min": 25.1, "max": 89.3, "p95": 62.1},
      "jitter_ms": {"avg": 4.2, "min": 0.8, "max": 15.2},
      "loss_percent": {"avg": 1.2, "max": 5.8}
    },
    "file_transfer": {...},
    "conference_call": {...}
  },
  "fairness": {
    "jains_index": 0.89,
    "throughput_ratio": {"min_max": 0.72, "std": 0.34}
  },
  "efficiency": {
    "total_bytes_transferred": 28453920,
    "bandwidth_utilization": 0.76
  }
}
```

### state_transitions.json

```json
{
  "transitions": [
    {
      "step": 1,
      "state": [0, 2, 1, 1, 2, 1],
      "action": 4,
      "action_decoded": "video.cubic_c.increase",
      "reward": 0.342,
      "next_state": [0, 2, 1, 1, 2, 1]
    },
    ...
  ]
}
```

### convergence_metrics.json

```json
{
  "q_value_changes": {
    "avg_delta_per_step": [0.15, 0.12, 0.09, 0.07, ...],
    "max_q_value_over_time": [0.2, 0.35, 0.42, 0.48, ...]
  },
  "exploration_ratio": {
    "steps_1_to_10": 0.82,
    "steps_11_to_20": 0.65,
    "steps_21_to_30": 0.48,
    "final": 0.15
  },
  "action_distribution": {
    "video.loss_reduction_factor.increase": 12,
    "video.loss_reduction_factor.decrease": 8,
    "video.cubic_c.increase": 15,
    "file.loss_reduction_factor.decrease": 11,
    "no-op": 23
  },
  "most_visited_states": [
    {"state": "(1, 2, 1, 1, 2, 1)", "visits": 24},
    {"state": "(0, 3, 1, 2, 2, 1)", "visits": 18}
  ]
}
```

---

## Nice to Have

| File | Description | Why It's Valuable |
|------|-------------|-------------------|
| **epochs.csv** | Per-epoch data for each connection (already collected internally) | Finer granularity than metrics_timeseries |
| **congestion_window_history.csv** | CWND evolution over time | Understand CUBIC behavior at the congestion control level |
| **network_conditions.json** | For `varying` scenario - actual bandwidth/RTT at each point | Correlate Q-learning adaptations with network changes |

### epochs.csv

```csv
epoch,connection,throughput,rtt,jitter,loss,bytes_sent,cwnd
1,video_streaming,1.25,32.5,2.1,0.01,156250,32000
1,file_transfer,2.45,28.3,1.5,0.00,306250,48000
1,conference_call,0.89,35.1,3.2,0.02,111250,24000
2,video_streaming,1.31,31.2,1.8,0.00,163750,34000
```

### congestion_window_history.csv

```csv
timestamp,conn_1_cwnd,conn_1_ssthresh,conn_2_cwnd,conn_2_ssthresh,conn_3_cwnd,conn_3_ssthresh
0.1,14000,65535,14000,65535,14000,65535
0.2,28000,65535,28000,65535,28000,65535
0.3,42000,65535,56000,65535,35000,65535
```

### network_conditions.json (for varying scenario)

```json
{
  "scenario": "varying",
  "base_bandwidth_bps": 20000000,
  "variation_amplitude": 0.4,
  "variation_period_seconds": 2.0,
  "sampled_conditions": [
    {"timestamp": 0.0, "bandwidth_bps": 20000000, "rtt_ms": 20},
    {"timestamp": 0.5, "bandwidth_bps": 26000000, "rtt_ms": 20},
    {"timestamp": 1.0, "bandwidth_bps": 20000000, "rtt_ms": 20},
    {"timestamp": 1.5, "bandwidth_bps": 14000000, "rtt_ms": 20}
  ]
}
```

---

## Priority Implementation Order

If implementing incrementally, here's the recommended order:

1. **q_table.json** - Without this, you lose what the agent learned
2. **metrics_timeseries.csv** - Can't analyze trends without time-series data
3. **config.json** - Reproducibility is critical for research
4. **performance_summary.json** - Quick comparison across runs
5. **rewards.csv** - Understanding learning progress
6. **parameter_history.csv** - Seeing parameter evolution
7. **state_transitions.json** - Full replay capability
8. **convergence_metrics.json** - Assess learning quality

---

## Folder Structure with All Files

```
results/
└── varying/
    └── run_Apr06_2026_1234PM/
        ├── README.md                  # Human-readable summary
        ├── qlearning_actions.json     # Action history (current)
        ├── qlearning_actions.csv      # Action history CSV (current)
        ├── metrics.json               # Final metrics (current)
        ├── q_table.json               # Learned Q-values
        ├── metrics_timeseries.csv     # Time-series metrics
        ├── config.json                # Run configuration
        ├── rewards.csv                # Reward history
        ├── parameter_history.csv      # Parameter evolution
        ├── performance_summary.json   # Aggregated stats
        ├── state_transitions.json     # Full transition log
        └── convergence_metrics.json   # Learning analysis
```
