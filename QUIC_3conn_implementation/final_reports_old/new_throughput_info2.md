# Throughput Measurement Fix: From QUIC ACKs to TC-Based Estimation

## Problem Identified

The previous implementation of "ACK-verified throughput" was incorrect. It used:

```python
bytes_acked = bytes_sent - bytes_in_flight
throughput_acked = bytes_acked / duration
```

### Why This Was Wrong

1. **QUIC-level ACKs don't reflect bottleneck throughput**: The `bytes_in_flight` metric tracks data sent by the QUIC stack but not yet acknowledged by the receiver. As ACKs come back, `bytes_acked` grows.

2. **Cumulative measurement issue**: Over time, `bytes_acked` approaches `bytes_sent` because eventually all data gets acknowledged (even if slowly through a bottleneck).

3. **Observed symptom**: File transfer showed ~210 Mbps "acked" on a 5 Mbps bottleneck, which is clearly wrong.

### Example of Incorrect Results (Before Fix)

```json
{
  "per_connection_throughput": {
    "1": {
      "application_type": "video_streaming",
      "offered_throughput_mbps": 1.325,
      "acked_throughput_mbps": 1.324  // Looks correct but for wrong reason
    },
    "2": {
      "application_type": "file_transfer",
      "offered_throughput_mbps": 210.23,
      "acked_throughput_mbps": 210.23  // WRONG - should be ~2 Mbps
    },
    "3": {
      "application_type": "conference_call",
      "offered_throughput_mbps": 0.114,
      "acked_throughput_mbps": 0.114  // Looks correct but for wrong reason
    }
  }
}
```

---

## Solution: TC-Based Estimation

Instead of using QUIC-level acknowledgments, we now estimate per-connection actual throughput based on the tc (traffic control) bottleneck statistics.

### Data Available

- `tc_observed_throughput_bps`: Total throughput through the tc qdisc bottleneck
- Per-connection `offered_throughput`: What each connection tried to send

### Estimation Logic

```
1. If total_offered <= tc_observed (no bottleneck active):
   actual = offered for all connections

2. If bottleneck is active:
   a. Identify non-bottlenecked connections (offered < fair_share)
      - These likely got ALL their data through
      - actual = offered

   b. Distribute remaining tc capacity to bottlenecked connections
      - Proportionally based on their offered load
```

### Implementation

New method in `3_conn_code/simulation/result.py`:

```python
def _estimate_actual_throughput_per_connection(
    self, observed_link_bps: float
) -> Dict[str, Any]:
    """
    Estimate actual throughput per connection based on tc bottleneck.

    Logic:
    - Connections that offered less than their share of tc capacity
      likely got ALL their data through (actual ≈ offered)
    - Bottlenecked connections share the remaining tc capacity
      proportionally based on their offered load
    """
    # ... implementation details in result.py
```

---

## Expected Results (After Fix)

With a 5 Mbps bottleneck and ~211 Mbps total offered:

| Connection | Application | Offered (Mbps) | Actual (Mbps) | Notes |
|------------|-------------|----------------|---------------|-------|
| 1 | Video Streaming | 1.33 | ~1.33 | Not bottlenecked (< fair share) |
| 2 | File Transfer | 210.0 | ~2.0-2.2 | Heavily bottlenecked |
| 3 | Conference Call | 0.11 | ~0.11 | Not bottlenecked (< fair share) |
| **Total** | - | ~211.5 | ~3.5-3.6 | Matches tc_observed |

### Validation Criteria

1. **Sum matches tc total**: `sum(actual_throughput) ≈ tc_observed_throughput`
2. **Actual <= Offered**: For each connection, actual never exceeds offered
3. **Non-bottlenecked preserved**: Small flows get their full offered throughput

---

## Files Modified

| File | Changes |
|------|---------|
| `3_conn_code/simulation/result.py` | Added `_estimate_actual_throughput_per_connection()` method |
| `3_conn_code/simulation/result.py` | Updated `get_bottleneck_summary()` to use tc-based estimation |
| `3_conn_code/simulation/result.py` | Updated `export_median_metrics_summary()` to show `actual_throughput_mbps` |
| `3_conn_code/simulation/result.py` | Removed incorrect `acked_throughput` from trimmed median calculation |

---

## Output Format Changes

### bottleneck_summary_*.json

**Before:**
```json
"per_connection_throughput": {
  "1": {
    "offered_throughput_mbps": 1.33,
    "acked_throughput_mbps": 1.32  // Incorrect QUIC-level measurement
  }
}
```

**After:**
```json
"per_connection_throughput": {
  "1": {
    "offered_throughput_mbps": 1.33,
    "actual_throughput_mbps": 1.33  // TC-based estimation
  }
}
```

### median_metrics_summary_*.json

**Before:**
```json
"connections": {
  "1": {
    "offered_throughput_median_mbps": 1.33,
    "acked_throughput_median_mbps": 0.0  // Often 0 due to per-sample issues
  }
}
```

**After:**
```json
"connections": {
  "1": {
    "offered_throughput_median_mbps": 1.33,
    "actual_throughput_mbps": 1.33  // TC-based estimation (not per-sample)
  }
}
```

---

## Why Not Use QUIC ACKs at All?

QUIC ACKs could theoretically measure actual throughput, but:

1. **Timing granularity**: ACKs are processed asynchronously; measuring instantaneous ACK rate is complex
2. **Cumulative vs rate**: `bytes_acked` is cumulative; converting to rate requires careful time windowing
3. **TC statistics are authoritative**: The tc qdisc knows exactly how much data passed through the bottleneck

For this simulation setup with Docker + tc, using tc statistics is the most accurate approach.

---

## Rebuild Required

After these changes, rebuild the Docker image:

```bash
cd /Users/steph/dev/research_folder/GIT_QUIC_3conn/QUIC_3conn_implementation
docker build -t quic-wireless -f Dockerfile .
```

Then run a new simulation to see corrected values.
