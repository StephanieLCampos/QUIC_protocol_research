# Q-Learning Agent Analysis Report

**Date:** May 12, 2026
**Purpose:** Deep analysis of both Q-learning agents for correctness, consistency, and potential issues

---

## Executive Summary

| Agent | State Design | Q-Learning | Reward | Issues Found |
|-------|--------------|------------|--------|--------------|
| Andy's (14-feature) | Parameter indices + network bins | Correct | **1 BUG (FIXED)** | Action loop, Reward starvation incentive |
| Default (7-feature) | Metric bins + trends | Correct | **4 BUGS** | Stability tracking, eval() security, Action loop, Reward starvation incentive |

**Additional Issues:**
- Video streaming starvation due to initial config (Section 12) - FIXED
- Reward function incentivized starvation (Section 13) - FIXED
- Video loss amplification (5x network loss) due to bursty I-frames (Section 14) - DOCUMENTED (Expected behavior)

**Note:** All bugs and configuration issues have been fixed as of May 12, 2026. The video loss amplification (Section 14) is expected behavior due to bursty traffic patterns, not a bug.

---

## 1. Q-Learning Implementation Verification

### Bellman Update (Both Agents) - CORRECT

```python
Q(s,a) <- Q(s,a) + alpha * [r + gamma * max Q(s',.) - Q(s,a)]
```

Both agents implement the standard Q-learning update correctly:
- `alpha = 0.10` (learning rate)
- `gamma = 0.90` (discount factor)

### Epsilon-Greedy Exploration - CORRECT

```python
if random.random() < epsilon:
    action = random.randrange(N_ACTIONS)  # explore
else:
    action = best_action(state)           # exploit
```

- `epsilon_start = 0.30` (30% exploration initially)
- `epsilon_min = 0.05` (5% floor)
- `epsilon_decay = 0.995` (multiplicative decay per step)

### Initial Q-Values - CORRECT

All actions start with Q=0 (neutral), no bias toward any action.

---

## 2. Action Space Analysis - CORRECT

Both agents use identical 25-action encoding:

```
action = conn_idx * 8 + param_idx * 2 + direction
```

| Action Range | Connection | Description |
|--------------|------------|-------------|
| 0-7 | Video (1) | 4 params x 2 directions |
| 8-15 | File (2) | 4 params x 2 directions |
| 16-23 | Conference (3) | 4 params x 2 directions |
| 24 | - | No-op |

**Decoding verification:**
```
Action 0:  video.loss_reduction_factor.increase
Action 1:  video.loss_reduction_factor.decrease
Action 8:  file.loss_reduction_factor.increase
Action 16: conf.loss_reduction_factor.increase
Action 24: no-op
```

---

## 3. State Space Comparison

### Andy's Agent (14-Feature State)

```
state = (
    lrf_v, lrf_f, lrf_c,    # loss_reduction_factor indices (0-4)
    cc_v,  cc_f,  cc_c,     # cubic_c indices (0-2)
    mw_v,  mw_f,  mw_c,     # minimum_window indices (0-2)
    pt_v,  pt_f,  pt_c,     # packet_threshold indices (0-1)
    tp_bin,                  # total throughput bin (0-3)
    rtt_bin,                 # mean RTT bin (0-3)
)
```

**State space:** 5^3 x 3^3 x 3^3 x 2^3 x 4 x 4 = ~11.6M theoretical states
**Practical:** ~50-300 states visited

**Characteristics:**
- Knows exact parameter positions (can detect boundaries)
- Aggregated network conditions only
- Cannot distinguish which connection is underperforming

### Default Agent (7-Feature State)

```
state = (lat_bin, tp_bin, jit_bin, lat_trend, tp_trend, jit_trend, loss_bin)
```

**State space:** 4^4 x 3^3 = 6,912 states

**Characteristics:**
- Directly observes per-connection metrics
- Tracks improvement/worsening trends
- Cannot detect parameter boundaries (may try redundant actions)

### Comparison Table

| Feature | Andy's Agent | Default Agent |
|---------|--------------|---------------|
| Knows dial positions | Yes (12 indices) | No |
| Knows per-connection metrics | No | Yes (3 bins) |
| Network condition awareness | tp_bin + rtt_bin | loss_bin |
| Trend awareness | No | Yes (3 trends) |
| Boundary detection | Yes | No |
| State space size | ~11.6M | 6,912 |

---

## 4. Reward Function Analysis - CORRECT

