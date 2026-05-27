# Why vc_friendly and mm_friendly Have Identical Optimal Parameters

## TL;DR

**The parameters are identical because the grid search ran on localhost (loopback) without network simulation.** In this environment, latency and jitter are both functions of the SAME underlying phenomenon: **queuing delay**. With real network conditions (packet loss, reordering, variable bandwidth), the parameters would likely diverge.

---

## The Current Situation

From grid search results:

| Configuration | Target | Optimal Parameters |
|---------------|--------|-------------------|
| `vc_friendly` (Conference Call) | Minimize Jitter = 1.73ms | LRF=0.3, CC=0.2, MW=2, PT=2 |
| `mm_friendly` (Video Streaming) | Minimize Latency = 1.23ms | LRF=0.3, CC=0.2, MW=2, PT=2 |

**Identical parameters → Same configuration optimizes both metrics**

---

## Understanding the Measurement Methods

### How Latency is Measured

```python
# 1. Collect RTT samples from aioquic
rtt_samples = [...]  # From aioquic._loss._rtt_smoothed

# 2. Calculate average RTT
rtt = mean(rtt_samples)

# 3. Estimate one-way latency
latency = rtt / 2  # Assumes symmetric network
```

**What RTT includes:**
```
RTT = 2 × (propagation_delay + transmission_delay + queuing_delay + processing_delay)
```

### How Jitter is Measured

```python
# 1. Record packet arrival timestamps
packet_timestamps = [t1, t2, t3, ...]

# 2. Calculate inter-packet delays
delays = [t2-t1, t3-t2, t4-t3, ...]

# 3. Jitter is standard deviation
jitter = stdev(delays)
```

**What causes jitter:**
- Variation in queuing delay
- Packet reordering (different paths)
- Variable bandwidth (rate limiting changes)
- Competing traffic interference
- Loss recovery timing

---

## Why They're the Same on Localhost

### Localhost Network Conditions

On localhost (127.0.0.1), there is:

| Component | Value | Impact |
|-----------|-------|--------|
| Propagation delay | **~0 ms** | Negligible |
| Transmission delay | **~0 ms** | Memory speed, not wire speed |
| Processing delay | **<0.1 ms** | CPU processing only |
| Queuing delay | **Variable** | **Only significant source** |
| Packet loss | **0%** | Perfect reliability |
| Packet reordering | **None** | Single path, in-order |
| Bandwidth variation | **None** | No physical medium |

### The Collapse to Queuing

With only queuing delay significant:

```
Latency ≈ Queuing_Delay / 2
Jitter ≈ σ(Queuing_Delay_Variation)
```

Both metrics are functions of **the same underlying phenomenon**: how much data queues up in buffers.

### How Congestion Control Affects Queuing

Conservative parameters (low `cubic_c`, low `loss_reduction_factor`):
- Send less aggressively
- Keep congestion window small
- **Less data in flight → Shorter queues → Lower queuing delay**

This simultaneously:
1. **Reduces average queuing delay** → Lowers latency
2. **Stabilizes queuing delay** → Lowers jitter

**Result:** Parameters that minimize one automatically minimize the other.

### The Positive Correlation

From our data:

| App Type | Latency-Jitter Correlation |
|----------|---------------------------|
| Video Streaming | **+0.499** |
| Conference Call | **+0.752** |

Strong positive correlation means: **When latency goes down, jitter goes down too.**

---

## What Would Happen With Network Simulation?

Your codebase has `wireless_bottleneck` scenarios. Let's analyze what would change.

### Scenario 1: Adding Propagation Delay Only

**Configuration:** 20ms propagation delay (40ms RTT base)

```
Before (localhost):
RTT = 2 × queuing_delay = 2ms (video streaming optimal)
Latency = 1ms

After (with propagation):
RTT = 2 × (20ms propagation + queuing_delay) = 41-45ms
Latency = 20.5-22.5ms
```

**Effect on parameter optimization:**
- The **relative differences** between parameter configs stay the same
- Conservative params still minimize queuing
- Propagation is **fixed** regardless of parameters

**Verdict:** Parameters would likely **STAY THE SAME** ✅

### Scenario 2: Adding Packet Loss (1-5%)

**Configuration:** 2% random packet loss

**How different parameters handle loss:**

