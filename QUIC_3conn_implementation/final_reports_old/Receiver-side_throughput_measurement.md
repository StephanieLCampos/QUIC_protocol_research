# Receiver-Side Throughput Measurement

## Comprehensive Report

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [What Is Receiver-Side Measurement](#2-what-is-receiver-side-measurement)
3. [How It Works](#3-how-it-works)
4. [System Architecture Overview](#4-system-architecture-overview)
5. [What It Measures](#5-what-it-measures)
6. [Comparison With Other Methods](#6-comparison-with-other-methods)
7. [Implementation Plan](#7-implementation-plan)
8. [Data Flow](#8-data-flow)
9. [Connection Matching Algorithm](#9-connection-matching-algorithm)
10. [Integration With Q-Learning](#10-integration-with-q-learning)
11. [Validation](#11-validation)

---

## 1. Executive Summary

**Receiver-side throughput measurement** is a technique where the data receiver (server) tracks how many bytes it receives from each connection over time. This provides an accurate measurement of the actual network throughput that successfully traversed the network path, including any bottlenecks.

### Key Points

- **What**: Server counts bytes received per connection
- **Why**: Directly measures successful data delivery
- **Accuracy**: Measures actual throughput, not estimates
- **Complexity**: Low - pure application-level implementation

---

## 2. What Is Receiver-Side Measurement

### Definition

Receiver-side measurement tracks the amount of data that successfully arrives at the destination, measured at the receiving application.

```
Throughput = bytes_received / time
```

### Intuition

Think of it like counting packages:

```
┌─────────┐                           ┌─────────┐
│ Sender  │  ── Sends 100 packages ─► │Receiver │
│         │                           │         │
│         │     Network may lose      │ Counts: │
│         │     or delay some         │ "I got  │
│         │                           │ 85"     │
└─────────┘                           └─────────┘

Receiver-side throughput = 85 packages / time
(Not 100 - that would be offered/sent throughput)
```

### Industry Standard

This is how throughput is measured in practice:

| Tool | Method |
|------|--------|
| iperf3 | Server reports bytes received |
| speedtest.net | Download = server sends, client measures received |
| Netflix/YouTube | Client measures bytes received for quality adaptation |
| File downloads | "Downloaded X MB" = bytes received |

---

## 3. How It Works

### Step-by-Step Process

```
1. Client sends data through QUIC connection
         │
         ▼
2. Data travels through network
   (may pass through bottleneck, experience loss/delay)
         │
         ▼
3. Server receives data on QUIC stream
         │
         ▼
4. Server increments counter: bytes_received[connection_id] += len(data)
         │
         ▼
5. At end of simulation, calculate:
   throughput = bytes_received[connection_id] / duration
```

### Pseudocode

```python
# Server-side tracking
class ServerProtocol:
    def __init__(self):
        self.bytes_received = {}  # Per-connection counters
        self.start_time = {}      # Per-connection start times

    def handle_stream_data(self, connection_id, data):
        # Track first data arrival
        if connection_id not in self.start_time:
            self.start_time[connection_id] = time.time()

        # Count bytes received
        if connection_id not in self.bytes_received:
            self.bytes_received[connection_id] = 0
        self.bytes_received[connection_id] += len(data)

    def get_throughput(self, connection_id):
        duration = time.time() - self.start_time[connection_id]
        if duration <= 0:
            return 0.0
        return self.bytes_received[connection_id] / duration
```

---

## 4. System Architecture Overview

### High-Level View

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SIMULATION ENVIRONMENT                        │
│                                                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐             │
│  │  Client 1   │    │  Client 2   │    │  Client 3   │             │
│  │   (Video)   │    │   (File)    │    │(Conference) │             │
│  │             │    │             │    │             │             │
│  │ Sends:      │    │ Sends:      │    │ Sends:      │             │
│  │ 1.33 Mbps   │    │ 210 Mbps    │    │ 0.11 Mbps   │             │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘             │
│         │                  │                  │                     │
│         └──────────────────┼──────────────────┘                     │
│                            │                                        │
│                            ▼                                        │
│                   ┌─────────────────┐                               │
│                   │    NETWORK      │                               │
│                   │   BOTTLENECK    │                               │
│                   │    (5 Mbps)     │                               │
│                   │                 │                               │
│                   │  Limits total   │                               │
│                   │  throughput     │                               │
│                   └────────┬────────┘                               │
│                            │                                        │
│                            ▼                                        │
│                   ┌─────────────────┐                               │
│                   │     SERVER      │                               │
│                   │                 │                               │
│                   │ ┌─────────────┐ │                               │
│                   │ │ Connection 1│ │  Received: 1.30 Mbps         │
│                   │ │   (Video)   │ │                               │
│                   │ └─────────────┘ │                               │
│                   │ ┌─────────────┐ │                               │
│                   │ │ Connection 2│ │  Received: 2.15 Mbps         │
│                   │ │   (File)    │ │                               │
│                   │ └─────────────┘ │                               │
│                   │ ┌─────────────┐ │                               │
│                   │ │ Connection 3│ │  Received: 0.10 Mbps         │
│                   │ │(Conference) │ │                               │
│                   │ └─────────────┘ │                               │
│                   │                 │                               │
│                   │ TOTAL: 3.55 Mbps│  ≈ tc observed               │
│                   └─────────────────┘                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Interaction

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│   CLIENT SIDE                      SERVER SIDE                   │
│                                                                  │
│   ┌────────────┐                   ┌────────────┐               │
│   │Synthesizer │                   │  Server    │               │
│   │            │                   │  Protocol  │               │
│   │ Generates  │                   │            │               │
│   │ app data   │                   │ Receives   │               │
│   └─────┬──────┘                   │ data       │               │
│         │                          └─────┬──────┘               │
│         ▼                                │                       │
│   ┌────────────┐                         │                       │
│   │   QUIC     │                         ▼                       │
│   │  Client    │    ─── Network ───►  ┌────────────┐            │
│   │            │                      │   QUIC     │            │
│   │ bytes_sent │                      │  Server    │            │
│   └────────────┘                      │            │            │
│                                       │bytes_recv  │◄── MEASURE │
│                                       └────────────┘    HERE    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 5. What It Measures

### Primary Metric

**Receiver-side throughput**: The rate at which data successfully arrives at the server.

```
receiver_throughput[conn] = bytes_received[conn] / duration
```

### What This Captures

| Factor | Captured? | How |
|--------|-----------|-----|
| Bottleneck limitation | Yes | Less data arrives if bottleneck is saturated |
| Packet loss | Yes | Lost packets don't arrive at receiver |
| Network congestion | Yes | Congestion reduces delivery rate |
| Queuing delays | Partially | Affects timing, not total bytes |
| Application demand | No | Only measures what arrived, not what was sent |

### What This Does NOT Capture

| Factor | Why Not |
|--------|---------|
| Offered load | That's measured at sender (already have this) |
| Where loss occurred | Only knows data didn't arrive |
| Bottleneck utilization | Need tc statistics for that |

### Units

```
bytes_received: bytes (raw count)
duration: seconds
throughput: bytes/second → convert to Mbps

throughput_mbps = (bytes_received * 8) / (duration * 1,000,000)
```

---

## 6. Comparison With Other Methods

### Method Comparison Table

| Method | Measures | Location | Accuracy | Complexity |
|--------|----------|----------|----------|------------|
| **Offered throughput** | App send rate | Client | High (for what's sent) | Low |
| **Proportional estimate** | tc_total × ratio | Calculated | Low (estimate only) | Low |
| **cwnd/RTT** | Congestion-limited rate | Client | Medium (sender's view) | Low |
| **tc per-IP filtering** | Bytes through bottleneck | Bottleneck | High | High |
| **Receiver-side** | Bytes delivered | Server | **High** | **Low** |

### Why Receiver-Side Is Best for This Project

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  Q-Learning Question:                                           │
│  "Did my parameter changes improve data delivery?"              │
│                                                                 │
│  ┌─────────────────┐                                           │
│  │ Offered (sent)  │ → "How much did the app try to send?"     │
│  │                 │   (Doesn't show bottleneck impact)        │
│  └─────────────────┘                                           │
│                                                                 │
│  ┌─────────────────┐                                           │
│  │ cwnd/RTT        │ → "What does sender think it can send?"   │
│  │                 │   (Sender's estimate, not actual)         │
│  └─────────────────┘                                           │
│                                                                 │
│  ┌─────────────────┐                                           │
│  │ Receiver-side   │ → "How much data actually arrived?"       │
│  │                 │   (DIRECTLY ANSWERS THE QUESTION)    ✓    │
│  └─────────────────┘                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. Implementation Plan

### Overview

```
Files to modify:
  1. 3_conn_code/simulation/server.py      ← Add bytes tracking
  2. 3_conn_code/simulation/result.py      ← Report receiver throughput
  3. 3_conn_code/simulation/worker_process.py ← Collect server metrics
```

### Step 1: Add Tracking in Server

```python
# In server.py - ServerProtocol class

class ServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bytes_received_per_stream = {}
        self.connection_start_time = None

    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            # Track bytes received
            stream_id = event.stream_id
            data_length = len(event.data)

            if stream_id not in self.bytes_received_per_stream:
                self.bytes_received_per_stream[stream_id] = 0
            self.bytes_received_per_stream[stream_id] += data_length

            # Track timing
            if self.connection_start_time is None:
                self.connection_start_time = time.time()

    def get_total_bytes_received(self):
        return sum(self.bytes_received_per_stream.values())

    def get_receiver_throughput(self):
        if self.connection_start_time is None:
            return 0.0
        duration = time.time() - self.connection_start_time
        if duration <= 0:
            return 0.0
        return self.get_total_bytes_received() / duration
```

### Step 2: Report Metrics Back to Client

The server needs to communicate its measurements back. Options:

**Option A: Via QUIC stream (in-band)**
```python
# Server sends metrics on a dedicated stream
metrics_data = {
    "bytes_received": self.get_total_bytes_received(),
    "duration": time.time() - self.connection_start_time,
    "throughput_bps": self.get_receiver_throughput() * 8
}
self.send_metrics(metrics_data)
```

**Option B: Via shared results (out-of-band)**
```python
# Server writes to shared file/memory that orchestrator reads
# Simpler for Docker setup
```

### Step 3: Include in Results

```python
# In result.py - add to per_connection_throughput

per_connection_throughput[str(conn_id)] = {
    "application_type": result.application_type,
    "offered_throughput_mbps": offered_mbps,
    "receiver_throughput_mbps": receiver_mbps,  # NEW
}
```

---

## 8. Data Flow

### Complete Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA FLOW                                    │
│                                                                     │
│  TIME ──────────────────────────────────────────────────────────►   │
│                                                                     │
│  t=0        t=1        t=2        t=3        t=end                 │
│   │          │          │          │          │                     │
│   ▼          ▼          ▼          ▼          ▼                     │
│                                                                     │
│  CLIENT:                                                            │
│  ┌────┐    ┌────┐    ┌────┐    ┌────┐    ┌────────────┐           │
│  │Send│    │Send│    │Send│    │Send│    │ Report:    │           │
│  │100 │    │100 │    │100 │    │100 │    │ bytes_sent │           │
│  │bytes│   │bytes│   │bytes│   │bytes│   │ = 400      │           │
│  └──┬─┘    └──┬─┘    └──┬─┘    └──┬─┘    └────────────┘           │
│     │         │         │         │                                 │
│     ▼         ▼         ▼         ▼                                 │
│                                                                     │
│  NETWORK (bottleneck may drop/delay):                               │
│     │         │         │         │                                 │
│     ▼         ▼         ▼         ▼                                 │
│    95        90        92        88     (bytes that make it)       │
│     │         │         │         │                                 │
│     ▼         ▼         ▼         ▼                                 │
│                                                                     │
│  SERVER:                                                            │
│  ┌────┐    ┌────┐    ┌────┐    ┌────┐    ┌────────────┐           │
│  │Recv│    │Recv│    │Recv│    │Recv│    │ Report:    │           │
│  │ 95 │    │ 90 │    │ 92 │    │ 88 │    │ bytes_recv │           │
│  │bytes│   │bytes│   │bytes│   │bytes│   │ = 365      │           │
│  └────┘    └────┘    └────┘    └────┘    └────────────┘           │
│                                                                     │
│  RESULT:                                                            │
│    offered_throughput  = 400 / duration                            │
│    receiver_throughput = 365 / duration   ◄── ACTUAL NETWORK       │
│    delivery_ratio      = 365 / 400 = 91.25%                        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Per-Connection Breakdown

```
┌────────────────────────────────────────────────────────────────────┐
│                    PER-CONNECTION METRICS                          │
│                                                                    │
│  Connection 1 (Video Streaming):                                   │
│    Client sent:     1,330,000 bytes/sec (offered)                  │
│    Server received: 1,300,000 bytes/sec (receiver throughput)      │
│    Delivery: 97.7%                                                 │
│                                                                    │
│  Connection 2 (File Transfer):                                     │
│    Client sent:     210,000,000 bytes/sec (offered)                │
│    Server received:   2,150,000 bytes/sec (receiver throughput)    │
│    Delivery: 1.02%  ← Heavily bottlenecked!                        │
│                                                                    │
│  Connection 3 (Conference Call):                                   │
│    Client sent:       110,000 bytes/sec (offered)                  │
│    Server received:   100,000 bytes/sec (receiver throughput)      │
│    Delivery: 90.9%                                                 │
│                                                                    │
│  ─────────────────────────────────────────────────────────────     │
│  Total receiver throughput: 3,550,000 bytes/sec ≈ 3.55 Mbps        │
│  (Matches tc observed throughput)                                  │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

---

## 9. Connection Matching Algorithm

### The Challenge

In a multi-container Docker setup, the server and clients run in separate containers. The server assigns connection IDs based on arrival order, which may differ from the client's connection IDs. We need to correlate server-side metrics with the correct client connections.

### Why Simple Matching Fails With Bottlenecks

Initial approach: Match where `bytes_sent ≈ bytes_received`

```
Problem scenario (5 Mbps bottleneck):

  Client Side:                    Server Side:
  ├─ Video: sent 50 MB           ├─ Conn 1: received 430 KB
  ├─ File:  sent 855 MB          ├─ Conn 2: received 5 MB
  └─ Conf:  sent 430 KB          └─ Conn 3: received 7 MB

  Video (50 MB) ≈ Server Conn 2 (5 MB)?   → Close enough ✓
  Conf (430 KB) ≈ Server Conn 1 (430 KB)? → Exact match ✓
  File (855 MB) ≈ Server Conn 3 (7 MB)?   → 855 MB ≠ 7 MB ✗

  File transfer sent 100x more than arrived due to bottleneck!
```

### Two-Pass Matching Algorithm

**Pass 1: Exact Matching**
- For connections where `bytes_sent ≈ bytes_received` (within 15%)
- Works for video and conference (not heavily bottlenecked)
- Sort clients by bytes ascending (smallest first - more likely to match)

**Pass 2: Ranking Matching**
- For unmatched connections (bottlenecked flows)
- Match by throughput rank: highest sender → highest receiver
- Logic: The biggest sender likely corresponds to the biggest receiver

```python
def _match_server_to_client_connections(self) -> Dict[int, int]:
    """
    Two-pass matching algorithm:
    1. Exact matching where bytes_sent ≈ bytes_received
    2. Ranking matching for bottlenecked flows
    """
    matches = {}
    used_server_ids = set()

    # PASS 1: Exact matching (ascending order - smallest first)
    for client_id, client_sent in sorted(client_bytes.items(), key=lambda x: x[1]):
        for server_id, server_data in server_metrics.items():
            if server_id in used_server_ids:
                continue
            server_received = server_data["bytes_received"]

            # 15% tolerance
            if abs(client_sent - server_received) < client_sent * 0.15:
                matches[client_id] = server_id
                used_server_ids.add(server_id)
                break

    # PASS 2: Ranking matching for unmatched
    unmatched_clients = sorted(
        [c for c in client_bytes if c not in matches],
        key=lambda c: client_bytes[c],
        reverse=True  # Highest first
    )
    unmatched_servers = sorted(
        [s for s in server_metrics if s not in used_server_ids],
        key=lambda s: server_metrics[s]["bytes_received"],
        reverse=True  # Highest first
    )

    # Match by rank: highest → highest
    for client_id, server_id in zip(unmatched_clients, unmatched_servers):
        matches[client_id] = server_id

    return matches
```

### Example With Bottleneck

```
Step 1: Collect data

  Client metrics:                 Server metrics:
  ├─ Conn 1 (Video): 50 MB       ├─ Server 1: 430 KB
  ├─ Conn 2 (File):  855 MB      ├─ Server 2: 5 MB
  └─ Conn 3 (Conf):  430 KB      └─ Server 3: 7 MB

Step 2: Pass 1 - Exact matching (smallest first)

  Conf (430 KB) vs Server 1 (430 KB) → Match! ✓
  Video (50 MB) vs Server 2 (5 MB)   → 50 MB ≠ 5 MB, skip
  Video (50 MB) vs Server 3 (7 MB)   → 50 MB ≠ 7 MB, skip
  File (855 MB) vs remaining         → No match

  After Pass 1:
    Conn 3 (Conf) → Server 1 ✓
    Conn 1 (Video) → unmatched
    Conn 2 (File) → unmatched

Step 3: Pass 2 - Ranking matching

  Unmatched clients (by bytes desc): [File (855 MB), Video (50 MB)]
  Unmatched servers (by bytes desc): [Server 3 (7 MB), Server 2 (5 MB)]

  Match by rank:
    File (highest client) → Server 3 (highest server) ✓
    Video (2nd client) → Server 2 (2nd server) ✓

Final matches:
  Conn 1 (Video) → Server 2 (5 MB received)   → 1.33 Mbps
  Conn 2 (File)  → Server 3 (7 MB received)   → 1.88 Mbps
  Conn 3 (Conf)  → Server 1 (430 KB received) → 0.115 Mbps
```

### Why This Works

1. **Small flows match exactly**: Video and conference aren't heavily bottlenecked, so `bytes_sent ≈ bytes_received`

2. **Large flows match by rank**: File transfer dominates both sending AND receiving, even if absolute values differ

3. **Handles any bottleneck severity**: Whether 10% or 1% of data gets through, ranking still works

---

## 10. Integration With Q-Learning

### Reward Signal

Receiver-side throughput provides a clear reward signal:

```python
def calculate_reward(metrics):
    # Throughput component (from receiver-side measurement)
    throughput_reward = sum(
        conn.receiver_throughput_mbps
        for conn in connections
    )

    # Fairness component
    fairness_reward = calculate_jains_fairness(
        [conn.receiver_throughput_mbps for conn in connections]
    )

    # QoS component (did real-time apps get enough?)
    qos_reward = 0
    for conn in connections:
        if conn.app_type in ['video', 'conference']:
            if conn.receiver_throughput >= conn.required_throughput:
                qos_reward += 1

    return throughput_reward + fairness_reward + qos_reward
```

### Why This Helps Q-Learning

```
Before (with proportional estimate):
  Q-Learning changes parameters
       │
       ▼
  cwnd changes, but proportional estimate
  still shows same ratio
       │
       ▼
  Weak/unclear learning signal


After (with receiver-side):
  Q-Learning changes parameters
       │
       ▼
  cwnd changes → sending rate changes
       │
       ▼
  Server receives different amount
       │
       ▼
  Receiver throughput directly reflects change
       │
       ▼
  Clear learning signal!
```

### Example Learning Scenario

```
Scenario: Q-Learning tries to help video streaming

State 1 (Before):
  Video:      receiver_throughput = 0.5 Mbps  (needs 1.33)  ✗
  File:       receiver_throughput = 3.0 Mbps
  Conference: receiver_throughput = 0.05 Mbps (needs 0.11) ✗

  Q-Learning sees: Video and Conference starving!
  Action: Reduce file transfer's max_cwnd

State 2 (After):
  Video:      receiver_throughput = 1.2 Mbps  (closer!)    ↑
  File:       receiver_throughput = 2.2 Mbps               ↓
  Conference: receiver_throughput = 0.1 Mbps  (almost!)    ↑

  Q-Learning sees: Improvement! Reinforce this action.
```

---

## 11. Validation

### How to Verify Correctness

#### Check 1: Sum Matches tc Total

```
sum(receiver_throughput) ≈ tc_observed_throughput

Example:
  Video:       1.30 Mbps
  File:        2.15 Mbps
  Conference:  0.10 Mbps
  ─────────────────────
  Total:       3.55 Mbps

  tc_observed: 3.60 Mbps

  Difference: 1.4% (acceptable - protocol overhead)
```

#### Check 2: Receiver <= Offered

```
For each connection:
  receiver_throughput <= offered_throughput

Cannot receive more than was sent.
```

#### Check 3: Consistency Over Time

```
Run same configuration multiple times:
  - Receiver throughput should be consistent (±5%)
  - Validates measurement stability
```

#### Check 4: Bottleneck Impact

```
Test 1: No bottleneck (high capacity)
  → receiver ≈ offered for all connections

Test 2: Tight bottleneck (low capacity)
  → receiver << offered for greedy connections
  → sum(receiver) ≈ bottleneck capacity
```

---

## Summary

| Aspect | Description |
|--------|-------------|
| **What** | Server counts bytes received per connection |
| **Where** | Measurement happens at the server (receiver) |
| **Why** | Directly measures successful data delivery |
| **Accuracy** | High - measures actual network throughput |
| **Complexity** | Low - pure application-level implementation |
| **Q-Learning benefit** | Clear, direct feedback on parameter effectiveness |

### Key Insight

```
Receiver-side throughput answers the fundamental question:

  "How much data actually made it through the network?"

This is exactly what Q-learning needs to know to optimize
congestion control parameters for fairness and performance.
```
