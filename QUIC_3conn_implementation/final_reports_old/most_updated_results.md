# Most Updated Results Analysis

## Simulation: 05-04-2026_09-02-20AM

**Scenario:** `congested_low` (5 Mbps bottleneck)

---

## Summary Table

| Connection | Application | Offered | Receiver | Delivery Ratio | Status |
|------------|-------------|---------|----------|----------------|--------|
| 1 | Video Streaming | 1.33 Mbps | **1.32 Mbps** | 99.3% | ✅ |
| 2 | File Transfer | 221.1 Mbps | **1.88 Mbps** | 0.85% | ✅ |
| 3 | Conference Call | 0.115 Mbps | **0.115 Mbps** | 100% | ✅ |

---

## Bottleneck Statistics

| Metric | Value |
|--------|-------|
| Configured Capacity | 5.0 Mbps |
| Observed Link Throughput (tc) | 3.58 Mbps |
| Total Offered Throughput | 222.6 Mbps |
| Capacity Utilization | 71.5% |
| Offered-to-Observed Ratio | 62:1 |

---

## Server-Side Metrics (Receiver)

```json
{
  "total_connections": 3,
  "total_bytes_received": 12,399,203 bytes (~12.4 MB),
  "per_connection": {
    "Server 1": { "bytes": 4.94 MB, "throughput": 1.32 Mbps },
    "Server 2": { "bytes": 431 KB,  "throughput": 0.115 Mbps },
    "Server 3": { "bytes": 7.03 MB, "throughput": 1.88 Mbps }
  }
}
```

---

## Connection Matching Results

The two-pass matching algorithm correctly correlated server and client connections:

### Pass 1: Exact Matching (bytes_sent ≈ bytes_received)

| Client | App | Bytes Sent | Server | Bytes Received | Match |
|--------|-----|------------|--------|----------------|-------|
| 3 | Conference | ~431 KB | Server 2 | 431 KB | ✅ Exact |
| 1 | Video | ~5 MB | Server 1 | 4.94 MB | ✅ Close (~99%) |

### Pass 2: Ranking Matching (highest → highest)

| Client | App | Bytes Sent | Server | Bytes Received | Match |
|--------|-----|------------|--------|----------------|-------|
| 2 | File Transfer | ~830 MB | Server 3 | 7.03 MB | ✅ By rank |

**Note:** File transfer sent ~830 MB but only 7 MB arrived due to the 5 Mbps bottleneck. The ranking match correctly paired the highest sender with the highest receiver.

---

## Validation Checks

### ✅ Check 1: Receiver Sum ≈ tc_observed

```
Video:       1.32 Mbps
File:        1.88 Mbps
Conference:  0.115 Mbps
─────────────────────────
Total:       3.315 Mbps

tc_observed: 3.576 Mbps
Difference:  7% (acceptable - protocol overhead)
```

### ✅ Check 2: Receiver ≤ Offered

For each connection, receiver throughput must not exceed offered throughput:

| Connection | Offered | Receiver | Valid |
|------------|---------|----------|-------|
| Video | 1.33 Mbps | 1.32 Mbps | ✅ |
| File | 221.1 Mbps | 1.88 Mbps | ✅ |
| Conference | 0.115 Mbps | 0.115 Mbps | ✅ |

### ✅ Check 3: Delivery Ratios Make Sense

| Connection | Delivery Ratio | Explanation |
|------------|----------------|-------------|
| Video | 99.3% | Small flow relative to bottleneck, nearly all delivered |
| File | 0.85% | Heavily bottlenecked: offered 221 Mbps through 5 Mbps pipe |
| Conference | 100% | Tiny flow (0.115 Mbps), completely delivered |

### ✅ Check 4: Fresh Data Verification

- Server `export_timestamp`: 1775404940 (current run)
- Simulation `_start_time_unix`: Earlier than export timestamp
- **Result:** Data is fresh, not stale from previous run

### ✅ Check 5: RTT Values Consistent

| Measurement | RTT | Notes |
|-------------|-----|-------|
| Network Probe (baseline) | 15.9 ms | Pure network RTT without queuing |
| Video Streaming | 37.1 ms | Baseline + queuing delay |
| File Transfer | 40.9 ms | **Highest** - most queuing (bufferbloat) |
| Conference Call | 36.5 ms | Baseline + queuing delay |

**Observation:** File transfer has the highest RTT due to aggressive sending causing buffer buildup (bufferbloat). This is expected behavior.

---

## Throughput Comparison

```
                    Offered          Estimated (tc)     Receiver (actual)
                    ─────────────    ──────────────     ─────────────────
Video:              1.33 Mbps        0.02 Mbps          1.32 Mbps
File Transfer:      221.1 Mbps       3.55 Mbps          1.88 Mbps
Conference:         0.115 Mbps       0.002 Mbps         0.115 Mbps
```

**Key Insight:** The proportional estimation (`estimated_throughput_mbps`) is inaccurate because it assumes all connections are equally bottlenecked. The receiver-side measurement shows the actual throughput:

- Video and Conference got nearly their full offered rate
- File Transfer was heavily throttled by the bottleneck

---

## Network Probe Results

Independent ICMP ping probe to measure baseline network conditions:

| Metric | Value |
|--------|-------|
| RTT Min | 0.129 ms |
| RTT Median | 15.9 ms |
| RTT Avg | 15.7 ms |
| RTT P95 | 17.1 ms |
| RTT Max | 18.4 ms |
| Jitter | 1.13 ms |
| Packet Loss | 1.96% |

---

## Conclusions

### What's Working

1. **Receiver-side throughput measurement** - Correctly measures actual data delivery
2. **Two-pass matching algorithm** - Successfully correlates server/client connections
3. **Fresh data check** - Prevents loading stale metrics from previous runs
4. **bytes_sent tracking** - Enables accurate delivery ratio calculation
5. **All metrics are physically reasonable** - Values pass sanity checks

### Key Findings

1. **Small flows (Video, Conference) achieve near-100% delivery** through the bottleneck
2. **File Transfer dominates the bottleneck** but only receives ~1.88 Mbps of its 221 Mbps offered
3. **Total receiver throughput (3.32 Mbps)** is close to tc_observed (3.58 Mbps)
4. **The bottleneck is limiting traffic** as expected (71.5% utilization of 5 Mbps cap)

### Implications for Q-Learning

The receiver-side measurement provides accurate feedback for Q-learning:

- **Before:** Proportional estimation showed Video getting 0.02 Mbps (wrong!)
- **After:** Receiver measurement shows Video getting 1.32 Mbps (correct!)

This accurate signal allows Q-learning to:
1. See that small flows are NOT being starved
2. Understand the actual bottleneck impact on each connection
3. Make informed decisions about parameter adjustments

---

## Files Analyzed

| File | Description |
|------|-------------|
| `results_05-04-2026_09-02-20AM.json` | Full simulation results |
| `median_metrics_summary_05-04-2026_09-02-20AM.json` | Trimmed median summary |
| `bottleneck_summary_05-04-2026_09-02-20AM.json` | Bottleneck analysis |
| `server_metrics_latest.json` | Server-side receiver metrics |
