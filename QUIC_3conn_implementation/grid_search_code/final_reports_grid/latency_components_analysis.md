# Latency Components: Why Adding Propagation Delay Alone Won't Change Optimal Parameters

## The User's Question

"Why is latency only measured by queuing delay? If it wasn't a loopback, would the latency be a different value, and potentially lead to mm_friendly to have different optimal parameter values?"

## Short Answer

1. **Latency is NOT only measured by queuing delay** - it includes all delay components
2. **On localhost, queuing delay dominates** because other components are negligible
3. **Adding fixed propagation delay would NOT change optimal parameters** (still minimizes queuing)
4. **Adding variable network effects (loss, reordering, variable BW) WOULD change optimal parameters**

---

## Complete Latency Breakdown

### The Full RTT Formula

```
RTT = 2 × (propagation_delay + transmission_delay + queuing_delay + processing_delay)
```

Then:
```
Latency = RTT / 2 = propagation_delay + transmission_delay + queuing_delay + processing_delay
```

### Component Values: Localhost vs Real Network

| Component | Localhost (127.0.0.1) | Real Network (e.g., WiFi, 20ms away) |
|-----------|----------------------|--------------------------------------|
| **Propagation delay** | ~0 μs (memory) | **20 ms** (speed of light × distance) |
| **Transmission delay** | ~0 μs (memory speed) | **0.12 ms** (1500 bytes @ 100 Mbps) |
| **Processing delay** | 0.01-0.1 ms (CPU) | 0.1-1 ms (router/switch processing) |
| **Queuing delay** | **1-500 ms** (varies) | **1-100 ms** (varies) |

### Why Queuing Dominates on Localhost

**Localhost example (from grid search):**
```
File Transfer optimal:
  RTT = 486.35 ms
  Latency = 243.17 ms

Breakdown:
  propagation_delay ≈ 0 ms
  transmission_delay ≈ 0 ms
  processing_delay ≈ 0.1 ms
  queuing_delay ≈ 243 ms  ← 99.96% of latency

Video Streaming optimal:
  RTT = 2.45 ms
  Latency = 1.23 ms

Breakdown:
  propagation_delay ≈ 0 ms
  transmission_delay ≈ 0 ms
  processing_delay ≈ 0.1 ms
  queuing_delay ≈ 1.1 ms  ← 89% of latency
```

---

## Scenario Analysis: What Changes Optimal Parameters?

### Scenario 1: Add Fixed Propagation Delay (20ms)

**Network:** WiFi access point 20ms away, no loss, no reordering

**New RTT values:**
```
Video Streaming with propagation:
  RTT = 2 × (20ms propagation + 1.1ms queuing + 0.1ms processing)
  RTT = 2 × 21.2ms = 42.4ms
  Latency = 21.2ms

File Transfer with propagation:
  RTT = 2 × (20ms propagation + 243ms queuing + 0.1ms processing)
  RTT = 2 × 263.1ms = 526.2ms
  Latency = 263.1ms
```

**Does this change optimal parameters?**

**NO** ✅ - Here's why:

```
Goal: Minimize Latency
  = Minimize(propagation + transmission + queuing + processing)
  = Minimize(20ms + 0.1ms + queuing + 0.1ms)
  = Minimize(20.2ms + queuing)
```

