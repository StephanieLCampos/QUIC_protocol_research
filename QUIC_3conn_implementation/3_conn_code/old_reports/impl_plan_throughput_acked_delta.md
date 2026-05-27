# Implementation Plan: Per-Epoch Delta ACK-Based Throughput

## Overview

This plan details how to implement a **windowed/per-epoch** throughput measurement that responds quickly to changing network conditions.

**Metric**: `throughput_acked_delta` (per-epoch)
**Formula**: `(bytes_acked_now - bytes_acked_prev) / epoch_duration`
**Use Case**: Q-learning under varying network conditions
**Responsiveness**: High (shows throughput for current epoch only)

---

## Why This Metric is Needed

The cumulative `throughput_acked` averages over the entire connection lifetime, making it slow to respond:

| Scenario | Cumulative Response | Delta Response |
|----------|---------------------|----------------|
| `stable_high` (100 Mbps) | Good | Good |
| `congested_low` (5 Mbps) | Good | Good |
| `varying` (20 Mbps ±40%) | **Slow** - lags behind | **Fast** - tracks changes |
| `lossy` (10 Mbps, 5% loss) | Good | Good |
| `asymmetric` (50/10 Mbps) | Good | Good |

For `varying` and any future dynamic scenarios, Q-learning needs responsive feedback.

---

## Current State

This metric **does not exist** and needs to be implemented:

| Component | Status | Location |
|-----------|--------|----------|
| Delta tracking in collector | ❌ New | `collector.py` |
| Delta throughput calculation | ❌ New | `collector.py` |
| IPC payload includes it | ❌ New | `worker_process.py` |
| Q-learning uses it | ❌ New | `q_learning_agent.py` |

---

## Implementation Steps

### Step 1: Add Delta Tracking to MetricsCollector

**File**: `metrics/collector.py`

**IMPORTANT**: `MetricsCollector` is a `@dataclass`, so new fields must be added as class-level field definitions, NOT in `__init__`.

**Location**: Add after existing field definitions (around line 58-61, after `_epoch_packets_offset`)

**Add these dataclass fields**:

```python
@dataclass
class MetricsCollector:
    # ... existing fields ...

    # Internal state for epoch reset
    _epoch_bytes_offset: int = 0
    _epoch_packets_offset: int = 0

    # Delta tracking for per-epoch throughput (NEW)
    _prev_bytes_acked: int = 0
    _prev_delta_time: Optional[float] = None
    _last_delta_throughput: float = 0.0
```

**Add new method (after `calculate_metrics` method, around line 220)**:

```python
def get_throughput_acked_delta(self) -> float:
    """
    Calculate throughput for the current epoch only (responsive to changes).

    Returns bytes/second for the period since last call, not cumulative average.
    This is useful for Q-learning under varying network conditions.
    """
    now = time.time()

    # First call - initialize and return 0
    if self._prev_delta_time is None:
        self._prev_delta_time = now
        self._prev_bytes_acked = self.bytes_acked
        return 0.0

    elapsed = now - self._prev_delta_time

    # Avoid division by zero and too-frequent calls
    if elapsed < 0.1:  # Minimum 100ms between delta calculations
        return self._last_delta_throughput

    # Calculate delta
    delta_bytes = self.bytes_acked - self._prev_bytes_acked
    delta_throughput = delta_bytes / elapsed if elapsed > 0 else 0.0

    # Update tracking for next call
    self._prev_bytes_acked = self.bytes_acked
    self._prev_delta_time = now
    self._last_delta_throughput = delta_throughput

    return delta_throughput

def reset_delta_tracking(self):
    """Reset delta tracking (call at epoch boundaries if needed)."""
    self._prev_bytes_acked = self.bytes_acked
    self._prev_delta_time = time.time()
    self._last_delta_throughput = 0.0
```

**Update `reset` method (around line 215)**:

```python
def reset(self):
    """Reset all metrics for a new measurement period."""
    # ... existing resets ...

    # Reset delta tracking
    self._prev_bytes_acked = 0
    self._prev_delta_time = None
    self._last_delta_throughput = 0.0
```

**Update `reset_for_new_epoch` method (around line 288)**:

```python
def reset_for_new_epoch(self):
    """
    Soft reset for new epoch measurement.
    """
    # ... existing code ...

    # Reset delta tracking for fresh epoch measurement (NEW)
    # Keep current bytes_acked as the baseline for next delta
    self._prev_bytes_acked = self.bytes_acked
    self._prev_delta_time = time.time()
    self._last_delta_throughput = 0.0
```