| Parameter Set | Loss Recovery Behavior | Latency Impact | Jitter Impact |
|---------------|------------------------|----------------|---------------|
| **High LRF (0.7)** | Slow recovery, gentle reduction | Slower avg recovery = **Higher latency** | Smooth, predictable = **Lower jitter** |
| **Low LRF (0.3)** | Fast recovery, aggressive reduction | Faster recovery = **Lower latency** | More oscillation = **Higher jitter** |

**Example:**
```
Loss event occurs:
- LRF=0.7: cwnd reduces to 70%, gradually increases back
  → Longer recovery time → Higher average latency
  → Smooth curve → Lower jitter

- LRF=0.3: cwnd reduces to 30%, quickly increases back
  → Shorter recovery time → Lower average latency
  → Aggressive jumps → Higher jitter
```

**Optimal parameters would diverge:**
- **Video Streaming (latency):** Prefers LRF=0.3 (fast recovery)
- **Conference Call (jitter):** Prefers LRF=0.5-0.7 (smooth recovery)

**Verdict:** Parameters would **DIVERGE** ❌

### Scenario 3: Adding Packet Reordering

**Configuration:** 1% packets arrive out of order

**How packet_threshold affects this:**

With `packet_threshold=2`:
- If 2 later packets arrive before an earlier one → Declare loss
- With reordering: **Spurious retransmissions** occur
- Results in:
  - Extra packets sent
  - Timing disruption
  - **Both latency and jitter increase**

With `packet_threshold=3` (RFC default):
- More tolerant of reordering
- Fewer spurious retransmissions
- **Better for both metrics**

**In reordering-free localhost:**
- `packet_threshold=2` works fine (faster loss detection)

**In real networks:**
- `packet_threshold=3` needed to avoid false positives

**Verdict:** Both would need PT=3, so might stay **SAME** ✅ (but different from localhost result)

### Scenario 4: Variable Bandwidth

**Configuration:** 20 Mbps ±40% every 2 seconds (wireless fading)

**How minimum_window affects this:**

| Parameter | Low Bandwidth Period Behavior | Latency | Jitter |
|-----------|-------------------------------|---------|--------|
| **MW=2** | Can drop to 2 packets, throughput collapses | **Higher** (buffering) | **Higher** (rate variation) |
| **MW=6** | Maintains 6 packets minimum, keeps throughput | **Lower** (less buffering) | **Lower** (more stable) |

But also:

| Parameter | High Bandwidth Period Behavior | Latency | Jitter |
|-----------|--------------------------------|---------|--------|
| **MW=2** | Quickly adapts down, low queuing | **Lower** | **Lower** |
| **MW=6** | Keeps sending even when not needed | **Higher** (queuing) | **Higher** |

**Trade-off emerges:**
- **Video Streaming (latency):** Might prefer MW=4 (balanced)
- **Conference Call (jitter):** Might prefer MW=2 (flexible) or MW=6 (stable), depending on which type of jitter is worse

**Verdict:** Parameters would likely **DIVERGE** ❌

### Scenario 5: Cross-Traffic Competition

**Configuration:** 3 connections sharing 10 Mbps link

**Competition effects:**

Conservative parameters (CC=0.2, LRF=0.3):
- Don't grab bandwidth aggressively
- **Lose out to more aggressive flows**
- Get variable throughput → Variable queuing → **Higher jitter**

Aggressive parameters (CC=0.6, LRF=0.7):
- Compete better for bandwidth
- More stable throughput share → **Lower jitter**
- But higher queuing overall → **Higher latency**

**Trade-off:**
- **Video Streaming (latency):** Prefers conservative (less queuing)
- **Conference Call (jitter):** Might prefer moderate aggressiveness (stable share)

**Verdict:** Parameters would likely **DIVERGE** ❌

---

## Mathematical Analysis

### Localhost Metrics

```
Latency_localhost = Queuing_Delay / 2
Jitter_localhost = σ(Queuing_Delay)
```

Since both depend only on queuing:
```
Minimize(Latency) ⟺ Minimize(Queuing)
Minimize(Jitter) ⟺ Minimize(σ(Queuing)) ≈ Minimize(Queuing)
```

**Same optimization problem → Same solution**

### With Network Simulation

```
Latency_network = (Propagation + Queuing + Loss_Recovery_Time) / 2
Jitter_network = σ(Queuing + Reordering_Delay + Bandwidth_Variation + Competition)
```

Now:
```
Minimize(Latency) ≠ Minimize(Jitter)
```

**Different optimization problems → Different solutions**

---

## Evidence From Grid Search Data

### Cross-Metric Correlation on Localhost

