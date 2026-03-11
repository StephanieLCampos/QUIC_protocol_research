# Wireless Bottleneck Simulation Guide

This guide explains how to use the wireless bottleneck simulation to constrain bandwidth, add packet loss, and simulate realistic network conditions for your QUIC 3-connection experiments.

## Quick Start (Multi-Container Docker - RECOMMENDED)

The **multi-container Docker Compose setup** is the only method that actually enforces bandwidth and packet loss constraints on traffic between the QUIC server and clients.

```bash
# Build the image
docker build -t quic-wireless -f Dockerfile .

# Run the multi-container setup
docker-compose up

# Clean up when done
docker-compose down
```

This will:
- Start a QUIC server container with bottleneck applied to eth0 (inter-container network)
- Start a clients container that connects to the server
- Enforce 5 Mbps bandwidth limit (configurable in docker-compose.yml scenario)
- Apply 30ms RTT and 2% packet loss (congested_low scenario)
- Run for 35 seconds total

## Architecture Comparison

| Method | Bandwidth Limiting | Packet Loss | RTT Delay | Why It Works / Doesn't |
|--------|-------------------|-------------|-----------|----------------------|
| **Multi-Container Docker (eth0)** | ✅ **YES** | ✅ **YES** | ✅ **YES** | Traffic crosses network interface where tc rules are enforced |
| Single-Container Docker (lo) | ❌ NO | ❌ NO | ✅ YES* | Linux kernel bypasses tc on loopback in same namespace |
| Single-Container veth pair | ❌ NO | ❌ NO | ✅ YES* | Kernel optimization for same-namespace traffic |
| macOS (lo) | ❌ NO | ❌ NO | ✅ YES* | tc not supported on loopback |

*RTT only = Kernel adds delay but kernel-level optimization prevents bandwidth/loss simulation

## How Multi-Container Setup Works

The multi-container approach solves the kernel same-namespace bypass issue by separating the server and clients into different Linux network namespaces:

```
┌─────────────────────────────────────┐
│ Docker Bridge Network 192.168.200/24│
├──────────────────────┬──────────────┤
│  Server Container    │ Client Container
│  192.168.200.10      │ 192.168.200.20
│                      │
│ eth0 ─── tc qdisc ┐  │  eth0 
│ (HTB + netem)     │  │
└──────────────────────┴──────────────┘
      ↑ Traffic here IS constrained ↑
      (crosses network interface)
```

When clients in the client container connect to the server in the server container:
1. Traffic leaves client container's eth0
2. Enters Docker bridge network
3. Arrives at server container's eth0
4. **tc qdisc on eth0 enforces bandwidth/loss**
5. Traffic processed by QUIC server

This is fundamentally different from single-container because traffic physically traverses a network interface where the kernel enforces tc rules.

## Configuration

Edit [docker-compose.yml](docker-compose.yml) to customize:

```yaml
server:
  environment:
    - RUN_MODE=server          # Run in server-only mode
    - SKIP_VETH=0              # Don't use veth (use eth0 instead)
  command: python -m main server --duration 35

clients:
  environment:
    - SKIP_VETH=1              # Skip veth setup in client container
  command: python -m main clients --server 192.168.200.10 --duration 30 --scenario congested_low
```

### Available Scenarios

Modify the `--scenario` parameter:

- **congested_low** (default): 5 Mbps, 30ms RTT, 2% loss - typical congested WiFi
- **stable_high**: 100 Mbps, 10ms RTT, 0.1% loss - fast stable link
- **varying**: Variable capacity (5-20 Mbps), 20ms RTT, 1% loss
- **lossy**: 10 Mbps, 25ms RTT, 5% loss - high loss environment
- **asymmetric**: 50 Mbps downlink, 10 Mbps uplink, 15ms RTT

## Verification

After running `docker-compose up`, you should see:

```
quic-server   | [Orchestrator] Multi-container Docker mode: applying bottleneck on eth0 (inter-container network)
quic-server   | Setting up wireless bottleneck on eth0...
quic-server   | Successfully configured bottleneck: 5000 kbit/s, 15ms delay, 2.0% loss
```

This confirms the bottleneck is active on eth0.

## Troubleshooting

### Server shows "Local mode: applying bottleneck on lo"

- **Cause**: `RUN_MODE` environment variable not set or `SKIP_VETH` is wrong
- **Fix**: Check docker-compose.yml has `RUN_MODE=server` and `SKIP_VETH=0`

### Clients can't connect to server

- **Cause**: Server isn't listening or firewall issue
- **Fix**: 
  - Ensure server logs show "Server started successfully"
  - Verify both containers are on the same network: `docker network inspect quic_3conn_implementation_quic-net`
  - Check IP addresses: `docker inspect quic-server | grep "IPAddress"`

### Throughput still 40+ Mbps instead of 5 Mbps

- **Possible causes**:
  1. tc rules not applied (check server logs for "Successfully configured bottleneck")
  2. Running single-container instead of multi-container
  3. Traffic not crossing eth0 interface
- **Solution**: Use multi-container docker-compose setup exclusively

## Single-Container (Deprecated)

The single-container setup with veth pairs is **no longer recommended** because the Linux kernel optimizes traffic within the same namespace, causing tc rules to be bypassed.

If you still need single-container mode:

```bash
# Set USE_VETH_INTERFACE for single-container veth mode
export USE_VETH_INTERFACE=1
uv run python -m main run --scenario congested_low
```

This will:
- Create a veth pair (veth0/veth1) inside the container
- Bind the server to veth0's IP (192.168.100.1)
- Apply tc rules to veth0
- **But still won't enforce bandwidth because same-namespace kernel bypass**

## macOS (Local Testing Only)

On macOS, the bottleneck only supports RTT delay (no bandwidth/loss):

```bash
uv run python -m main run --scenario congested_low
```

This simulates 30ms RTT but **not** the 5 Mbps bandwidth limit. Use Docker for realistic network simulation.

## Implementation Details

The bottleneck simulation uses Linux tc (traffic control):

```bash
# HTB (Hierarchical Token Bucket) for rate limiting
tc qdisc add dev eth0 root handle 1: htb default 11

# HTB class with rate limit
tc class add dev eth0 parent 1: classid 1:11 htb rate 5000kbit ceil 5000kbit

# netem (network emulator) for delay and loss
tc qdisc add dev eth0 parent 1:11 handle 10: netem delay 15ms loss 2%
```

The bottleneck is managed by the `WirelessBottleneck` context manager in `ProcessOrchestrator.run()`.

## For More Information

- [Wireless Bottleneck Module](wireless_bottleneck/) - Implementation details
- [Docker Compose Config](docker-compose.yml) - Multi-container setup
- [Main Entry Point](3_conn_code/main.py) - Server/client command implementations
- [Process Orchestrator](3_conn_code/simulation/process_orchestrator.py) - Bottleneck integration

