# Parameter Timing and Mid-Connection Changes

This document explains when each aioquic parameter is used during a QUIC connection, and whether changing it mid-connection will have any effect.

## Overview

Not all parameters work the same way:
- Some are used **only at connection start** - changing them mid-connection has no effect
- Some are used **continuously** - changing them mid-connection affects future behavior
- Some are **negotiated at handshake** - cannot be changed after connection starts

## Parameter Categories

### Category 1: Start-Only Parameters

These parameters are read once at connection start. Changing them mid-connection has **no effect** on the current connection.

```
┌─────────────────────────────────────────────────────────────────┐
│  START-ONLY PARAMETERS                                          │
│                                                                 │
│  TIME 0: Connection starts                                      │
│          Parameter value is READ ONCE                           │
│          Used as starting point or initial configuration        │
│                                                                 │
│  TIME 1s+: ML changes parameter value                           │
│            NOTHING HAPPENS to current connection                │
│            Only affects NEW connections started after change    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

| Parameter | When Read | Why No Mid-Connection Effect |
|-----------|-----------|------------------------------|
| `K_INITIAL_WINDOW` | Connection start | cwnd is now managed by CC |
| `initial_rtt` | Until first RTT measured | Real RTT measurements replace it |

### Category 2: Continuously-Used Parameters

These parameters are read every time the relevant event occurs. Changing them mid-connection **will affect** future behavior.

```
┌─────────────────────────────────────────────────────────────────┐
│  CONTINUOUSLY-USED PARAMETERS                                   │
│                                                                 │
│  TIME 0: Connection starts with parameter = X                   │
│                                                                 │
│  TIME 1s: Event occurs                                          │
│           CC reads parameter, uses value X                      │
│                                                                 │
│  TIME 2s: ML changes parameter to Y                             │
│                                                                 │
│  TIME 3s: Event occurs again                                    │
│           CC reads parameter, uses NEW value Y                  │
│                                                                 │
│  CHANGE TAKES EFFECT on next relevant event                     │
└─────────────────────────────────────────────────────────────────┘
```

| Parameter | When Read | Effect of Mid-Connection Change |
|-----------|-----------|--------------------------------|
| `K_CUBIC_LOSS_REDUCTION_FACTOR` | Every loss event | Next loss uses new factor |
| `K_CUBIC_C` | Every cwnd growth calculation | Immediate effect on growth |
| `K_MINIMUM_WINDOW` | Every cwnd adjustment | Immediate effect on floor |
| `K_CUBIC_MAX_IDLE_TIME` | Every packet send | Immediate effect on idle detection |
| `K_PACKET_THRESHOLD` | Every loss detection check | Immediate effect on loss detection |
| `K_TIME_THRESHOLD` | Every loss detection check | Immediate effect on loss timing |

### Category 3: Handshake-Negotiated Parameters

These parameters are exchanged during the QUIC handshake and locked for the connection. Changing them mid-connection has **no effect** - the negotiated values are already stored.

```
┌─────────────────────────────────────────────────────────────────┐
│  HANDSHAKE-NEGOTIATED PARAMETERS                                │
│                                                                 │
│  TIME 0: Handshake                                              │
│          Client: "My max_ack_delay is 25ms"                     │
│          Server: "My max_ack_delay is 10ms"                     │
│          Values LOCKED for this connection                      │
│                                                                 │
│  TIME 2s: ML changes the parameter variable                     │
│           NOTHING HAPPENS - handshake already complete          │
│           Connection uses the negotiated values                 │
│                                                                 │
│  CANNOT change mid-connection (QUIC protocol requirement)       │
└─────────────────────────────────────────────────────────────────┘
```

| Parameter | When Negotiated | Why No Mid-Connection Effect |
|-----------|-----------------|------------------------------|
| `max_ack_delay` | Handshake | Transport parameter locked |
| `max_data` | Handshake | Requires MAX_DATA frame to update |
| `max_stream_data` | Handshake | Requires MAX_STREAM_DATA frame to update |

---

## Detailed Parameter Analysis

### K_INITIAL_WINDOW

**Category:** Start-Only

**When used:** Once at connection start to set initial `cwnd`

**Code path:**
```python
# In CubicCongestionControl.reset()
self.congestion_window = K_INITIAL_WINDOW * self._max_datagram_size
```

**Mid-connection change:**
```
TIME 0:   Connection starts
          cwnd = K_INITIAL_WINDOW × 1200 = 12000 bytes

TIME 1s:  ML sets K_INITIAL_WINDOW = 100
          NO EFFECT - cwnd is already being managed by CC
          cwnd might be 50000 bytes now (grown via slow start)