---

### Step 2: Add Delta to get_summary Method

**File**: `metrics/collector.py`
**Location**: `get_summary` method (around line 240)

**Add to the returned dictionary**:

```python
def get_summary(self) -> dict:
    """Get a summary of collected metrics."""
    # ... existing code ...

    return {
        # ... existing fields ...
        "throughput_acked_bps": throughput_acked,
        "throughput_acked_delta_bps": self.get_throughput_acked_delta(),  # NEW
        # ... rest of fields ...
    }
```

---

### Step 3: Add Delta to IPC Payload

**File**: `simulation/worker_process.py`
**Location**: `_send_metrics` method (lines 138-159)

**Modified code**:

```python
def _send_metrics(self):
    """Send current metrics to main process."""
    metrics = self._metrics_collector.calculate_metrics()

    # Get delta throughput (per-epoch, responsive)
    throughput_acked_delta = self._metrics_collector.get_throughput_acked_delta()

    msg = IPCMessage(
        msg_type=MessageType.METRICS,
        connection_id=self.config.connection_id,
        timestamp=time.time(),
        payload={
            "throughput": metrics.throughput,
            "throughput_acked": metrics.throughput_acked,        # Cumulative
            "throughput_acked_delta": throughput_acked_delta,    # Per-epoch (NEW)
            "rtt": metrics.rtt,
            "latency": metrics.latency,
            "jitter": metrics.jitter,
            "packet_loss_rate": metrics.packet_loss_rate,
            "bytes_sent": self._metrics_collector.bytes_sent,
            "bytes_acked": metrics.bytes_acked,
            "current_params": {
                "loss_reduction_factor": self.config.loss_reduction_factor,
                "cubic_c": self.config.cubic_c,
                "minimum_window": self.config.minimum_window,
            },
        },
    )
    self.metrics_queue.put(msg)
```

---

### Step 4: Update Q-Learning to Use Delta Throughput

**File**: `ml_callbacks/q_learning_agent.py`

#### 4a. Add Configuration Flag (top of file, around line 87)

```python
# Throughput metric selection
# Use delta (per-epoch) for varying conditions, cumulative for stable conditions
USE_DELTA_THROUGHPUT = True  # Set to False for cumulative
```

#### 4b. Update `_build_state` Method (lines 317-341)

```python
def _build_state(self, metrics: Dict[int, dict]) -> Optional[Tuple]:
    if not all(c in metrics for c in CONNECTIONS):
        return None

    lat = metrics[CONN_VIDEO].get("latency", 0.0)

    # Use delta throughput for responsiveness, cumulative for stability
    if USE_DELTA_THROUGHPUT:
        tp = metrics[CONN_FILE].get("throughput_acked_delta", 0.0)
    else:
        tp = metrics[CONN_FILE].get("throughput_acked", 0.0)

    jit = metrics[CONN_CONF].get("jitter", 0.0)

    # ... rest of method unchanged ...
```

#### 4c. Update `_reward` Method (lines 345-372)

```python
def _reward(self, metrics: Dict[int, dict], action_changed: bool) -> float:
    if not all(c in metrics for c in CONNECTIONS):
        return 0.0

    lat = metrics[CONN_VIDEO].get("latency", 0.0)

    # Use delta throughput for responsiveness
    if USE_DELTA_THROUGHPUT:
        tp = metrics[CONN_FILE].get("throughput_acked_delta", 0.0)
    else:
        tp = metrics[CONN_FILE].get("throughput_acked", 0.0)

    jit = metrics[CONN_CONF].get("jitter", 0.0)

    # ... rest of method unchanged ...
```

#### 4d. Update `_log` Method (lines 468-490)

```python
def _log(self, state, action, decisions, metrics):
    lat_ms = metrics.get(CONN_VIDEO, {}).get("latency", 0.0) * 1000

    # Log both for comparison
    tp_cumulative = metrics.get(CONN_FILE, {}).get("throughput_acked", 0.0) * 8 / 1e6
    tp_delta = metrics.get(CONN_FILE, {}).get("throughput_acked_delta", 0.0) * 8 / 1e6
    tp_mbs = tp_delta if USE_DELTA_THROUGHPUT else tp_cumulative

    jit_ms = metrics.get(CONN_CONF, {}).get("jitter", 0.0) * 1000

    # ... rest of logging ...

    print(
        f"[QLAgent step={self.step_count:4d}] "
        f"state={state} action={act_str} "
        f"ε={self.epsilon:.3f} "
        f"lat={lat_ms:.1f}ms tp={tp_mbs:.2f}Mbps (Δ={tp_delta:.2f}) jit={jit_ms:.1f}ms "
        f"avg_R={avg_r:+.3f} Q-states={len(self._q)}"
    )
```

