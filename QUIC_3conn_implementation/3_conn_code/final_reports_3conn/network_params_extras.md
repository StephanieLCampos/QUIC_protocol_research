# Adding Network Parameters to Q-Learning State

This document explores the idea of adding network condition parameters to the Q-learning state representation for more context-aware decision making.

---

## Current State (No Network Context)

```
state = (latency_bin, throughput_bin, jitter_bin, latency_trend, throughput_trend, jitter_trend)
```

**Total states:** 1,728 (4³ × 3³)

**Problem:** The agent learns ONE policy for ALL network conditions. What works in `stable_high` might not work in `lossy`.

---

## Proposed State (With Network Context)

```
state = (latency_bin, throughput_bin, jitter_bin,
         latency_trend, throughput_trend, jitter_trend,
         bandwidth_bin, rtt_bin, loss_bin)  ← NEW
```

**Total states:** 110,592 (4³ × 3³ × 4³)

**Benefit:** Agent learns DIFFERENT policies for DIFFERENT conditions:
- "When bandwidth is low AND loss is high → be conservative"
- "When bandwidth is high AND loss is low → be aggressive"

---

## Example: Why Network Context Matters

| Scenario | Network Bins | Best Action Might Be |
|----------|--------------|----------------------|
| `stable_high` | (bw=3, rtt=0, loss=0) | Aggressive throughput push |
| `congested_low` | (bw=0, rtt=2, loss=2) | Conservative, avoid loss |
| `lossy` | (bw=1, rtt=2, loss=3) | Quick recovery settings |

Same performance metrics could require **different optimal actions** based on underlying network conditions.

---

## Possible Network Parameter Bins

### Bandwidth Bins

| Bin | Range | Typical Scenario |
|-----|-------|------------------|
| 0 | < 5 Mbps | congested_low |
| 1 | 5-20 Mbps | lossy, varying |
| 2 | 20-50 Mbps | asymmetric |
| 3 | > 50 Mbps | stable_high |

### RTT Bins

| Bin | Range | Typical Scenario |
|-----|-------|------------------|
| 0 | < 15ms | stable_high |
| 1 | 15-25ms | asymmetric, varying |
| 2 | 25-40ms | congested_low |
| 3 | > 40ms | lossy |

### Loss Rate Bins

| Bin | Range | Typical Scenario |
|-----|-------|------------------|
| 0 | < 1% | stable_high, per_ideal, per_1 |
| 1 | 1-5% | congested_low, per_5 |
| 2 | 5-10% | lossy, per_10 |
| 3 | > 10% | per_20 |

---

## State Space Comparison

| Configuration | States | State-Action Pairs | Multiplier |
|---------------|--------|-------------------|------------|
| Current (6 components) | 1,728 | 43,200 | 1x |
| + loss_bin only | 6,912 | 172,800 | 4x |
| + loss_bin + bandwidth_bin | 27,648 | 691,200 | 16x |
| + all 3 network params | 110,592 | 2,764,800 | 64x |

---

## Training Time Estimates

The agent makes 1 decision every **2 seconds** (CONTROL_INTERVAL).

### Time to Visit Each State Once

| Configuration | States | Time to Visit Each 1x |
|---------------|--------|----------------------|
| Current | 1,728 | ~1 hour |
| + loss_bin | 6,912 | ~4 hours |
| + loss + bandwidth | 27,648 | ~15 hours |
| + all 3 params | 110,592 | ~61 hours |

### Time to Visit Each State 5x (Minimum for Learning)

| Configuration | States | Time (5x visits) |
|---------------|--------|------------------|
| Current | 1,728 | ~5 hours |
| + loss_bin | 6,912 | ~19 hours |
| + loss + bandwidth | 27,648 | ~77 hours (~3 days) |
| + all 3 params | 110,592 | ~307 hours (~13 days) |

### Time to Visit Each State 10x (Good Coverage)

| Configuration | States | Time (10x visits) |
|---------------|--------|-------------------|
| Current | 1,728 | ~10 hours |
| + loss_bin | 6,912 | ~38 hours |
| + loss + bandwidth | 27,648 | ~154 hours (~6 days) |
| + all 3 params | 110,592 | ~614 hours (~26 days) |

---

## Reality Check: Not All States Are Equal

The estimates above assume uniform visitation, but in practice:

1. **Some states are rare** - High bandwidth + terrible throughput combinations may never occur
2. **Training focuses on reachable states** - Only 10-20% of possible states might actually be visited
3. **Scenarios determine which states appear** - Running `congested_low` won't explore high-bandwidth states

### Practical Training Estimate

| Configuration | Recommended Sessions | Duration Each | Total Time |
|---------------|---------------------|---------------|------------|
| Current | 30 sessions | 5 min | ~2.5 hours |
| + loss_bin | 50 sessions | 10 min | ~8 hours |
| + loss + bandwidth | 100 sessions | 10 min | ~17 hours |
| + all 3 params | 200+ sessions | 10 min | ~35+ hours |

