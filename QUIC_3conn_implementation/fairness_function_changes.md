# Fairness Function Changes for Q-Learning Agents

**Date:** May 19, 2026
**Status:** IMPLEMENTED
**Purpose:** Improve reward function to better achieve balanced connections while respecting each connection's goals.

---

## Goals

1. **File gets highest throughput** - It's the only connection with 100% throughput utility
2. **Understand goals** - Respect each connection's primary objective (latency/throughput/jitter)
3. **No suffering** - Penalize only when a connection is struggling (utility < 0.4)
4. **No starvation** - Ensure minimum viable throughput for all connections
5. **Stability** - Avoid excessive parameter changes

**Key insight:** We want file to excel at throughput, as long as video/conference aren't suffering. We do NOT want strict utility equality.

---

## Current Implementation (After Changes)

### Reward Formula

```python
R = mean(U_video, U_file, U_conf)
    - μ × changed                         # Stability penalty (μ=0.05)
    - starvation_penalty                  # 0.2 per connection below 500 KB/s
    - suffering_penalty                   # 0.15 per connection with utility < 0.4
```

### Per-Connection Utilities

| Connection | Utility Formula | Primary Goal |
|------------|-----------------|--------------|
| Video | `0.7 × latency_util + 0.3 × throughput_util` | Low latency |
| File | `1.0 × throughput_util` | High throughput |
| Conference | `0.7 × jitter_util + 0.3 × throughput_util` | Low jitter |

### Current Constants (UPDATED)

```python
THROUGHPUT_MAX = 1_250_000             # 10 Mbps - fair share of 30 Mbps link
MU_STABILITY = 0.05                    # Stability penalty weight
MIN_VIABLE_THROUGHPUT = 500_000        # 500 KB/s minimum (throughput-based)
STARVATION_PENALTY = 0.2               # Per starving connection
UTILITY_SUFFERING_THRESHOLD = 0.4      # Below this = suffering (utility-based)
UTILITY_SUFFERING_PENALTY = 0.15       # Per suffering connection
```

### Option B Fairness (Implemented)

Instead of penalizing ALL utility differences (strict equality), we only penalize when a connection is **suffering** (utility < 0.4).

| Scenario | Old Approach (Option A) | New Approach (Option B) |
|----------|-------------------------|-------------------------|
| Video=0.9, File=0.7, Conf=0.6 | Penalized (unequal) | **OK** (no one suffering) |
| Video=0.8, File=0.3, Conf=0.7 | Penalized (unequal) | **Penalized** (file < 0.4) |
| Video=0.5, File=0.5, Conf=0.5 | Perfect (equal) | OK (no one suffering) |

---

## Identified Problems

### Problem 1: THROUGHPUT_MAX is Unrealistic

**Current:** `THROUGHPUT_MAX = 30 Mbps`

With a 30 Mbps shared bottleneck and 3 connections:
- Each connection can realistically get ~10 Mbps (fair share)
- File utility = 10 Mbps / 30 Mbps = **0.33 maximum**
- This severely limits achievable rewards (~0.30 range)

**Example:**
| Throughput | Current Utility | Problem |
|------------|-----------------|---------|
| 9 Mbps | 9/30 = 0.30 | "Poor" despite being a good share |
| 6 Mbps | 6/30 = 0.20 | "Very poor" despite being reasonable |
| 3 Mbps | 3/30 = 0.10 | "Terrible" despite meeting app needs |

### Problem 2: Fairness Penalty Balances Utilities, Not Throughput

The current fairness penalty (`λ × std(utilities)`) balances **utility happiness**, not **bandwidth sharing**.

**Problematic Scenario:**
| Connection | Throughput | Utility | Assessment |
|------------|------------|---------|------------|
| Video | 2 Mbps | 0.80 | Happy (great latency) |
| File | 10 Mbps | 0.33 | Sad (low utility despite high bandwidth) |
| Conference | 2 Mbps | 0.75 | Happy (great jitter) |

The agent sees similar utilities (0.80, 0.33, 0.75) and may not realize file is consuming 5x more bandwidth than others. The fairness penalty doesn't directly discourage bandwidth hogging.