TIME 2s:  NEW connection starts
          cwnd = 100 × 1200 = 120000 bytes (uses new value)
```

**Verdict:** Change only affects new connections

---

### K_CUBIC_LOSS_REDUCTION_FACTOR

**Category:** Continuously-Used

**When used:** Every time loss is detected

**Code path:**
```python
# In CubicCongestionControl.on_packets_lost()
new_ssthresh = max(
    int(flight_size * K_CUBIC_LOSS_REDUCTION_FACTOR),
    K_MINIMUM_WINDOW * self._max_datagram_size,
)
```

**Mid-connection change:**
```
TIME 0:   Connection starts, factor = 0.5
          cwnd = 12000 bytes

TIME 1s:  cwnd has grown to 100000 bytes
          Loss detected!
          new_cwnd = 100000 × 0.5 = 50000 bytes

TIME 2s:  ML sets K_CUBIC_LOSS_REDUCTION_FACTOR = 0.8
          cwnd has grown to 80000 bytes

TIME 3s:  Loss detected!
          new_cwnd = 80000 × 0.8 = 64000 bytes (uses NEW factor!)
```

**Verdict:** Change takes effect on next loss event

---

### K_CUBIC_C

**Category:** Continuously-Used

**When used:** Every cwnd growth calculation in congestion avoidance

**Code path:**
```python
# In CubicCongestionControl.W_cubic()
target_segments = K_CUBIC_C * (t - self.K) ** 3 + (W_max_segments)
```

**Mid-connection change:**
```
TIME 0:   Connection in congestion avoidance, C = 0.4
          cwnd growing following cubic curve

TIME 1s:  ML sets K_CUBIC_C = 0.2 (less aggressive)
          IMMEDIATELY affects growth rate
          cwnd grows more slowly

TIME 2s:  ML sets K_CUBIC_C = 0.6 (more aggressive)
          IMMEDIATELY affects growth rate
          cwnd grows faster
```

**Verdict:** Change takes effect immediately on next calculation

---

### K_MINIMUM_WINDOW

**Category:** Continuously-Used

**When used:** Every cwnd adjustment to enforce floor

**Code path:**
```python
# In CubicCongestionControl.on_packets_lost()
self.congestion_window = max(
    self.ssthresh, K_MINIMUM_WINDOW * self._max_datagram_size
)
```

**Mid-connection change:**
```
TIME 0:   K_MINIMUM_WINDOW = 2 (floor = 2400 bytes)

TIME 1s:  Severe loss, cwnd wants to go to 1000 bytes
          cwnd = max(1000, 2400) = 2400 bytes (floor enforced)

TIME 2s:  ML sets K_MINIMUM_WINDOW = 10 (floor = 12000 bytes)

TIME 3s:  Loss detected, cwnd wants to go to 5000 bytes
          cwnd = max(5000, 12000) = 12000 bytes (new floor enforced)
```

**Verdict:** Change takes effect on next cwnd adjustment

---

### K_CUBIC_MAX_IDLE_TIME

**Category:** Continuously-Used

**When used:** Every packet send to check for idle reset

**Code path:**
```python
# In CubicCongestionControl.on_packet_sent()
elapsed_idle = packet.sent_time - self.last_ack
if elapsed_idle >= K_CUBIC_MAX_IDLE_TIME:
    self.reset()
```

**Mid-connection change:**
```
TIME 0:   K_CUBIC_MAX_IDLE_TIME = 2 seconds

TIME 1s:  No activity for 1.5 seconds
          Packet sent - no reset (1.5 < 2)

TIME 2s:  ML sets K_CUBIC_MAX_IDLE_TIME = 1 second

TIME 3s:  No activity for 1.5 seconds
          Packet sent - RESET triggered (1.5 >= 1)
          cwnd returns to initial window
```

**Verdict:** Change takes effect on next packet send

---

### K_PACKET_THRESHOLD

**Category:** Continuously-Used

**When used:** Every loss detection check

**Code path:**
```python
# In QuicPacketRecovery._detect_loss()
packet_threshold = space.largest_acked_packet - K_PACKET_THRESHOLD
```

**Mid-connection change:**
```
TIME 0:   K_PACKET_THRESHOLD = 3
          Packet considered lost if 3 later packets are ACKed

TIME 1s:  ML sets K_PACKET_THRESHOLD = 5
          Now need 5 later packets ACKed to declare loss
          More conservative loss detection
