# Wireless Bottleneck Simulation Module

This module extends the QUIC research testbed with shared wireless bottleneck simulation capabilities. It enables controlled experiments where multiple QUIC connections compete over emulated wireless links with configurable characteristics.

## Overview

The wireless bottleneck module uses Linux Traffic Control (`tc`) to emulate realistic wireless network conditions including:

- **Link capacity** (bandwidth limiting)
- **Propagation delay** (latency)
- **Packet loss** (random and burst models)
- **Queue management** (FIFO, RED, CoDel, PIE)
- **Time-varying behavior** (mobility/fading simulation)
- **Asymmetric links** (different uplink/downlink rates)

## Requirements

- Linux system with `iproute2` package (provides `tc` command)
- Root/sudo access for network configuration
- Python 3.12+

### For macOS/Windows users:

- Use Docker with Linux container
- Use a Linux VM (VirtualBox, VMware, etc.)
- Use WSL2 on Windows

## Installation

```bash
# Ensure tc is installed (Ubuntu/Debian)
sudo apt-get install iproute2

# For CentOS/RHEL
sudo yum install iproute2

# No additional Python packages needed (uses standard library + existing deps)
```

## Quick Start

### List Available Scenarios

```bash
cd code
python -m wireless_bottleneck.cli list
```

### Show Scenario Details

```bash
python -m wireless_bottleneck.cli show --scenario congested_low
```

### Test a Scenario

```bash
python -m wireless_bottleneck.cli test --scenario lossy --interface lo
```

### Validate Setup

```bash
python -m wireless_bottleneck.cli validate
```

### Create Custom Bottleneck

```bash
python -m wireless_bottleneck.cli custom --capacity 20 --delay 30 --loss 2
```

## Predefined Wireless Scenarios

### 1. Stable High Capacity (`stable_high`)

Represents a good WiFi or wired connection.

- **Capacity**: 100 Mbps
- **RTT**: 10 ms
- **Loss**: 0.1%
- **Queue**: 200 packets (FIFO)
- **Time-varying**: No

**Use case**: Baseline performance testing

### 2. Congested Low Capacity (`congested_low`)

Represents a congested shared WiFi network.

- **Capacity**: 5 Mbps
- **RTT**: 30 ms
- **Loss**: 2%
- **Queue**: 50 packets (RED)
- **Time-varying**: No

**Use case**: Testing congestion control behavior

### 3. Rapidly Varying Capacity (`varying`)

Simulates mobility or signal fading.

- **Capacity**: 20 Mbps (±40% variation every 2s)
- **RTT**: 20 ms
- **Loss**: 1%
- **Queue**: 100 packets (CoDel)
- **Time-varying**: Yes (sinusoidal)

**Use case**: Testing adaptation to changing conditions

### 4. Loss Dominated (`lossy`)

Represents poor wireless conditions.

- **Capacity**: 10 Mbps
- **RTT**: 40 ms
- **Loss**: 5% (Gilbert-Elliott burst model)
- **Queue**: 75 packets (FIFO)
- **Time-varying**: No

**Use case**: Testing loss recovery mechanisms

### 5. Asymmetric (`asymmetric`)

Simulates mobile/cellular networks.

- **Downlink**: 50 Mbps
- **Uplink**: 10 Mbps
- **RTT**: 25 ms
- **Loss**: 0.5%
- **Queue**: 150 packets (FIFO)
- **Time-varying**: No

**Use case**: Testing with asymmetric bandwidth

## Python API Usage

### Basic Usage

```python
from wireless_bottleneck import WirelessBottleneck, get_scenario

# Get a predefined scenario
scenario = get_scenario("congested_low")

# Set up bottleneck
with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
    # Run your QUIC simulations here
    # All connections will experience the bottleneck
    
    # Get bottleneck metrics
    metrics = bottleneck.get_metrics()
    summary = metrics.summary()
    
    print(f"Loss rate: {summary['total_packets']['loss_rate']:.2%}")
    print(f"Avg queue occupancy: {summary['queue']['avg_occupancy_packets']:.1f}")
```

### Custom Configuration

```python
from wireless_bottleneck import WirelessBottleneck, BottleneckConfig, QueueDiscipline

config = BottleneckConfig(
    capacity_bps=20_000_000,  # 20 Mbps
    propagation_delay=0.015,  # 15ms (30ms RTT)
    loss_rate=0.02,  # 2%
    queue_size_packets=100,
    queue_discipline=QueueDiscipline.CODEL,
    time_varying=False,
)

with WirelessBottleneck(config) as bottleneck:
    # Your experiment here
    pass
```

### Time-Varying Capacity

```python
import math
from wireless_bottleneck import BottleneckConfig

def custom_capacity_function(elapsed_time: float) -> int:
    """Custom capacity variation (e.g., periodic step function)."""
    period = 5.0  # 5 second period
    phase = int(elapsed_time / period) % 2
    return 50_000_000 if phase == 0 else 10_000_000  # Toggle between 50 and 10 Mbps

config = BottleneckConfig(
    capacity_bps=30_000_000,  # Average
    time_varying=True,
    capacity_variation_function=custom_capacity_function,
)
```

