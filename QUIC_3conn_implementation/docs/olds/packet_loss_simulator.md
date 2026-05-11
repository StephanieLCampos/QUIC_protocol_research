# Packet Loss Simulation Guide

This document explains how to simulate network conditions (packet loss, latency) to observe the effects of the `loss_reduction_factor` parameter in the QUIC tuning research framework.

## Background

### How the Loss Reduction Factor Works

The `loss_reduction_factor` (β) is applied by patching aioquic's CUBIC congestion control at runtime:

```python
# simulation/runner.py:116
aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = self.loss_reduction_factor
```

This parameter controls how much the congestion window shrinks when packet loss is detected:

| Value | Behavior | Use Case |
|-------|----------|----------|
| **0.4** | Aggressive - window reduced to 40% | Low-latency apps (video, conferencing) |
| **0.5** | Standard - window reduced to 50% | General purpose |
| **0.6** | Moderate - window reduced to 60% | Balanced throughput/stability |
| **0.7** | Conservative - window reduced to 70% | High-throughput apps (file transfer) |

### The Problem

Simulations running on localhost have essentially **zero natural packet loss**. Without actual packet loss events, the loss reduction factor never triggers and has no observable effect.

---

## Simulation Methods

### Option 1: OS-Level Network Emulation (Recommended)

#### macOS (using dummynet)

```bash
# Create a dummynet pipe with 5% packet loss
sudo dnctl pipe 1 config plr 0.05

# Create pf rules to route localhost traffic through the pipe
echo "dummynet in proto udp from any to 127.0.0.1 port 4433 pipe 1" | sudo pfctl -f -

# Enable pf
sudo pfctl -e

# Run your simulation
uv run python code/main.py single --app video_streaming --loss-factor 0.5

# Clean up afterward
sudo pfctl -d
sudo dnctl -q flush
```

**Available parameters:**
- `plr 0.05` - 5% packet loss rate
- `delay 50ms` - add 50ms one-way latency (100ms RTT)
- `bw 1Mbit/s` - limit bandwidth to 1 Mbps

**Combined example (realistic network conditions):**
```bash
sudo dnctl pipe 1 config delay 25ms bw 10Mbit/s plr 0.02
```

#### Linux (using tc netem)

```bash
# Add 5% packet loss to loopback interface
sudo tc qdisc add dev lo root netem loss 5%

# Run your simulation
uv run python code/main.py single --app video_streaming --loss-factor 0.5

# Clean up
sudo tc qdisc del dev lo root
```

**Combined example:**
```bash
sudo tc qdisc add dev lo root netem delay 25ms loss 2% rate 10mbit
```

---

### Option 2: Application-Level Packet Loss

Modify the client code to randomly drop packets. Add to `simulation/client.py`:

```python
import random

class LossyQuicClient(QuicClient):
    """QUIC client with simulated packet loss."""

    def __init__(self, *args, loss_rate=0.05, **kwargs):
        super().__init__(*args, **kwargs)
        self.loss_rate = loss_rate

    async def send_data(self, stream_id, data):
        if random.random() < self.loss_rate:
            # Simulate loss by not sending
            return
        await super().send_data(stream_id, data)
```

Then update `simulation/runner.py` to use `LossyQuicClient` with a configurable loss rate.

---

### Option 3: Network Emulator Tools

For more sophisticated testing, consider:

- **Mininet** - Software-defined network emulator
- **ns-3** - Discrete-event network simulator
- **Comcast** - CLI tool for simulating network conditions (https://github.com/tylertreat/comcast)

---

## Testing Procedure

### Quick Comparison Test

Run simulations with different loss factors under identical network conditions:

```bash
# Set up network conditions (macOS)
sudo dnctl pipe 1 config delay 25ms plr 0.03
echo "dummynet in proto udp from any to 127.0.0.1 port 4433 pipe 1" | sudo pfctl -f -
sudo pfctl -e

# Test aggressive recovery (β = 0.4)
uv run python code/main.py single --app video_streaming --loss-factor 0.4

# Test standard recovery (β = 0.5)
uv run python code/main.py single --app video_streaming --loss-factor 0.5

# Test conservative recovery (β = 0.7)
uv run python code/main.py single --app video_streaming --loss-factor 0.7

# Clean up
sudo pfctl -d
sudo dnctl -q flush
```

### Full Grid Search with Network Conditions

```bash
# Set up network conditions
sudo dnctl pipe 1 config delay 25ms plr 0.02
echo "dummynet in proto udp from any to 127.0.0.1 port 4433 pipe 1" | sudo pfctl -f -
sudo pfctl -e

# Run full grid search
uv run python code/main.py grid

# Clean up
sudo pfctl -d
sudo dnctl -q flush
```

---

## Expected Observations

### Effect of Loss Reduction Factor on Recovery

| Metric | Low β (0.4) | High β (0.7) |
|--------|-------------|--------------|
| **Congestion window after loss** | Drops to 40% | Drops to 70% |
| **Throughput stability** | More volatile | More stable |
| **Recovery speed** | Faster ramp-up attempts | Slower, safer ramp-up |
| **Risk of repeated loss** | Higher (aggressive probing) | Lower (conservative) |

### Application-Specific Recommendations

| Application Type | Recommended β | Rationale |
|------------------|---------------|-----------|
| Video Streaming | 0.4 - 0.5 | Prioritize quick recovery for low latency |
| File Transfer | 0.6 - 0.7 | Prioritize stable throughput |
| Conference Call | 0.4 - 0.5 | Prioritize responsiveness over throughput |

---

## Metrics to Monitor

The simulation collects these metrics (see `metrics/collector.py`):

1. **Throughput** (bytes/second) - Overall data transfer rate
2. **RTT** (seconds) - Round-trip time from aioquic internals
3. **Latency** (seconds) - Estimated as RTT/2
4. **Jitter** (seconds) - Standard deviation of inter-packet delays
5. **Packet Loss Rate** - Ratio of lost to sent packets
6. **Connection Establishment Time** - QUIC handshake duration

Results are exported to CSV files in the `output/` directory.

---

## Troubleshooting

### macOS: "pfctl: pf not enabled"
```bash
sudo pfctl -e
```

### macOS: Permission denied for dnctl
Ensure you're running with `sudo`.

### No observable difference between loss factors
- Verify network emulation is active: `sudo dnctl list`
- Increase packet loss rate to 5-10% for more pronounced effects
- Ensure simulation duration is long enough (default: 10 seconds)

### Cleanup commands
```bash
# macOS
sudo pfctl -d
sudo dnctl -q flush

# Linux
sudo tc qdisc del dev lo root 2>/dev/null
```
