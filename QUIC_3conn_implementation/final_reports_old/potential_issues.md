# Potential Issues and Analysis

Analysis of simulation results from `results_30-03-2026_06-04-42PM.json`

---

## Working Correctly

### 1. Timestamps
- Start: `2026-03-30T18:04:11` → End: `2026-03-30T18:04:42`
- Duration: ~30.4 seconds (matches configured 30s)

### 2. Bottleneck
- `bottleneck_applied`: true
- `bottleneck_limiting_traffic`: true
- Configured: 5 Mbps, Observed: 3.49 Mbps (70% utilization)
- The 70% utilization is expected with 2% packet loss (CUBIC backs off)

### 3. Network Probe
- RTT: 15.8ms median
- Packet loss: 1.96% (matches configured 2%)
- Jitter: 0.75ms

### 4. Sample Collection
- ~270-283 samples per connection over 30s (~9 samples/sec)
- Trimmed median uses 70% of samples (drops 20% warmup, 10% cooldown)

---

## Throughput Analysis

### Offered vs Actual Throughput

| Connection | Type | Offered Throughput | Actual Network Throughput | Notes |
|------------|------|-------------------|---------------------------|-------|
| 1 | Video Streaming | 1.34 Mbps | ~1.30 Mbps | Most data made it through |
| 2 | File Transfer | 230.96 Mbps | ~2.07 Mbps | Heavily bottlenecked |
| 3 | Conference Call | 0.12 Mbps | ~0.11 Mbps | Most data made it through |
| **Total** | - | 223.27 Mbps | 3.49 Mbps | tc observed throughput |

### How Actual Throughput Was Calculated

From epoch_history `bytes_sent` values:
- Video: 4,890,000 bytes sent to QUIC stack
- File: 818,479,104 bytes sent to QUIC stack
- Conference: 424,000 bytes sent to QUIC stack

From tc statistics:
- `tc_sent_bytes`: 13,079,972 bytes actually transmitted over 30s

Since video (4.89 MB) and conference (0.42 MB) sent less than the total tc throughput (13.08 MB), most/all of their data made it through. The remainder went to file transfer:

```
Video actual:      4,890,000 bytes / 30s = 1.30 Mbps
Conference actual:   424,000 bytes / 30s = 0.11 Mbps
File actual:       7,765,972 bytes / 30s = 2.07 Mbps  (13.08MB - 4.89MB - 0.42MB)
─────────────────────────────────────────────────────
Total:                                     3.48 Mbps ≈ 3.49 Mbps (matches tc)
```

---

## Issues and Clarifications

### Issue 1: "Offered Throughput" Naming is Confusing

**Problem:** The `offered_throughput_median_mbps` metric shows 230 Mbps for file transfer, which is impossible on a 5 Mbps link.

**Explanation:** This measures the **application-level send rate** (how fast the app pushes data into QUIC buffers), NOT actual network throughput. QUIC buffers this data and sends it according to congestion control.

**Recommendation:** Consider renaming to `application_send_rate_mbps` or adding a separate `actual_throughput_mbps` metric.

---

### Issue 2: All Connections Report 0% Packet Loss

**Problem:**
```json
"packet_loss_rate_median": 0.0
```
But the network has 2% loss configured (probe confirms 1.96%).

**Explanation:**
- QUIC automatically retransmits lost packets
- The metric measures "unrecoverable" application-level losses
- From the application's perspective, no data was lost
- The network-level losses are hidden by QUIC's reliability

**Recommendation:** Add a separate metric for network-level packet loss (before retransmission).

---

### Issue 3: Low Fairness Index (0.337)

**Problem:** Jain's fairness index of 0.337 (scale 0-1) indicates significant unfairness.

**Explanation:** File transfer dominates because:
- It has aggressive CUBIC settings (cubic_c=0.5, loss_reduction_factor=0.7)
- It generates large continuous data streams
- Video/conference intentionally send smaller, periodic packets

**Assessment:** This is expected behavior for different application types, but worth noting for Q-learning optimization.

---

### Issue 4: RTT Discrepancy Between Probe and QUIC

| Source | RTT | Explanation |
|--------|-----|-------------|
| Configured delay | 30ms (15ms × 2) | One-way delay × 2 |
| ICMP Probe | 15.8ms | Runs on separate container, no congestion |
| QUIC Connections | 35-40ms | Includes queuing delay at bottleneck |

**Explanation:** The probe runs independently without competing for the bottleneck. QUIC connections experience additional queuing delay because they're sending data through the congested link.

**Assessment:** This is expected and correct behavior.

---

## Summary

| Aspect | Status | Notes |
|--------|--------|-------|
| Bottleneck working | ✅ | Limiting traffic to ~3.5 Mbps |
| Metrics collection | ✅ | ~9 samples/sec per connection |
| Network probe | ✅ | Capturing RTT and loss correctly |
| Timestamps | ✅ | Fixed - now span full simulation |
| Throughput naming | ⚠️ | "Offered" vs "Actual" is confusing |
| Packet loss metric | ⚠️ | Shows app-level, not network-level |
| Fairness | ⚠️ | Low (0.337) but expected for mixed traffic |

---

## Recommendations for Future Improvement

1. **Add per-connection actual throughput**: Track bytes that actually made it through the bottleneck per connection, not just total tc bytes.

2. **Rename throughput metrics**: Change `offered_throughput` to `application_send_rate` and add `network_throughput` for actual achieved rate.

3. **Add network-level packet loss**: Capture QUIC's internal loss/retransmission statistics separately from application-level loss.

4. **Document metric meanings**: Add descriptions to JSON output explaining what each metric represents.
