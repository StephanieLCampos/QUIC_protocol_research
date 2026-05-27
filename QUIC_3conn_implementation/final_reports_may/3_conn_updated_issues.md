# Q-Learning Output Analysis Report

**Date:** May 12, 2026
**Scenario Analyzed:** per_5 (5% Packet Error Rate)
**Run:** run_May12_2026_0514PM

---

## Critical Issues Found

### 1. Wrong Agent Being Used
**Severity: HIGH**

The Q-table shows a **7-feature state format**:
```
(latency_bin, throughput_bin, jitter_bin, latency_trend, throughput_trend, jitter_trend, loss_bin)
Example: "(1, 3, 0, 1, 1, 1)"
```

This is the **DEFAULT agent**, NOT Andy's 14-feature agent. Andy's agent should have per-connection features in the state. The system is using the wrong Q-learning agent.

**Evidence:**
- Q-table states like `(2, 3, 0, 1, 1, 1)` have 7 elements
- `state_readable` shows aggregated metrics, not per-connection metrics
- Andy's agent should produce 14-feature states with separate bins for each connection

**Impact:** The Q-learning is optimizing based on aggregate network state rather than per-connection state, limiting its ability to make connection-specific optimizations.

---

### 2. rewards.csv Is Empty
**Severity: HIGH**

The rewards file contains only the header:
```
step,timestamp,reward,epsilon,action,state,next_state
(no data rows)
```

**Evidence:**
- `avg_reward_last_100: 0.0` in summary
- 450 Q-learning steps reported, but 0 reward entries logged

**Impact:** Cannot analyze learning progress over time. Unable to verify if reward function is working correctly or if agent is improving.

---

### 3. Throughput Metric Is Still Wrong
**Severity: HIGH**

The timeseries shows file_transfer throughput values of **200-300+ MB/s**:
```
timestamp 0.31: conn2_throughput_mbps = 363.17 MB/s
timestamp 0.40: conn2_throughput_mbps = 244.82 MB/s
```

With a 50 Mbps bottleneck, the **maximum possible delivered throughput is ~6.25 MB/s**.

**Evidence:**
- Final metrics.json shows `file_transfer: 161.57 MB/s`
- Timeseries shows values up to 363 MB/s
- These values exceed physical bottleneck capacity by 25-50x

**Root Cause:** The throughput metric is measuring **offered throughput** (bytes sent to buffer), NOT **delivered throughput** (bytes actually acked/received through the bottleneck).

**Impact:** Q-learning agent is optimizing based on incorrect throughput signals. Reward calculations are skewed.

---

### 4. Loss Measurement Inconsistency
**Severity: MEDIUM**

Configured scenario is `per_5` (5% packet error rate), but measured loss is much lower:

| Connection | Final Loss (%) | Expected (~5%) |
|------------|---------------|----------------|
| Video Streaming | 0.12% | ~5% |
| File Transfer | 0.01% | ~5% |
| Conference Call | 0.0% | ~5% |

**Evidence:**
- During Q-learning actions, loss varied from 0-3.6%
- Final metrics show 0.0-0.12% loss
- The 5% PER should result in approximately 5% observed packet loss

**Impact:** Loss-based optimizations in Q-learning may not be triggering correctly.

---

## What Is Working Correctly

### Q-Learning Mechanics
- **54 unique states** visited (decent exploration)
- **8 parameter changes** made (actions being taken)
- **Q-values are being learned** (non-zero values accumulating)
- **Epsilon decayed correctly**: 0.3 -> 0.05 (exploration -> exploitation)
- **450 total Q-learning steps** completed

### Actions Are Being Recorded
The `qlearning_actions.json` shows proper parameter changes:
- Loss reduction factor: 0.6 <-> 0.7
- Cubic C: 0.4 -> 0.3
- Packet threshold: 2 -> 3 -> 4
- Minimum window: 6 -> 4

### RTT and Jitter Look Reasonable
- RTT: 22-31ms (reasonable for simulated network)
- Jitter: 1-16ms (reasonable variation)

---

## Metrics Consistency Check

| Metric | During Simulation | Final (metrics.json) | Expected | Status |
|--------|-------------------|---------------------|----------|--------|
| Video Throughput | 0.11-0.19 MB/s | 1.03 MB/s | ~0.1-1 MB/s | OK |
| File Transfer Throughput | 10-36 MB/s | 161.57 MB/s | ~4-6 MB/s | **WRONG** |
| Conference Throughput | 0.008-0.017 MB/s | 0.116 MB/s | ~0.01-0.1 MB/s | OK |
| RTT (all connections) | 22-29ms | 22-31ms | ~20-30ms | OK |
| Loss (all connections) | 0-3.6% | 0.01-0.12% | ~5% | **LOW** |

---

## Root Causes Summary

1. **Wrong agent loaded**: The `get_qlearning_summary()` function or `MLController` is loading the default 7-feature agent instead of Andy's 14-feature agent.

2. **Throughput calculation**: Despite fixes to add `throughput_cwnd`, the final export is still using raw `bytes_sent`-based throughput calculation.

3. **Rewards not being written**: The reward logging mechanism in the agent's `_log_reward()` or similar function isn't executing or isn't flushing to disk.

4. **Loss calculation**: The packet loss estimation methods may not be accurately capturing the configured 5% PER from the Docker bottleneck.

---

## Recommendations

### Priority 1: Fix Agent Selection
- Verify `MLController` instantiates Andy's agent
- Check that `get_qlearning_summary()` returns the correct agent's data
- Confirm agent type in startup logs

### Priority 2: Fix Throughput Export
- Final metrics export should use `throughput_cwnd` or `throughput_acked`
- Remove or replace `bytes_sent / duration` calculation
- Verify bottleneck is actually limiting throughput in Docker setup

### Priority 3: Fix Reward Logging
- Add explicit flush/write calls to ensure rewards are written
- Verify `rewards.csv` file path is correct
- Check for exceptions silently swallowing write errors

### Priority 4: Verify Loss Measurement
- Confirm Docker bottleneck is applying 5% PER correctly
- Review packet loss calculation methods in worker_process.py
- Compare configured loss rate vs measured loss rate

---

## Files Analyzed

| File | Description | Key Finding |
|------|-------------|-------------|
| `README.md` | Run summary | 450 steps, 8 actions, 54 states |
| `q_table.json` | Learned Q-values | Wrong agent format (7-feature) |
| `metrics.json` | Final metrics | Throughput values too high |
| `qlearning_actions.json` | Parameter changes | Actions recorded correctly |
| `rewards.csv` | Reward history | Empty (header only) |
| `metrics_timeseries.csv` | Time series data | Throughput 200-300+ MB/s |
| `config.json` | Run configuration | Hyperparameters correct |
