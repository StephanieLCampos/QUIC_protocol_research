# Q-Learning for QUIC Parameter Optimization

## Executive Summary

This report explains how Q-learning is used to dynamically optimize QUIC congestion control parameters across three concurrent connections with different performance objectives.

**Key Points:**
- **Goal**: Automatically tune CUBIC parameters to maximize overall performance
- **State Space**: 1,728 discrete states based on network metrics and trends
- **Action Space**: 25 actions (parameter adjustments across 3 connections + no-op)
- **Reward Function**: Balances throughput, latency, jitter with fairness penalties

---

## Table of Contents

1. [Problem Overview](#1-problem-overview)
2. [Q-Learning Fundamentals](#2-q-learning-fundamentals)
3. [State Space Design](#3-state-space-design)
4. [Action Space Design](#4-action-space-design)
5. [Reward Function](#5-reward-function)
6. [Q-Learning Algorithm](#6-q-learning-algorithm)
7. [Hyperparameters](#7-hyperparameters)
8. [Integration with QUIC Simulation](#8-integration-with-quic-simulation)
9. [Output and Analysis](#9-output-and-analysis)

---

## 1. Problem Overview

### The Challenge

We have **3 concurrent QUIC connections** sharing a bottleneck link, each with different optimization goals:

| Connection | Application | Optimization Goal | Key Metric |
|------------|-------------|-------------------|------------|
| 1 | Video Streaming | Minimize latency | RTT |
| 2 | File Transfer | Maximize throughput | Bytes/second |
| 3 | Conference Call | Minimize jitter | RTT variance |

### Why Q-Learning?

Traditional congestion control (like CUBIC) uses fixed parameters. But optimal parameters depend on:
- Current network conditions (bandwidth, loss, delay)
- Traffic mix from other connections
- Application requirements

Q-learning allows the system to **learn** which parameter adjustments work best in different situations, without needing an explicit model of the network.

---

## 2. Q-Learning Fundamentals

### What is Q-Learning?

Q-learning is a **model-free reinforcement learning** algorithm that learns the value of actions in different states through trial and error.

```
Agent observes State → Takes Action → Receives Reward → Observes New State
                ↑                                              │
                └──────────── Learns from experience ──────────┘
```

### The Q-Table

The "Q" stands for "Quality." The Q-table stores the expected cumulative reward for taking each action in each state:

```
Q(state, action) = Expected future reward if we take this action in this state
```

### Learning Process

1. **Observe** current state (network metrics)
2. **Choose** action (ε-greedy: explore randomly or exploit best known)
3. **Execute** action (adjust a parameter)
4. **Receive** reward (based on resulting metrics)
5. **Update** Q-value using Bellman equation
6. **Repeat**

---

## 3. State Space Design

### State Representation

The state is a **6-tuple** encoding the current network conditions:

```python
state = (latency_bin, throughput_bin, jitter_bin,
         latency_trend, throughput_trend, jitter_trend)
```

### Metric Bins (Current Values)

Each metric is discretized into 4 bins (0-3):

#### Latency Bins (lower is better, so bin 0 = excellent)

| Bin | Latency Range | Quality |
|-----|---------------|---------|
| 0 | < 10 ms | Excellent |
| 1 | 10 - 25 ms | Good |
| 2 | 25 - 50 ms | Fair |
| 3 | > 50 ms | Poor |

#### Throughput Bins (higher is better, so bin 3 = excellent)

| Bin | Throughput Range | Quality |
|-----|------------------|---------|
| 0 | < 1 MB/s | Poor |
| 1 | 1 - 2 MB/s | Fair |
| 2 | 2 - 3 MB/s | Good |
| 3 | > 3 MB/s | Excellent |

#### Jitter Bins (lower is better, so bin 0 = excellent)

| Bin | Jitter Range | Quality |
|-----|--------------|---------|
| 0 | < 5 ms | Excellent |
| 1 | 5 - 15 ms | Good |
| 2 | 15 - 30 ms | Fair |
| 3 | > 30 ms | Poor |

### Trend Bins (Rate of Change)

Each metric also has a trend indicator (0-2):

| Trend | Meaning | Detection |
|-------|---------|-----------|
| 0 | Worsening | Changed by > 5% in bad direction |
| 1 | Stable | Within ± 5% of previous |
| 2 | Improving | Changed by > 5% in good direction |

### Total State Space Size

```
4 bins × 4 bins × 4 bins × 3 trends × 3 trends × 3 trends = 1,728 states
```

### Example States

```python
# State: (lat_bin, tp_bin, jit_bin, lat_trend, tp_trend, jit_trend)

(0, 3, 0, 1, 1, 1)  # Excellent metrics, all stable
(2, 1, 2, 0, 0, 0)  # Fair metrics, all worsening → agent should act!
(1, 2, 1, 2, 2, 2)  # Good metrics, all improving → maybe do nothing
```

### Why This Design?

1. **Discretization**: Continuous metrics → discrete bins reduces state space from infinite to 1,728
2. **Trends**: Knowing if metrics are improving/worsening helps predict future
3. **Per-Goal Metrics**: Latency for video, throughput for file, jitter for conference

---

## 4. Action Space Design

### Action Encoding

There are **25 possible actions**:

```
Actions 0-23: Change one parameter on one connection by one step
Action 24:    No-op (do nothing)
```

### Action Structure

Each action (except no-op) is encoded as:

```
action = connection_index × 8 + parameter_index × 2 + direction

Where:
- connection_index: 0, 1, 2 (video, file, conference)
- parameter_index: 0, 1, 2, 3 (the 4 tunable parameters)
- direction: 0 = increase, 1 = decrease
```

### Tunable Parameters

| Parameter | Step Size | Range | Effect on CUBIC |
|-----------|-----------|-------|-----------------|
| `loss_reduction_factor` | 0.1 | 0.3 - 0.7 | How much to reduce cwnd on loss |
| `cubic_c` | 0.1 | 0.2 - 0.4 | Aggressiveness of window growth |
| `minimum_window` | 1 | 2 - 4 | Floor for congestion window |
| `packet_threshold` | 1 | 3 - 4 | Packets before declaring loss |

### Action Examples

| Action # | Decoded | Meaning |
|----------|---------|---------|
| 0 | video.loss_reduction_factor.increase | Increase video's loss reduction |
| 1 | video.loss_reduction_factor.decrease | Decrease video's loss reduction |
| 4 | video.minimum_window.increase | Increase video's min window |
| 8 | file.loss_reduction_factor.increase | Increase file transfer's loss reduction |
| 16 | conf.loss_reduction_factor.increase | Increase conference's loss reduction |
| 24 | no-op | Do nothing this step |

### Why Include No-Op?

The no-op action is critical because:
1. Sometimes the current parameters are already optimal
2. Changing parameters has a "stability penalty" in the reward
3. Prevents unnecessary thrashing when metrics are good

---

## 5. Reward Function

### Reward Formula

```python
R = mean(U_video, U_file, U_conf) - λ × std(U_video, U_file, U_conf) - μ × changed
```

Where:
- **Mean utility**: Average performance across all 3 connections
- **λ × std**: Fairness penalty (penalizes imbalance between connections)
- **μ × changed**: Stability penalty (penalizes unnecessary changes)

### Utility Functions

Each connection has a utility function mapping its key metric to [0, 1]:

#### Video Streaming (Latency Utility)

```python
U_video = (latency_worst - latency) / (latency_worst - latency_best)

Where:
- latency_best = 20 ms
- latency_worst = 200 ms
```

| Latency | Utility |
|---------|---------|
| 20 ms | 1.0 (perfect) |
| 110 ms | 0.5 |
| 200 ms | 0.0 (terrible) |

#### File Transfer (Throughput Utility)

```python
U_file = throughput / throughput_max

Where:
- throughput_max = 3.75 MB/s (30 Mbps)
```

| Throughput | Utility |
|------------|---------|
| 3.75 MB/s | 1.0 (perfect) |
| 1.875 MB/s | 0.5 |
| 0 MB/s | 0.0 (terrible) |

#### Conference Call (Jitter Utility)

```python
U_conf = (jitter_worst - jitter) / jitter_worst

Where:
- jitter_worst = 50 ms
```

| Jitter | Utility |
|--------|---------|
| 0 ms | 1.0 (perfect) |
| 25 ms | 0.5 |
| 50 ms | 0.0 (terrible) |

### Penalty Weights

| Parameter | Value | Purpose |
|-----------|-------|---------|
| λ (lambda) | 0.10 | Fairness penalty - discourages optimizing one connection at others' expense |
| μ (mu) | 0.05 | Stability penalty - discourages constant parameter changes |

### Reward Examples

**Example 1: Good, balanced performance**
```
U_video = 0.8, U_file = 0.7, U_conf = 0.75
mean = 0.75
std = 0.05
changed = False

R = 0.75 - 0.10 × 0.05 - 0.0 = 0.745
```

**Example 2: Unbalanced performance**
```
U_video = 0.9, U_file = 0.3, U_conf = 0.8
mean = 0.67
std = 0.32
changed = True

R = 0.67 - 0.10 × 0.32 - 0.05 = 0.588
```

The fairness penalty reduces the reward even though mean is decent.

---

## 6. Q-Learning Algorithm

### Bellman Update Equation

After each action, the Q-value is updated:

```python
Q(s, a) ← Q(s, a) + α × [r + γ × max_a' Q(s', a') - Q(s, a)]
```

Where:
- `s` = current state
- `a` = action taken
- `r` = reward received
- `s'` = next state
- `α` = learning rate (how much to update)
- `γ` = discount factor (importance of future rewards)

### ε-Greedy Action Selection

```python
if random() < ε:
    action = random_action()      # Explore
else:
    action = argmax(Q[state])     # Exploit best known
```

**Exploration vs. Exploitation:**
- **Explore**: Try random actions to discover new strategies
- **Exploit**: Use the best known action based on Q-table

### Epsilon Decay

Exploration rate decreases over time:

```python
ε = max(ε_min, ε × ε_decay)

Starting: ε = 0.30 (30% exploration)
Minimum:  ε = 0.05 (5% exploration)
Decay:    ε_decay = 0.995 (per step)
```

After ~460 steps, ε reaches minimum (0.05).

### Algorithm Pseudocode

```python
Initialize Q(s, a) = 0 for all states and actions
ε = 0.30

for each time step:
    # 1. Observe state
    state = discretize(latency, throughput, jitter, trends)

    # 2. Choose action (ε-greedy)
    if random() < ε:
        action = random(0, 24)
    else:
        action = argmax(Q[state])

    # 3. Execute action
    apply_parameter_change(action)

    # 4. Wait for effect (2 seconds)
    wait(control_interval)

    # 5. Observe new state and reward
    new_state = discretize(new_metrics)
    reward = calculate_reward(new_metrics)

    # 6. Update Q-value
    Q[state][action] += α × (reward + γ × max(Q[new_state]) - Q[state][action])

    # 7. Decay exploration
    ε = max(ε_min, ε × ε_decay)

    state = new_state
```

---

## 7. Hyperparameters

### Learning Parameters

| Parameter | Symbol | Value | Purpose |
|-----------|--------|-------|---------|
| Learning Rate | α | 0.10 | How quickly to update Q-values |
| Discount Factor | γ | 0.90 | Importance of future rewards (0=myopic, 1=far-sighted) |
| Initial Exploration | ε₀ | 0.30 | Starting exploration probability |
| Minimum Exploration | ε_min | 0.05 | Floor for exploration |
| Exploration Decay | ε_decay | 0.995 | Multiplicative decay per step |

### Timing Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Control Interval | 2.0 s | Time between Q-learning decisions |
| Settling Time | 1.5 s | Wait after parameter change before measuring |
| Metrics Interval | 0.1 s | How often metrics are sampled |

### Why These Values?

**α = 0.10**: Moderate learning rate balances learning speed with stability. Too high causes oscillation, too low learns too slowly.

**γ = 0.90**: High discount factor means the agent cares about long-term performance, not just immediate reward.

**ε = 0.30 → 0.05**: Start with significant exploration (30%), decay to mostly exploitation (5%) but never stop exploring entirely.

**Control Interval = 2.0s**: CUBIC needs time to respond to parameter changes. Acting faster would measure effects of previous changes.

---

## 8. Integration with QUIC Simulation

### Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         Every 0.1 seconds                        │
│                                                                  │
│   Worker 1 ──┐                                                   │
│   Worker 2 ──┼──► Metrics Queue ──► ML Controller ──► Q-Agent   │
│   Worker 3 ──┘                              │              │     │
│                                             │              │     │
│                                             ▼              │     │
│                                       (every 2s)           │     │
│                                             │              │     │
│                                             ▼              ▼     │
│   Worker 1 ◄──┐                      Parameter         Q-Table  │
│   Worker 2 ◄──┼── Command Pipes ◄── Update             Update   │
│   Worker 3 ◄──┘                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | File | Responsibility |
|-----------|------|----------------|
| Q-Learning Agent | `ml_callbacks/q_learning_agent.py` | State encoding, action selection, Q-updates |
| ML Controller | `simulation/ml_controller.py` | Calls agent, sends parameter updates, tracks history |
| Process Orchestrator | `simulation/process_orchestrator.py` | Creates ML controller, manages workers |
| Worker Process | `simulation/worker_process.py` | Applies parameters to QUIC connection |

### Timing Diagram

```
Time:  0.0   0.1   0.2   ...   2.0   2.1   2.2   ...   4.0
       │     │     │           │     │     │           │
       ▼     ▼     ▼           ▼     ▼     ▼           ▼
      [M]   [M]   [M]   ...   [M]   [M]   [M]   ...   [M]   ← Metrics collected
                              [A]                     [A]   ← Q-learning acts
                              [U]                     [U]   ← Q-table updated

M = Metrics sampled
A = Action taken (parameter changed)
U = Q-value updated based on reward
```

### Parameter Application

When the agent decides to change a parameter:

1. **Agent returns**: `{connection_id: {param_name: new_value}}`
2. **ML Controller**: Sends IPC message to worker
3. **Worker Process**: Updates its local config
4. **QUIC Connection**: Uses new parameter on next congestion event

```python
# Example: Agent decides to increase file transfer's cubic_c
decisions = {2: {"cubic_c": 0.5}}  # Connection 2, cubic_c = 0.5

# Sent to worker via IPC pipe
msg = IPCMessage(
    msg_type=MessageType.UPDATE_PARAM,
    connection_id=2,
    payload={"param_name": "cubic_c", "value": 0.5}
)
```

---

## 9. Output and Analysis

### Q-Table Export (q_table.json)

The learned policy is saved with human-readable state descriptions:

```json
{
  "total_states": 127,
  "q_table": {
    "(1, 2, 1, 1, 2, 1)": {
      "state_readable": {
        "latency_bin": "10-25ms",
        "throughput_bin": "2-3MB/s",
        "jitter_bin": "5-15ms",
        "latency_trend": "stable",
        "throughput_trend": "improving",
        "jitter_trend": "stable"
      },
      "q_values": [0.12, -0.05, 0.23, ...],
      "best_action": "file.cubic_c.increase",
      "best_q_value": 0.45
    }
  }
}
```

### Rewards History (rewards.csv)

Track learning progress over time:

```csv
step,timestamp,reward,epsilon,action,state,next_state
1,2.0,0.342,0.300,video.cubic_c.increase,"(0,2,1,1,2,1)","(0,2,1,1,2,1)"
2,4.0,0.289,0.299,file.loss_reduction.decrease,"(0,2,1,1,2,1)","(1,2,1,0,2,1)"
3,6.0,0.401,0.297,no-op,"(1,2,1,0,2,1)","(1,3,1,2,2,1)"
```

### Interpreting Results

**Signs of Good Learning:**
- Rewards increase over time (or at least stabilize high)
- ε decreases toward minimum
- Fewer states visited = agent found good states and stays there
- More no-op actions = parameters are well-tuned

**Signs of Problems:**
- Rewards decrease or highly variable
- Agent never stops exploring
- Same bad states visited repeatedly
- All actions are changes (never no-op)

### Visualization Ideas

1. **Reward over time**: Plot rewards.csv to see learning curve
2. **State visitation heatmap**: Which states does agent spend time in?
3. **Action distribution**: Pie chart of which actions were taken
4. **Metrics timeline**: Compare metrics_timeseries.csv before/after learning

---

## Appendix A: Code References

| Concept | File | Line Numbers |
|---------|------|--------------|
| State binning | `q_learning_agent.py` | 98-106 |
| State building | `q_learning_agent.py` | 346-370 |
| Action decoding | `q_learning_agent.py` | 244-255 |
| Reward calculation | `q_learning_agent.py` | 374-401 |
| Bellman update | `q_learning_agent.py` | 338-342 |
| Main callback | `q_learning_agent.py` | 439-493 |
| ML Controller | `ml_controller.py` | 61-96 |

---

## Appendix B: Quick Reference Card

```
┌────────────────────────────────────────────────────────────────┐
│                    Q-LEARNING QUICK REFERENCE                   │
├────────────────────────────────────────────────────────────────┤
│ STATE: (lat_bin, tp_bin, jit_bin, lat_trend, tp_trend, jit_trend) │
│        4 × 4 × 4 × 3 × 3 × 3 = 1,728 states                    │
├────────────────────────────────────────────────────────────────┤
│ ACTIONS: 25 total                                               │
│   • 24 parameter changes (3 conn × 4 params × 2 directions)    │
│   • 1 no-op                                                     │
├────────────────────────────────────────────────────────────────┤
│ REWARD: mean(utilities) - 0.10×std - 0.05×changed              │
├────────────────────────────────────────────────────────────────┤
│ UPDATE: Q(s,a) += 0.10 × [r + 0.90 × max Q(s') - Q(s,a)]      │
├────────────────────────────────────────────────────────────────┤
│ EXPLORATION: 30% → 5% (decay 0.995/step)                       │
├────────────────────────────────────────────────────────────────┤
│ TIMING: Decide every 2s, metrics every 0.1s                    │
└────────────────────────────────────────────────────────────────┘
```
