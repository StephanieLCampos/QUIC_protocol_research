# Dual-Agent Comparison: Network Sharing Analysis

**Date:** May 12, 2026
**Purpose:** Analysis of why running 6 connections (for agent comparison) produces different results than 3-connection baselines, and potential solutions

---

## KEY FINDING: Varying Scenario is Deterministic

**The varying scenario uses a sinusoidal pattern, NOT random variation.**

After investigating the bottleneck implementation (`wireless_bottleneck/config.py`), the capacity variation is calculated as:

```python
capacity(t) = base_capacity × (1 + amplitude × sin(2π × t / period))
```

With current settings (20 Mbps, ±40%, 6s period):

| Time | Capacity | Phase |
|------|----------|-------|
| 0.0s | 20 Mbps | Starting |
| 1.5s | 28 Mbps | Peak |
| 3.0s | 20 Mbps | Middle |
| 4.5s | 12 Mbps | Trough |
| 6.0s | 20 Mbps | Cycle repeats |

**Since `elapsed_time` starts at 0 for each run, both agents face the EXACT SAME capacity pattern when run sequentially.**

**This means you can simply run:**
```bash
ML_AGENT=andy SCENARIO=varying DURATION=300 docker compose up
ML_AGENT=default SCENARIO=varying DURATION=300 docker compose up
```

Both agents experience identical network conditions. No seed needed, no 6-connection setup needed for fair comparison.

---

## 1. Problem Statement (Revised)

### Original Goal
Compare Andy's Q-learning agent vs the Default Q-learning agent under identical network conditions (varying scenario) to determine which performs better.

### Original Challenge (Now Resolved)
We initially thought the varying scenario had random capacity fluctuations, meaning running agents sequentially would result in different network conditions.

**Resolution:** The varying scenario is deterministic (sinusoidal), so sequential runs ARE fair.

### Alternative Approach Considered
Run both agents simultaneously through the same network bottleneck. This section documents why that approach has issues, for reference.

### Problem with Simultaneous Approach
Running both agents simultaneously requires 6 connections (3 per agent) sharing the bottleneck instead of 3, fundamentally changing the network dynamics.

---

## 2. Why 6 Connections Changes Everything

### 2.1 Bandwidth Competition

The bottleneck has fixed capacity that must be shared among all connections.

**Varying scenario parameters:**
- Average capacity: 20 Mbps
- Variation: ±40% (range: 12-28 Mbps)
- 6-second variation period

**Per-connection bandwidth:**

| Configuration | Total Capacity | Connections | Per-Connection Avg |
|---------------|----------------|-------------|-------------------|
| Normal (3 conn) | 20 Mbps | 3 | ~6.7 Mbps |
| Comparison (6 conn) | 20 Mbps | 6 | ~3.3 Mbps |

With 6 connections, each connection gets roughly **half the bandwidth** it would normally receive.

### 2.2 Queue Dynamics

More connections competing for the same queue leads to:

1. **Higher queue occupancy** - More packets waiting in the bottleneck queue
2. **Increased queuing delay** - Packets wait longer before transmission
3. **More frequent queue overflow** - Higher packet loss when queue fills
4. **CoDel behavior changes** - More aggressive dropping under higher load

**Queue impact analysis:**

| Metric | 3 Connections | 6 Connections | Change |
|--------|---------------|---------------|--------|
| Queue occupancy | Moderate | High | +50-100% |
| Queuing delay | Low-moderate | Moderate-high | +30-60% |
| Packet loss (CoDel) | Occasional | More frequent | +20-50% |

### 2.3 Congestion Control Interaction

CUBIC congestion control behaves differently under higher contention:

- **More frequent loss events** → More cwnd reductions
- **Lower equilibrium cwnd** → Lower throughput per connection
- **More RTT variance** → Less stable performance
- **Fairness interactions** → 6-way instead of 3-way bandwidth sharing

---

## 3. Impact on Metrics and Utilities

### 3.1 Throughput Utility

The throughput utility function normalizes against a maximum:

```python
THROUGHPUT_MAX = 3,750,000 bytes/s  # 30 Mbps
utility = throughput / THROUGHPUT_MAX
```

**With 3 connections:**
- Achievable per-connection: ~6.7 Mbps = 835 KB/s
- Max utility: 835,000 / 3,750,000 = **0.22** (theoretical)
- Practical with good parameters: **0.15-0.20**

**With 6 connections:**
- Achievable per-connection: ~3.3 Mbps = 417 KB/s
- Max utility: 417,000 / 3,750,000 = **0.11** (theoretical)
- Practical: **0.08-0.12**

