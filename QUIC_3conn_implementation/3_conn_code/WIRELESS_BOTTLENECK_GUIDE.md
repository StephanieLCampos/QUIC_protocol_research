# Wireless Bottleneck Guide

This guide explains how to run QUIC 3-connection simulations with network bottleneck simulation using the `wireless_bottleneck` module.

## Quick Start - Local (macOS)

On macOS, you can run simulations with RTT/latency simulation. Rate limiting and packet loss don't fully work on the loopback interface due to Linux `tc` tool limitations.

```bash
# Run with a predefined scenario
uv run python -m main run --scenario congested_low

# Run with specific duration
uv run python -m main run --duration 30 --scenario stable_high

# Run with browser UI
uv run python -m main run --ui --scenario lossy
```

## Full Bottleneck - Multi-Container Docker ✅ WORKING

**This now works!** By running server and clients in separate Docker containers on a custom bridge network, the bottleneck properly constrains bandwidth, latency, and packet loss.

```bash
# Build the Docker image (run from QUIC_3conn_implementation directory)
cd /Users/sean/Documents/GitHub/QUIC_research/QUIC_3conn_implementation
docker build -t quic-wireless -f Dockerfile .

# Run with docker-compose (server + 3 clients in separate containers)
docker-compose up
```

**What you'll see:**
- ✅ "Successfully configured bottleneck: 5000 kbit/s..." on eth0
- ✅ All 3 clients connect to server (192.168.200.10)
- ✅ Data transfer completes successfully
- ✅ **Bottleneck is enforced** (bandwidth, latency, loss all work)
- ✅ Clients show measured throughput respecting the 5 Mbps limit

**Why multi-container works:**
Traffic between containers crosses the eth0 network interface where Linux `tc` rules are actually enforced. This avoids the same-namespace kernel optimization that blocks veth pair approaches.

**Configuration:**
- Server: 192.168.200.10 on docker network, applies bottleneck to eth0
- Clients: 192.168.200.20 on same docker network
- Scenario: congested_low (5 Mbps, 30ms RTT, 2% loss) or any other
- Network: Custom bridge 192.168.200.0/24

**Docker Compose Usage:**

```bash
# Run with default scenario (congested_low: 5 Mbps, 30ms RTT, 2% loss)
docker-compose up

# Run with different scenario
SCENARIO=stable_high docker-compose up
SCENARIO=lossy docker-compose up
SCENARIO=varying docker-compose up
SCENARIO=asymmetric docker-compose up

# Stop containers
docker-compose down
```

## Available Scenarios

All scenarios are predefined with realistic parameters:

| Scenario | Bandwidth | RTT | Loss | Use Case |
|----------|-----------|-----|------|----------|
| `stable_high` | 100 Mbps | 10ms | 0.1% | High-capacity link |
| `congested_low` | 5 Mbps | 30ms | 2% | Congested network |
| `varying` | 20 Mbps ±40% | 20ms | 1% | Unstable conditions |
| `lossy` | 10 Mbps | 40ms | 5% | High-loss network |
| `asymmetric` | 50↓/10↑ Mbps | 25ms | 0.5% | Asymmetric (like DSL) |

Use with `--scenario <name>` flag.

## What Gets Constrained

The bottleneck applies network constraints to **all 3 connections simultaneously**:

- **Bandwidth**: Aggregate throughput shared across 3 connections
- **Latency**: Added RTT delay (same for all connections)
- **Packet Loss**: Random loss applied to all traffic
- **Jitter**: Simulated queue-based delay variation (Docker only)

Example: With `congested_low` (5 Mbps total), 3 connections sharing:
- Each connection gets ~1.67 Mbps average (if fairly allocated)
- All experience 30ms RTT added delay
- 2% of packets randomly dropped

## Key Differences: Local vs Docker

### Local (macOS) - RTT Only
```bash
uv run python -m main run --scenario congested_low
```
✅ RTT/latency simulation works (adds configured delay)
❌ Bandwidth limiting doesn't apply (tc doesn't support macOS loopback)
❌ Packet loss doesn't apply

### Docker Multi-Container (Linux) - FULLY WORKING ✅
```bash
cd /Users/sean/Documents/GitHub/QUIC_research/QUIC_3conn_implementation
docker-compose up
```
✅ RTT/latency simulation works
✅ Bandwidth limiting works (enforces 5 Mbps limit)
✅ Packet loss works
✅ Server and clients in separate containers
✅ tc rules apply on eth0 (inter-container interface)
✅ Traffic physically traverses the bottleneck

**Why multi-container works**: Server and clients run in separate containers with different network namespaces. Traffic between them must physically cross eth0 where the Linux kernel actually enforces tc rules. No kernel optimization bypass.

**How to verify**: Look for these messages in docker-compose output:
- ✅ "Multi-container Docker mode: applying bottleneck on eth0"
- ✅ "Successfully configured bottleneck: 5000 kbit/s..."
- ✅ "Connected to server, starting to send data..." (all 3 connections)
- ✅ "Server run duration complete" (server finishes successfully)
- ✅ Total throughput respects the 5 Mbps limit (not 30+ Mbps)

### Docker Single-Container (Limited)
For comparison, single-container mode with veth pairs doesn't work because of same-namespace kernel optimization:
```bash
docker run -it --rm --privileged quic-wireless \
  python -m main run --scenario congested_low
```
❌ Bandwidth limiting doesn't work (kernel optimization bypass)
❌ Packet loss doesn't work
✅ RTT/latency simulation works
✅ tc commands execute successfully (but traffic bypasses them)