---

### Step 5: Adjust Throughput Bins for Delta Measurement

The delta measurement can be more variable than cumulative. Consider adjusting bins:

**File**: `ml_callbacks/q_learning_agent.py`
**Location**: Lines 101-103

**Current bins** (for high throughput scenarios):

```python
THROUGHPUT_BINS = [1_000_000, 2_000_000, 3_000_000]  # bytes/s
THROUGHPUT_MAX = 3_750_000.0  # 30 Mbps
```

**Option: Scenario-aware bins**:

```python
# Adaptive bins based on expected throughput range
def get_throughput_bins(scenario: str) -> Tuple[List[int], float]:
    """Return (bins, max) based on scenario."""
    if scenario in ("congested_low",):
        # 5 Mbps cap = 625 KB/s max
        return [100_000, 250_000, 450_000], 625_000.0
    elif scenario in ("lossy",):
        # 10 Mbps cap = 1.25 MB/s max
        return [200_000, 500_000, 900_000], 1_250_000.0
    elif scenario in ("varying",):
        # 20 Mbps ±40% = 12-28 Mbps range
        return [500_000, 1_500_000, 2_500_000], 3_500_000.0
    else:
        # Default high throughput
        return [1_000_000, 2_000_000, 3_000_000], 3_750_000.0
```

**Note**: This is optional and can be added later after testing.

---

## Files Changed Summary

| File | Changes |
|------|---------|
| `metrics/collector.py` | Add `_prev_bytes_acked`, `_prev_delta_time`, `get_throughput_acked_delta()`, update `reset()` |
| `simulation/worker_process.py` | Add `throughput_acked_delta` to IPC payload |
| `ml_callbacks/q_learning_agent.py` | Add `USE_DELTA_THROUGHPUT` flag, update `_build_state`, `_reward`, `_log` |

---

## Timing Considerations

### When is Delta Calculated?

The delta is calculated on each `_send_metrics()` call (~100ms interval):

```
t=0.0s:   _send_metrics() → delta = 0 (first call)
t=0.1s:   _send_metrics() → delta = (bytes_acked - prev) / 0.1s
t=0.2s:   _send_metrics() → delta = (bytes_acked - prev) / 0.1s
...
t=2.0s:   Q-learning reads latest delta value
```

### Alignment with Q-Learning Interval

**IMPORTANT CAVEAT**: Q-learning decides every 2 seconds, but the delta represents only the most recent ~100ms window, NOT the full 2s epoch.

```
Q-Learning Timeline:
├──────────────────────────────────────────┤
0s                                        2s
        ↑ Q-learning reads delta here
        │
        └── Delta only covers last ~100ms (t=1.9s to t=2.0s)
            NOT the full 0s to 2s window
```

**Implications**:
- If bandwidth fluctuates within the 2s interval, Q-learning only sees the final ~100ms
- Spikes or drops earlier in the interval are missed
- For most scenarios this is acceptable since network conditions change slowly

**Alternative (Recommended for True Epoch Alignment)**: Calculate delta over the full Q-learning interval in the agent itself:

```python
# In q_learning_agent.py __init__, add:
self._prev_epoch_bytes_acked: Dict[int, int] = {}
self._prev_epoch_time: float = 0.0

# Add this method:
def _get_epoch_throughput(self, metrics: Dict[int, dict], conn_id: int) -> float:
    """
    Calculate throughput over the full Q-learning control interval.

    This gives throughput for the entire 2-second epoch, not just the last 100ms.
    """
    current_acked = metrics[conn_id].get("bytes_acked", 0)
    prev_acked = self._prev_epoch_bytes_acked.get(conn_id, 0)

    delta = current_acked - prev_acked
    throughput = delta / self.control_interval  # 2 seconds

    # Update for next epoch
    self._prev_epoch_bytes_acked[conn_id] = current_acked
    return throughput

# Then use in _build_state():
def _build_state(self, metrics: Dict[int, dict]) -> Optional[Tuple]:
    # ...
    tp = self._get_epoch_throughput(metrics, CONN_FILE)
    # ...
```

