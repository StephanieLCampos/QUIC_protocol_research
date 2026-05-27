# Q-Learning Reward Function Documentation

This document details the reward function used by the Q-learning agent for QUIC parameter optimization.

## Overview

The reward function balances three objectives:
1. **Performance**: Maximize satisfaction across all connection types
2. **Fairness**: Ensure no single connection dominates at others' expense
3. **Stability**: Discourage unnecessary parameter changes

---

## Reward Equation

```
R = mean(U_stream, U_file, U_conf) - λ·std(U_stream, U_file, U_conf) - μ·changed
```

### Parameters

| Symbol | Name | Value | Description |
|--------|------|-------|-------------|
| λ | `LAMBDA_FAIRNESS` | 0.10 | Penalizes imbalance between connections |
| μ | `MU_STABILITY` | 0.05 | Penalizes unnecessary parameter changes |
| changed | - | 0 or 1 | 1 if action modified a parameter, 0 otherwise |

---

## Utility Functions

Each connection has a utility function normalized to [0, 1] where **1 is best**.

### Video Streaming Utility (Minimize Latency)

```
U_stream = (latency_worst - latency) / (latency_worst - latency_best)
```

Expanded:
```
U_stream = (0.200 - latency) / (0.200 - 0.020)
         = (0.200 - latency) / 0.180
```

| Latency | U_stream |
|---------|----------|
| 20ms (best) | 1.000 |
| 50ms | 0.833 |
| 100ms | 0.556 |
| 200ms (worst) | 0.000 |

### File Transfer Utility (Maximize Throughput)

```
U_file = throughput / throughput_max
       = throughput / 3,750,000
```

| Throughput | U_file |
|------------|--------|
| 3.75 MB/s (30 Mbps) | 1.000 |
| 2.0 MB/s (16 Mbps) | 0.533 |
| 1.0 MB/s (8 Mbps) | 0.267 |
| 0 MB/s | 0.000 |

### Conference Call Utility (Minimize Jitter)

```
U_conf = (jitter_worst - jitter) / jitter_worst
       = (0.050 - jitter) / 0.050
```

| Jitter | U_conf |
|--------|--------|
| 0ms (best) | 1.000 |
| 10ms | 0.800 |
| 25ms | 0.500 |
| 50ms (worst) | 0.000 |

---

## Constants

| Constant | Value | Unit | Description |
|----------|-------|------|-------------|
| `LATENCY_BEST` | 0.020 | seconds (20ms) | Best achievable latency |
| `LATENCY_WORST` | 0.200 | seconds (200ms) | Worst tolerable latency |
| `THROUGHPUT_MAX` | 3,750,000 | bytes/s (30 Mbps) | Target throughput |
| `JITTER_WORST` | 0.050 | seconds (50ms) | Worst tolerable jitter |

---

## Code Implementation

From `ml_callbacks/q_learning_agent.py:345-372`:

```python
def _reward(self, metrics: Dict[int, dict], action_changed: bool) -> float:
    """
    Compute scalar reward from current metrics.

    R = mean(U_stream, U_file, U_conf)
        - lambda * std(utilities)   # fairness penalty
        - mu * changed              # stability penalty
    """
    if not all(c in metrics for c in CONNECTIONS):
        return 0.0

    # Extract metrics for each connection type
    lat = metrics[CONN_VIDEO].get("latency", 0.0)
    tp  = metrics[CONN_FILE].get("throughput", 0.0)
    jit = metrics[CONN_CONF].get("jitter", 0.0)

    # Compute utilities (each normalized to 0-1)
    u_stream = _utility_latency(lat)
    u_file   = _utility_throughput(tp)
    u_conf   = _utility_jitter(jit)

    # Mean utility (performance term)
    mean_u = (u_stream + u_file + u_conf) / 3.0

    # Standard deviation (fairness penalty)
    try:
        std_u = statistics.stdev([u_stream, u_file, u_conf])
    except statistics.StatisticsError:
        std_u = 0.0

    # Stability penalty
    churn = MU_STABILITY if action_changed else 0.0

    return mean_u - LAMBDA_FAIRNESS * std_u - churn
```

### Helper Functions

```python
def _utility_latency(v: float) -> float:
    """Normalize latency to [0,1] where 1 is best (lowest)."""
    u = (LATENCY_WORST - v) / (LATENCY_WORST - LATENCY_BEST)
    return max(0.0, min(1.0, u))


def _utility_throughput(v: float) -> float:
    """Normalize throughput to [0,1] where 1 is best (highest)."""
    return max(0.0, min(1.0, v / THROUGHPUT_MAX))


def _utility_jitter(v: float) -> float:
    """Normalize jitter to [0,1] where 1 is best (lowest)."""
    if JITTER_WORST == 0:
        return 1.0
    return max(0.0, min(1.0, (JITTER_WORST - v) / JITTER_WORST))
```

---

## Reward Calculation Example

### Given Metrics

| Connection | Metric | Value |
|------------|--------|-------|
| Video Streaming | Latency | 30ms (0.030s) |
| File Transfer | Throughput | 2 MB/s (2,000,000 bytes/s) |
| Conference Call | Jitter | 10ms (0.010s) |
| Action | Changed | Yes (1) |