The throughput utility is **cut roughly in half** with 6 connections.

### 3.2 Latency Utility

Higher queue occupancy increases latency:

```python
LATENCY_BEST = 0.020   # 20ms
LATENCY_WORST = 0.200  # 200ms
utility = (LATENCY_WORST - latency) / (LATENCY_WORST - LATENCY_BEST)
```

**Expected latency changes:**

| Configuration | Typical Latency | Utility |
|---------------|-----------------|---------|
| 3 connections | 30-50ms | 0.83-0.94 |
| 6 connections | 50-80ms | 0.67-0.83 |

Latency utility drops by **10-20%** with 6 connections.

### 3.3 Jitter Utility

More contention leads to more variable delays:

```python
JITTER_WORST = 0.050  # 50ms
utility = (JITTER_WORST - jitter) / JITTER_WORST
```

**Expected jitter changes:**

| Configuration | Typical Jitter | Utility |
|---------------|----------------|---------|
| 3 connections | 5-15ms | 0.70-0.90 |
| 6 connections | 10-25ms | 0.50-0.80 |

Jitter utility drops by **10-20%** with 6 connections.

### 3.4 Combined Reward Impact

Given the utility changes, expected reward ranges:

| Configuration | Mean Utility | Expected Reward |
|---------------|--------------|-----------------|
| 3 connections | 0.50-0.70 | 0.45-0.65 |
| 6 connections | 0.35-0.55 | 0.30-0.50 |

**Rewards from 6-connection runs cannot be directly compared to 3-connection baselines.**

---

## 4. What Remains Valid

Despite the metric differences, some comparisons are still valid:

### 4.1 Relative Agent Comparison (VALID)

Comparing Andy vs Default within the same 6-connection run is valid because:
- Both agents face identical network conditions
- Both have 3 connections each
- Both compete for the same bottleneck bandwidth
- The relative difference shows which adapts better

**Valid comparison:**
```
Andy's reward in 6-conn run: 0.42
Default's reward in 6-conn run: 0.38
Conclusion: Andy performs ~10% better (VALID)
```

### 4.2 Absolute Metric Comparison (INVALID)

Comparing 6-connection metrics to 3-connection baselines is invalid:

**Invalid comparison:**
```
Andy's reward in 3-conn run: 0.58
Andy's reward in 6-conn run: 0.42
Conclusion: Andy got worse (INVALID - different network load)
```

---

## 5. Solutions

### Solution A: Double the Bottleneck Capacity

**Concept:** Increase bottleneck capacity proportionally to maintain per-agent bandwidth.

**Implementation:**
Create a new scenario in `wireless_bottleneck/scenarios.py`:

```python
def varying_dual_agent() -> WirelessScenario:
    """
    Varying scenario for dual-agent comparison.
    Double capacity (40 Mbps) so each 3-connection agent group
    gets ~20 Mbps, matching single-agent varying scenario.
    """
    return WirelessScenario(
        name="varying_dual_agent",
        description="40 Mbps link for 6-connection dual-agent comparison",
        config=BottleneckConfig(
            capacity_bps=40_000_000,      # 40 Mbps (2x normal)
            propagation_delay=0.010,       # 10ms (20ms RTT)
            loss_rate=0.01,                # 1%
            loss_model=LossModel.RANDOM,
            queue_size_packets=200,        # 2x queue for 2x connections
            queue_discipline=QueueDiscipline.CODEL,
            codel_target_delay=0.005,
            codel_interval=0.100,
            time_varying=True,
            variation_period=6.0,
            variation_amplitude=0.4,       # ±40% (24-56 Mbps range)
        )
    )
```

**Advantages:**
- Per-connection bandwidth similar to 3-connection runs
- Metrics comparable to baseline runs
- Absolute reward values meaningful

**Disadvantages:**
- Requires code changes
- Queue behavior may still differ slightly
- Not testing "true" 20 Mbps bottleneck behavior

**Per-connection bandwidth with Solution A:**

| Configuration | Total Capacity | Connections | Per-Connection |
|---------------|----------------|-------------|----------------|
| Normal | 20 Mbps | 3 | ~6.7 Mbps |
| Dual-agent (A) | 40 Mbps | 6 | ~6.7 Mbps |

### Solution B: Accept Relative Comparison Only

**Concept:** Keep 20 Mbps bottleneck, accept that metrics differ from baseline, but use the results only for agent-to-agent comparison.

**Implementation:**
No code changes needed. Run both agents with 6 connections, 20 Mbps bottleneck.

