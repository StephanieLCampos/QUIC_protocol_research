# Network Parameters Options for Q-Learning State

This document explores different approaches to make Q-learning states more specific to network conditions, improving the accuracy and context-awareness of the learned policies.

---

## Current State Structure

```
state = (latency_bin, throughput_bin, jitter_bin,
         latency_trend, throughput_trend, jitter_trend,
         loss_bin)
```

**Total states:** 6,912 (4^4 × 3^3)

### Current Limitations

- Each metric comes from a single connection (not network-wide)
- Only `loss_bin` provides network condition context
- Agent learns one policy that must work across all bandwidth/RTT conditions

---

## Option 1: Add Individual Network Parameter Bins

Add `bandwidth_bin` and/or `rtt_bin` to the state tuple.

### State Structure

```python
# With bandwidth only
state = (..., loss_bin, bandwidth_bin)
# States: 27,648 (4^5 × 3^3)

# With bandwidth and RTT
state = (..., loss_bin, bandwidth_bin, rtt_bin)
# States: 110,592 (4^6 × 3^3)
```

### Proposed Bins

#### Bandwidth Bins
| Bin | Range | Typical Scenario |
|-----|-------|------------------|
| 0 | < 10 Mbps | congested_low, lossy |
| 1 | 10-30 Mbps | varying |
| 2 | 30-70 Mbps | asymmetric, per_* |
| 3 | > 70 Mbps | stable_high |

#### RTT Bins
| Bin | Range | Typical Scenario |
|-----|-------|------------------|
| 0 | < 15ms | stable_high |
| 1 | 15-25ms | asymmetric, varying |
| 2 | 25-35ms | congested_low |
| 3 | > 35ms | lossy |

### Training Time Estimates

| Configuration | States | Training Time |
|---------------|--------|---------------|
| Current (loss_bin only) | 6,912 | ~8 hours |
| + bandwidth_bin | 27,648 | ~17 hours |
| + bandwidth_bin + rtt_bin | 110,592 | ~35+ hours |

### Pros and Cons

| Pros | Cons |
|------|------|
| Most granular network context | State space explosion |
| Agent can learn precise policies | Longer training time |
| Works with any network condition | May have sparse state visits |

### Recommendation

**Add `bandwidth_bin` only.** RTT is partially captured by `latency_bin`, so adding `rtt_bin` provides diminishing returns.

---

## Option 2: Scenario ID as State Component

Instead of binning network parameters, directly include the scenario identifier.

### State Structure

```python
SCENARIO_IDS = {
    "stable_high": 0,
    "congested_low": 1,
    "varying": 2,
    "lossy": 3,
    "asymmetric": 4,
}

state = (latency_bin, throughput_bin, jitter_bin,
         latency_trend, throughput_trend, jitter_trend,
         scenario_id)  # 0-4
```

**Total states:** 6,912 × 5 = 34,560

### Implementation

```python
# In q_learning_agent.py
def _build_state(self, metrics, scenario_name):
    # ... existing bin calculations ...
    scenario_id = SCENARIO_IDS.get(scenario_name, 0)
    return (lat_bin, tp_bin, jit_bin, lat_trend, tp_trend, jit_trend, scenario_id)
```

### Pros and Cons

| Pros | Cons |
|------|------|
| Simple to implement | Only works for known scenarios |
| No additional bins needed | Doesn't generalize to new conditions |
| Clear policy separation | Agent must know scenario at runtime |
| Moderate state space | No interpolation between scenarios |

### Best For

Controlled experiments with a fixed, known set of scenarios.

---

## Option 3: Separate Q-Tables Per Scenario

Maintain completely separate Q-tables for each network condition.

### Structure

