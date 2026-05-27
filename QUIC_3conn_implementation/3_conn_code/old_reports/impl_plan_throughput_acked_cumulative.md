# Implementation Plan: Cumulative ACK-Based Throughput

## Overview

This plan details how to wire the existing `throughput_acked` metric (cumulative average) through IPC to make it available for Q-learning.

**Metric**: `throughput_acked` (cumulative)
**Formula**: `bytes_acked / total_duration`
**Use Case**: Steady-state analysis, final results, stable network conditions
**Responsiveness**: Low (averages over entire connection lifetime)

---

## Current State

The metric **already exists** but is not exposed to Q-learning:

| Component | Status | Location |
|-----------|--------|----------|
| `bytes_acked` calculation | ✅ Implemented | `collector.py:152-154` |
| `throughput_acked` field | ✅ Defined | `calculator.py:25` |
| `throughput_acked` calculation | ✅ Implemented | `collector.py:265` |
| IPC payload includes it | ❌ Missing | `worker_process.py:145-157` |
| Q-learning uses it | ❌ Missing | `q_learning_agent.py:324-326` |

---

## Implementation Steps

### Step 1: Add `throughput_acked` to IPC Payload

**File**: `simulation/worker_process.py`
**Location**: Lines 138-159 (`_send_metrics` method)

**Current code**:
```python
def _send_metrics(self):
    """Send current metrics to main process."""
    metrics = self._metrics_collector.calculate_metrics()
    msg = IPCMessage(
        msg_type=MessageType.METRICS,
        connection_id=self.config.connection_id,
        timestamp=time.time(),
        payload={
            "throughput": metrics.throughput,
            "rtt": metrics.rtt,
            "latency": metrics.latency,
            "jitter": metrics.jitter,
            "packet_loss_rate": metrics.packet_loss_rate,
            "bytes_sent": self._metrics_collector.bytes_sent,
            "current_params": {
                "loss_reduction_factor": self.config.loss_reduction_factor,
                "cubic_c": self.config.cubic_c,
                "minimum_window": self.config.minimum_window,
            },
        },
    )
    self.metrics_queue.put(msg)
```

**Modified code**:
```python
def _send_metrics(self):
    """Send current metrics to main process."""
    metrics = self._metrics_collector.calculate_metrics()
    msg = IPCMessage(
        msg_type=MessageType.METRICS,
        connection_id=self.config.connection_id,
        timestamp=time.time(),
        payload={
            "throughput": metrics.throughput,
            "throughput_acked": metrics.throughput_acked,  # NEW
            "rtt": metrics.rtt,
            "latency": metrics.latency,
            "jitter": metrics.jitter,
            "packet_loss_rate": metrics.packet_loss_rate,
            "bytes_sent": self._metrics_collector.bytes_sent,
            "bytes_acked": metrics.bytes_acked,  # NEW (useful for debugging)
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

### Step 2: Update Q-Learning State Building

**File**: `ml_callbacks/q_learning_agent.py`
**Location**: Lines 317-341 (`_build_state` method)

**Current code**:
```python
def _build_state(self, metrics: Dict[int, dict]) -> Optional[Tuple]:
    if not all(c in metrics for c in CONNECTIONS):
        return None

    lat = metrics[CONN_VIDEO].get("latency",    0.0)
    tp  = metrics[CONN_FILE ].get("throughput", 0.0)  # ← OFFERED
    jit = metrics[CONN_CONF ].get("jitter",     0.0)
    # ... rest of method
```

**Modified code**:
```python
def _build_state(self, metrics: Dict[int, dict]) -> Optional[Tuple]:
    if not all(c in metrics for c in CONNECTIONS):
        return None

    lat = metrics[CONN_VIDEO].get("latency",    0.0)
    tp  = metrics[CONN_FILE ].get("throughput_acked", 0.0)  # ← ACK-VERIFIED
    jit = metrics[CONN_CONF ].get("jitter",     0.0)
    # ... rest of method
```

---

### Step 3: Update Q-Learning Reward Calculation

**File**: `ml_callbacks/q_learning_agent.py`
**Location**: Lines 345-372 (`_reward` method)

**Current code**:
```python
def _reward(self, metrics: Dict[int, dict], action_changed: bool) -> float:
    if not all(c in metrics for c in CONNECTIONS):
        return 0.0

    lat = metrics[CONN_VIDEO].get("latency",    0.0)
    tp  = metrics[CONN_FILE ].get("throughput", 0.0)  # ← OFFERED
    jit = metrics[CONN_CONF ].get("jitter",     0.0)
    # ... rest of method