### Problem 3: Stability Penalty is Weak

**Current:** `MU_STABILITY = 0.05`

This small penalty may not sufficiently discourage excessive parameter changes, leading to:
- Oscillating parameters
- Unstable connections
- Suboptimal convergence

---

## Proposed Changes

### Change 1: Lower THROUGHPUT_MAX (High Priority)

**From:**
```python
THROUGHPUT_MAX = 3_750_000  # 30 Mbps - full link capacity
```

**To:**
```python
THROUGHPUT_MAX = 1_250_000  # 10 Mbps - fair share of 30 Mbps link
```

**Rationale:**
- 30 Mbps / 3 connections = 10 Mbps per connection (fair share)
- "Excellent" throughput should mean "achieving your fair share"
- Not "saturating the entire shared link alone"

**Impact:**
| Throughput | Old Utility | New Utility |
|------------|-------------|-------------|
| 10 Mbps | 0.33 | **1.00** |
| 8 Mbps | 0.27 | **0.80** |
| 6 Mbps | 0.20 | **0.60** |
| 4 Mbps | 0.13 | **0.40** |

**Expected reward increase:** From ~0.30 to ~0.50-0.65

---

### Change 2: Add Throughput Fairness Penalty (Medium Priority)

**Add new constant:**
```python
LAMBDA_TP_FAIRNESS = 0.10  # Throughput distribution fairness weight
```

**Modify reward calculation:**
```python
def _reward(self, metrics: Dict[int, dict], action_changed: bool) -> float:
    # ... existing utility calculations ...

    # NEW: Throughput fairness penalty
    # Penalizes uneven bandwidth distribution directly
    tp_values = [video_tp, file_tp, conf_tp]
    tp_mean = sum(tp_values) / len(tp_values)
    if tp_mean > 0:
        try:
            tp_std = statistics.stdev(tp_values)
            tp_cv = tp_std / tp_mean  # Coefficient of variation (0 = perfect equality)
        except statistics.StatisticsError:
            tp_cv = 0.0
    else:
        tp_cv = 0.0

    tp_fairness_penalty = LAMBDA_TP_FAIRNESS * tp_cv

    return mean_u - LAMBDA_FAIRNESS * std_u - tp_fairness_penalty - churn - starvation
```

**Rationale:**
- Directly penalizes uneven throughput distribution
- Uses coefficient of variation (std/mean) for scale-invariance
- Complements utility fairness (which balances "happiness")

**Example Impact:**
| Video TP | File TP | Conf TP | CV | Penalty |
|----------|---------|---------|-----|---------|
| 5 Mbps | 5 Mbps | 5 Mbps | 0.0 | 0.00 |
| 4 Mbps | 8 Mbps | 3 Mbps | 0.53 | 0.053 |
| 2 Mbps | 10 Mbps | 2 Mbps | 0.98 | 0.098 |

---

### Change 3: Increase Stability Penalty (Low Priority)

**From:**
```python
MU_STABILITY = 0.05  # Very weak
```

**To:**
```python
MU_STABILITY = 0.10  # Moderate
```

**Rationale:**
- Discourages excessive parameter tweaking
- Promotes convergence to stable policies
- Still allows necessary adjustments (not too restrictive)

**Trade-off:**
- Higher penalty = more stable but slower adaptation
- Lower penalty = faster adaptation but more oscillation
- 0.10 is a balanced middle ground

---

## Summary of Changes

| Change | Current | Proposed | Priority |
|--------|---------|----------|----------|
| `THROUGHPUT_MAX` | 30 Mbps | **10 Mbps** | High |
| Throughput fairness penalty | None | **0.10 × CV** | Medium |
| `MU_STABILITY` | 0.05 | **0.10** | Low |

---

## Implementation Checklist

Files to modify:
- [ ] `ml_callbacks/q_learning_agent.py` (Default agent)
- [ ] `ml_callbacks/q_learning_agent_andy.py` (Andy agent)
- [ ] `ml_callbacks/q_learning_agent_hybrid.py` (Hybrid agent)