**Recommendation**:
- **Option A (Simpler)**: Start with per-IPC-tick delta from collector. Good for most scenarios.
- **Option B (More Accurate)**: Use agent-side epoch calculation for true 2-second averaging. Better for highly variable conditions.

Both approaches require `bytes_acked` to be in the IPC payload (added in Plan 1).

---

## Testing Plan

### Unit Test: Delta Calculation

```python
def test_delta_throughput_calculation():
    collector = MetricsCollector(connection_id=1)

    # Simulate bytes_acked increasing over time
    collector.bytes_acked = 0
    t1 = collector.get_throughput_acked_delta()  # First call, returns 0

    time.sleep(0.2)
    collector.bytes_acked = 100_000  # 100 KB in 0.2s = 500 KB/s
    t2 = collector.get_throughput_acked_delta()

    assert abs(t2 - 500_000) < 50_000  # Within 10% tolerance
```

### Integration Test: Varying Scenario

```bash
# Run with varying scenario
uv run python -m main run --with-ml --scenario varying --duration 60

# Observe Q-learning logs
# Delta throughput should track bandwidth changes:
# - When BW is high: delta shows high throughput
# - When BW is low: delta shows low throughput quickly (not averaged)
```

### Comparison Test: Cumulative vs Delta

Run the same scenario twice:
1. With `USE_DELTA_THROUGHPUT = False` (cumulative)
2. With `USE_DELTA_THROUGHPUT = True` (delta)

Compare Q-learning adaptation speed in varying conditions.

---

## Potential Issues and Mitigations

### Issue 1: Noisy Delta Values

Delta can fluctuate more than cumulative average.

**Mitigation**: Apply exponential moving average (EMA) smoothing:

```python
def get_throughput_acked_delta_smoothed(self, alpha: float = 0.3) -> float:
    """EMA-smoothed delta throughput."""
    raw_delta = self.get_throughput_acked_delta()
    self._ema_delta = alpha * raw_delta + (1 - alpha) * self._ema_delta
    return self._ema_delta
```

### Issue 2: Zero Delta on First Calls

First few calls return 0 while tracking initializes.

**Mitigation**: Fall back to cumulative if delta is 0:

```python
tp_delta = metrics[CONN_FILE].get("throughput_acked_delta", 0.0)
if tp_delta == 0:
    tp_delta = metrics[CONN_FILE].get("throughput_acked", 0.0)
```

### Issue 3: Race Condition on Reset

If `reset()` is called during delta calculation.

**Mitigation**: The current design doesn't share state across threads, so this shouldn't occur.

---

## Configuration Options

Add to `q_learning_agent.py` for flexibility:

```python
# Throughput measurement configuration
THROUGHPUT_METRIC = "delta"  # Options: "offered", "acked", "delta"

def _get_throughput(self, metrics: Dict[int, dict], conn_id: int) -> float:
    """Get throughput based on configured metric type."""
    if THROUGHPUT_METRIC == "offered":
        return metrics[conn_id].get("throughput", 0.0)
    elif THROUGHPUT_METRIC == "acked":
        return metrics[conn_id].get("throughput_acked", 0.0)
    elif THROUGHPUT_METRIC == "delta":
        delta = metrics[conn_id].get("throughput_acked_delta", 0.0)
        # Fall back to cumulative if delta not available
        return delta if delta > 0 else metrics[conn_id].get("throughput_acked", 0.0)
    else:
        return metrics[conn_id].get("throughput", 0.0)
```

---

## Rollback Plan

If delta throughput causes issues:

1. Set `USE_DELTA_THROUGHPUT = False` in q_learning_agent.py
2. Or set `THROUGHPUT_METRIC = "acked"` to use cumulative
3. Delta code remains but is not used

---

## Dependencies

This implementation depends on:
1. Cumulative `throughput_acked` being implemented first (see `impl_plan_throughput_acked_cumulative.md`)
2. `bytes_acked` being accurately tracked in `collector.py`

---

## Next Steps

1. Implement cumulative `throughput_acked` first
2. Test under stable scenario (`congested_low`)
3. Implement delta throughput
4. Test under varying scenario
5. Compare Q-learning performance with both metrics
6. Tune throughput bins if needed