---

## Available Scenarios for Training

| Scenario | Bandwidth | RTT | Loss | Network Bins (bw, rtt, loss) |
|----------|-----------|-----|------|------------------------------|
| `stable_high` | 100 Mbps | 10ms | 0.1% | (3, 0, 0) |
| `congested_low` | 5 Mbps | 30ms | 2% | (0, 2, 1) |
| `varying` | 20 Mbps | 20ms | 1% | (1, 1, 0) |
| `lossy` | 10 Mbps | 40ms | 5% | (1, 3, 2) |
| `asymmetric` | 50 Mbps | 25ms | 0.5% | (2, 1, 0) |
| `per_ideal` | 50 Mbps | 20ms | 0% | (2, 1, 0) |
| `per_1` | 50 Mbps | 20ms | 1% | (2, 1, 0) |
| `per_5` | 50 Mbps | 20ms | 5% | (2, 1, 2) |
| `per_10` | 50 Mbps | 20ms | 10% | (2, 1, 2) |
| `per_20` | 50 Mbps | 20ms | 20% | (2, 1, 3) |

---

## Recommendations

### Option 1: Add Only Loss Bin (Recommended Starting Point)

```
state = (latency_bin, throughput_bin, jitter_bin,
         latency_trend, throughput_trend, jitter_trend,
         loss_bin)
```

- **4x larger state space** (6,912 states)
- **~8 hours training** across all scenarios
- Loss rate has the biggest impact on congestion control behavior
- Good balance of context vs. training time

### Option 2: Add Loss + Bandwidth Bins

```
state = (latency_bin, throughput_bin, jitter_bin,
         latency_trend, throughput_trend, jitter_trend,
         loss_bin, bandwidth_bin)
```

- **16x larger state space** (27,648 states)
- **~17 hours training**
- Captures both capacity constraints and channel quality

### Option 3: Add All Three Network Parameters

```
state = (latency_bin, throughput_bin, jitter_bin,
         latency_trend, throughput_trend, jitter_trend,
         bandwidth_bin, rtt_bin, loss_bin)
```

- **64x larger state space** (110,592 states)
- **~35+ hours training**
- Most complete picture, but may be overkill
- RTT is partially captured by latency_bin already

---

## Implementation Considerations

### How to Obtain Network Parameters at Runtime

| Parameter | Source | Challenge |
|-----------|--------|-----------|
| Loss rate | Measured from packet_loss_rate metric | Already available |
| Bandwidth | From scenario config OR estimated from throughput | May need to pass from config |
| RTT | From RTT metric | Already available (similar to latency) |

### Code Changes Required

1. **q_learning_agent.py:**
   - Add new bin constants (LOSS_BINS, BANDWIDTH_BINS, etc.)
   - Update `_build_state()` to include network parameters
   - Update state space size comments

2. **worker_process.py:**
   - Ensure network parameters are included in metrics sent to ML controller

3. **Delete checkpoint:**
   - Old Q-table is incompatible with new state structure
   - Must start fresh: `rm -f results/q_learning_checkpoint.json`

---

## Training Script for Extended State Space

```bash
#!/bin/bash
# train_extended_q_learning.sh

SCENARIOS=(
    "stable_high"
    "congested_low"
    "varying"
    "lossy"
    "asymmetric"
    "per_ideal"
    "per_1"
    "per_5"
    "per_10"
    "per_20"
)

DURATION=600      # 10 minutes per session
SESSIONS=5        # Sessions per scenario

# Clear old Q-table (required after state space change)
rm -f results/q_learning_checkpoint.json

echo "Starting extended Q-learning training..."
echo "Estimated time: ~8-17 hours depending on configuration"
echo ""

for scenario in "${SCENARIOS[@]}"; do
    echo ""
    echo "=========================================="
    echo "Training: $scenario"
    echo "=========================================="
    for i in $(seq 1 $SESSIONS); do
        echo "--- Session $i/$SESSIONS ---"
        DURATION=$DURATION SCENARIO=$scenario docker-compose up --abort-on-container-exit
        docker-compose down
        sleep 3
    done
done

echo ""
echo "Training complete!"
echo "Q-table saved to: results/q_learning_checkpoint.json"
```

---

## Summary

| Approach | States | Training Time | Recommendation |
|----------|--------|---------------|----------------|
| Current (no network) | 1,728 | ~2.5 hours | Good for testing |
| + loss_bin | 6,912 | ~8 hours | **Best starting point** |
| + loss + bandwidth | 27,648 | ~17 hours | Good if time permits |
| + all 3 params | 110,592 | ~35+ hours | Only if necessary |

**Start with loss_bin only** - it provides the most value for the least additional training time.
