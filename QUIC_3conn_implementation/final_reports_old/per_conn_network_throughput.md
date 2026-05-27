# Implementation Plan: Per-Connection Actual Network Throughput

## Goal

Add actual network throughput (bytes that made it through the bottleneck) per connection to the simulation results, alongside the existing offered throughput metrics.

---

## Current State

### What We Have
- `tc_sent_bytes`: Total bytes transmitted through the tc qdisc (bottleneck)
- `tc_observed_throughput_bps`: Total throughput through the bottleneck
- Per-connection `bytes_sent`: Bytes pushed into QUIC stack (offered, not actual)
- Per-connection `offered_throughput_median_mbps`: Application-level send rate

### What's Missing
- Per-connection actual network throughput (how much of each connection's data made it through the bottleneck)

---

## Calculation Logic

### Step 1: Gather Data
```
tc_sent_bytes = network_config["tc_sent_bytes"]  # Total through bottleneck
duration = simulation_duration

per_connection_offered_bytes = {
    conn_id: sum(epoch["metrics"]["bytes_sent"] for epoch in epochs)
    for each connection
}
```

### Step 2: Estimate Actual Bytes Per Connection

**Logic:**
- Connections that sent less data than tc_sent_bytes likely got ALL their data through
- The remaining tc capacity went to the bottlenecked connection(s)

```python
remaining_tc_bytes = tc_sent_bytes
actual_bytes = {}

# First pass: connections that likely got all data through
for conn_id, offered_bytes in per_connection_offered_bytes.items():
    if offered_bytes < tc_sent_bytes * 0.9:  # Not bottlenecked
        actual_bytes[conn_id] = offered_bytes
        remaining_tc_bytes -= offered_bytes

# Second pass: distribute remaining to bottlenecked connections
for conn_id in bottlenecked_connections:
    actual_bytes[conn_id] = remaining_tc_bytes * (proportion based on offered)
```

### Step 3: Calculate Throughput
```python
actual_throughput_bps = (actual_bytes * 8) / duration
actual_throughput_mbps = actual_throughput_bps / 1_000_000
```

---

## Files to Modify

### 1. `3_conn_code/simulation/result.py`

**Add new method:**
```python
def get_actual_throughput_per_connection(self) -> Dict[str, Any]:
    """
    Calculate actual network throughput per connection.

    Returns dict with per-connection:
    - offered_bytes
    - actual_bytes
    - offered_throughput_mbps
    - actual_throughput_mbps
    """
```

**Modify `get_bottleneck_summary()`:**
- Include `per_connection_throughput` from the new method

**Modify `to_dict()`:**
- Add `actual_throughput_per_connection` to output

### 2. `3_conn_code/simulation/result.py` - Export Methods

**Modify `export_bottleneck_summary()`:**
- Include per-connection actual throughput

**Modify `export_median_metrics_summary()`:**
- Add `actual_throughput_mbps` alongside `offered_throughput_median_mbps`

---

## Output Format

### In `bottleneck_summary_*.json`:
```json
{
  "bottleneck_summary": {
    "configured_capacity_mbps": 5.0,
    "observed_link_throughput_mbps": 3.49,
    "per_connection_throughput": {
      "1": {
        "application_type": "video_streaming",
        "offered_throughput_mbps": 1.34,
        "actual_throughput_mbps": 1.30
      },
      "2": {
        "application_type": "file_transfer",
        "offered_throughput_mbps": 230.96,
        "actual_throughput_mbps": 2.07
      },
      "3": {
        "application_type": "conference_call",
        "offered_throughput_mbps": 0.12,
        "actual_throughput_mbps": 0.11
      }
    }
  }
}
```

### In `median_metrics_summary_*.json`:
```json
{
  "connections": {
    "1": {
      "application_type": "video_streaming",
      "offered_throughput_median_mbps": 1.34,
      "actual_throughput_mbps": 1.30,
      "rtt_median_ms": 35.7
    }
  }
}
```

---

## Implementation Steps

### Step 1: Add Calculation Method
- [ ] Add `get_actual_throughput_per_connection()` to `MultiConnectionResult` class
- [ ] Handle edge cases (no tc data, zero duration, missing epochs)

### Step 2: Integrate into Existing Outputs
- [ ] Add to `get_bottleneck_summary()` return value
- [ ] Add to `to_dict()` output
- [ ] Update `export_bottleneck_summary()`
- [ ] Update `export_median_metrics_summary()`

### Step 3: Test
- [ ] Rebuild Docker image
- [ ] Run simulation
- [ ] Verify calculations match expected values:
  - Video: ~1.30 Mbps actual
  - File: ~2.07 Mbps actual
  - Conference: ~0.11 Mbps actual
  - Total: ~3.49 Mbps (matches tc_observed)

### Step 4: Update Documentation
- [ ] Update `potential_issues.md` to note this is now tracked
- [ ] Update `FULL_report.md` with new metric descriptions

---

## Validation

After implementation, verify:

1. **Sum matches tc total:**
   ```
   sum(actual_throughput) ≈ tc_observed_throughput
   ```

2. **Actual ≤ Offered for each connection:**
   ```
   actual_throughput_mbps <= offered_throughput_mbps
   ```

3. **Non-bottlenecked connections:**
   ```
   If offered < tc_capacity: actual ≈ offered
   ```

---

## Estimated Changes

| File | Lines Added | Lines Modified |
|------|-------------|----------------|
| `result.py` | ~60 | ~10 |
| **Total** | ~60 | ~10 |
