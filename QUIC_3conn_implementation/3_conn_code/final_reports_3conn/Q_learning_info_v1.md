# Q-Learning Implementation for QUIC Parameter Optimization

This document explains how Q-learning is implemented in this codebase to dynamically tune QUIC congestion control parameters across three simultaneous connections.

---

## Table of Contents

1. [What is Q-Learning?](#what-is-q-learning)
2. [The Problem We're Solving](#the-problem-were-solving)
3. [The Three Connections](#the-three-connections)
4. [States: How the Agent Sees the World](#states-how-the-agent-sees-the-world)
5. [Actions: What the Agent Can Do](#actions-what-the-agent-can-do)
6. [Rewards: How the Agent Learns What's Good](#rewards-how-the-agent-learns-whats-good)
7. [The Q-Table: The Agent's Memory](#the-q-table-the-agents-memory)
8. [Hyperparameters](#hyperparameters)
9. [The Learning Loop](#the-learning-loop)
10. [Checkpoint Persistence](#checkpoint-persistence)

---

## What is Q-Learning?

Q-learning is a type of **reinforcement learning** where an agent learns to make decisions by trial and error. Think of it like training a dog:

- The agent (dog) observes a **state** (sees a ball)
- The agent takes an **action** (fetches the ball)
- The agent receives a **reward** (gets a treat) or penalty (gets ignored)
- Over time, the agent learns which actions lead to rewards in which situations

The "Q" in Q-learning refers to the **Q-value**, which represents "how good" an action is in a given state. The agent maintains a **Q-table** that maps every (state, action) pair to a Q-value. Higher Q-values mean better expected outcomes.

**Key insight**: The agent doesn't need to know *how* the system works internally. It just tries actions, observes results, and learns from experience.

---

## The Problem We're Solving

We have three QUIC connections running simultaneously, each with different performance goals:

| Connection | Application Type | Performance Goal |
|------------|------------------|------------------|
| 1 | Video Streaming | Minimize **latency** (fast response) |
| 2 | File Transfer | Maximize **throughput** (fast downloads) |
| 3 | Conference Call | Minimize **jitter** (smooth audio/video) |

Each connection has tunable congestion control parameters that affect its performance. The challenge is: **how do we tune these parameters dynamically to optimize each connection's goal while sharing limited network bandwidth fairly?**

This is where Q-learning comes in. The agent observes network conditions and learns which parameter adjustments improve performance.

---

## The Three Connections

### Connection 1: Video Streaming
- **Goal**: Low latency (fast response time)
- **Why it matters**: Video needs quick frame delivery to avoid buffering
- **Priority metric**: Latency (one-way delay)

### Connection 2: File Transfer
- **Goal**: High throughput (maximum data transfer rate)
- **Why it matters**: Large files should download as fast as possible
- **Priority metric**: Throughput (bytes per second)

### Connection 3: Conference Call
- **Goal**: Low jitter (consistent timing)
- **Why it matters**: Audio/video calls need steady packet timing to avoid choppy playback
- **Priority metric**: Jitter (variation in packet delay)

---

## States: How the Agent Sees the World

The agent observes network conditions and converts them into a **discrete state**. The state is a 7-tuple:

```
state = (latency_bin, throughput_bin, jitter_bin, latency_trend, throughput_trend, jitter_trend, loss_bin)
```

### Important: Which Metrics Come From Which Connection

The state is built from **specific connections**, not aggregated across all three:

| Metric | Source Connection | Reason |
|--------|-------------------|--------|
| Latency | Connection 1 (Video Streaming) | Video's priority is low latency |
| Throughput | Connection 2 (File Transfer) | File transfer's priority is high throughput |
| Jitter | Connection 3 (Conference Call) | Conference call's priority is low jitter |
| Packet Loss | Average across all 3 connections | Network condition context |

This means each metric in the state represents the performance of the connection that cares most about it. The packet loss rate is averaged across all connections to provide network condition context.

**Note on Throughput**: The agent uses "delta" throughput (bytes acknowledged in the current measurement window) rather than cumulative average. This makes the agent more responsive to changing network conditions.

### Metric Bins (Current Performance)

Each metric is categorized into 4 bins (0-3):

#### Latency Bins (lower is better)
| Bin | Range | Meaning |
|-----|-------|---------|
| 0 | < 10ms | Excellent |
| 1 | 10-25ms | Good |
| 2 | 25-50ms | Fair |
| 3 | > 50ms | Poor |

#### Throughput Bins (higher is better)
| Bin | Range | Meaning |
|-----|-------|---------|
| 0 | < 1 MB/s | Poor |
| 1 | 1-2 MB/s | Fair |
| 2 | 2-3 MB/s | Good |
| 3 | > 3 MB/s | Excellent |

#### Jitter Bins (lower is better)
| Bin | Range | Meaning |
|-----|-------|---------|
| 0 | < 5ms | Excellent |
| 1 | 5-15ms | Good |
| 2 | 15-30ms | Fair |
| 3 | > 30ms | Poor |

#### Packet Loss Bins (lower is better)
| Bin | Range | Meaning |
|-----|-------|---------|
| 0 | < 1% | Excellent |
| 1 | 1-5% | Good |
| 2 | 5-10% | Fair |
| 3 | > 10% | Poor |

### Trend Indicators (Direction of Change)

Each metric also has a trend indicator showing whether it's improving or worsening:

| Trend | Value | Meaning |
|-------|-------|---------|
| 0 | Worsening | Metric getting worse (>5% change in bad direction) |
| 1 | Stable | Metric roughly unchanged (within 5%) |
| 2 | Improving | Metric getting better (>5% change in good direction) |

### Total State Space

- 4 bins × 4 bins × 4 bins × 4 bins = 256 metric combinations (latency, throughput, jitter, loss)
- 3 trends × 3 trends × 3 trends = 27 trend combinations
- **Total: 256 × 27 = 6,912 possible states**

### Example State

```
state = (1, 3, 0, 1, 0, 2, 1)
```

This means:
- Latency bin 1: 10-25ms (good)
- Throughput bin 3: >3 MB/s (excellent)
- Jitter bin 0: <5ms (excellent)
- Latency trend 1: stable
- Throughput trend 0: worsening
- Jitter trend 2: improving
- Loss bin 1: 1-5% packet loss (good network conditions)

---

## Actions: What the Agent Can Do

The agent can adjust **4 tunable parameters** on any of the **3 connections**, in **2 directions** (increase or decrease). Plus one "do nothing" action.

### Tunable Parameters

| Parameter | Description | Range | Step |
|-----------|-------------|-------|------|
| `loss_reduction_factor` | How aggressively to reduce sending rate after packet loss | 0.3 - 0.7 | 0.1 |
| `cubic_c` | CUBIC algorithm aggressiveness constant | 0.2 - 0.5 | 0.1 |
| `minimum_window` | Minimum congestion window size (packets) | 2 - 6 | 1 |
| `packet_threshold` | Number of duplicate ACKs before assuming loss | 2 - 4 | 1 |

### Initial Parameter Values (Per Connection)

Each connection starts with different default values optimized for its use case:

| Parameter | Video (Conn 1) | File (Conn 2) | Conference (Conn 3) |
|-----------|----------------|---------------|---------------------|
| `loss_reduction_factor` | 0.6 | 0.7 | 0.5 |
| `cubic_c` | 0.4 | 0.5 | 0.3 |
| `minimum_window` | 4 | 2 | 6 |
| `packet_threshold` | 2 | 2 | 2 |

### Action Encoding

Actions are numbered 0-24:

```
action = connection_index × 8 + parameter_index × 2 + direction
```

Where:
- `connection_index`: 0 (video), 1 (file), 2 (conference)
- `parameter_index`: 0-3 (which parameter)
- `direction`: 0 (increase), 1 (decrease)
- Action 24 = **no-op** (do nothing)

### Total Actions: 25

- 3 connections × 4 parameters × 2 directions = 24 parameter changes
- 1 no-op action
- **Total: 25 actions**

### Example Actions

| Action # | Meaning |
|----------|---------|
| 0 | Video: increase loss_reduction_factor |
| 1 | Video: decrease loss_reduction_factor |
| 2 | Video: increase cubic_c |
| 8 | File: increase loss_reduction_factor |
| 16 | Conference: increase loss_reduction_factor |
| 24 | Do nothing |

---

## Rewards: How the Agent Learns What's Good

The reward function tells the agent how well it's doing. A higher reward means better performance.

### Reward Formula

```
R = mean(U_video, U_file, U_conf) - λ × std(U_video, U_file, U_conf) - μ × changed
```

Where:
- **Mean utility**: Average satisfaction across all three connections (0 to 1)
- **Fairness penalty (λ)**: Penalizes imbalance between connections
- **Stability penalty (μ)**: Penalizes unnecessary parameter changes

### Individual Utility Functions

Each connection has its own utility function, normalized to 0-1 where 1 is best:

#### Video Streaming Utility (Latency-based)
```
U_video = (latency_worst - latency) / (latency_worst - latency_best)
```
- `latency_best` = 20ms (floor)
- `latency_worst` = 200ms (ceiling)
- Lower latency → higher utility

#### File Transfer Utility (Throughput-based)
```
U_file = throughput / throughput_max
```
- `throughput_max` = 3.75 MB/s (30 Mbps)
- Higher throughput → higher utility
- **Note**: Uses "delta" throughput (per-epoch measurement) for responsiveness to changes, not cumulative average

#### Conference Call Utility (Jitter-based)
```
U_conf = (jitter_worst - jitter) / jitter_worst
```
- `jitter_worst` = 50ms
- Lower jitter → higher utility

### Penalty Weights

| Penalty | Symbol | Value | Purpose |
|---------|--------|-------|---------|
| Fairness | λ | 0.10 | Prevents one connection from dominating |
| Stability | μ | 0.05 | Discourages excessive parameter changes |

### Example Reward Calculation

Suppose:
- Latency = 30ms → U_video = (200-30)/(200-20) = 0.944
- Throughput = 2 MB/s → U_file = 2/3.75 = 0.533
- Jitter = 10ms → U_conf = (50-10)/50 = 0.800

Mean utility = (0.944 + 0.533 + 0.800) / 3 = 0.759

Standard deviation ≈ 0.168

If a parameter was changed:
```
R = 0.759 - 0.10 × 0.168 - 0.05 = 0.759 - 0.017 - 0.05 = 0.692
```

---

## The Q-Table: The Agent's Memory

The Q-table stores learned values for every (state, action) pair.

### Structure

```python
Q-table = {
    (1, 3, 0, 1, 0, 2): [0.45, 0.32, 0.51, ..., 0.12],  # 25 values, one per action
    (2, 2, 1, 1, 1, 1): [0.38, 0.41, 0.29, ..., 0.55],
    ...
}
```

### Q-Value Update (Bellman Equation)

When the agent takes action `a` in state `s`, observes reward `r`, and ends up in state `s'`:

```
Q(s, a) ← Q(s, a) + α × [r + γ × max Q(s', a') - Q(s, a)]
```

Where:
- **α (alpha)**: Learning rate - how much to update (0.1)
- **γ (gamma)**: Discount factor - how much to value future rewards (0.9)
- **max Q(s', a')**: Best possible Q-value from the next state

### Intuition

- If the reward was better than expected, increase Q(s, a)
- If the reward was worse than expected, decrease Q(s, a)
- The discount factor (0.9) means future rewards are almost as important as immediate rewards

---

## Hyperparameters

| Parameter | Symbol | Value | Description |
|-----------|--------|-------|-------------|
| Learning rate | α | 0.10 | How fast to update Q-values |
| Discount factor | γ | 0.90 | How much to value future vs. immediate rewards |
| Initial exploration | ε₀ | 0.30 | Starting probability of random action (30%) |
| Minimum exploration | ε_min | 0.05 | Floor for exploration (5%) |
| Exploration decay | - | 0.995 | Multiply ε by this each step |
| Control interval | - | 2.0s | Time between decisions |

### Exploration vs. Exploitation (ε-greedy)

The agent uses **ε-greedy** action selection:

- With probability **ε**: Choose a **random** action (explore)
- With probability **1-ε**: Choose the **best known** action (exploit)

As training progresses, ε decays from 30% to 5%, so the agent explores less and exploits more.

```
ε_new = max(0.05, ε_old × 0.995)
```

---

## The Learning Loop

Every **2 seconds**, the agent:

1. **Observes** current metrics from all 3 connections
2. **Builds state** by binning metrics and computing trends
3. **Updates Q-table** based on previous action's results
4. **Selects action** using ε-greedy policy
5. **Applies action** (sends parameter change to worker process)
6. **Decays ε** slightly
7. **Saves checkpoint** every 50 steps

### Why 2 Seconds?

QUIC's CUBIC congestion control needs time to react to parameter changes. The 2-second interval gives the network time to stabilize before measuring results.

### Timing Flow

```
t=0s:  Agent observes state S1, takes action A1
t=2s:  Agent observes state S2, computes reward for A1, updates Q(S1, A1), takes action A2
t=4s:  Agent observes state S3, computes reward for A2, updates Q(S2, A2), takes action A3
...
```

---

## Checkpoint Persistence

The Q-table and training state are saved to:
```
results/q_learning_checkpoint.json
```

### What's Saved

- Complete Q-table (all learned state-action values)
- Current epsilon (exploration rate)
- Step count

### Benefits

- **Continuous learning**: Knowledge accumulates across runs
- **Resume training**: Can stop and restart without losing progress
- **Faster convergence**: Pre-trained agent performs better immediately

### When to Reset

Delete the checkpoint file to start fresh when:
- You change the state space or action space
- You modify the reward function
- You want to benchmark from-scratch learning

```bash
rm -f results/q_learning_checkpoint.json
```

---

## Summary

| Component | Details |
|-----------|---------|
| **Algorithm** | Tabular Q-learning with ε-greedy exploration |
| **State space** | 6,912 states (7-tuple: 4 metric bins + 3 trends + loss bin) |
| **Action space** | 25 actions (parameter changes + no-op) |
| **Reward** | Mean utility - fairness penalty - stability penalty |
| **Update rule** | Bellman equation with α=0.1, γ=0.9 |
| **Exploration** | ε-greedy, decaying from 30% to 5% |
| **Decision interval** | Every 2 seconds |
| **Persistence** | Checkpoint saved every 50 steps |

The agent learns to balance three competing objectives (low latency, high throughput, low jitter) by adjusting QUIC congestion control parameters in real-time based on observed network conditions. The loss_bin provides network condition context, allowing the agent to learn different policies for different packet loss environments.