```

**Verdict:** Change takes effect on next loss detection check

---

### K_TIME_THRESHOLD

**Category:** Continuously-Used

**When used:** Every loss detection check

**Code path:**
```python
# In QuicPacketRecovery._detect_loss()
loss_delay = K_TIME_THRESHOLD * max(self._rtt_latest, self._rtt_smoothed)
```

**Mid-connection change:**
```
TIME 0:   K_TIME_THRESHOLD = 9/8 = 1.125
          Loss delay = 1.125 × RTT

TIME 1s:  ML sets K_TIME_THRESHOLD = 1.5
          Loss delay = 1.5 × RTT
          More time before declaring packet lost
```

**Verdict:** Change takes effect on next loss detection check

---

### max_ack_delay

**Category:** Handshake-Negotiated

**When used:** Negotiated during handshake, used throughout connection

**Code path:**
```python
# In QuicPacketRecovery.on_ack_received()
ack_delay = min(ack_delay, self.max_ack_delay)
```

**Mid-connection change:**
```
TIME 0:   Handshake completes
          max_ack_delay = 25ms negotiated and stored

TIME 1s:  ML changes max_ack_delay variable to 10ms
          NO EFFECT - connection is using the negotiated 25ms
          The variable change doesn't reach the connection object
```

**Verdict:** Cannot change mid-connection (QUIC protocol)

---

### initial_rtt

**Category:** Start-Only (quickly replaced)

**When used:** Until first RTT measurement arrives

**Code path:**
```python
# In QuicPacketRecovery
self._rtt_initial = initial_rtt  # Used until first measurement

# After first ACK:
if not self._rtt_initialized:
    self._rtt_initialized = True
    self._rtt_smoothed = latest_rtt  # Real measurement takes over
```

**Mid-connection change:**
```
TIME 0:     Connection starts, initial_rtt = 100ms
            Used for first PTO calculation

TIME 50ms:  First ACK received
            Real RTT measured = 30ms
            initial_rtt NO LONGER USED

TIME 1s:    ML sets initial_rtt = 200ms
            NO EFFECT - real RTT measurements are being used
```

**Verdict:** No effect after first RTT measurement

---

## Summary Table

| Parameter | Category | Mid-Connection Change Works? | When Effect Occurs |
|-----------|----------|------------------------------|-------------------|
| `K_INITIAL_WINDOW` | Start-Only | No | Only new connections |
| `K_CUBIC_LOSS_REDUCTION_FACTOR` | Continuous | **Yes** | Next loss event |
| `K_CUBIC_C` | Continuous | **Yes** | Next cwnd calculation |
| `K_MINIMUM_WINDOW` | Continuous | **Yes** | Next cwnd adjustment |
| `K_CUBIC_MAX_IDLE_TIME` | Continuous | **Yes** | Next packet send |
| `K_PACKET_THRESHOLD` | Continuous | **Yes** | Next loss detection |
| `K_TIME_THRESHOLD` | Continuous | **Yes** | Next loss detection |
| `max_ack_delay` | Handshake | No | Locked at handshake |
| `initial_rtt` | Start-Only | No | Replaced by measurements |
| `max_data` | Handshake | Special | Requires MAX_DATA frame |
| `max_stream_data` | Handshake | Special | Requires MAX_STREAM_DATA frame |

---

## Implications for ML

### Parameters ML Can Tune Dynamically

These can be changed mid-connection for real-time adaptation:

```python
# All of these will affect the current connection:
aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = new_value  # On next loss
aioquic_cubic.K_CUBIC_C = new_value                       # Immediately
aioquic_cubic.K_MINIMUM_WINDOW = new_value                # Immediately
aioquic_cubic.K_CUBIC_MAX_IDLE_TIME = new_value           # Immediately
recovery.K_PACKET_THRESHOLD = new_value                   # Immediately
recovery.K_TIME_THRESHOLD = new_value                     # Immediately
```

### Parameters ML Should Set at Connection Start

These only matter at the beginning:

```python
# Set these BEFORE connection starts:
aioquic_cubic.K_INITIAL_WINDOW = value      # Sets starting cwnd
config.max_ack_delay = value                 # Negotiated in handshake
config.initial_rtt = value                   # Used until first measurement
```

### Your Current Parameters

| Your Parameter | Maps To | Dynamic? |
|----------------|---------|----------|
| `initial_cw` | `K_INITIAL_WINDOW` | No - start only |
| `max_ack_delay` | `max_ack_delay` | No - handshake only |
| `loss_reduction_factor` | `K_CUBIC_LOSS_REDUCTION_FACTOR` | **Yes - dynamic** |

**Conclusion:** Of your three parameters, only `loss_reduction_factor` can be meaningfully changed mid-connection. The other two should be set before the connection starts.