| App Type | Latency vs Jitter Correlation |
|----------|------------------------------|
| Video Streaming | **+0.499** (moderate positive) |
| Conference Call | **+0.752** (strong positive) |

Positive correlation means: Configurations that reduce one tend to reduce the other.

### Expected With Network Simulation

With packet loss and variable bandwidth:
- Some configs: Low latency (fast recovery) but high jitter (oscillating)
- Other configs: High latency (slow recovery) but low jitter (stable)

Expected correlation: **Near zero or negative**

---

## Practical Implications

### Current Grid Search Results Are Valid For:

✅ Localhost testing
✅ Datacenter networks (very low latency, negligible loss)
✅ Controlled lab environments
✅ Initial parameter exploration

### NOT Representative Of:

❌ Wireless networks (variable bandwidth, fading)
❌ Mobile networks (high latency, asymmetric, handoffs)
❌ Satellite links (very high latency, loss)
❌ Congested networks (cross-traffic, competing flows)
❌ Long-distance Internet (propagation delay, diverse paths)

### To Get Realistic Results:

Re-run grid search with `wireless_bottleneck` scenarios:

```bash
cd grid_search_code

# Run with realistic wireless scenario
python main.py run --scenario congested_low --duration 30

# Or with loss-dominated scenario
python main.py run --scenario lossy --duration 30

# Or with variable bandwidth
python main.py run --scenario varying --duration 30
```

---

## Expected Divergence With Realistic Conditions

Based on analysis, here are predicted optimal parameters with network simulation:

### Predicted: Video Streaming (Latency) With 2% Loss

| Parameter | Predicted Value | Rationale |
|-----------|----------------|-----------|
| `loss_reduction_factor` | **0.3-0.4** | Fast recovery reduces avg latency |
| `cubic_c` | **0.4** | Moderate aggressiveness |
| `minimum_window` | **4** | Balance stability and responsiveness |
| `packet_threshold` | **3** | RFC default, handles reordering |

### Predicted: Conference Call (Jitter) With 2% Loss

| Parameter | Predicted Value | Rationale |
|-----------|----------------|-----------|
| `loss_reduction_factor` | **0.5-0.7** | Gentle reduction for stability |
| `cubic_c` | **0.2** | Conservative to avoid oscillation |
| `minimum_window` | **2 or 6** | Either flexible or stable |
| `packet_threshold` | **3** | RFC default, handles reordering |

**Key difference:** `loss_reduction_factor` would diverge (0.3 vs 0.5-0.7)

---

## Validation Experiment

To verify this analysis:

### Step 1: Run Grid Search With Network Simulation

```bash
cd grid_search_code

# Modify executor.py to use network scenario
# Or run with different scenarios
python main.py run --scenario lossy --duration 30
python main.py analyze
```

### Step 2: Compare Results

Compare optimal parameters:
- Localhost (current): vc=0.3/0.2/2/2, mm=0.3/0.2/2/2 (identical)
- With loss: vc=?, mm=? (expected to diverge)

### Step 3: Check Correlation

Compare latency-jitter correlation:
- Localhost: +0.50 to +0.75 (strong positive)
- With loss: Expected near 0 or negative

---

## Conclusion

### The Core Issue

On localhost, both latency and jitter measure **the same thing** (queuing behavior), so they have the same optimal parameters.

### The Measurement Methods Are Correct

- Throughput: `total_bytes / duration` ✅
- RTT: From aioquic internal tracking ✅
- Latency: `RTT / 2` ✅ (reasonable estimate)
- Jitter: `stdev(packet_delays)` ✅ (standard metric)

The measurements are fine. The issue is the **testing environment**.

### What This Means

1. **Current results are valid** for localhost/datacenter scenarios
2. **Results are NOT valid** for wireless/Internet deployments
3. **Parameters would diverge** with realistic network conditions
4. **Grid search should be re-run** with `wireless_bottleneck` scenarios

### Recommendation

Before deploying these configurations in production:

1. **Re-run grid search** with realistic network scenarios (lossy, varying, congested_low)
2. **Validate** that optimal parameters diverge as expected
3. **Test** the derived configurations in real network conditions
4. **Consider** that optimal parameters may vary by network type (WiFi vs LTE vs 5G)

---

## References

- Grid Search Results: `grid_search_code/output/analysis/optimal_configs.json`
- Correlation Analysis: `grid_search_code/param_correlations.md`
- Network Scenarios: `3_conn_code/wireless_bottleneck/scenarios.py`
- Measurement Methods: `measuring_metrics.md`
