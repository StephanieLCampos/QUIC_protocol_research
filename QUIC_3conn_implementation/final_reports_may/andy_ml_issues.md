# Andy's Q-Learning Agent - Comprehensive Code Review

**Date:** May 12, 2026
**File Analyzed:** `3_conn_code/ml_callbacks/q_learning_agent_andy.py`
**Agent Design:** 14-Feature State with Parameter Step Indices + Network Condition Bins

---

## Executive Summary

The Q-learning implementation is **largely correct** with one critical bug in the stability penalty calculation. The state space, action space, and reward function are well-designed for the multi-connection QUIC optimization problem.

| Component | Status | Notes |
|-----------|--------|-------|
| Q-learning update | CORRECT | Standard Bellman equation |
| Epsilon-greedy | CORRECT | Proper exploration/exploitation |
| Epsilon decay | CORRECT | Multiplicative with floor |
| State building | CORRECT | 14 features, proper ordering |
| Action encoding | CORRECT | 25 actions, proper decode |
| Utility functions | CORRECT | Proper normalization |
| Reward formula | CORRECT | Multi-objective design |
| Param sync | CORRECT | Echoes from workers |
| **Stability penalty** | **BUG** | Penalizes boundary hits incorrectly |

---

## 1. Q-Learning Algorithm Correctness

### Bellman Update (Lines 317-321)

```python
def _update(self, s: Tuple, a: int, r: float, s_next: Tuple):
    q     = self._get_q(s)
    q_max = max(self._get_q(s_next))
    q[a] += self.alpha * (r + self.gamma * q_max - q[a])
```