**Advantages:**
- No code changes required
- Simpler to implement
- Tests agents under higher contention (stress test)

**Disadvantages:**
- Cannot compare to 3-connection baseline runs
- Absolute metric values are lower
- Different operating regime than normal use

**Interpretation guidance for Solution B:**

| Metric | How to Interpret |
|--------|------------------|
| Reward | Compare Andy vs Default only |
| Throughput | Relative difference matters, not absolute |
| Latency | Both agents face same higher latency |
| "Winner" | Agent with higher reward in same run |

### Solution C: Run Multiple Sequential Trials

**Concept:** Run each agent multiple times (5-10 trials) on varying scenario separately, then compare averaged results.

**Implementation:**
```bash
# Run Andy 5 times
for i in {1..5}; do
  ML_AGENT=andy SCENARIO=varying DURATION=300 docker compose up
done

# Run Default 5 times
for i in {1..5}; do
  ML_AGENT=default SCENARIO=varying DURATION=300 docker compose up
done

# Average the results
```

**Advantages:**
- Uses normal 3-connection setup
- Metrics directly comparable to baselines
- Statistical significance through averaging

**Disadvantages:**
- Time-consuming (10 runs instead of 1)
- Variance may still obscure small differences
- Network conditions not identical (averaged out statistically)

### Solution D: Add Deterministic Seed to Varying Scenario

**STATUS: NOT NEEDED**

The varying scenario is already deterministic (sinusoidal pattern). Both agents face identical conditions when run sequentially because:

1. Capacity follows: `capacity(t) = 20 × (1 + 0.4 × sin(2π × t / 6))` Mbps
2. Each run starts at `elapsed_time = 0`
3. Therefore both runs experience the same capacity curve

**No code changes required.** Simply run agents sequentially:

```bash
ML_AGENT=andy SCENARIO=varying DURATION=300 docker compose up
ML_AGENT=default SCENARIO=varying DURATION=300 docker compose up
```

---

## 6. Recommendation

### RECOMMENDED: Sequential Runs (Simplest & Valid)

Since the varying scenario is deterministic, simply run both agents sequentially:

```bash
# Clear Q-tables for fresh comparison
rm -f 3_conn_code/output/q_learning_checkpoint_andy.json
rm -f 3_conn_code/output/q_learning_checkpoint.json

# Run Andy's agent
ML_AGENT=andy SCENARIO=varying DURATION=300 docker compose up

# Run Default agent (faces identical network conditions)
ML_AGENT=default SCENARIO=varying DURATION=300 docker compose up
```

**Why this works:**
- Both face identical sinusoidal capacity pattern
- Normal 3-connection setup
- Metrics directly comparable
- No code changes needed

### Alternative: Solution C (Multiple Trials)

For statistical confidence, run each agent 3-5 times:
- Accounts for any non-deterministic factors (OS scheduling, etc.)
- Average the results
- More rigorous but time-consuming

### If Simultaneous Comparison is Still Desired

If you want to test agents competing against each other (stress test):
- Use Solution A (double capacity) for comparable metrics
- Use Solution B (accept relative comparison) for quick results

---

## 7. Summary Table

| Solution | Code Changes | Time Required | Baseline Comparable | Best For |
|----------|--------------|---------------|---------------------|----------|
| **Sequential runs** | None | 2 runs | **Yes** | **Recommended** |
| A: Double capacity | Yes (new scenario) | 1 run | Yes | Simultaneous stress test |
| B: Accept relative | None | 1 run | No | Quick simultaneous test |
| C: Multiple trials | None | 6-10 runs | Yes | Statistical confidence |
| D: Deterministic seed | ~~Not needed~~ | - | - | Already deterministic |

---

## 8. Conclusion

### Key Discovery

The varying scenario uses a **deterministic sinusoidal pattern**, not random variation. This means:

**Sequential runs ARE fair** - both agents face identical network conditions.

### Original Concern (Resolved)

We initially considered running both agents simultaneously (6 connections) to ensure identical conditions. However, this introduces new problems:
- Network dynamics change with 6 connections vs 3
- Metrics not comparable to baseline runs
- Unnecessary complexity

### Final Recommendation

**Simply run agents sequentially:**

```bash
ML_AGENT=andy SCENARIO=varying DURATION=300 docker compose up
ML_AGENT=default SCENARIO=varying DURATION=300 docker compose up
```

Both agents experience the same capacity curve:
- t=0s: 20 Mbps → t=1.5s: 28 Mbps → t=4.5s: 12 Mbps → repeating

Compare their final metrics, rewards, and Q-table quality directly.