```python
class MultiScenarioQLearning:
    def __init__(self):
        self.q_tables = {
            "stable_high": {},      # Q-table for high bandwidth, low loss
            "congested_low": {},    # Q-table for low bandwidth, high loss
            "varying": {},          # Q-table for varying conditions
            "lossy": {},            # Q-table for high loss
            "asymmetric": {},       # Q-table for asymmetric links
        }
        self.current_scenario = None

    def select_action(self, state, scenario):
        q_table = self.q_tables[scenario]
        return self._best_action(q_table, state)

    def update(self, state, action, reward, next_state, scenario):
        q_table = self.q_tables[scenario]
        # Standard Q-learning update on scenario-specific table
```

**States per table:** 1,728 (original 6-tuple without loss_bin)
**Total storage:** 1,728 × 5 = 8,640 states across all tables

### Training Approach

```bash
# Train each scenario independently
for scenario in stable_high congested_low varying lossy asymmetric; do
    SCENARIO=$scenario DURATION=300 docker-compose up
done
```

### Pros and Cons

| Pros | Cons |
|------|------|
| Each policy fully specialized | No knowledge transfer between scenarios |
| Small state space per table | Must know which scenario you're in |
| Fast training per scenario | More storage (5× Q-tables) |
| Policies don't interfere | Cannot handle unknown scenarios |

### Best For

When scenarios are very different and you always know which one you're operating in.

---

## Option 4: Composite Network Condition Index

Create a single derived metric that captures overall network health.

### Formula

```python
def compute_network_condition_index(bandwidth_mbps, rtt_ms, loss_pct):
    """
    Compute a composite network condition score (0.0 to 1.0).

    Higher score = better network conditions.
    """
    # Normalize each factor to 0-1
    bw_score = min(1.0, bandwidth_mbps / 100)      # 100 Mbps = max
    rtt_score = max(0.0, 1 - rtt_ms / 50)          # 50ms = worst
    loss_score = max(0.0, 1 - loss_pct / 10)       # 10% = worst

    # Weighted combination (adjust weights based on importance)
    return 0.4 * bw_score + 0.3 * rtt_score + 0.3 * loss_score
```

### Bins

```python
NETWORK_CONDITION_BINS = [0.33, 0.55, 0.75]

# Results in:
# Bin 0: index < 0.33  → Poor conditions
# Bin 1: 0.33-0.55     → Fair conditions
# Bin 2: 0.55-0.75     → Good conditions
# Bin 3: index > 0.75  → Excellent conditions
```

### State Structure

```python
state = (latency_bin, throughput_bin, jitter_bin,
         latency_trend, throughput_trend, jitter_trend,
         network_condition_bin)  # Replaces loss_bin
```

**Total states:** 6,912 (same as current with loss_bin)

### Scenario Mapping

| Scenario | BW (Mbps) | RTT (ms) | Loss (%) | Index | Bin |
|----------|-----------|----------|----------|-------|-----|
| stable_high | 100 | 10 | 0.1 | 0.89 | 3 (excellent) |
| congested_low | 5 | 30 | 2.0 | 0.32 | 0 (poor) |
| varying | 20 | 20 | 1.0 | 0.50 | 1 (fair) |
| lossy | 10 | 40 | 5.0 | 0.27 | 0 (poor) |
| asymmetric | 50 | 25 | 0.5 | 0.60 | 2 (good) |

### Pros and Cons

| Pros | Cons |
|------|------|
| Only 1 extra state dimension | Loses granularity |
| Same state space as loss_bin only | Must tune the formula weights |
| Captures multiple factors at once | May miss edge cases |
| Good generalization | Single index may oversimplify |

### Best For

When you want network context without state space explosion, and training time is limited.

---

## Option 5: Neural Network Q-Learning (DQN)

Replace tabular Q-learning with a neural network that can handle continuous states.

### Architecture

```python
import torch
import torch.nn as nn

class DQN(nn.Module):
    def __init__(self, state_dim=10, action_dim=25, hidden_dim=128):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, action_dim)
        )

    def forward(self, state):
        return self.network(state)
```

### State Vector (Continuous)