### Step 1: Calculate Utilities

```
U_stream = (0.200 - 0.030) / 0.180 = 0.170 / 0.180 = 0.944
U_file   = 2,000,000 / 3,750,000 = 0.533
U_conf   = (0.050 - 0.010) / 0.050 = 0.040 / 0.050 = 0.800
```

### Step 2: Calculate Mean Utility

```
mean_u = (0.944 + 0.533 + 0.800) / 3
       = 2.277 / 3
       = 0.759
```

### Step 3: Calculate Fairness Penalty

```
std_u = stdev([0.944, 0.533, 0.800])
      = 0.206

fairness_penalty = λ × std_u
                 = 0.10 × 0.206
                 = 0.021
```

### Step 4: Calculate Stability Penalty

```
stability_penalty = μ × changed
                  = 0.05 × 1
                  = 0.05
```

### Step 5: Final Reward

```
R = mean_u - fairness_penalty - stability_penalty
  = 0.759 - 0.021 - 0.05
  = 0.688
```

---

## Reward Components Explained

| Component | Formula | Range | Purpose |
|-----------|---------|-------|---------|
| **Performance** | `mean(U_stream, U_file, U_conf)` | 0.0 - 1.0 | Maximize overall satisfaction |
| **Fairness Penalty** | `-λ·std(utilities)` | -0.05 - 0.0 | Discourage one app dominating |
| **Stability Penalty** | `-μ·changed` | -0.05 or 0.0 | Discourage parameter thrashing |

### Why Each Component Matters

**Performance (mean utility)**:
- Encourages the agent to find parameters that work well for all connections
- Higher is better for each individual connection type

**Fairness Penalty (standard deviation)**:
- Without this, the agent might maximize one connection at the expense of others
- Example: Boosting file transfer to 100% utility while video drops to 20%
- The std penalty ensures balanced performance across all three apps

**Stability Penalty (change penalty)**:
- Without this, the agent might constantly change parameters
- CUBIC congestion control needs time to adapt after parameter changes
- This encourages the agent to only change parameters when beneficial

---

## Reward Range Analysis

### Theoretical Bounds

| Scenario | mean_u | std_u | changed | R |
|----------|--------|-------|---------|---|
| Perfect (all U=1.0) | 1.000 | 0.000 | 0 | **1.000** |
| Perfect but changed | 1.000 | 0.000 | 1 | **0.950** |
| Good balanced (all U=0.8) | 0.800 | 0.000 | 0 | **0.800** |
| Good unbalanced (0.9, 0.8, 0.6) | 0.767 | 0.153 | 0 | **0.752** |
| Mixed (1.0, 0.5, 0.5) | 0.667 | 0.289 | 0 | **0.638** |
| Poor balanced (all U=0.3) | 0.300 | 0.000 | 0 | **0.300** |
| Worst case (all U=0.0) | 0.000 | 0.000 | 0 | **0.000** |

### Practical Reward Ranges

| Performance Level | Approximate R |
|-------------------|---------------|
| Excellent (all connections satisfied) | 0.8 - 1.0 |
| Good (most connections satisfied) | 0.6 - 0.8 |
| Fair (mixed performance) | 0.4 - 0.6 |
| Poor (struggling connections) | 0.2 - 0.4 |
| Bad (most connections unsatisfied) | 0.0 - 0.2 |

---

## Impact of Penalty Weights

### Fairness Weight (λ = 0.10)

| λ Value | Effect |
|---------|--------|
| 0.00 | No fairness consideration; may sacrifice some connections |
| 0.10 | Moderate fairness; balanced optimization (default) |
| 0.20 | Strong fairness; prioritizes equality over total performance |
| 0.50 | Extreme fairness; equality dominates decision-making |

### Stability Weight (μ = 0.05)

| μ Value | Effect |
|---------|--------|
| 0.00 | No stability penalty; may change parameters every step |
| 0.05 | Moderate stability; changes when beneficial (default) |
| 0.10 | Conservative; requires significant improvement to change |
| 0.20 | Very conservative; rarely changes parameters |

---

## Q-Learning Update Using Reward

The reward is used in the Bellman equation to update Q-values:

```
Q(s, a) ← Q(s, a) + α [R + γ · max_a' Q(s', a') - Q(s, a)]
```

Where:
- `α = 0.10` (learning rate)
- `γ = 0.90` (discount factor)
- `R` = reward calculated above
- `s` = current state
- `a` = action taken
- `s'` = next state

This means:
1. Actions that lead to higher rewards get higher Q-values
2. The agent learns which parameter changes improve performance
3. Over time, the Q-table maps states to optimal actions

---

## Summary

The reward function is designed to:

1. **Maximize overall performance** across all three connection types (video, file, conference)

2. **Ensure fairness** by penalizing situations where one connection thrives at others' expense

3. **Encourage stability** by penalizing unnecessary parameter changes that disrupt CUBIC congestion control

The balanced design allows the Q-learning agent to find parameter configurations that provide good, fair, and stable performance under constrained network conditions created by the wireless bottleneck.