Since propagation, transmission, and processing are **fixed** (don't change with congestion control parameters), minimizing latency still means **minimizing queuing delay**.

**Optimal parameters stay the same:**
- `loss_reduction_factor = 0.3` (minimizes queuing)
- `cubic_c = 0.2` (minimizes queuing)
- `minimum_window = 2` (minimizes queuing)

**Latency value would be different** (21.2ms vs 1.23ms), but **optimal parameters unchanged**.

---

### Scenario 2: Add Packet Loss (2%)

**Network:** WiFi with 20ms propagation + 2% random loss

**Now latency includes loss recovery time:**

```
Latency = propagation + transmission + queuing + processing + loss_recovery
```

**Loss recovery time depends on parameters:**

| Parameter Set | Loss Recovery Behavior | Average Latency |
|---------------|------------------------|-----------------|
| `LRF=0.3, CC=0.2` | **Fast recovery:** cwnd drops to 30%, quickly ramps up | **Lower** |
| `LRF=0.7, CC=0.2` | **Slow recovery:** cwnd drops to 70%, slowly ramps up | **Higher** |

**Example with 2% loss:**

```
Configuration A (LRF=0.3, aggressive recovery):
  Base delay: 20.2ms
  Loss recovery overhead: +5ms average
  Total latency: 25.2ms

Configuration B (LRF=0.7, gentle recovery):
  Base delay: 20.2ms
  Loss recovery overhead: +15ms average  (slower recovery)
  Total latency: 35.2ms
```

**Does this change optimal parameters for latency?**

**NO** ✅ - LRF=0.3 is still optimal (fast recovery minimizes latency)

**But what about jitter?**

### Jitter Impact of Loss Recovery

**Configuration A (LRF=0.3):**
```
Loss event → cwnd: 100 → 30 → 35 → 45 → 65 → 100 (aggressive jumps)
Packet delays: 20ms → 50ms → 40ms → 25ms → 20ms
Jitter = σ(delays) = HIGH (large variation)
```

**Configuration B (LRF=0.7):**
```
Loss event → cwnd: 100 → 70 → 75 → 80 → 90 → 100 (smooth curve)
Packet delays: 20ms → 30ms → 28ms → 25ms → 22ms
Jitter = σ(delays) = LOW (small variation)
```

**NOW THEY DIVERGE:**
- **mm_friendly (latency):** LRF=0.3 (fast recovery = lower avg latency)
- **vc_friendly (jitter):** LRF=0.7 (smooth recovery = lower variation)

**This is the key difference!**

---

### Scenario 3: Add Variable Bandwidth

**Network:** WiFi with fading, bandwidth varies 5-20 Mbps

**Impact on latency:**
```
During low bandwidth (5 Mbps):
  Transmission delay increases
  Queuing delay increases (packets accumulate)
  Latency spikes

During high bandwidth (20 Mbps):
  Transmission delay decreases
  Queuing drains faster
  Latency returns to normal
```

**Parameter impact:**

| Parameter | Bandwidth Drop Response | Latency | Jitter |
|-----------|------------------------|---------|--------|
| **MW=2** | Can drop to 2 packets, very responsive | Higher peak, lower avg | Higher variation |
| **MW=6** | Maintains 6 packets minimum, less responsive | Lower peak, higher avg | Lower variation |

**Trade-off emerges:**
- **mm_friendly (latency):** MW=2 or 4 (lower average)
- **vc_friendly (jitter):** MW=6 (more stable)

**DIVERGENCE** ❌

---

## Mathematical Proof: Fixed Delays Don't Change Optimization

### Optimization Problem

**Goal:** Find parameters `p` that minimize latency `L(p)`

```
L(p) = L_fixed + L_variable(p)

where:
  L_fixed = propagation + transmission + processing  (doesn't depend on p)
  L_variable(p) = queuing(p)  (depends on congestion control parameters p)
```

**Optimization:**
```
min L(p) = min (L_fixed + L_variable(p))
   p         p

         = L_fixed + min L_variable(p)
                      p
```

Since `L_fixed` is constant:
```
argmin L(p) = argmin L_variable(p)
   p             p
```

**The optimal parameters `p*` are the same regardless of `L_fixed`!**

---

## When Do Optimal Parameters Change?

Parameters change when the **variable component** changes behavior:

| Network Change | Variable Component Affected | Parameters Change? |
|----------------|----------------------------|-------------------|
| Add propagation delay (fixed) | None | **NO** ✅ |
| Add transmission delay (fixed) | None | **NO** ✅ |
| Add packet loss | Loss recovery time (varies with parameters) | **YES** ❌ |
| Add packet reordering | Detection/retransmission (varies with parameters) | **YES** ❌ |
| Add variable bandwidth | Queuing + adaptation (varies with parameters) | **YES** ❌ |
| Add competing traffic | Queuing + bandwidth share (varies with parameters) | **YES** ❌ |

---

## Real World Example: Video Streaming

### Localhost (Current)

```
Optimal parameters: LRF=0.3, CC=0.2, MW=2, PT=2
Latency achieved: 1.23 ms

Breakdown:
  Queuing: 1.1 ms  (minimized by conservative parameters)
  Other: 0.13 ms

This is THE optimal for minimizing total latency.
```

### WiFi 20ms Away (Hypothetical)

```
Same optimal parameters: LRF=0.3, CC=0.2, MW=2, PT=2
Latency achieved: 21.3 ms

Breakdown:
  Propagation: 20 ms (fixed, can't optimize)
  Queuing: 1.1 ms (minimized by conservative parameters)
  Other: 0.2 ms

Still THE optimal for minimizing total latency.
```

### WiFi 20ms Away + 2% Loss (Realistic)

```
For LATENCY, optimal might be: LRF=0.3, CC=0.2, MW=2, PT=3
Latency achieved: 25 ms

Breakdown:
  Propagation: 20 ms (fixed)
  Queuing: 1.1 ms (minimized)
  Loss recovery: 3.5 ms (minimized by fast recovery LRF=0.3)
  Other: 0.4 ms

For JITTER, optimal might be: LRF=0.6, CC=0.2, MW=6, PT=3
Jitter achieved: 2.5 ms

  Slower recovery (LRF=0.6) → smoother cwnd changes → less jitter
  Higher minimum (MW=6) → more stable sending rate → less jitter
```

**NOW THEY DIVERGE!**

---

## Summary Table

| Scenario | mm_friendly Optimal | vc_friendly Optimal | Diverge? |
|----------|-------------------|-------------------|----------|
| **Localhost (current)** | LRF=0.3, CC=0.2, MW=2 | LRF=0.3, CC=0.2, MW=2 | NO ✅ |
| **+ Fixed propagation** | LRF=0.3, CC=0.2, MW=2 | LRF=0.3, CC=0.2, MW=2 | NO ✅ |
| **+ Packet loss (2%)** | LRF=0.3, CC=0.2, MW=2 | LRF=0.6, CC=0.2, MW=6 | **YES** ❌ |
| **+ Variable BW** | LRF=0.3, CC=0.2, MW=4 | LRF=0.3, CC=0.2, MW=6 | **YES** ❌ |
| **+ Competing traffic** | LRF=0.3, CC=0.4, MW=4 | LRF=0.5, CC=0.2, MW=6 | **YES** ❌ |

---

## Conclusion

### Answering the Original Question

**Q: "Why is latency only measured by queuing delay?"**

**A:** It's not. Latency includes all delay components:
```
Latency = propagation + transmission + queuing + processing
```

On localhost, queuing dominates (99%+), so minimizing latency ≈ minimizing queuing.

---

**Q: "If it wasn't a loopback, would the latency be a different value?"**

**A:** Yes, the value would be different (higher), but the optimal parameters would **stay the same** if you only add fixed delays.

Example:
- Localhost: Latency = 1.23 ms (mostly queuing)
- WiFi: Latency = 21.3 ms (20ms propagation + 1.23ms queuing)

Same optimal parameters, different absolute value.

---

**Q: "Would mm_friendly have different optimal parameter values?"**

**A:** Only if you add **variable network effects** (loss, reordering, variable bandwidth, competing traffic).

- ✅ Fixed propagation delay alone: **NO change** in optimal parameters
- ❌ Propagation + packet loss: **YES, parameters diverge**
- ❌ Propagation + variable bandwidth: **YES, parameters diverge**

---

## Validation Experiment

To see parameter divergence in practice:

```bash
cd grid_search_code

# Test 1: With loss (should show divergence)
python main.py run --scenario lossy --duration 30
python main.py analyze

# Expected:
# mm_friendly: LRF=0.3 (fast recovery)
# vc_friendly: LRF=0.5-0.7 (smooth recovery)

# Test 2: With variable bandwidth (should show divergence)
python main.py run --scenario varying --duration 30
python main.py analyze

# Expected:
# mm_friendly: MW=2-4 (responsive)
# vc_friendly: MW=6 (stable)
```

---

## Key Takeaway

Adding a **fixed offset** to latency doesn't change what minimizes it. It's like:

```
Problem: Minimize f(x) = 100 + x²
Solution: x = 0

Problem: Minimize g(x) = 200 + x²
Solution: x = 0 (same!)

Problem: Minimize h(x) = 100 + x² + |x-5|
Solution: x = ??? (different! now there's a trade-off)
```

The third problem (with loss, reordering, etc.) introduces trade-offs that cause parameter divergence.
