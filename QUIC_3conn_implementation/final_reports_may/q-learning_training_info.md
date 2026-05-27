# Q-Learning Training and Evaluation Guide

**Date:** May 12, 2026
**Purpose:** Instructions for training and evaluating the Q-learning agents

---

## Quick Reference Commands

```bash
# Build and run with Andy's agent for 5 minutes
docker compose build && ML_AGENT=andy SCENARIO=per_5 DURATION=300 docker compose up

# Build and run with Andy's agent for 10 minutes
docker compose build && ML_AGENT=andy SCENARIO=per_5 DURATION=600 docker compose up

# Run without rebuilding (if no code changes)
ML_AGENT=andy SCENARIO=per_5 DURATION=300 docker compose up
```

---

## 1. Training the Q-Learning Agent

### Run Longer Sessions

To properly fill the Q-table, run longer training sessions:

```bash
# 5 minutes (~150 Q-learning steps)
ML_AGENT=andy SCENARIO=per_5 DURATION=300 docker compose up

# 10 minutes (~300 Q-learning steps)
ML_AGENT=andy SCENARIO=per_5 DURATION=600 docker compose up

# 20 minutes (~600 Q-learning steps)
ML_AGENT=andy SCENARIO=per_5 DURATION=1200 docker compose up
```

**Note:** Q-learning decisions happen every 2 seconds (CONTROL_INTERVAL), so:
- 300 seconds = ~150 steps
- 600 seconds = ~300 steps
- 1200 seconds = ~600 steps

### Q-Table Persistence

The Q-table is saved to checkpoints and persists between runs:

- **Andy's agent:** `output/q_learning_checkpoint_andy.json`
- **Default agent:** `output/q_learning_checkpoint.json`

Each run continues learning from the previous checkpoint, so you can accumulate experience across multiple runs.

### Multi-Run Training Strategy

```bash
# Run 1: Initial training on per_5 (5% loss)
ML_AGENT=andy SCENARIO=per_5 DURATION=300 docker compose up

# Run 2: Continue training on per_5 (Q-table continues from Run 1)
ML_AGENT=andy SCENARIO=per_5 DURATION=300 docker compose up

# Run 3: Train on different scenario to test generalization
ML_AGENT=andy SCENARIO=per_10 DURATION=300 docker compose up

# Run 4: Train on low loss scenario
ML_AGENT=andy SCENARIO=per_1 DURATION=300 docker compose up
```

---

## 2. Training Progress Indicators

Monitor these values in the dashboard to track training progress:

| Indicator | Still Training | Ready to Evaluate |
|-----------|----------------|-------------------|
| **Steps** | < 500 | 500+ |
| **Exploration (ε)** | > 5% | 5% (minimum reached) |
| **Q-States** | < 50 | 50-100+ |
| **Avg Reward** | Fluctuating | Stable (0.5-0.7) |

### Epsilon Decay Schedule

The exploration rate decays from 30% to 5%:

| Steps | Approximate ε |
|-------|---------------|
| 0 | 30.0% |
| 50 | 22.2% |
| 100 | 16.4% |
| 150 | 12.2% |
| 200 | 9.0% |
| 250 | 6.7% |
| 300 | 5.0% (minimum) |

After ~300 steps, the agent is 95% exploiting its learned policy.

---

## 3. Evaluating the Trained Policy

### Option A: Observe at Low Exploration

Once exploration reaches 5%, the agent is mostly exploiting. Simply observe:
- Are the metrics (latency, throughput, jitter) stable?
- Is the Avg Reward consistently positive?
- Are the Q-learning actions making sensible parameter changes?

### Option B: Pure Exploitation Mode

To test with zero exploration (pure learned policy):

1. Temporarily edit `q_learning_agent_andy.py`:
```python
EPSILON_START = 0.0  # No exploration - pure exploitation
```

2. Run the simulation:
```bash
ML_AGENT=andy SCENARIO=per_5 DURATION=120 docker compose up
```

3. Observe if the agent consistently makes good decisions.

4. **Remember to revert** `EPSILON_START = 0.30` for future training.

### Option C: Compare With Baseline

Run with and without Q-learning to compare:

```bash
# WITH Q-learning (uses learned policy)
ML_AGENT=andy SCENARIO=per_5 DURATION=120 docker compose up
# Record final metrics: throughput, latency, jitter

# WITHOUT Q-learning (static parameters, no ML)
SCENARIO=per_5 DURATION=120 docker compose up
# Record final metrics: throughput, latency, jitter
```

Compare the results to see if Q-learning improved performance.

---

## 4. Output Files for Analysis

After each run, check the results directory for detailed analysis:

```
results/per_5/run_<timestamp>/
├── README.md              # Summary of the run
├── q_table.json           # Learned Q-values
├── qlearning_actions.json # Parameter changes made
├── qlearning_actions.csv  # Same, for spreadsheets
├── metrics.json           # Final metrics per connection
├── metrics_timeseries.csv # Metrics over time
├── rewards.csv            # Reward at each step
└── config.json            # Run configuration
```

### Key Files to Examine

1. **q_table.json** - Shows what the agent learned
   - States visited and their Q-values
   - Best action for each state

2. **qlearning_actions.json** - Shows what actions were taken
   - Which parameters were changed
   - Before/after metrics for each change

3. **rewards.csv** - Shows learning progress
   - Reward trend over time
   - Should generally increase or stabilize

---

## 5. Available Scenarios

### Static Scenarios (Fixed Network Conditions)