**Formula:** Q(s,a) <- Q(s,a) + alpha * [r + gamma * max Q(s',.) - Q(s,a)]

**Verdict:** CORRECT - Standard Q-learning Bellman update.

### Epsilon-Greedy Action Selection (Lines 474-478)

```python
if random.random() < self.epsilon:
    action = random.randrange(N_ACTIONS)  # explore
else:
    action = self._best_action(state)      # exploit
```

**Verdict:** CORRECT - Explores with probability epsilon, exploits with probability (1-epsilon).

### Epsilon Decay (Line 481)

```python
self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
```

**Parameters:**
- epsilon_start = 0.30 (30% exploration initially)
- epsilon_min = 0.05 (5% exploration floor)
- epsilon_decay = 0.995 (multiplicative decay per step)

**Verdict:** CORRECT - Proper multiplicative decay with floor.

### Reward Timing (Lines 447-451)

```python
if self._last_state is not None and self._last_action is not None:
    changed = (self._last_action != ACTION_NOOP)
    r = self._reward(metrics, changed)
    self._update(self._last_state, self._last_action, r, state)
```

**Verdict:** CORRECT - Reward for action `a` in state `s` is computed from resulting metrics in state `s'`. This gives the CUBIC parameters 2 seconds (CONTROL_INTERVAL) to take effect before measuring reward.

---

## 2. State Space Analysis

### 14-Feature State Structure

```
state = (
    lrf_v, lrf_f, lrf_c,    # loss_reduction_factor step idx (0-4) per connection
    cc_v,  cc_f,  cc_c,     # cubic_c step idx (0-2) per connection
    mw_v,  mw_f,  mw_c,     # minimum_window step idx (0-2) per connection
    pt_v,  pt_f,  pt_c,     # packet_threshold step idx (0-1) per connection
    tp_bin,                  # total throughput bin (0-3)
    rtt_bin,                 # mean RTT bin (0-3)
)
```

### Feature Index Mapping

| Index | Feature | Range | Possible Values |
|-------|---------|-------|-----------------|
| 0 | loss_reduction_factor_video | 0-4 | 5 values |
| 1 | loss_reduction_factor_file | 0-4 | 5 values |
| 2 | loss_reduction_factor_conf | 0-4 | 5 values |
| 3 | cubic_c_video | 0-2 | 3 values |
| 4 | cubic_c_file | 0-2 | 3 values |
| 5 | cubic_c_conf | 0-2 | 3 values |
| 6 | minimum_window_video | 0-2 | 3 values |
| 7 | minimum_window_file | 0-2 | 3 values |
| 8 | minimum_window_conf | 0-2 | 3 values |
| 9 | packet_threshold_video | 0-1 | 2 values |
| 10 | packet_threshold_file | 0-1 | 2 values |
| 11 | packet_threshold_conf | 0-1 | 2 values |
| 12 | tp_bin (total throughput) | 0-3 | 4 values |
| 13 | rtt_bin (mean RTT) | 0-3 | 4 values |

### Theoretical State Space Size

```
5^3 x 3^3 x 3^3 x 2^3 x 4 x 4 = 11,664,000 states
```

**Practical visited:** ~50-300 states (sparse Q-table only allocates visited states)

### Parameter Space Definition

| Parameter | Min | Max | Step | Values | Index Range |
|-----------|-----|-----|------|--------|-------------|
| loss_reduction_factor | 0.3 | 0.7 | 0.1 | {0.3, 0.4, 0.5, 0.6, 0.7} | 0-4 |
| cubic_c | 0.2 | 0.4 | 0.1 | {0.2, 0.3, 0.4} | 0-2 |
| minimum_window | 2 | 4 | 1 | {2, 3, 4} | 0-2 |
| packet_threshold | 3 | 4 | 1 | {3, 4} | 0-1 |

### Network Condition Bins

**Total Throughput Bins (bytes/s):**
- Bin 0: < 500,000 (~4 Mbps) - Very low
- Bin 1: 500,000 - 2,000,000 (~4-16 Mbps) - Low
- Bin 2: 2,000,000 - 3,500,000 (~16-28 Mbps) - Medium
- Bin 3: > 3,500,000 (~28+ Mbps) - High

**Mean RTT Bins (seconds):**
- Bin 0: < 0.050 (< 50ms) - Healthy
- Bin 1: 0.050 - 0.100 (50-100ms) - Moderate
- Bin 2: 0.100 - 0.200 (100-200ms) - Congested
- Bin 3: > 0.200 (> 200ms) - Severe congestion

### State Design Rationale

**Why parameter indices in state?**
- Allows agent to know current "dial positions"
- Can detect when parameters are at boundaries
- Enables learning boundary-aware policies

**Why network condition bins?**
- Provides context about current network state
- Allows different policies for different conditions
- Abstracts continuous metrics into discrete buckets

**Verdict:** CORRECT - Well-designed state space balancing expressiveness and tractability.

---

## 3. Action Space Analysis

### 25 Actions Total

```python
N_PARAMS = 4  # loss_reduction_factor, cubic_c, minimum_window, packet_threshold
N_CONNS = 3   # video, file, conf
N_ACTIONS = N_CONNS * N_PARAMS * 2 + 1 = 25
ACTION_NOOP = 24
```

### Action Encoding

```
action = conn_idx * (N_PARAMS * 2) + param_idx * 2 + direction
```

Where:
- conn_idx: 0=video, 1=file, 2=conf
- param_idx: 0=loss_reduction_factor, 1=cubic_c, 2=minimum_window, 3=packet_threshold
- direction: 0=increase, 1=decrease

### Action Index Table

| Action | Connection | Parameter | Direction |
|--------|------------|-----------|-----------|
| 0 | Video | loss_reduction_factor | increase |
| 1 | Video | loss_reduction_factor | decrease |
| 2 | Video | cubic_c | increase |
| 3 | Video | cubic_c | decrease |
| 4 | Video | minimum_window | increase |
| 5 | Video | minimum_window | decrease |
| 6 | Video | packet_threshold | increase |
| 7 | Video | packet_threshold | decrease |
| 8 | File | loss_reduction_factor | increase |
| 9 | File | loss_reduction_factor | decrease |
| 10 | File | cubic_c | increase |
| 11 | File | cubic_c | decrease |
| 12 | File | minimum_window | increase |
| 13 | File | minimum_window | decrease |
| 14 | File | packet_threshold | increase |
| 15 | File | packet_threshold | decrease |
| 16 | Conf | loss_reduction_factor | increase |
| 17 | Conf | loss_reduction_factor | decrease |
| 18 | Conf | cubic_c | increase |
| 19 | Conf | cubic_c | decrease |
| 20 | Conf | minimum_window | increase |
| 21 | Conf | minimum_window | decrease |
| 22 | Conf | packet_threshold | increase |
| 23 | Conf | packet_threshold | decrease |
| 24 | - | NO-OP | - |

### Action Decoding Verification

```python
def _decode_action(action: int):
    if action == ACTION_NOOP:
        return None
    conn_idx  = action // (N_PARAMS * 2)        # action // 8
    remainder = action  % (N_PARAMS * 2)        # action % 8
    param_idx = remainder // 2
    direction = remainder  % 2
    return CONNECTIONS[conn_idx], TUNABLE_PARAMS[param_idx], direction
```

**Test Cases:**
- Action 0: conn_idx=0, param_idx=0, direction=0 -> (video, loss_reduction_factor, increase) CORRECT
- Action 10: conn_idx=1, param_idx=1, direction=0 -> (file, cubic_c, increase) CORRECT
- Action 23: conn_idx=2, param_idx=3, direction=1 -> (conf, packet_threshold, decrease) CORRECT

**Verdict:** CORRECT - Proper encoding and decoding of 25 actions.

---

## 4. Reward Function Analysis

### Utility Functions

**Latency Utility (Lines 199-202):**
```python
def _utility_latency(v: float) -> float:
    u = (LATENCY_WORST - v) / (LATENCY_WORST - LATENCY_BEST)
    return max(0.0, min(1.0, u))
```

- LATENCY_BEST = 0.020s (20ms)
- LATENCY_WORST = 0.200s (200ms)
- Range = 0.180s
- Example: lat=20ms -> u=1.0 (best), lat=200ms -> u=0.0 (worst)

**Throughput Utility (Lines 205-207):**
```python
def _utility_throughput(v: float) -> float:
    return max(0.0, min(1.0, v / THROUGHPUT_MAX))
```

- THROUGHPUT_MAX = 3,750,000 bytes/s (30 Mbps)
- Example: tp=0 -> u=0.0 (worst), tp=30Mbps -> u=1.0 (best)

**Jitter Utility (Lines 210-214):**
```python
def _utility_jitter(v: float) -> float:
    if JITTER_WORST == 0:
        return 1.0
    return max(0.0, min(1.0, (JITTER_WORST - v) / JITTER_WORST))
```

- JITTER_WORST = 0.050s (50ms)
- Example: jit=0ms -> u=1.0 (best), jit=50ms -> u=0.0 (worst)

### Connection-to-Utility Mapping

| Connection | Optimization Goal | Utility Function |
|------------|-------------------|------------------|
| Video Streaming | Minimize latency | _utility_latency |
| File Transfer | Maximize throughput | _utility_throughput |
| Conference Call | Minimize jitter | _utility_jitter |

### Reward Formula (Lines 358-388)

```python
def _reward(self, metrics, action_changed):
    lat = metrics[CONN_VIDEO].get("latency", 0.0)
    tp  = metrics[CONN_FILE].get("throughput_cwnd", 0.0) or ...
    jit = metrics[CONN_CONF].get("jitter", 0.0)

    u_stream = _utility_latency(lat)
    u_file   = _utility_throughput(tp)
    u_conf   = _utility_jitter(jit)

    mean_u = (u_stream + u_file + u_conf) / 3.0
    std_u = statistics.stdev([u_stream, u_file, u_conf])
    churn = MU_STABILITY if action_changed else 0.0

    return mean_u - LAMBDA_FAIRNESS * std_u - churn
```

### Reward Components

| Component | Formula | Weight | Range | Purpose |
|-----------|---------|--------|-------|---------|
| Mean Utility | (U_v + U_f + U_c) / 3 | 1.0 | [0, 1] | Maximize performance |
| Fairness Penalty | -std(U_v, U_f, U_c) | 0.10 | [-0.05, 0] | Balance connections |
| Stability Penalty | -1 if changed | 0.05 | [-0.05, 0] | Discourage thrashing |

### Reward Range

- **Best case:** All utilities = 1.0, no variance, no change
  - R = 1.0 - 0.10*0 - 0 = **1.0**

- **Worst case:** All utilities = 0.0, high variance, change made
  - R = 0.0 - 0.10*0.5 - 0.05 = **-0.10**

- **Typical case:** Mixed utilities ~0.5-0.7
  - R = 0.6 - 0.10*0.15 - 0.05 = **0.535**

**Verdict:** CORRECT - Well-designed multi-objective reward balancing performance, fairness, and stability.

---

## 5. Critical Bug: Stability Penalty

### Bug Location

**Lines 448-450 and 483-490:**

```python
# In __call__:
if self._last_state is not None and self._last_action is not None:
    changed = (self._last_action != ACTION_NOOP)  # BUG: Checks action index
    r = self._reward(metrics, changed)

# Later:
decisions = self._apply_action(action)
self._last_action = action  # Stores action index regardless of result
```

### Bug Description

When an action hits a parameter boundary, `_apply_action()` returns `{}` (no actual change), but `self._last_action` still stores the original action index. The next reward calculation sees `changed = True` even though no parameter change occurred.

### Example Scenario

1. Agent selects action 5 (decrease minimum_window for video)
2. Video's minimum_window is already at min (2)
3. `_apply_action(5)` detects boundary, returns `{}` (no change made)
4. `self._last_action = 5` (stores action index anyway)
5. Next step: `changed = (5 != 24) = True`
6. Stability penalty -0.05 is incorrectly applied

### Impact

- Agent is penalized for attempting actions at boundaries
- Creates incorrect negative signal when exploring boundary states
- May slow learning or cause suboptimal policy

### Recommended Fix

```python
# Track whether action actually changed something
decisions = self._apply_action(action)
self._last_action = action
self._last_action_resulted_in_change = bool(decisions)  # ADD THIS LINE

# In reward calculation (next step):
if self._last_state is not None and self._last_action is not None:
    changed = getattr(self, '_last_action_resulted_in_change', False)  # USE THIS
    r = self._reward(metrics, changed)
```

---

## 6. Minor Issues

### Issue: Initial Parameter Values Mismatch

**Location:** Lines 277-284

The initial `_params` values don't perfectly match `multi_connection_config.py`:

| Connection | Parameter | Andy's Init | Actual Default |
|------------|-----------|-------------|----------------|
| Video | packet_threshold | 4 | 2 |
| File | packet_threshold | 3 | 2 |
| Conf | packet_threshold | 3 | 2 |

**Impact:** Minor - `_sync_from_metrics()` corrects this on first tick by reading echoed values from workers.

### Issue: No Metric Validation

The code assumes metrics dictionary contains expected fields. Missing fields default to 0.0 via `.get()`, which is safe but could mask issues.

---

## 7. Code Quality Notes

### Strengths

1. **Clean separation** of concerns (state building, action encoding, reward calculation)
2. **Proper use of constants** for all hyperparameters
3. **Defensive coding** with clamping and bounds checking
4. **Good documentation** in docstrings and comments
5. **Checkpoint support** for saving/loading Q-table
6. **Detailed history** tracking for analysis

### Suggestions

1. Add type hints to all methods for clarity
2. Consider adding unit tests for action encoding/decoding
3. Add validation logging when unexpected metric values are received

---

## 8. Summary

### What's Working Correctly

- Q-learning Bellman update
- Epsilon-greedy action selection with decay
- 14-feature state design with proper indexing
- 25-action space with correct encoding/decoding
- Multi-objective reward function
- Parameter synchronization from workers
- Checkpoint save/load functionality

### What Needs Fixing

1. **CRITICAL:** Stability penalty bug - penalizes boundary-hitting actions incorrectly

### Recommendations

1. Fix the stability penalty bug (see Section 5)
2. Add logging when actions hit boundaries (for debugging)
3. Consider reducing stability penalty weight (0.05 -> 0.02) to encourage more exploration

---

## Appendix: Hyperparameters Reference

| Parameter | Value | Description |
|-----------|-------|-------------|
| ALPHA | 0.10 | Learning rate |
| GAMMA | 0.90 | Discount factor |
| EPSILON_START | 0.30 | Initial exploration rate |
| EPSILON_MIN | 0.05 | Minimum exploration rate |
| EPSILON_DECAY | 0.995 | Decay per decision step |
| CONTROL_INTERVAL | 2.0s | Time between Q-learning decisions |
| LAMBDA_FAIRNESS | 0.10 | Fairness penalty weight |
| MU_STABILITY | 0.05 | Stability penalty weight |
| LATENCY_BEST | 0.020s | Best latency (20ms) |
| LATENCY_WORST | 0.200s | Worst latency (200ms) |
| THROUGHPUT_MAX | 3,750,000 B/s | Max throughput (30 Mbps) |
| JITTER_WORST | 0.050s | Worst jitter (50ms) |