## Running with Other Options

All options work with scenarios:

```bash
# With specific duration
uv run python -m main run --scenario congested_low --duration 60

# With ML controller
uv run python -m main run --scenario varying --with-ml

# With browser UI
uv run python -m main run --ui --scenario lossy

# In Docker with options
docker run -it --rm --privileged quic-wireless \
  python -m main run --scenario congested_low --duration 60
```

## Viewing Results

### From docker-compose

After running `docker-compose up`, results are saved to the `results/` directory in the host:

```bash
# Run simulation
SCENARIO=congested_low docker-compose up

# View results (persisted on host)
ls results/
cat results/epoch_history_*.json
cat results/summary.json  # If available
```

**Results files:**
- `epoch_history_*.json` - Per-epoch metrics (throughput, RTT, loss, jitter)
- `metrics/` - Connection-level performance data
- `reports/` - Summary statistics and analysis

### From docker run (single-container)

```bash
docker run -it --rm --privileged quic-wireless \
  python -m main run --scenario congested_low --duration 10

# Results are printed to stdout during execution
# Look for "Simulation Complete" section with throughput/RTT/fairness
```

### From local macOS

```bash
uv run python -m main run --scenario congested_low

# Results printed to stdout
# Output files saved to output/, reports/, metrics/
```

## Analyzing Fairness

The bottleneck is useful for testing **fairness across 3 connections**:

Run the same scenario multiple times, then compare:
- How each connection adapts to the bottleneck
- Whether one connection dominates bandwidth
- How congestion control responds to loss
- Queue behavior under sustained load

## Docker Setup Details

The Dockerfile includes necessary tools for full bottleneck simulation:

```dockerfile
# Required for tc (Linux traffic control)
RUN apt-get install -y iproute2

# Required for simulation
RUN apt-get install -y python3-pip curl

# Python environment
RUN pip install uv aioquic pydantic
```

The `--privileged` flag is required because:
- `tc` needs elevated kernel access for network namespace manipulation
- veth pair creation and traffic control require CAP_NET_ADMIN
- It's not a security risk in this context (it's a simulation container)

## Troubleshooting

**"wireless_bottleneck module not found"**
- Run from `/3_conn_code` directory
- The module is at `../wireless_bottleneck`

**"Successfully configured bottleneck" but still getting 30+ Mbps (local or single-container)**
- This is the same-namespace kernel optimization issue
- Traffic between server and clients takes an in-kernel shortcut
- Linux kernel detects destination is "local" and optimizes away network traversal
- Traffic never physically crosses the interface where tc rules are applied
- **To fix**: Use `docker-compose up` instead (multi-container setup separates namespaces)

**Server binds to 192.168.100.1 but traffic still bypassed**
- Correct! The issue isn't the IP binding (that works)
- The issue is both server and clients share the same network namespace
- Kernel optimizes away the actual network transmission
- This is a fundamental Linux networking optimization, not a configuration error

**"Operation not permitted" errors with Docker**
- Make sure to use `--privileged` flag
- Without it, `tc` and `ip` commands fail

**tc command failures in Docker**
- If you see "Successfully configured bottleneck", tc is working
- If you see "Failed to set up qdisc/netem", check --privileged flag

**No bandwidth limiting on macOS or single-container Docker**
- macOS: loopback doesn't support tc
- Single-container Docker: same-namespace kernel optimization
- RTT simulation still works (adds consistent delays)
- **Solution**: Use `docker-compose up` for multi-container setup (fully working)

**Simulation hangs on startup**
- Check if Docker container is properly initialized
- Try with `--duration 10` for shorter test
- Verify QUIC server starts: look for "[Orchestrator] Server setup complete"

## Files

- `wireless_bottleneck/__init__.py` - Module exports and scenario access
- `wireless_bottleneck/config.py` - `BottleneckConfig` class and network parameters
- `wireless_bottleneck/scenarios.py` - 5 predefined scenarios
- `wireless_bottleneck/bottleneck.py` - `WirelessBottleneck` context manager
- `wireless_bottleneck/monitor.py` - Real-time metrics collection
- `main.py` - Supports `server` and `clients` subcommands for multi-container setup
- `docker-compose.yml` - Multi-container orchestration (server + clients)
- `Dockerfile` - Container image with all dependencies
- `setup_veth.sh` - Network configuration (used for single-container mode)

## Summary

| Feature | Local macOS | Docker Single | Docker Multi-Container |
|---------|-------------|---------------|--------------------------|
| Setup | Direct `uv run` | `docker run --privileged` | `docker-compose up` |
| RTT simulation | ✅ | ✅ | ✅ |
| Bandwidth limiting | ❌ | ❌ | ✅ **WORKS** |
| Packet loss | ❌ | ❌ | ✅ **WORKS** |
| Speed | ✅ Fast | ⚠️ Slower | ⚠️ Slower |
| Accuracy | ⚠️ RTT only | ⚠️ RTT only | ✅ **Full** |
| Recommended for | Development | Architecture | **Production Testing** |

**Current Best Option**: Use **docker-compose multi-container setup** for full, accurate bottleneck simulation with bandwidth, latency, and loss constraints properly enforced.

**For Development**: Use local macOS mode with `uv run` for RTT-aware testing and faster iteration. Bandwidth is not constrained but you can still verify congestion control behavior under latency.

**Why Multi-Container Works**: Separate namespaces force traffic to physically traverse eth0 where Linux tc rules are enforced. Single-container and macOS both have kernel/OS-level optimizations that bypass rate limiting.
