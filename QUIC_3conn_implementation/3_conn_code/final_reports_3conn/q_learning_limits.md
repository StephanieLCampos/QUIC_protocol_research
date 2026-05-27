# Q-Learning Limitations and Missing Interactions

This document describes the limitations of the current Q-learning implementation and interactions that are not captured in the state representation.

---

## Overview

The Q-learning agent uses the same metrics for both **states** and **rewards**:

| Component | Uses Metrics For |
|-----------|------------------|
| **State** | "What's happening?" (binned into categories) |
| **Reward** | "How good is this?" (continuous utility score) |

This is intentional, but the simplified state representation means some interactions are not directly visible to the agent.

---

## What the State Captures

```
state = (latency_bin, throughput_bin, jitter_bin, latency_trend, throughput_trend, jitter_trend)
              ↑              ↑             ↑
         Conn 1 only    Conn 2 only   Conn 3 only
```

The state only includes:
- **Latency** from Connection 1 (Video Streaming)
- **Throughput** from Connection 2 (File Transfer)
- **Jitter** from Connection 3 (Conference Call)
- **Trends** for each of these three metrics

---

## What the State Misses

### 1. Cross-Connection Effects

**Scenario:** Agent increases `cubic_c` on File (Conn 2) to boost throughput.

| What Happens | State Sees | State Misses |
|--------------|------------|--------------|
| File throughput increases | Yes | |
| Video latency increases (competing for bandwidth) | No | Hidden |
| Conference jitter spikes | No | Hidden |

The agent only learns this was bad **after** the reward penalizes it—but it doesn't understand **why**.

**Impact:** The agent cannot anticipate side effects on other connections. It must learn through trial and error that certain actions hurt overall performance.

---

### 2. Other Connections' Metrics

Each metric only comes from one connection. The agent is blind to the same metric on other connections.

**Example:** Video (Conn 1) has terrible throughput, but the state doesn't include it.

```
Conn 1: latency=15ms, throughput=0.1 MB/s (struggling!)
Conn 2: latency=50ms, throughput=3 MB/s
Conn 3: latency=30ms, jitter=8ms

State = (1, 3, 1, ...)
         ↑  ↑  ↑
         │  │  └── Conn 3 jitter only
         │  └───── Conn 2 throughput only
         └──────── Conn 1 latency only (throughput ignored!)
```

**Impact:** The agent has no idea Connection 1's throughput is terrible. It cannot directly respond to this situation.

---

### 3. Parameter Values Themselves

The state doesn't include **current parameter values**.

```
Two situations with identical states:

Situation A:
- cubic_c = 0.2 (at minimum)
- State = (1, 3, 0, 1, 1, 1)
- Action "increase cubic_c" will work

Situation B:
- cubic_c = 0.5 (at maximum)
- State = (1, 3, 0, 1, 1, 1)
- Action "increase cubic_c" will do nothing (already at max)
```

**Impact:** The agent sees these as the **same state** but the same action has different effects. It must learn boundary conditions indirectly.

---

### 4. Network Conditions

The state doesn't directly capture underlying network conditions:

| Not Captured | Why It Matters |
|--------------|----------------|
| Packet loss rate | High loss requires different parameter tuning |
| Buffer sizes | Affects latency and jitter behavior |
| Congestion level | Determines how aggressive parameters should be |
| Available bandwidth | Sets upper bound on achievable throughput |
| RTT variance | Affects jitter calculations |

The agent only sees the **effects** (latency, throughput, jitter), not the **causes**.

**Impact:** The agent cannot distinguish between different root causes that produce similar metrics.

---

### 5. Discretization Loses Granularity

Metrics are binned into 4 categories, losing precision:

```
Latency 11ms → Bin 1 (10-25ms)
Latency 24ms → Bin 1 (10-25ms)

Same bin, but 24ms is more than twice as slow!
```

| Metric | Bin Boundaries |
|--------|----------------|
| Latency | 10ms, 25ms, 50ms |
| Throughput | 1 MB/s, 2 MB/s, 3 MB/s |
| Jitter | 5ms, 15ms, 30ms |

**Impact:** The agent treats all values within a bin as identical, even when differences are significant.

---

## Visual Comparison

### Reality (Full Picture)

```
┌─────────────────────────────────────────────────────────────┐
│ Connection 1 (Video):                                       │
│   latency=15ms, throughput=2MB/s, jitter=3ms, loss=1%       │
│   params: lrf=0.6, cubic_c=0.4, min_win=4, pkt_thresh=2     │
│                                                             │
│ Connection 2 (File):                                        │
│   latency=40ms, throughput=3MB/s, jitter=5ms, loss=0.5%     │
│   params: lrf=0.7, cubic_c=0.5, min_win=2, pkt_thresh=2     │
│                                                             │
│ Connection 3 (Conference):                                  │
│   latency=25ms, throughput=1MB/s, jitter=12ms, loss=2%      │
│   params: lrf=0.5, cubic_c=0.3, min_win=6, pkt_thresh=2     │
│                                                             │
│ Network: 70% utilized, buffer 80% full, 5Mbps bottleneck    │
└─────────────────────────────────────────────────────────────┘
```

### What Agent Sees (Simplified)

```
┌─────────────────────────────────────────────────────────────┐
│ state = (1, 3, 1, 1, 1, 2)                                  │
│                                                             │
│ Translation:                                                │
│   - Latency bin 1: "10-25ms" (good)                         │
│   - Throughput bin 3: ">3 MB/s" (excellent)                 │
│   - Jitter bin 1: "5-15ms" (good)                           │
│   - Latency trend: stable                                   │
│   - Throughput trend: stable                                │
│   - Jitter trend: improving                                 │
└─────────────────────────────────────────────────────────────┘
```

The agent makes decisions with **limited information**.

---

## Consequences of Limited State

1. **Slower Learning:** Agent must try many actions to discover cause-and-effect relationships that aren't visible in the state.

2. **Suboptimal Decisions:** Without seeing full picture, agent may take actions that look good for one metric but hurt others.

3. **State Aliasing:** Different real-world situations map to the same state, so the agent learns an "average" policy that may not be optimal for any specific situation.

4. **Inability to Anticipate:** Agent cannot predict side effects; it only learns them after receiving negative rewards.

---

## Potential Improvements

| Approach | Benefit | Tradeoff |
|----------|---------|----------|
| Add more metrics to state | Agent sees fuller picture | Larger state space, slower learning |
| Use finer bins | More granular states | More states to explore |
| Include all connections' metrics | See cross-connection effects | 3x more state dimensions |
| Add parameter values to state | Know current settings | Much larger state space |
| Use function approximation (neural network) | Handle continuous states | More complex, less interpretable |
| Include network condition indicators | Understand root causes | May not be directly observable |

---

## Summary

The current Q-learning implementation uses a **simplified state representation** that:

- Captures the **primary metric** for each connection's goal
- Tracks **trends** to understand direction of change
- Keeps state space manageable (1,728 states)

But it **cannot directly see**:

- How actions affect other connections
- Current parameter values
- Underlying network conditions
- Fine-grained metric differences within bins

The agent compensates by learning through trial and error, using the **reward signal** to indirectly discover what the state doesn't show.