```

**Modified code**:
```python
def _reward(self, metrics: Dict[int, dict], action_changed: bool) -> float:
    if not all(c in metrics for c in CONNECTIONS):
        return 0.0

    lat = metrics[CONN_VIDEO].get("latency",    0.0)
    tp  = metrics[CONN_FILE ].get("throughput_acked", 0.0)  # ← ACK-VERIFIED
    jit = metrics[CONN_CONF ].get("jitter",     0.0)
    # ... rest of method
```

---

### Step 4: Update Q-Learning Logging

**File**: `ml_callbacks/q_learning_agent.py`
**Location**: Lines 468-490 (`_log` method)

**Current code**:
```python
def _log(self, state, action, decisions, metrics):
    lat_ms = metrics.get(CONN_VIDEO, {}).get("latency",    0.0) * 1000
    tp_mbs = metrics.get(CONN_FILE,  {}).get("throughput", 0.0) * 8 / 1e6  # ← OFFERED
    jit_ms = metrics.get(CONN_CONF,  {}).get("jitter",     0.0) * 1000
    # ... rest of method
```

**Modified code**:
```python
def _log(self, state, action, decisions, metrics):
    lat_ms = metrics.get(CONN_VIDEO, {}).get("latency",    0.0) * 1000
    tp_mbs = metrics.get(CONN_FILE,  {}).get("throughput_acked", 0.0) * 8 / 1e6  # ← ACK-VERIFIED
    jit_ms = metrics.get(CONN_CONF,  {}).get("jitter",     0.0) * 1000
    # ... rest of method
```

---

### Step 5: Update Throughput Bins (Optional)

The current throughput bins in Q-learning are scaled for offered throughput (up to 3 MB/s = 24 Mbps):

```python
THROUGHPUT_BINS = [1_000_000, 2_000_000, 3_000_000]  # bytes/s
THROUGHPUT_MAX = 3_750_000.0  # 30 Mbps in bytes/s
```

For bottlenecked scenarios (5 Mbps = 625 KB/s), these bins may need adjustment:

**Option A**: Keep current bins (File Transfer will always be in bin 0)
**Option B**: Add scenario-aware bins:

```python
# For congested_low (5 Mbps bottleneck)
THROUGHPUT_BINS_LOW = [100_000, 300_000, 500_000]  # 0.8, 2.4, 4 Mbps
THROUGHPUT_MAX_LOW = 625_000.0  # 5 Mbps in bytes/s
```

**Recommendation**: Start with Option A, evaluate after testing.

---

## Files Changed Summary

| File | Changes |
|------|---------|
| `simulation/worker_process.py` | Add `throughput_acked` and `bytes_acked` to IPC payload |
| `ml_callbacks/q_learning_agent.py` | Use `throughput_acked` in `_build_state`, `_reward`, `_log` |

---

## Testing Plan

### Unit Test: Verify IPC Payload

```python
# Verify throughput_acked is in metrics
def test_ipc_includes_throughput_acked():
    # Mock metrics collector with known values
    # Call _send_metrics()
    # Assert payload contains "throughput_acked"
```

### Integration Test: Verify Q-Learning Receives Metric

```bash
# Run with Q-learning and check logs
uv run python -m main run --with-ml --scenario congested_low --duration 30

# Verify log shows realistic throughput (not 221 Mbps for File Transfer)
# Expected: ~1-2 Mbps under 5 Mbps bottleneck
```

### Validation: Compare to Receiver Throughput

After simulation, compare:
- `throughput_acked` from Q-learning logs
- `receiver_throughput_mbps` from results JSON

They should be within ~10% of each other.

---

## Rollback Plan

If issues arise, revert to using `throughput` (offered):

```python
# In q_learning_agent.py
tp = metrics[CONN_FILE].get("throughput", 0.0)  # Revert to offered
```

---

## Limitations

1. **Cumulative average**: Slow to respond to network changes
2. **Not suitable for varying scenarios**: Use `throughput_acked_delta` instead
3. **RTT lag**: Reflects delivery from ~40ms ago

---

## Next Steps

After implementing this:
1. Test under `congested_low` scenario
2. Verify Q-learning sees realistic throughput values
3. If varying scenarios needed, implement `throughput_acked_delta`
