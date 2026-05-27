# Alternative Throughput Measurement Approaches

## Overview

This document describes various approaches for measuring per-connection throughput in the QUIC 3-connection simulation. Each approach has trade-offs in terms of accuracy, complexity, and suitability for Q-learning feedback.

---

## Table of Contents

1. [Current Approach: Proportional Estimation](#1-current-approach-proportional-estimation)
2. [Receiver-Side Measurement](#2-receiver-side-measurement)
   - [2.1 Bytes-Based Matching](#21-bytes-based-matching)
   - [2.2 Connection ID Encoding](#22-connection-id-encoding)
   - [2.3 Separate Server Ports](#23-separate-server-ports)
   - [2.4 Aggregate Only](#24-aggregate-only)
3. [Effective Throughput (cwnd/RTT)](#3-effective-throughput-cwndrtt)
4. [Separate IP Addresses](#4-separate-ip-addresses)
5. [QUIC ACK-Based Measurement](#5-quic-ack-based-measurement)
6. [Comparison Matrix](#6-comparison-matrix)
7. [Recommendations](#7-recommendations)

---

## 1. Current Approach: Proportional Estimation

### How It Works

Uses the tc (traffic control) aggregate throughput and distributes it proportionally based on offered load:

```
actual_throughput[i] = tc_observed × (offered[i] / total_offered)
```

### Example

| Connection | Offered | Proportion | Actual (5 Mbps bottleneck) |
|------------|---------|------------|---------------------------|
| Video | 1.33 Mbps | 0.6% | 0.03 Mbps |
| File | 210 Mbps | 99.3% | 4.96 Mbps |
| Conference | 0.11 Mbps | 0.05% | 0.003 Mbps |

### Pros
- No code changes required
- Works with existing tc statistics
- Simple calculation

### Cons
- **Estimation only** - not actual measurement
- Assumes proportional sharing (real networks may differ)
- Doesn't reflect actual congestion control behavior
- Small flows appear starved even if they got full throughput

### Best For
- Quick approximation when actual measurement isn't available

---

## 2. Receiver-Side Measurement

### Core Concept

Measure bytes actually received at the server, then calculate throughput:

```
receiver_throughput = bytes_received / duration
```

This directly measures what made it through the bottleneck.

---

### 2.1 Bytes-Based Matching

**How It Works:**
Match server protocols to client connections based on total bytes:

```python
def match_connections(client_metrics, server_metrics):
    """Match where server.bytes_received ≈ client.bytes_sent"""
    matches = {}

    for conn_id, client_data in client_metrics.items():
        client_bytes = client_data["bytes_sent"]

        for server_id, server_data in server_metrics.items():
            server_bytes = server_data["bytes_received"]

            # 5% tolerance for protocol overhead
            if abs(client_bytes - server_bytes) < client_bytes * 0.05:
                matches[conn_id] = server_id
                break

    return matches
```

**Pros:**
- No protocol changes needed
- Works with current implementation

**Cons:**
- **Fails if applications send similar byte counts**
- Ambiguous matching possible

**Best For:**
- Applications with distinctly different data volumes (current setup)

---

### 2.2 Connection ID Encoding

**How It Works:**
Client encodes its connection ID in the first data packet:

```python
# Client side (synthesizer)
class BaseSynthesizer:
    def __init__(self, connection_id: int, ...):
        self.connection_id = connection_id
        self._sent_header = False

    async def generate(self):
        async for packet in self._generate_data():
            if not self._sent_header:
                # Prepend 4-byte connection ID header
                header = self.connection_id.to_bytes(4, 'big')
                packet.data = header + packet.data
                self._sent_header = True
            yield packet
```

```python
# Server side
class ServerProtocol:
    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            if self.connection_id is None and len(event.data) >= 4:
                # Extract connection ID from first packet
                self.connection_id = int.from_bytes(event.data[:4], 'big')
                event.data = event.data[4:]  # Remove header

            self.total_bytes_received += len(event.data)
```

**Pros:**
- **Robust matching regardless of data volumes**
- Minimal overhead (4 bytes once per connection)
- Deterministic correlation

**Cons:**
- Requires changes to synthesizers
- Requires server-side extraction logic
- Slightly modifies data stream

**Best For:**
- Production use where applications may have similar throughput
- When deterministic matching is required

---

### 2.3 Separate Server Ports

**How It Works:**
Each application connects to a different port:

```yaml
# docker-compose.yml
services:
  server:
    ports:
      - "4433:4433"  # Video
      - "4434:4434"  # File Transfer
      - "4435:4435"  # Conference
```

```python
# Server configuration
PORT_TO_APP = {
    4433: "video_streaming",
    4434: "file_transfer",
    4435: "conference_call",
}

# Client configuration
APP_TO_PORT = {
    "video_streaming": 4433,
    "file_transfer": 4434,
    "conference_call": 4435,
}
```

**Pros:**
- **No matching needed** - port identifies application
- Clean separation
- Easy to debug (can filter by port)

**Cons:**
- Requires multiple server listeners
- More complex configuration
- Doesn't reflect real-world single-endpoint scenarios

**Best For:**
- Testing/debugging individual applications
- When isolation is more important than realism

---

### 2.4 Aggregate Only

**How It Works:**
Report only total server throughput without per-connection breakdown:

```python
def get_aggregate_receiver_throughput(self) -> float:
    """Total throughput across all connections."""
    total_bytes = sum(p.total_bytes_received for p in self._protocols)
    total_duration = max(p.get_duration() for p in self._protocols)

    return (total_bytes * 8) / total_duration  # bps
```

**Output:**
```json
{
  "aggregate_receiver_throughput_mbps": 3.58,
  "tc_observed_throughput_mbps": 3.60,
  "match": true
}
```

**Pros:**
- **No matching needed**
- Validates bottleneck is working correctly
- Simple implementation

**Cons:**
- No per-connection visibility
- Can't see individual application performance
- Less useful for Q-learning per-connection rewards

**Best For:**
- Validating the bottleneck setup
- When only aggregate throughput matters

---

## 3. Effective Throughput (cwnd/RTT)

### How It Works

Calculate throughput from congestion control state:

```
effective_throughput = congestion_window / RTT
```

This measures the **maximum achievable throughput** given current congestion control parameters.

```python
def get_effective_throughput(self) -> float:
    """Calculate throughput based on cwnd/RTT."""
    avg_cwnd = statistics.mean(self.cwnd_samples)  # bytes
    avg_rtt = statistics.mean(self.rtt_samples)    # seconds

    if avg_rtt <= 0:
        return 0.0

    return avg_cwnd / avg_rtt  # bytes per second
```

### Example

| Connection | avg_cwnd | avg_rtt | Effective Throughput |
|------------|----------|---------|---------------------|
| Video | 50 KB | 40 ms | 10 Mbps |
| File | 100 KB | 45 ms | 17.8 Mbps |
| Conference | 15 KB | 38 ms | 3.16 Mbps |

### Pros
- **Direct feedback on congestion control state**
- Shows immediate impact of Q-learning parameter changes
- No server-side changes needed
- Already have cwnd and RTT samples

### Cons
- Measures **potential** throughput, not **actual** delivery
- Doesn't account for packet loss
- May overestimate if application doesn't saturate cwnd

### Best For
- Q-learning feedback on parameter effectiveness
- Understanding congestion control behavior
- When you care about what the network *allows* vs what was *delivered*

---

## 4. Separate IP Addresses

### How It Works

Give each client a different IP address, then use tc per-flow statistics:

```yaml
# docker-compose.yml
services:
  client-video:
    networks:
      quic-net:
        ipv4_address: 192.168.200.21

  client-file:
    networks:
      quic-net:
        ipv4_address: 192.168.200.22

  client-conference:
    networks:
      quic-net:
        ipv4_address: 192.168.200.23
```

```bash
# tc filter per source IP
tc filter add dev eth0 parent 1: protocol ip prio 1 \
    u32 match ip src 192.168.200.21 flowid 1:10
tc filter add dev eth0 parent 1: protocol ip prio 1 \
    u32 match ip src 192.168.200.22 flowid 1:20
tc filter add dev eth0 parent 1: protocol ip prio 1 \
    u32 match ip src 192.168.200.23 flowid 1:30

# Get per-class statistics
tc -s class show dev eth0
```

### Pros
- **True per-flow network measurement**
- Uses kernel-level statistics (most accurate)
- Can apply different shaping per flow

### Cons
- **Significant architecture change**
- Requires separate containers or network namespaces
- More complex Docker setup
- tc filter configuration complexity

### Best For
- Research requiring precise per-flow measurement
- When you need to shape flows differently
- Production multi-tenant scenarios

---

## 5. QUIC ACK-Based Measurement

### How It Works (Original Attempt)

Track bytes acknowledged by the receiver:

```python
bytes_acked = bytes_sent - bytes_in_flight
acked_throughput = bytes_acked / duration
```

### Why It Failed

QUIC ACKs are **cumulative over time**. Eventually all sent data gets acknowledged, even through a bottleneck:

```
Time    bytes_sent    bytes_in_flight    bytes_acked
0s      0             0                  0
10s     100 MB        50 KB              99.95 MB
30s     800 MB        50 KB              799.95 MB  ← Looks like 210 Mbps!
```

The bottleneck slows delivery, but ACKs still come back eventually.

### Potential Fix: Windowed ACK Rate

```python
def get_ack_rate(self, window_seconds: float = 1.0) -> float:
    """Calculate ACK rate over a sliding window."""
    now = time.time()
    recent_acks = [
        (ts, bytes) for ts, bytes in self.ack_timeline
        if now - ts <= window_seconds
    ]

    if len(recent_acks) < 2:
        return 0.0

    bytes_in_window = recent_acks[-1][1] - recent_acks[0][1]
    time_span = recent_acks[-1][0] - recent_acks[0][0]

    return bytes_in_window / time_span
```

### Pros
- Client-side only (no server changes)
- Reflects actual acknowledgment rate

### Cons
- Complex to implement correctly
- Requires precise timing
- Still doesn't measure *delivery*, just *acknowledgment*

### Best For
- When server-side measurement isn't possible
- Debugging congestion control behavior

---

## 6. Comparison Matrix

| Approach | Accuracy | Complexity | Server Changes | Q-Learning Suitability |
|----------|----------|------------|----------------|----------------------|
| Proportional Estimation | Low | Low | None | Poor - estimation only |
| Receiver-Side (Bytes Match) | High | Medium | Yes | Good |
| Receiver-Side (ID Encoding) | High | Medium | Yes | Good |
| Receiver-Side (Separate Ports) | High | High | Yes | Good |
| Receiver-Side (Aggregate) | Medium | Low | Yes | Limited - no per-conn |
| Effective (cwnd/RTT) | Medium | Low | None | **Excellent** - direct feedback |
| Separate IPs + tc | **Highest** | **Highest** | Yes | Good |
| ACK-Based (Windowed) | Medium | High | None | Medium |

---

## 7. Recommendations

### For Q-Learning Optimization

**Recommended: Effective Throughput (cwnd/RTT)**

Why:
- Direct feedback on parameter changes
- No server modifications needed
- Shows congestion control state immediately
- Already collecting cwnd and RTT samples

### For Accurate Network Measurement

**Recommended: Receiver-Side with ID Encoding**

Why:
- Measures actual bytes delivered
- Robust matching regardless of application data rates
- Minimal protocol overhead
- Works with single server endpoint

### For Quick Validation

**Recommended: Receiver-Side Aggregate**

Why:
- Confirms bottleneck is working
- Simple implementation
- sum(receiver) ≈ tc_observed validates setup

### For Research/Production

**Recommended: Separate IP Addresses**

Why:
- True per-flow kernel statistics
- Most accurate measurement possible
- Enables per-flow traffic shaping

---

## Implementation Priority

If implementing from scratch:

1. **Start with cwnd/RTT** - Already have the data, just need calculation
2. **Add Receiver-Side Aggregate** - Validates bottleneck, simple addition
3. **Add ID Encoding** - If per-connection accuracy needed
4. **Consider Separate IPs** - Only if research requires precise measurement

---

## Summary

| Goal | Best Approach |
|------|---------------|
| Q-learning feedback | cwnd/RTT |
| Actual delivery measurement | Receiver-side (ID encoding) |
| Bottleneck validation | Receiver-side (aggregate) |
| Maximum accuracy | Separate IPs + tc filters |
| Minimal changes | Proportional estimation (current) |