| Scenario | Description | Command |
|----------|-------------|---------|
| `per_1` | 1% packet error rate, 50 Mbps | `SCENARIO=per_1` |
| `per_5` | 5% packet error rate, 50 Mbps | `SCENARIO=per_5` |
| `per_10` | 10% packet error rate, 50 Mbps | `SCENARIO=per_10` |

### Dynamic Scenario (Time-Varying Network)

| Scenario | Description | Command |
|----------|-------------|---------|
| `varying` | 20 Mbps ±40%, 1% loss, changes every 6s | `SCENARIO=varying` |

**Varying Scenario Details:**
- **Capacity:** 20 Mbps average (ranges 12-28 Mbps)
- **Variation period:** 6 seconds
- **Loss rate:** 1% (constant)
- **Queue:** CoDel (5ms target)

**Why 6-second variation period?**

The Q-learning agent makes decisions every 2 seconds (CONTROL_INTERVAL). With a 6-second variation period, the agent gets **3 decisions per network state**:

```
Network State A (e.g., 12 Mbps low capacity)
├── t=0s: Agent observes condition → makes initial adjustment
├── t=2s: Agent sees result → fine-tunes if needed
├── t=4s: Agent confirms stability
└── t=6s: Network transitions to State B

Network State B (e.g., 28 Mbps high capacity)
├── t=6s: Agent observes new condition → adjusts
├── t=8s: Agent sees result → fine-tunes
...
```

This allows proper cause-effect learning - the agent can see the impact of its action before the network changes again.

### Training Across Scenarios

For a robust policy, train on multiple scenarios:

```bash
# Train on static scenarios first (builds foundation)
ML_AGENT=andy SCENARIO=per_1 DURATION=300 docker compose up
ML_AGENT=andy SCENARIO=per_5 DURATION=300 docker compose up
ML_AGENT=andy SCENARIO=per_10 DURATION=300 docker compose up

# Then train on varying scenario (teaches adaptation)
ML_AGENT=andy SCENARIO=varying DURATION=600 docker compose up
```

This helps the agent learn policies that work across different network conditions and adapt to changes.

---

## 6. Troubleshooting

### Q-Table Not Growing

If Q-States stays low:
- Check that `--with-ml` and `--ml-agent andy` are being passed
- Verify the checkpoint file exists and is being loaded
- Ensure metrics are being received from all 3 connections

### Avg Reward is 0 or Negative

If Avg Reward is consistently 0:
- Check `rewards.csv` to see if rewards are being logged
- Verify the agent is the correct one (Andy's vs default)

### No Parameter Changes Being Made

If no Q-learning actions appear:
- The agent may be selecting "no-op" frequently
- This can happen if current parameters are already good
- Or if exploration is too low to try new actions

---

## 7. Recommended Training Protocol

For a thorough training and evaluation:

```bash
# Step 1: Fresh build
docker compose build --no-cache

# Step 2: Initial training on medium loss (10 minutes)
ML_AGENT=andy SCENARIO=per_5 DURATION=600 docker compose up

# Step 3: Cross-scenario training on static scenarios
ML_AGENT=andy SCENARIO=per_1 DURATION=300 docker compose up
ML_AGENT=andy SCENARIO=per_10 DURATION=300 docker compose up

# Step 4: Dynamic scenario training (teaches adaptation)
ML_AGENT=andy SCENARIO=varying DURATION=600 docker compose up

# Step 5: Final evaluation on varying conditions
ML_AGENT=andy SCENARIO=varying DURATION=120 docker compose up
```

Total training time: ~30 minutes
Expected Q-States: 100-200+
Expected Avg Reward: 0.5-0.7

---

## 8. Understanding Q-Learning Decisions

The agent optimizes for three goals simultaneously:

| Connection | Goal | Metric Optimized |
|------------|------|------------------|
| Video Streaming | Low Latency | Minimize latency |
| File Transfer | High Throughput | Maximize throughput |
| Conference Call | Low Jitter | Minimize jitter variance |

The reward function balances:
1. **Mean utility** across all connections (performance)
2. **Fairness penalty** for imbalanced utilities
3. **Stability penalty** for frequent parameter changes

A well-trained agent should:
- Make parameter changes that improve the target metrics
- Avoid thrashing (constant changes)
- Find a balance across all three connection goals

---

## 9. Customizing the Varying Scenario

The varying scenario is defined in `wireless_bottleneck/scenarios.py` and can be customized:

```python
def rapidly_varying_capacity() -> WirelessScenario:
    return WirelessScenario(
        name="rapidly_varying_capacity",
        description="20 Mbps link with ±40% capacity variation every 6s",
        config=BottleneckConfig(
            capacity_bps=20_000_000,     # Average capacity (20 Mbps)
            variation_period=6.0,         # How often capacity changes
            variation_amplitude=0.4,      # ±40% variation range
            loss_rate=0.01,               # 1% packet loss
            # ... other settings
        )
    )
```

**Adjustable Parameters:**

| Parameter | Current | Effect |
|-----------|---------|--------|
| `capacity_bps` | 20 Mbps | Average link capacity |
| `variation_period` | 6.0s | Time between capacity changes |
| `variation_amplitude` | 0.4 | ±40% means range is 12-28 Mbps |
| `loss_rate` | 0.01 | Base packet loss rate (1%) |

**Guideline for variation_period:**

- Should be ≥ 3× the control interval (2s) for effective learning
- 6 seconds = 3 decisions per network state (recommended)
- Longer periods (8-10s) give more time to observe effects
- Shorter periods (4s) test faster adaptation but harder to learn
