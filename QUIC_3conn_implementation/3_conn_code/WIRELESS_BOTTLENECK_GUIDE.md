"""
Wireless Bottleneck Integration Guide for QUIC_3conn_implementation

The wireless_bottleneck module has been integrated into the 3_conn_code project.
This provides network simulation capabilities for testing 3-connection QUIC setups
under various wireless conditions.
"""

# Quick Start

## Using via main.py

The wireless bottleneck is already integrated into main.py. Run with scenarios:

```bash
# Run with specific scenario
uv run python -m main run --scenario congested_low

# Available scenarios:
# - stable_high (100 Mbps, 10ms RTT, 0.1% loss)
# - congested_low (5 Mbps, 30ms RTT, 2% loss)
# - varying (20 Mbps ±40%, 20ms RTT, 1% loss)
# - lossy (10 Mbps, 40ms RTT, 5% burst loss)
# - asymmetric (50↓/10↑ Mbps, 25ms RTT, 0.5% loss)

# Run with duration and scenario
uv run python -m main run --duration 30 --scenario congested_low

# With browser UI
uv run python -m main run --ui --scenario lossy
```

## Using Example Scripts

```bash
# Test 3-connection setup through a specific scenario
python3 examples/run_3conn_through_bottleneck.py --scenario congested_low --duration 20
```

## Via Docker (Recommended for accurate bottleneck)

The Docker image includes all dependencies (tc, iproute2, etc.):

```bash
# Test through congested scenario
docker run -it --rm --privileged -v $(pwd):/workspace quic-wireless \
  bash -c "cd /workspace/3_conn_code && python3 examples/run_3conn_through_bottleneck.py --scenario congested_low"

# Test through stable scenario
docker run -it --rm --privileged -v $(pwd):/workspace quic-wireless \
  bash -c "cd /workspace/3_conn_code && uv run python -m main run --scenario stable_high"
```

# Understanding the Bottleneck

The bottleneck adds realistic wireless link conditions to all 3 connections:
- All 3 connections compete over the same bottleneck
- Capacity limits affect aggregated throughput
- Latency/RTT affects individual connection performance
- Loss affects congestion control behavior

## Limitations

- **On loopback interface (main.py)**: Adds RTT/latency delays correctly, but rate limiting
  and loss injection don't fully apply (Linux tc limitation on lo interface)
- **On veth interface (Docker)**: Full bottleneck simulation with real bandwidth/loss constraints

# Key Files

- `wireless_bottleneck/__init__.py` - Module exports
- `wireless_bottleneck/config.py` - BottleneckConfig class and parameters
- `wireless_bottleneck/scenarios.py` - 5 predefined scenarios
- `wireless_bottleneck/bottleneck.py` - WirelessBottleneck implementation
- `wireless_bottleneck/monitor.py` - Metrics collection
- `examples/run_3conn_through_bottleneck.py` - Example script

# Available Scenarios

```python
from wireless_bottleneck import get_scenario, list_scenarios

# List all scenarios
for name in list_scenarios():
    print(name)

# Get scenario config
scenario = get_scenario("congested_low")
print(f"Capacity: {scenario.config.capacity_bps / 1_000_000} Mbps")
print(f"RTT: {scenario.config.propagation_delay * 2000} ms")
print(f"Loss: {scenario.config.loss_rate * 100}%")
```

# Analyzing Results

After running simulations, check:
- `output/epoch_history_*.json` - Detailed per-epoch metrics
- `output/*.csv` - Aggregated statistics
- `metrics/` - Per-connection performance data

Each epoch includes:
- Throughput, RTT, jitter, loss per connection
- Fairness metrics across connections
- Queue occupancy and drops (if available)

# Customizing Scenarios

Create custom scenario:

```python
from wireless_bottleneck import BottleneckConfig, WirelessBottleneck, LossModel

custom_config = BottleneckConfig(
    capacity_bps=20_000_000,  # 20 Mbps
    propagation_delay=0.025,  # 25ms one-way
    loss_rate=0.01,  # 1%
    loss_model=LossModel.RANDOM,
)

with WirelessBottleneck(custom_config, interface="lo") as bottleneck:
    # Run your simulation
    pass
```

# Integration with main.py

The main.py already supports scenarios via `--scenario` flag:

```python
# In main.py, the scenario is automatically loaded:
try:
    from wireless_bottleneck import get_scenario, WirelessBottleneck
    scenario = get_scenario(scenario_name)
    # ... bottleneck setup and metrics collection
except ImportError:
    print("Warning: wireless_bottleneck module not found")
```

No additional changes needed to main.py - it already integrates the bottleneck!