```python
state_vector = [
    latency_ms,           # Connection 1 latency
    throughput_mbps,      # Connection 2 throughput
    jitter_ms,            # Connection 3 jitter
    latency_delta,        # Change from previous
    throughput_delta,     # Change from previous
    jitter_delta,         # Change from previous
    loss_rate,            # Network packet loss (0-1)
    bandwidth_mbps,       # Available bandwidth
    rtt_ms,               # Network RTT
    utilization,          # Bandwidth utilization (0-1)
]
```

### Training Requirements

- Experience replay buffer (10,000+ transitions)
- Target network with periodic updates
- Batch training (32-64 samples per update)
- More training episodes (100+ hours)

### Pros and Cons

| Pros | Cons |
|------|------|
| Handles continuous states | More complex to implement |
| No state space explosion | Requires more training data |
| Generalizes to unseen conditions | Less interpretable |
| Can use all network parameters | Needs hyperparameter tuning |
| State-of-the-art approach | Harder to debug |

### Best For

Long-term, production-quality solution where training time and complexity are acceptable.

---

## Option 6: Adaptive Binning Based on Observed Range

Dynamically adjust bin thresholds based on what the agent actually observes during training.

### Implementation

```python
class AdaptiveBinner:
    def __init__(self, num_bins=4):
        self.num_bins = num_bins
        self.observations = []
        self.thresholds = None

    def observe(self, value):
        self.observations.append(value)
        # Recompute thresholds periodically
        if len(self.observations) % 100 == 0:
            self._update_thresholds()

    def _update_thresholds(self):
        sorted_obs = sorted(self.observations)
        percentiles = [25, 50, 75]  # Quartiles
        self.thresholds = [
            sorted_obs[int(len(sorted_obs) * p / 100)]
            for p in percentiles
        ]

    def get_bin(self, value):
        if self.thresholds is None:
            return 0  # Default until enough data
        for i, t in enumerate(self.thresholds):
            if value < t:
                return i
        return self.num_bins - 1
```

### Pros and Cons

| Pros | Cons |
|------|------|
| Bins adapt to actual conditions | Bins change during training |
| Better use of state space | Can cause instability |
| Works across different networks | Q-values may become inconsistent |
| No manual threshold tuning | More complex to implement |

### Best For

When deploying to unknown network environments where fixed bins may not be appropriate.

---

## Comparison Summary

| Option | States | Training Time | Complexity | Generalization |
|--------|--------|---------------|------------|----------------|
| 1. Add bandwidth_bin | 27,648 | ~17 hours | Low | Good |
| 2. Scenario ID | 34,560 | ~19 hours | Very Low | Poor |
| 3. Separate Q-tables | 1,728 × 5 | ~2.5 hrs × 5 | Low | Poor |
| **4. Condition Index** | **6,912** | **~8 hours** | **Low** | **Good** |
| 5. Neural Network (DQN) | Unlimited | Days | High | Excellent |
| 6. Adaptive Binning | ~6,912 | ~8 hours | Medium | Good |

---

## Recommendation

### For Your Current Setup

**Use Option 4: Composite Network Condition Index**

Reasons:
1. **Minimal state explosion** - Same 6,912 states as current implementation
2. **Captures all network factors** - Bandwidth, RTT, and loss in one metric
3. **Simple to implement** - Just one new function and bin calculation
4. **Practical training time** - ~8 hours (same as current)
5. **Good generalization** - Works with any network condition, not just known scenarios

### For Future Enhancement

Consider **Option 5: Neural Network (DQN)** when:
- You have more training resources available
- You want to handle continuous parameter spaces
- You need to generalize to arbitrary network conditions
- Interpretability is less important than performance

---

## Implementation Priority

1. **Now:** Keep current implementation with `loss_bin`
2. **Short-term:** Add Composite Network Condition Index (Option 4)
3. **Medium-term:** Add `bandwidth_bin` if more granularity needed (Option 1)
4. **Long-term:** Consider DQN for production deployment (Option 5)
