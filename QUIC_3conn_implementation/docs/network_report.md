# Creating Genuine Network Connections with Bottlenecks

This document explains how to move beyond localhost testing to create real network conditions with actual bottlenecks, enabling realistic QUIC performance measurement.

---

## Table of Contents

1. [The Problem with Localhost](#the-problem-with-localhost)
2. [Option 1: Separate Machines](#option-1-separate-machines-real-network)
3. [Option 2: Network Emulation](#option-2-network-emulation-same-machine-simulated-bottleneck)
4. [Option 3: Docker Network](#option-3-docker-network-isolated-virtual-network)
5. [Option 4: Linux Network Namespaces](#option-4-linux-network-namespaces-lightweight-virtual-network)
6. [Option 5: Mininet](#option-5-mininet-full-network-emulator)
7. [Comparison and Recommendations](#comparison-and-recommendations)

---

## The Problem with Localhost

Currently, the simulation runs entirely on `localhost`:

```python
# config/settings.py
server_host: str = "localhost"
server_port: int = 4433
```

This means packets never actually traverse a real network:

```
┌─────────────────────────────────────────────────────────────┐
│                      SAME MACHINE                           │
│                                                             │
│   ┌──────────┐         Memory         ┌──────────┐         │
│   │  Client  │ ◄─────────────────────► │  Server  │         │
│   └──────────┘    (no real network)    └──────────┘         │
│                                                             │
│   • No bandwidth limits                                     │
│   • No real latency                                         │
│   • No packet loss                                          │
│   • No congestion                                           │
└─────────────────────────────────────────────────────────────┘
```

**Result:** The `loss_reduction_factor` and other congestion control parameters have minimal observable effect because there's no actual network stress.

---

## Option 1: Separate Machines (Real Network)

The simplest and most realistic approach - use actual network hardware.

### Architecture

```
┌─────────────────┐                          ┌─────────────────┐
│   Machine A     │      Real Network        │   Machine B     │
│   (Client)      │ ◄─────────────────────►  │   (Server)      │
│                 │   WiFi / Ethernet / WAN  │                 │
└─────────────────┘                          └─────────────────┘
```

### Code Changes Required

**On Machine B (Server) - `config/settings.py`:**

```python
# Change from localhost to all interfaces
server_host: str = "0.0.0.0"  # Listen on all network interfaces
server_port: int = 4433
```

**On Machine A (Client) - modify connection:**

```python
# Point to Machine B's IP address
client = QuicClient(
    host="192.168.1.100",  # Machine B's IP
    port=4433
)
```

### Running the Test

```bash
# On Machine B (server)
uv run python -c "from simulation.server import run_server_standalone; import asyncio; asyncio.run(run_server_standalone(host='0.0.0.0'))"

# On Machine A (client)
uv run python code/main.py single --host 192.168.1.100 --app video_streaming
```

### Bottlenecks You Get Automatically

| Bottleneck | Source |
|------------|--------|
| Bandwidth limits | Physical link capacity |
| Real latency | Distance, routing hops |
| Packet loss | WiFi interference, congestion |
| Jitter | Network load variation |
| Congestion | Other traffic on the network |

### Pros and Cons

| Pros | Cons |
|------|------|
| Most realistic | Requires two machines |
| No simulation artifacts | Less reproducible |
| Tests real hardware | Network conditions vary |

---

## Option 2: Network Emulation (Same Machine, Simulated Bottleneck)

Use OS-level tools to add artificial constraints to localhost traffic.

### macOS (using dummynet/pfctl)

```bash
# Step 1: Create a dummynet pipe with constraints
sudo dnctl pipe 1 config bw 1Mbit/s delay 50ms plr 0.02

# Step 2: Route localhost QUIC traffic through the pipe
echo "dummynet in proto udp from any to 127.0.0.1 port 4433 pipe 1" | sudo pfctl -f -

# Step 3: Enable packet filter
sudo pfctl -e

# Step 4: Run your simulation - traffic is now constrained!
uv run python code/main.py run

# Step 5: Clean up when done
sudo pfctl -d
sudo dnctl -q flush
```

### Available Parameters

| Parameter | Example | Effect |
|-----------|---------|--------|
| `bw` | `1Mbit/s`, `10Mbit/s`, `100Kbit/s` | Bandwidth limit |
| `delay` | `50ms`, `100ms`, `5ms` | One-way latency (RTT = 2x) |
| `plr` | `0.02`, `0.05`, `0.10` | Packet loss rate (2%, 5%, 10%) |
| `queue` | `50`, `100` | Queue/buffer size in packets |

### Example Configurations

```bash
# Simulate 4G mobile network
sudo dnctl pipe 1 config bw 10Mbit/s delay 30ms plr 0.01

# Simulate congested WiFi
sudo dnctl pipe 1 config bw 5Mbit/s delay 10ms plr 0.03

# Simulate satellite link
sudo dnctl pipe 1 config bw 1Mbit/s delay 300ms plr 0.001

# Simulate lossy connection (for testing loss_reduction_factor)
sudo dnctl pipe 1 config bw 10Mbit/s delay 25ms plr 0.05
```

### Linux (using tc/netem)

```bash
# Add constraints to loopback interface
sudo tc qdisc add dev lo root netem \
    rate 1mbit \
    delay 50ms 10ms \
    loss 2%

# Run simulation
uv run python code/main.py run

# Clean up
sudo tc qdisc del dev lo root
```

### Linux Parameter Options

| Parameter | Example | Effect |
|-----------|---------|--------|
| `rate` | `1mbit`, `10mbit` | Bandwidth limit |
| `delay` | `50ms`, `50ms 10ms` | Latency (optional variance) |
| `loss` | `2%`, `5% 25%` | Loss rate (optional correlation) |
| `duplicate` | `1%` | Duplicate packets |
| `reorder` | `5% 50%` | Reorder packets |
| `corrupt` | `0.1%` | Corrupt packet data |

### Automation Script for macOS

```bash
#!/bin/bash
# setup_network_emulation.sh

# Configuration
BANDWIDTH="5Mbit/s"
DELAY="25ms"
LOSS="0.02"
PORT="4433"

echo "Setting up network emulation..."
echo "  Bandwidth: $BANDWIDTH"
echo "  Delay: $DELAY (RTT: ~$((${DELAY%ms}*2))ms)"
echo "  Loss: $LOSS"

# Create pipe
sudo dnctl pipe 1 config bw $BANDWIDTH delay $DELAY plr $LOSS

# Set up packet filter rule
echo "dummynet in proto udp from any to 127.0.0.1 port $PORT pipe 1" | sudo pfctl -f -
sudo pfctl -e

echo "Network emulation active. Run your tests now."
echo "Press Enter to disable and clean up..."
read

# Clean up
sudo pfctl -d
sudo dnctl -q flush
echo "Network emulation disabled."
```

### Pros and Cons

| Pros | Cons |
|------|------|
| No code changes needed | Requires sudo/admin |
| Highly configurable | Platform-specific commands |
| Reproducible conditions | Still same-machine (no real NIC) |

---

## Option 3: Docker Network (Isolated Virtual Network)

Create containers with a virtual network between them.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Host                              │
│                                                             │
│   ┌───────────────┐     Docker      ┌───────────────┐      │
│   │   Container   │     Network     │   Container   │      │
│   │   (Client)    │ ◄─────────────► │   (Server)    │      │
│   │  172.20.0.3   │   quic_net      │  172.20.0.2   │      │
│   └───────────────┘                 └───────────────┘      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  server:
    build:
      context: .
      dockerfile: Dockerfile
    command: >
      python -c "
      from simulation.server import run_server_standalone
      import asyncio
      asyncio.run(run_server_standalone(host='0.0.0.0'))
      "
    networks:
      quic_net:
        ipv4_address: 172.20.0.2
    cap_add:
      - NET_ADMIN  # Required for tc commands

  client:
    build:
      context: .
      dockerfile: Dockerfile
    command: >
      python -c "
      from simulation.client import run_client_test
      import asyncio
      asyncio.run(run_client_test(host='172.20.0.2'))
      "
    networks:
      quic_net:
        ipv4_address: 172.20.0.3
    depends_on:
      - server
    cap_add:
      - NET_ADMIN

networks:
  quic_net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install network tools for tc/netem
RUN apt-get update && apt-get install -y iproute2 && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY pyproject.toml .
RUN pip install uv && uv pip install --system -e .

COPY . .
```

### Adding Bottleneck Inside Container

```bash
# Enter the client container
docker exec -it <client_container_id> bash

# Add network constraints
tc qdisc add dev eth0 root netem rate 1mbit delay 50ms loss 2%

# Run tests
python client.py --host 172.20.0.2
```

### Pros and Cons

| Pros | Cons |
|------|------|
| Reproducible environment | More setup complexity |
| Isolated from host | Container overhead |
| Easy to share/distribute | Requires Docker knowledge |

---

## Option 4: Linux Network Namespaces (Lightweight Virtual Network)

Create isolated network namespaces connected by a virtual ethernet pair.

### Architecture

```
┌────────────────────┐         Virtual Link         ┌────────────────────┐
│   client_ns        │        (with netem)          │   server_ns        │
│   ┌──────────┐     │                              │     ┌──────────┐   │
│   │  Client  │     │   ┌──────────────────────┐   │     │  Server  │   │
│   │ 10.0.0.1 │◄────┼───│  1Mbit, 25ms, 1%loss │───┼────►│ 10.0.0.2 │   │
│   └──────────┘     │   └──────────────────────┘   │     └──────────┘   │
└────────────────────┘                              └────────────────────┘
```

### Setup Script

```bash
#!/bin/bash
# setup_namespaces.sh

set -e

echo "Creating network namespaces..."

# Create two network namespaces
sudo ip netns add client_ns
sudo ip netns add server_ns

# Create a virtual ethernet pair
sudo ip link add veth-client type veth peer name veth-server

# Assign each end to a namespace
sudo ip link set veth-client netns client_ns
sudo ip link set veth-server netns server_ns

# Configure IP addresses
sudo ip netns exec client_ns ip addr add 10.0.0.1/24 dev veth-client
sudo ip netns exec server_ns ip addr add 10.0.0.2/24 dev veth-server

# Bring interfaces up
sudo ip netns exec client_ns ip link set lo up
sudo ip netns exec client_ns ip link set veth-client up
sudo ip netns exec server_ns ip link set lo up
sudo ip netns exec server_ns ip link set veth-server up

# Add bottleneck on the server side
sudo ip netns exec server_ns tc qdisc add dev veth-server root netem \
    rate 1mbit \
    delay 25ms \
    loss 1%

echo "Network namespaces ready!"
echo ""
echo "To run server:"
echo "  sudo ip netns exec server_ns python server.py --host 10.0.0.2"
echo ""
echo "To run client:"
echo "  sudo ip netns exec client_ns python client.py --host 10.0.0.2"
```

### Cleanup Script

```bash
#!/bin/bash
# cleanup_namespaces.sh

sudo ip netns del client_ns 2>/dev/null || true
sudo ip netns del server_ns 2>/dev/null || true

echo "Network namespaces cleaned up."
```

### Running Tests

```bash
# Terminal 1: Start server
sudo ip netns exec server_ns uv run python -c "
from simulation.server import run_server_standalone
import asyncio
asyncio.run(run_server_standalone(host='10.0.0.2'))
"

# Terminal 2: Run client
sudo ip netns exec client_ns uv run python -c "
from simulation.client import run_client_test
import asyncio
asyncio.run(run_client_test(host='10.0.0.2'))
"
```

### Pros and Cons

| Pros | Cons |
|------|------|
| Lightweight (no VMs/containers) | Linux only |
| Full network isolation | Requires root |
| Real kernel network stack | More complex setup |

---

## Option 5: Mininet (Full Network Emulator)

For complex topologies with routers, switches, and multiple bottleneck points.

### Architecture

```
                    ┌─────────────────────────────────────────┐
                    │              Mininet Topology            │
                    │                                         │
┌──────────┐        │        ┌──────────┐        ┌──────────┐ │        ┌──────────┐
│  Client  │◄───────┼───────►│ Switch 1 │◄──────►│ Switch 2 │◄┼───────►│  Server  │
│ 10.0.0.1 │        │ 10Mbps │          │ 1Mbps  │          │ │ 10Mbps │ 10.0.0.2 │
└──────────┘        │  5ms   └──────────┘ 50ms   └──────────┘ │  5ms   └──────────┘
                    │        (bottleneck link in the middle)  │
                    └─────────────────────────────────────────┘
```

### Installation

```bash
# Ubuntu/Debian
sudo apt-get install mininet

# Or install from source
git clone https://github.com/mininet/mininet
cd mininet
sudo ./util/install.sh -a
```

### Python Topology Script

```python
#!/usr/bin/env python3
# mininet_quic_test.py

from mininet.net import Mininet
from mininet.node import Controller
from mininet.link import TCLink
from mininet.log import setLogLevel
import time

def run_quic_test():
    setLogLevel('info')

    net = Mininet(link=TCLink)

    # Add hosts
    client = net.addHost('client', ip='10.0.0.1/24')
    server = net.addHost('server', ip='10.0.0.2/24')

    # Add switches
    s1 = net.addSwitch('s1')
    s2 = net.addSwitch('s2')

    # Add links with bandwidth/delay/loss constraints
    # Client to Switch 1: fast link
    net.addLink(client, s1, bw=10, delay='5ms', loss=0)

    # Switch 1 to Switch 2: bottleneck link
    net.addLink(s1, s2, bw=1, delay='50ms', loss=2)

    # Switch 2 to Server: fast link
    net.addLink(s2, server, bw=10, delay='5ms', loss=0)

    net.start()

    print("Network topology created!")
    print("Client: 10.0.0.1")
    print("Server: 10.0.0.2")
    print("Bottleneck: 1Mbps, 50ms delay, 2% loss")
    print()

    # Start server
    print("Starting QUIC server...")
    server.cmd('cd /path/to/code && python -m simulation.server --host 10.0.0.2 &')
    time.sleep(2)

    # Run client test
    print("Running QUIC client...")
    result = client.cmd('cd /path/to/code && python -m simulation.client --host 10.0.0.2')
    print(result)

    # Interactive CLI (optional)
    # from mininet.cli import CLI
    # CLI(net)

    net.stop()

if __name__ == '__main__':
    run_quic_test()
```

### Running

```bash
sudo python mininet_quic_test.py
```

### Pros and Cons

| Pros | Cons |
|------|------|
| Complex topologies possible | Linux only |
| Multiple bottleneck points | Learning curve |
| Research-grade emulation | Requires root |
| Reproducible experiments | Heavier than other options |

---

## Comparison and Recommendations

### Feature Comparison

| Option | Complexity | Realism | Platform | Root Required |
|--------|------------|---------|----------|---------------|
| Separate machines | Low | Highest | Any | No |
| macOS dnctl/pfctl | Low | Good | macOS | Yes |
| Linux tc/netem | Low | Good | Linux | Yes |
| Docker network | Medium | Good | Any | No (usually) |
| Network namespaces | Medium | Good | Linux | Yes |
| Mininet | High | Very good | Linux | Yes |

### Recommendation by Use Case

| Use Case | Recommended Option |
|----------|-------------------|
| Quick local testing on macOS | **Option 2: dnctl/pfctl** |
| Quick local testing on Linux | **Option 2: tc/netem** |
| Production-like testing | **Option 1: Separate machines** |
| CI/CD pipelines | **Option 3: Docker** |
| Research experiments | **Option 5: Mininet** |
| Lightweight isolation | **Option 4: Network namespaces** |

### Quick Start (macOS)

For immediate testing on your macOS system:

```bash
# 1. Set up bottleneck (run once)
sudo dnctl pipe 1 config bw 5Mbit/s delay 25ms plr 0.02
echo "dummynet in proto udp from any to 127.0.0.1 port 4433 pipe 1" | sudo pfctl -f -
sudo pfctl -e

# 2. Run your tests
uv run python code/main.py single --app video_streaming --loss-factor 0.4
uv run python code/main.py single --app video_streaming --loss-factor 0.7

# 3. Compare results - you should now see differences!

# 4. Clean up
sudo pfctl -d && sudo dnctl -q flush
```

This will finally let you observe the effects of `loss_reduction_factor` because packets will actually be lost and the congestion control will need to respond.