### Integration with Your QUIC Simulations

```python
from wireless_bottleneck import WirelessBottleneck, get_scenario
from simulation.runner import SimulationRunner

async def run_experiment_under_wireless_conditions():
    # Choose wireless scenario
    scenario = get_scenario("congested_low")
    
    # Set up bottleneck
    with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
        # Run your QUIC simulation
        runner = SimulationRunner(
            application_type="file_transfer",
            initial_cw=12000,
            max_ack_delay=0.025,
            loss_reduction_factor=0.5,
        )
        
        result = await runner.run()
        
        # Analyze results
        print(f"Throughput: {result.metrics.throughput / 1_000_000:.2f} Mbps")
        print(f"RTT: {result.metrics.rtt * 1000:.2f} ms")
        
        # Get bottleneck-specific metrics
        bottleneck_metrics = bottleneck.get_metrics()
        summary = bottleneck_metrics.summary()
        print(f"Queue drops: {summary['total_packets']['dropped']}")
        print(f"Fairness index: {summary['fairness_index']:.3f}")
```

## Instrumentation and Metrics

The bottleneck monitor tracks:

- **Queue occupancy** over time (packets and bytes)
- **Packet drops** (total and by cause)
- **Per-flow statistics** (packets, bytes, drops)
- **Queue delays**
- **Fairness index** (Jain's fairness)

### Accessing Metrics

```python
metrics = bottleneck.get_metrics()
summary = metrics.summary()

# Total statistics
print(f"Packets dropped: {summary['total_packets']['dropped']}")
print(f"Byte loss rate: {summary['total_bytes']['loss_rate']:.2%}")

# Queue statistics
print(f"Avg queue occupancy: {summary['queue']['avg_occupancy_packets']:.1f}")
print(f"Max queue delay: {summary['queue']['max_delay_ms']:.2f} ms")

# Per-flow fairness
print(f"Fairness index: {summary['fairness_index']:.3f}")

# Per-flow details
for flow_id, flow_stats in summary['flows'].items():
    print(f"Flow {flow_id}: {flow_stats['share']:.2%} of bandwidth")
```

## Multi-Flow Experiments

Test multiple QUIC connections competing over the same bottleneck:

```python
import asyncio
from wireless_bottleneck import WirelessBottleneck, get_scenario
from simulation.runner import SimulationRunner

async def run_concurrent_flows():
    scenario = get_scenario("congested_low")
    
    with WirelessBottleneck(scenario.config) as bottleneck:
        # Run 3 concurrent QUIC connections
        runners = [
            SimulationRunner("file_transfer", 12000, 0.025, 0.5),
            SimulationRunner("file_transfer", 12000, 0.025, 0.5),
            SimulationRunner("file_transfer", 12000, 0.025, 0.5),
        ]
        
        results = await asyncio.gather(*[r.run() for r in runners])
        
        # Check fairness
        metrics = bottleneck.get_metrics()
        fairness = metrics.get_flow_fairness_index()
        print(f"Fairness index: {fairness:.3f}")  # 1.0 = perfectly fair
```

## Integration with Grid Search

Run grid searches over QUIC parameters under different wireless conditions:

```python
from wireless_bottleneck import get_scenario, WirelessBottleneck
from grid_search.executor import GridSearchExecutor

async def grid_search_under_wireless_conditions():
    # Run grid search under congested conditions
    scenario = get_scenario("congested_low")
    
    with WirelessBottleneck(scenario.config) as bottleneck:
        executor = GridSearchExecutor()
        await executor.run_all()
        
        # Analyze bottleneck impact
        metrics = bottleneck.get_metrics()
        print(f"Total experiments run through bottleneck")
        print(f"Fairness across all flows: {metrics.get_flow_fairness_index():.3f}")
```

## Command-Line Interface

### Available Commands

| Command | Description |
|---------|-------------|
| `list` | List all predefined scenarios |
| `show` | Show details of a specific scenario |
| `test` | Test bottleneck setup (interactive) |
| `validate` | Run validation tests |
| `custom` | Create custom bottleneck configuration |

### Examples

```bash
# List scenarios
python -m wireless_bottleneck.cli list

# Show scenario details
python -m wireless_bottleneck.cli show --scenario varying

# Test a scenario (Ctrl+C to stop)
python -m wireless_bottleneck.cli test --scenario lossy --interface lo

# Custom configuration
python -m wireless_bottleneck.cli custom \
    --capacity 15 \
    --delay 25 \
    --loss 3 \
    --queue-size 75 \
    --interface lo
```

## Validation Tests

The validation script verifies:

1. ✓ Bottleneck can be configured and torn down
2. ✓ Context manager works correctly
3. ✓ All predefined scenarios are accessible
4. ✓ Metrics collection functions properly
5. ✓ Time-varying scenarios work as expected

Run validation:

```bash
python -m wireless_bottleneck.cli validate
```

## Architecture

```
wireless_bottleneck/
├── __init__.py          # Module exports
├── config.py            # BottleneckConfig, LossModel, QueueDiscipline
├── scenarios.py         # Predefined wireless scenarios
├── bottleneck.py        # WirelessBottleneck implementation (tc wrapper)
├── monitor.py           # BottleneckMonitor and metrics collection
├── validate.py          # Validation tests
└── cli.py               # Command-line interface
```

## How It Works

1. **Traffic Control (tc)**: Uses Linux kernel's traffic control subsystem
2. **Queueing disciplines**: Implements FIFO, RED, CoDel, PIE for queue management
3. **Network emulation (netem)**: Adds delay, loss, and jitter
4. **Token Bucket Filter (TBF)**: Enforces bandwidth limits
5. **Monitoring**: Samples queue state and tracks packet events

### TC Command Structure

```
root qdisc (FIFO/RED/CoDel/PIE) - Queue management
  └─ netem - Delay and loss emulation
      └─ tbf - Rate limiting
```

## Limitations

1. **Linux only**: `tc` is Linux-specific. Use VM/container on other platforms.
2. **Root access**: Requires sudo for network configuration.
3. **Localhost testing**: Current default uses loopback interface.
4. **Simplified models**: Loss and delay models are statistical approximations.

## Advanced Topics

### Using Real Network Interfaces

To apply bottleneck to a real interface (e.g., `eth0`, `wlan0`):

```python
bottleneck = WirelessBottleneck(config, interface="eth0")
```

**⚠️ Warning**: This affects all traffic on that interface!

### Docker Integration

Create a Dockerfile for running experiments:

```dockerfile
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    iproute2 \
    python3.12 \
    python3-pip

COPY code /app/code
WORKDIR /app/code

# Run with --privileged flag to allow tc operations
CMD ["python3", "-m", "wireless_bottleneck.cli", "validate"]
```

Run with:
`/
## Troubleshooting

### Permission Denied

```
Error: Operation not permitted
```

**Solution**: Run with sudo:

```bash
sudo python -m wireless_bottleneck.cli validate
```

### tc Command Not Found

```
Error: tc: command not found
```

**Solution**: Install iproute2:

```bash
sudo apt-get install iproute2  # Ubuntu/Debian
sudo yum install iproute2      # CentOS/RHEL
```

### Bottleneck Not Affecting Traffic

**Checklist**:
1. Correct interface specified?
2. Traffic actually going through that interface?
3. tc rules active? Check with: `tc qdisc show dev <interface>`
4. Using sudo/root?

### macOS "tc not found"

**Solution**: macOS doesn't have `tc`. Options:
1. Use Docker with Linux container
2. Use a Linux VM (VirtualBox, Parallels, VMware)
3. Use remote Linux server

## Future Enhancements

Potential additions for future development:

- [ ] Cross-traffic generation
- [ ] More sophisticated wireless models (Rayleigh fading, etc.)
- [ ] Integration with real wireless testbeds
- [ ] GUI for real-time monitoring
- [ ] Support for other emulation tools (mahimahi, mininet)
- [ ] Per-flow statistics from tc
- [ ] Automated scenario recommendations based on QUIC parameters

## Research Use Cases

This module enables investigation of:

1. **Congestion control**: How does QUIC's CC adapt to varying capacity?
2. **Loss recovery**: Performance under different loss patterns
3. **Fairness**: How do multiple QUIC flows share bottleneck bandwidth?
4. **Queue management**: Impact of different AQM algorithms on QUIC
5. **Parameter tuning**: Optimal QUIC parameters for specific wireless conditions
6. **Time-varying links**: Adaptation to mobility and fading

## Contributing

When adding new scenarios:

1. Create scenario function in `scenarios.py`
2. Add to `PREDEFINED_SCENARIOS` dictionary
3. Document characteristics and use cases
4. Add validation test in `validate.py`

## References

- [Linux Traffic Control HOWTO](https://tldp.org/HOWTO/Traffic-Control-HOWTO/)
- [iproute2 Documentation](https://wiki.linuxfoundation.org/networking/iproute2)
- [CoDel RFC 8289](https://www.rfc-editor.org/rfc/rfc8289.html)
- [RED RFC 2309](https://www.rfc-editor.org/rfc/rfc2309.html)
- [QUIC RFC 9000](https://www.rfc-editor.org/rfc/rfc9000.html)
- [Gilbert-Elliott Model](https://en.wikipedia.org/wiki/Gilbert%E2%80%93Elliott_model)

## License

Part of the QUIC research testbed project.

## Support

For issues or questions:
1. Check the troubleshooting section
2. Run validation tests: `python -m wireless_bottleneck.cli validate`
3. Verify tc installation: `tc -Version`
4. Check system logs: `dmesg | grep -i tc`