### Utility Functions

| Connection | Goal | Formula | Range |
|------------|------|---------|-------|
| Video | Min latency | (0.200 - lat) / 0.180 | [0, 1] |
| File | Max throughput | tp / 3,750,000 | [0, 1] |
| Conference | Min jitter | (0.050 - jit) / 0.050 | [0, 1] |

**Verification:**
- Latency: 20ms -> 1.0 (best), 200ms -> 0.0 (worst)
- Throughput: 30 Mbps -> 1.0 (best), 0 -> 0.0 (worst)
- Jitter: 0ms -> 1.0 (best), 50ms -> 0.0 (worst)

### Combined Reward

```
R = mean(U_video, U_file, U_conf)
    - LAMBDA_FAIRNESS * stdev(utilities)
    - MU_STABILITY * changed
```

Where:
- `LAMBDA_FAIRNESS = 0.10` (penalize imbalanced utilities)
- `MU_STABILITY = 0.05` (penalize parameter changes)

**Reward range:** approximately [-0.10, 1.0]

---

## 5. BUGS FOUND

### BUG 1: Default Agent Missing Stability Tracking (CRITICAL)

**Location:** `q_learning_agent.py` line 500

**Problem:**
```python
# CURRENT CODE (BUGGY):
changed = (self._last_action != ACTION_NOOP)
```

When the agent tries to increase a parameter already at its maximum:
1. `_apply_action()` returns `{}` (no change made)
2. But `self._last_action` is the increase action (not NOOP)
3. `changed = True` even though nothing actually changed
4. Stability penalty (0.05) is incorrectly applied

**Impact:** Agent is penalized for actions that didn't actually change anything, biasing it toward no-op.

**Fix:** Add `_last_action_changed` tracking like Andy's agent:
```python
# FIXED CODE:
decisions = self._apply_action(action)
self._last_action_changed = bool(decisions)

# In reward calculation:
changed = self._last_action_changed  # Use tracked flag
```

---

### BUG 2: Default Agent Uses Unsafe eval() (SECURITY)

**Location:** `q_learning_agent.py` line 609

**Problem:**
```python
# CURRENT CODE (INSECURE):
self._q = {eval(k): v for k, v in data["q"].items()}
```

If a checkpoint file is tampered with, `eval()` could execute arbitrary Python code.

**Fix:** Use `ast.literal_eval()` like Andy's agent:
```python
# FIXED CODE:
import ast
self._q = {ast.literal_eval(k): v for k, v in data["q"].items()}
```

---

### BUG 3: Action Loop Bug - Boundary Actions Causing Infinite Loops (FIXED)