For each file:
1. [ ] Change `THROUGHPUT_MAX` from 3,750,000 to 1,250,000
2. [ ] Add `LAMBDA_TP_FAIRNESS = 0.10` constant
3. [ ] Add throughput fairness calculation in `_reward()` method
4. [ ] Change `MU_STABILITY` from 0.05 to 0.10

---

## Expected Outcomes

### Before Changes
- Reward range: ~0.25-0.35
- File utility: ~0.10-0.30 (always "poor")
- Throughput hogging: Not directly penalized

### After Changes
- Reward range: ~0.50-0.70
- File utility: ~0.60-1.00 (realistic)
- Throughput hogging: Directly penalized via CV
- More stable parameter convergence

---

## Testing Plan

1. **Clear Q-tables** - Start fresh training after changes
2. **Train all agents** - Run training script for all 3 agents
3. **Compare metrics:**
   - Average reward (expect ~0.50-0.65)
   - Throughput distribution (expect more balanced)
   - Parameter change frequency (expect fewer changes)
4. **Validate no starvation** - Ensure all connections stay above 500 KB/s

---

## Code Snippets for Implementation

### Updated Constants (all agents)

```python
# Throughput normalization - fair share of 30 Mbps shared link
THROUGHPUT_MAX = 1_250_000  # 10 Mbps (1.25 MB/s) per connection

# Reward penalty weights
LAMBDA_FAIRNESS = 0.25      # Utility fairness penalty weight
LAMBDA_TP_FAIRNESS = 0.10   # Throughput distribution fairness weight
MU_STABILITY = 0.10         # Stability penalty weight (increased from 0.05)
```

### Updated Reward Function

```python
def _reward(self, metrics: Dict[int, dict], action_changed: bool) -> float:
    if not all(c in metrics for c in CONNECTIONS):
        return 0.0

    # Get metrics for each connection
    video_lat = metrics[CONN_VIDEO].get("latency", 0.0)
    video_tp  = _get_throughput(metrics, CONN_VIDEO)
    file_tp   = _get_throughput(metrics, CONN_FILE)
    conf_jit  = metrics[CONN_CONF].get("jitter", 0.0)
    conf_tp   = _get_throughput(metrics, CONN_CONF)

    # Compute per-connection utilities
    u_video = 0.7 * _utility_latency(video_lat) + 0.3 * _utility_throughput(video_tp)
    u_file = _utility_throughput(file_tp)
    u_conf = 0.7 * _utility_jitter(conf_jit) + 0.3 * _utility_throughput(conf_tp)

    mean_u = (u_video + u_file + u_conf) / 3.0

    # Utility fairness penalty
    try:
        std_u = statistics.stdev([u_video, u_file, u_conf])
    except statistics.StatisticsError:
        std_u = 0.0

    # NEW: Throughput fairness penalty (coefficient of variation)
    tp_values = [video_tp, file_tp, conf_tp]
    tp_mean = sum(tp_values) / len(tp_values)
    if tp_mean > 0:
        try:
            tp_std = statistics.stdev(tp_values)
            tp_cv = tp_std / tp_mean
        except statistics.StatisticsError:
            tp_cv = 0.0
    else:
        tp_cv = 0.0
    tp_fairness_penalty = LAMBDA_TP_FAIRNESS * tp_cv

    # Stability penalty
    churn = MU_STABILITY if action_changed else 0.0

    # Starvation penalty
    starvation = 0.0
    for conn_id, tp in [(CONN_VIDEO, video_tp), (CONN_FILE, file_tp), (CONN_CONF, conf_tp)]:
        if tp < MIN_VIABLE_THROUGHPUT:
            starvation += STARVATION_PENALTY

    return mean_u - LAMBDA_FAIRNESS * std_u - tp_fairness_penalty - churn - starvation
```

---

## Notes

- These changes should be applied to all 3 agents for consistency
- Q-tables must be cleared and agents retrained after changes
- Monitor for unintended consequences (e.g., file transfer becoming too conservative)
- The throughput fairness penalty may need tuning (0.10 is a starting point)