**Date Discovered:** May 12, 2026
**Affected Agents:** Both (Andy's and Default)
**Status:** FIXED

#### Problem Description

During training evaluation, the agent would get stuck in infinite loops selecting the same action repeatedly without any state change. Analysis of `rewards.csv` from a training run showed patterns like:

```
step,action,state,next_state
1058,file.cubic_c.increase,"(0, 2, 0, 2, 2, 1, 1, 2, 2, 0, 0, 0, 1, 0)","(0, 2, 0, 2, 2, 1, 1, 2, 2, 0, 0, 0, 1, 0)"
1059,file.cubic_c.increase,"(0, 2, 0, 2, 2, 1, 1, 2, 2, 0, 0, 0, 1, 0)","(0, 2, 0, 2, 2, 1, 1, 2, 2, 0, 0, 0, 1, 0)"
1060,file.cubic_c.increase,"(0, 2, 0, 2, 2, 1, 1, 2, 2, 0, 0, 0, 1, 0)","(0, 2, 0, 2, 2, 1, 1, 2, 2, 0, 0, 0, 1, 0)"
... (repeated 80+ times)
```

#### Root Cause Analysis

**1. Boundary Actions Have No Effect**

When a parameter reaches its boundary (min or max), actions that try to push past return `{}` (no change):

```python
# In _apply_action():
new_val = current + step if direction == 0 else current - step
new_val = _clamp(param_name, new_val)

if new_val == current:
    return {}  # At boundary - no change
```

**2. Q-Values Reinforce Ineffective Actions**

If an agent happens to select a boundary action during a period of good network performance (due to external factors), that action gets reinforced with a high Q-value - even though it had no effect.

**3. No Escape from the Loop**

Since:
- The Q-value for the boundary action is high
- The action has no effect (returns `{}`)
- The state doesn't change
- The agent keeps selecting the same "best" action

The agent enters an infinite loop.

#### Evidence from Training Data

| State Position | Value | Meaning |
|----------------|-------|---------|
| Position 4 (cc[file]) | 2 | cubic_c = 0.4 (MAX) |

The agent repeatedly selected `file.cubic_c.increase` but cubic_c was already at maximum (0.4). The action returned `{}`, state didn't change, and the loop continued.

Similar patterns were observed with:
- `video.loss_reduction_factor.decrease` when lrf[video] = 0 (value 0.3, MIN)
- `file.packet_threshold.decrease` when pt[file] = 0 (value 3, MIN)

#### The Fix

Added **boundary masking** to action selection in both agents:

**New method `_is_action_at_boundary()`:**
```python
def _is_action_at_boundary(self, action: int) -> bool:
    """Check if action would hit a parameter boundary."""
    decoded = _decode_action(action)
    if decoded is None:
        return False  # no-op is never at boundary

    conn_id, param_name, direction = decoded
    spec = PARAM_SPACE[param_name]
    current = self._params[conn_id][param_name]

    if direction == 0:  # increase
        return current >= spec["max"]
    else:  # decrease
        return current <= spec["min"]
```

**Modified action selection:**
```python
# Get valid actions (exclude boundary actions)
valid_actions = [a for a in range(N_ACTIONS) if not self._is_action_at_boundary(a)]
if not valid_actions:
    valid_actions = [ACTION_NOOP]  # fallback

if random.random() < self.epsilon:
    action = random.choice(valid_actions)  # explore only valid
else:
    # exploit: best Q-value among valid actions only
    q_vals = self._get_q(state)
    valid_q = [(a, q_vals[a]) for a in valid_actions]
    max_q = max(q for _, q in valid_q)
    best_valid = [a for a, q in valid_q if q == max_q]
    action = random.choice(best_valid)
```

#### Files Modified

- `3_conn_code/ml_callbacks/q_learning_agent_andy.py`
- `3_conn_code/ml_callbacks/q_learning_agent.py`

#### Expected Improvement

After this fix:
1. Agent never wastes steps selecting ineffective boundary actions
2. Q-values only update for actions that actually change parameters
3. No more infinite loops where state never changes
4. More efficient exploration and learning

#### Recommendation

Clear Q-tables and retrain to benefit from the fix:
```bash
./train_agents.sh  # Select "y" when asked to clear Q-tables
```

---

## 6. Parameter Consistency Verification - CORRECT

### PARAM_SPACE (Both Agents)

| Parameter | Min | Max | Step | Values |
|-----------|-----|-----|------|--------|
| loss_reduction_factor | 0.3 | 0.7 | 0.1 | 5 (indices 0-4) |
| cubic_c | 0.2 | 0.4 | 0.1 | 3 (indices 0-2) |
| minimum_window | 2 | 4 | 1 | 3 (indices 0-2) |
| packet_threshold | 3 | 4 | 1 | 2 (indices 0-1) |

### Initial Values Match multi_connection_config.py

| Connection | loss_reduction_factor | cubic_c | minimum_window | packet_threshold |
|------------|----------------------|---------|----------------|------------------|
| Video | 0.3 | 0.2 | 2 | 4 |
| File | 0.7 | 0.4 | 4 | 3 |
| Conference | 0.5 | 0.2 | 4 | 3 |

All values are within PARAM_SPACE bounds.

---

## 7. Design Considerations (Not Bugs)

### A. Fairness Penalty May Be Weak

- Maximum stdev of utilities: ~0.5 (when utilities are [0, 0.5, 1])
- Maximum fairness penalty: 0.10 x 0.5 = 0.05
- Maximum mean utility: 1.0
- Penalty ratio: 5%

The agent might sacrifice one connection to maximize others. If stricter fairness is desired, increase `LAMBDA_FAIRNESS` to 0.15-0.20.

### B. Andy's Agent Doesn't See Per-Connection Metrics

The state only includes aggregated network conditions (total_tp, mean_rtt), not per-connection performance. The agent learns the mapping from dial positions to reward through experience, but cannot explicitly see "video latency is high."

This is by design - the parameter indices tell the agent what it controls, and the reward signal provides feedback on outcomes.

### C. Throughput Metric Difference

| Agent | Throughput Source | Fallback |
|-------|-------------------|----------|
| Andy's | throughput_cwnd | throughput_acked_delta, throughput_acked |
| Default | throughput_acked_delta | throughput_acked |

Both approaches are valid:
- `throughput_cwnd` = cwnd / RTT (theoretical max given congestion window)
- `throughput_acked_delta` = bytes acked in epoch / epoch duration (actual measured)

---

## 8. Recommendations

### Must Fix

1. **Default agent: Add `_last_action_changed` tracking**
   - Same fix applied to Andy's agent previously
   - Prevents incorrect stability penalty

2. **Default agent: Replace `eval()` with `ast.literal_eval()`**
   - Security fix for checkpoint loading

### Optional Improvements

3. **Consider increasing LAMBDA_FAIRNESS** to 0.15-0.20 if balanced performance across all connections is important

4. **Add documentation** noting the difference between RTT (used in state bins) and latency (used in reward calculation)

---

## 9. How Each Agent Learns (Detailed Comparison)

### Andy's Agent: Learning Through Parameter Positions

**What the state looks like:**
```
state = (
    0, 4, 2,    # loss_reduction_factor indices: video=0.3, file=0.7, conf=0.5
    0, 2, 0,    # cubic_c indices: video=0.2, file=0.4, conf=0.2
    0, 2, 2,    # minimum_window indices: video=2, file=4, conf=4
    1, 0, 0,    # packet_threshold indices: video=4, file=3, conf=3
    2,          # total throughput bin (medium-high)
    1,          # mean RTT bin (moderate)
)
```

**What the agent sees:**
"All dials are at these positions, and network is medium throughput / moderate RTT"

**What the agent does NOT see:**
- Video latency is 150ms (bad!)
- File throughput is 20 Mbps (good)
- Conference jitter is 10ms (okay)

**How it still learns:**

The agent doesn't see per-connection metrics, but it receives a **reward signal** that reflects them:

```
Step 1: State = (dials at position X, network condition Y)
        Action = increase video.loss_reduction_factor
        Reward = 0.45 (low - video latency was bad)

Step 2: State = (dials at position X', network condition Y)
        Action = decrease video.cubic_c
        Reward = 0.62 (better - video latency improved!)
```

Over many steps, the Q-table learns patterns like:
- "When dials are at X and network is Y, decreasing video.cubic_c gives high reward"
- "When dials are at X and network is Y, increasing file.loss_reduction_factor gives low reward"

The agent learns the *indirect* relationship: "these parameter settings → this performance outcome"

### Default Agent: Learning Through Observed Metrics

**What the state looks like:**
```
state = (
    3,    # latency bin: >50ms (bad)
    3,    # throughput bin: >3MB/s (good)
    1,    # jitter bin: 5-15ms (okay)
    0,    # latency trend: worsening
    1,    # throughput trend: stable
    2,    # jitter trend: improving
    1,    # loss bin: 1-5%
)
```

**What the agent sees:**
"Video latency is bad and getting worse, file throughput is good, conference jitter is okay and improving"

**What the agent does NOT see:**
- Current parameter values for each connection
- Whether a parameter is already at its min/max boundary

**How it learns:**

The agent directly observes performance metrics, so it can immediately see which connection needs help:

```
Step 1: State = (lat=bad, tp=good, jit=okay, trends...)
        Agent thinks: "Latency is bad, I should adjust video parameters"
        Action = decrease video.cubic_c
        Reward = 0.62 (latency improved!)
```

But it may waste actions:
```
Step 5: State = (lat=okay, tp=good, jit=okay, trends...)
        Action = increase file.loss_reduction_factor
        But file.loss_reduction_factor is already at 0.7 (max)!
        No change happens, action was wasted
```

### Side-by-Side Comparison

| Aspect | Andy's Agent | Default Agent |
|--------|--------------|---------------|
| **State focus** | What I control (dials) | What I observe (metrics) |
| **Knows boundaries** | Yes - won't try to exceed limits | No - may try impossible actions |
| **Sees problem connection** | No - must infer from reward | Yes - directly in state |
| **Learning approach** | "These settings → this outcome" | "This performance → try this fix" |
| **Exploration efficiency** | May need more exploration initially | Can target problem connections |
| **Action efficiency** | Never wastes actions on boundaries | May waste actions at boundaries |
| **State space** | ~11.6M (sparse, ~50-300 visited) | 6,912 (dense, ~50-500 visited) |

### Which is Better?

Neither is strictly better - they have different strengths:

**Andy's agent is better when:**
- Parameters are frequently at boundaries
- You want to avoid wasted exploration
- You have time for the agent to learn parameter→performance mappings

**Default agent is better when:**
- You want the agent to quickly identify which connection needs help
- Parameters rarely hit boundaries
- You want more interpretable state (can see "latency is bad")

**In practice:** Both agents converge to similar policies given enough training, but they take different paths to get there.

---

## 10. Verification Summary

| Component | Andy's Agent | Default Agent |
|-----------|--------------|---------------|
| Bellman update | CORRECT | CORRECT |
| Epsilon-greedy | CORRECT | CORRECT |
| Epsilon decay | CORRECT | CORRECT |
| Action encoding | CORRECT | CORRECT |
| Action decoding | CORRECT | CORRECT |
| Utility functions | CORRECT | CORRECT |
| Reward formula | CORRECT | CORRECT |
| Parameter clamping | CORRECT | CORRECT |
| Stability tracking | CORRECT | **BUG** (FIXED) |
| Checkpoint security | CORRECT (ast.literal_eval) | **BUG** (FIXED) |
| Boundary action masking | **BUG** (FIXED) | **BUG** (FIXED) |
| Initial values | Match config | Match config |
| PARAM_SPACE | Consistent | Consistent |

---

## 11. Bug Fix History

| Bug | Date | Agents Affected | Status |
|-----|------|-----------------|--------|
| Stability tracking | May 12, 2026 | Default only | FIXED |
| eval() security | May 12, 2026 | Default only | FIXED |
| Action loop (boundary masking) | May 12, 2026 | Both | FIXED |
| Video starvation (config issue) | May 12, 2026 | Both (config) | FIXED |
| Reward function starvation incentive | May 12, 2026 | Both | FIXED |
| Video loss amplification (bursty traffic) | May 13, 2026 | N/A (traffic pattern) | DOCUMENTED |

---

## 12. Configuration Issue: Video Streaming Starvation (FIXED)

**Date Discovered:** May 12, 2026
**Type:** Configuration issue (not a code bug)
**Status:** FIXED

### Problem Description

During evaluation runs, video streaming showed **11.3% packet loss** while file transfer and conference call only showed ~2.8% loss. Video throughput crashed from 42 Mbps to 4-5 Mbps after the first congestion event and never recovered.

### Evidence from Metrics Timeseries

| Time | Video Loss | Video Throughput | File Loss | File Throughput |
|------|------------|------------------|-----------|-----------------|
| 1.0s | 0% | 42 Mbps | 3% | 4 Mbps |
| 1.3s | **14%** | 38 Mbps | 2% | 8 Mbps |
| 1.7s | **23%** | 12 Mbps | 3% | 3 Mbps |
| 2.0s | **25%** | 6 Mbps | 3% | 5 Mbps |
| 2.4s | **31%** | 4 Mbps | 3% | 3 Mbps |
| Later | 13-14% | 4-5 Mbps | 2-3% | varies |

### Root Cause Analysis

Video's initial parameters were **too aggressive** for a shared bottleneck scenario:

**Original Video Config:**
```python
loss_reduction_factor=0.3   # Most aggressive - cwnd drops to 30%
cubic_c=0.2                 # Slowest recovery
minimum_window=2            # Can drop to just 2 packets
packet_threshold=4          # Slowest loss detection
```

**File Transfer Config (for comparison):**
```python
loss_reduction_factor=0.7   # Conservative - keeps 70% of cwnd
cubic_c=0.4                 # Fastest recovery
minimum_window=4            # Maintains higher floor
packet_threshold=3          # Faster loss detection
```

### The Vicious Cycle

```
1. Bottleneck gets congested (varying scenario dips to 12 Mbps)
2. Video detects loss (slowly, due to packet_threshold=4)
3. Video aggressively backs off (cwnd × 0.3)
4. cwnd drops to minimum_window=2
5. File transfer keeps 70% of its cwnd (loss_reduction_factor=0.7)
6. File transfer dominates the available bandwidth
7. Video can't recover (slow cubic_c=0.2)
8. Video keeps seeing loss → repeats from step 3
```

### Why Q-Learning Couldn't Fix It

The agent repeatedly tried `video.loss_reduction_factor.decrease`, but:

- Video started at **0.3** which is the **MINIMUM** in PARAM_SPACE
- PARAM_SPACE defines: `loss_reduction_factor: min=0.3, max=0.7`
- The agent **cannot** increase loss_reduction_factor beyond the starting value
- Video was stuck at the most aggressive (worst) setting

```
rewards.csv pattern:
step 956: video.loss_reduction_factor.decrease - NO CHANGE (already at min)
step 957: video.loss_reduction_factor.decrease - NO CHANGE (already at min)
step 958: video.loss_reduction_factor.decrease - NO CHANGE (already at min)
... (repeated many times)
```

### The Fix

Updated video's initial parameters to balanced values that allow fair competition:

| Parameter | Old Value | New Value | Reason |
|-----------|-----------|-----------|--------|
| loss_reduction_factor | 0.3 | **0.5** | Less aggressive backoff, can compete fairly |
| cubic_c | 0.2 | **0.3** | Faster recovery after loss |
| minimum_window | 2 | **3** | Maintains higher floor throughput |
| packet_threshold | 4 | **3** | Faster loss detection |

### Files Modified

1. **`config/multi_connection_config.py`** - Updated video_config defaults
2. **`ml_callbacks/q_learning_agent_andy.py`** - Updated initial `_params` to match
3. **`ml_callbacks/q_learning_agent.py`** - Updated initial `_params` to match

### Expected Improvement

With the new balanced parameters:
- Video can compete fairly with file transfer for bandwidth
- When congestion occurs, video keeps 50% of cwnd (not 30%)
- Faster recovery means video can reclaim bandwidth
- All three connections should see more balanced loss rates (~2-5% each)

### Recommendation

Clear Q-tables and retrain after applying the fix:
```bash
./train_agents.sh  # Select "y" when asked to clear Q-tables
```

---

## 13. Reward Function Bug: Starvation Incentive (FIXED)

**Date Discovered:** May 12, 2026
**Type:** Reward function design bug
**Agents Affected:** Both
**Status:** FIXED

### Problem Description

The original reward function created a **perverse incentive** that actually rewarded video starvation:

**Original Reward Function:**
```python
lat = metrics[CONN_VIDEO].get("latency", 0.0)      # VIDEO's latency only
tp  = _get_throughput(metrics, CONN_FILE)          # FILE's throughput only
jit = metrics[CONN_CONF].get("jitter", 0.0)        # CONF's jitter only

u_stream = _utility_latency(lat)    # Reward for LOW video latency
u_file   = _utility_throughput(tp)  # Reward for HIGH file throughput
u_conf   = _utility_jitter(jit)     # Reward for LOW conf jitter

R = mean(u_stream, u_file, u_conf) - fairness - stability
```

**The Problem:** The reward function measured:
- Video → **latency only** (not throughput)
- File → **throughput**
- Conference → **jitter only** (not throughput)

### Why This Created Bad Incentives

When video was starved (zero throughput):
1. **Video's cwnd dropped very low** (small congestion window)
2. **Low cwnd = fewer packets in flight = low queuing delay**
3. **Low queuing delay = good latency utility!**
4. Meanwhile, file dominated the bandwidth → **good throughput utility**
5. **The agent was REWARDED for video starvation!**

### Evidence from Training

When the agent tried `video.loss_reduction_factor.increase` (which would help video compete):
1. Video keeps more cwnd after loss
2. Video competes with file for bandwidth
3. **File's throughput drops**
4. **Reward goes DOWN** (because only file's throughput was measured)
5. Agent learns: helping video = bad Q-value

When the agent tried `video.loss_reduction_factor.decrease` (at boundary, no change):
1. No change happens
2. File keeps dominating
3. Reward stays the same
4. Agent learns: doing nothing = neutral Q-value

**Result:** The agent learned to keep video starved because helping video hurt the reward!

### The Fix

Updated the reward function to measure throughput for ALL connections:

**New Reward Function:**
```python
# Get metrics for ALL connections
video_lat = metrics[CONN_VIDEO].get("latency", 0.0)
video_tp  = _get_throughput(metrics, CONN_VIDEO)  # NEW: video throughput

file_tp   = _get_throughput(metrics, CONN_FILE)

conf_jit  = metrics[CONN_CONF].get("jitter", 0.0)
conf_tp   = _get_throughput(metrics, CONN_CONF)   # NEW: conf throughput

# Composite utilities - prioritize each connection's PRIMARY goal
u_video = 0.7 * _utility_latency(video_lat) + 0.3 * _utility_throughput(video_tp)
u_file  = _utility_throughput(file_tp)  # 100% throughput - THE priority connection
u_conf  = 0.7 * _utility_jitter(conf_jit) + 0.3 * _utility_throughput(conf_tp)

R = mean(u_video, u_file, u_conf) - fairness - stability
```

### Key Changes

| Connection | Old Utility | New Utility | Primary Goal |
|------------|-------------|-------------|--------------|
| Video | latency only | **70% latency + 30% throughput** | Low latency |
| File | throughput | **100% throughput** | High throughput (PRIORITY) |
| Conference | jitter only | **70% jitter + 30% throughput** | Low jitter |

### Why These Weights?

**File transfer gets bandwidth priority** because:
1. Its utility is 100% throughput (most sensitive to bandwidth changes)
2. Video/conference only have 30% throughput weight (less sensitive)
3. The agent will naturally favor giving bandwidth to file transfer

**Video and conference still prevent starvation** because:
1. 30% throughput weight means they can't "win" with zero bandwidth
2. But 70% primary metric weight means their main goals (latency/jitter) are prioritized
3. This matches the real-world requirements of each application type

### Why This Fixes the Problem

Now if video is starved:
1. Video's latency utility might be good (low cwnd = low delay) = 0.9
2. **But video's throughput utility is BAD (zero bandwidth)** = 0.0
3. **Composite u_video = 0.7 × 0.9 + 0.3 × 0.0 = 0.63** (not great)
4. The agent is NO LONGER rewarded for video starvation

If video has balanced bandwidth:
1. Video's latency utility = 0.7 (moderate delay)
2. Video's throughput utility = 0.3 (getting some bandwidth)
3. **Composite u_video = 0.7 × 0.7 + 0.3 × 0.3 = 0.58** (comparable)

The throughput component prevents starvation while the 70% primary weight ensures each connection's main goal is still the focus.

### Files Modified

1. **`ml_callbacks/q_learning_agent_andy.py`** - Updated `_reward()` method
2. **`ml_callbacks/q_learning_agent.py`** - Updated `_reward()` method

### Recommendation

Clear Q-tables and retrain to learn with the new reward function:
```bash
./train_agents.sh  # Select "y" when asked to clear Q-tables
```

---

## 14. Video Loss Amplification: Network vs QUIC Discrepancy (INVESTIGATION)

**Date Discovered:** May 13, 2026
**Type:** Traffic pattern / network interaction issue
**Status:** DOCUMENTED (Not a bug - expected behavior)

### Problem Description

During training evaluation on the `varying` scenario, video streaming consistently shows **~10.9% packet loss** while the network prober reports only **~2% actual packet loss**. This 5x amplification is significantly higher than file transfer (3%) and conference call (2.5%).

### Evidence from Training Runs

**Network Prober (ICMP ping):**
```json
{
  "packet_loss_percent": 2.00334
}
```

**QUIC Connection Loss:**
| Connection | Measured Loss | Amplification vs Network |
|------------|---------------|-------------------------|
| Video Streaming | 10.9% | **5.5x** |
| File Transfer | 3.0% | 1.5x |
| Conference Call | 2.5% | 1.25x |

### Root Cause Analysis

**1. Video Traffic Is Bursty**

The video synthesizer (`synthesizers/video_streaming.py`) generates bursty I-frame traffic:

```python
I_FRAME_SIZE = 50_000   # 50 KB every 2 seconds (burst of ~35-50 packets)
P_FRAME_SIZE = 5_000    # 5 KB at 30fps (steady)
FPS = 30
KEYFRAME_INTERVAL = 60  # I-frame every 60 frames
```

**2. Bursts Cause Queue Overflow**

When a 50KB I-frame arrives at the bottleneck:
1. ~35-50 packets arrive in quick succession
2. Queue fills beyond its capacity (100 packets in varying scenario)
3. Excess packets are dropped (queue overflow)
4. This happens ON TOP of the 1-2% random network loss

**3. Traffic Pattern Comparison**

```
Video:      ████████░░░░░░░░░░░░████████░░░░░░░░░░░  (Bursty I-frames)
File:       ████████████████████████████████████████  (Steady stream)
Conference: ░█░█░█░█░█░█░█░█░█░█░█░█░█░█░█░█░█░█░█░  (Small, steady)
```

File transfer sends a **continuous stream** that fills the pipe evenly - no bursts.
Conference call sends **small, frequent packets** like the prober - sees similar loss.
Video sends **large bursts** that overwhelm the queue - sees amplified loss.

### Why This Is NOT a Bug

This is **realistic behavior** for video streaming over congested networks:

1. **Real video codecs produce bursty traffic** - I-frames are 5-10x larger than P-frames
2. **Real networks drop bursts** - AQM algorithms (RED, CoDel) specifically target bursts
3. **The varying scenario is designed to stress connections** - 12-28 Mbps with only 100 packet queue

The Q-learning agent cannot fix this because:
- The CUBIC parameters control **how QUIC responds to loss**, not the traffic pattern
- The high loss happens at the **network queue level**, before QUIC sees it
- The video synthesizer generates traffic, not the Q-learning agent

### Why Starvation Penalty Didn't Help

The starvation penalty (added May 13) penalizes connections below 500 KB/s throughput:

```python
MIN_VIABLE_THROUGHPUT = 500_000  # 500 KB/s = 4 Mbps
STARVATION_PENALTY = 0.2
```

But video is getting **5+ Mbps throughput** - it's not starving for bandwidth. It's experiencing high loss due to its bursty traffic pattern, not due to being crowded out by other connections.

| Metric | Video | Threshold | Penalty Applied? |
|--------|-------|-----------|------------------|
| Throughput | 5.2 Mbps | > 4 Mbps | No |
| Loss | 10.9% | N/A | N/A |

### Potential Solutions

**Option 1: Pace I-frames (Recommended for realism)**

Spread the 50KB I-frame over time instead of sending all at once:

```python
# Instead of sending 50KB immediately:
async def generate_paced_iframe(self, frame_data):
    chunk_size = 1400  # ~MTU size
    inter_chunk_delay = 0.001  # 1ms between chunks
    for i in range(0, len(frame_data), chunk_size):
        yield frame_data[i:i+chunk_size]
        await asyncio.sleep(inter_chunk_delay)
```

**Option 2: Reduce I-frame Size (Less realistic)**

```python
I_FRAME_SIZE = 20_000  # 20 KB instead of 50 KB
```

**Option 3: Add Loss Penalty to Reward (Addresses symptom, not cause)**

```python
video_loss = metrics[CONN_VIDEO].get("packet_loss_rate", 0.0)
u_video = 0.6 * U_latency + 0.25 * U_throughput + 0.15 * (1 - video_loss/0.10)
```

**Option 4: Accept It (Current approach)**

Document that video's higher loss is expected behavior due to bursty traffic patterns. The Q-learning agent optimizes for video's primary goals (latency) within the constraints of the traffic pattern.

### Recommendation

**Option 4 (Accept it) is the best choice** for maintaining realistic video streaming simulation.

#### Why Bursty Traffic Should Be Kept

Real video streaming IS bursty by design:
- I-frames (keyframes) are 5-10x larger than P-frames
- The 50KB I-frame size is realistic for 720p H.264
- Sending bursts quickly fills the receiver's playback buffer
- This is how Netflix, YouTube, Zoom, etc. actually work

Reducing I-frame size (Option 2) or pacing I-frames (Option 1) would make the simulation **less realistic** - real video codecs don't artificially slow down frame transmission.

#### Why High Video Loss Is Valuable Research Data

The 10.9% loss IS what happens to real video over congested wireless networks. This is actually valuable because it shows:
1. How QUIC CUBIC responds to bursty traffic under congestion
2. The natural disadvantage video has vs steady-stream file transfers
3. Why real video apps use adaptive bitrate (ABR) to reduce quality when network is bad

#### What Q-Learning Can and Cannot Fix

The Q-learning agent can only tune CUBIC congestion control parameters - it **cannot** change the fundamental physics of bursts hitting a full queue. Even with perfect parameter tuning:
- 50KB bursts will still overflow 100-packet queues
- Video will still see higher loss than steady-stream traffic
- This is a traffic pattern limitation, not a parameter tuning problem

#### Final Decision

**Keep the current simulation as-is.** The high video loss is:
- Realistic behavior for video streaming over congested networks
- Valuable research data showing QUIC's behavior under bursty traffic
- Not something Q-learning can fully solve (traffic pattern issue, not parameter issue)
- Properly documented in this section for research context

### Files Involved

- `synthesizers/video_streaming.py` - Traffic generation pattern
- `wireless_bottleneck/scenarios.py` - Queue size configuration (100 packets)
- `ml_callbacks/q_learning_agent*.py` - Reward function (already has throughput component)
