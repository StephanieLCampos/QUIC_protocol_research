# Updated Issues - Metrics Analysis

Analysis of how RTT, latency, throughput, and jitter are measured in the simulation.

---

## Issue 1: Throughput Measures Application Send Rate, Not Network Throughput

### How It's Currently Calculated
```python
throughput = bytes_sent / duration_seconds
```

### The Problem
- `bytes_sent` is incremented when the app pushes data to QUIC buffers
- This measures **application send rate**, not actual network throughput
- Explains why file transfer shows 230 Mbps on a 5 Mbps link

### Fix Applied
- Metric already named "offered_throughput" in output files
- Per-connection actual throughput to be implemented separately (see per_conn_network_throughput.md)

---

## Issue 2: Jitter Uses Send Timestamps Instead of Receive Timestamps

### How It's Currently Calculated
```python
packet_timestamps = self.receive_timestamps or self.send_timestamps
delays = [t[i] - t[i-1] for i in range(1, len(packet_timestamps))]
jitter = statistics.stdev(delays)
```

### The Problem
- `record_packet_received()` is **never called** in the codebase
- `receive_timestamps` is always empty
- Falls back to `send_timestamps`
- Measures variance in when app sends packets, NOT network delay variation

### Fix Applied
- Changed jitter calculation to use **RFC 3550 EWMA algorithm** with RTT variation
- Measures **RTT jitter** (not one-way) since QUIC uses RTT for congestion control
- Formula: `J = J + (|D(i)| - J) / 16` where `D(i) = RTT(i) - RTT(i-1)`
- The 1/16 smoothing factor provides noise reduction while maintaining convergence

### New Calculation
```python
# In calculator.py - calculate_jitter_rfc3550() method
jitter = 0.0
for i in range(1, len(rtt_samples)):
    d = abs(rtt_samples[i] - rtt_samples[i - 1])
    jitter = jitter + (d - jitter) / 16.0
return jitter  # RTT jitter (not divided by 2)
```

### Files Changed
- `metrics/calculator.py:106-132` - Added `calculate_jitter_rfc3550()` method
- `metrics/calculator.py:210` - Updated `calculate_all()` to use RFC 3550 jitter

---

## Issue 3: Packet Loss Always Shows 0%

### How It's Currently Calculated
```python
actual_packets_lost = getattr(loss_handler, "_packets_lost", 0)
actual_packets_sent = getattr(loss_handler, "_packets_sent", 0)
packet_loss_rate = (packets_sent - packets_received) / packets_sent
```

### The Problem
- aioquic's `QuicPacketRecovery` class does NOT have `_packets_lost` or `_packets_sent` attributes
- `getattr(..., 0)` always returns 0
- Result: packet_loss_rate = 0 / packets_sent = 0 (always)

### Verified from aioquic source
From [aioquic recovery.py](https://github.com/aiortc/aioquic/blob/main/src/aioquic/quic/recovery.py):
- Has: `_rtt_smoothed`, `_rtt_min`, `_pto_count`
- Does NOT have: `_packets_lost`, `_packets_sent`

### Fix Applied
- Track packet loss using `_pto_count` (Probe Timeout count) as a proxy
- PTO events indicate the connection detected potential packet loss
- Also calculate loss from congestion window reductions

### New Calculation
```python
# In collector.py - calculate_metrics() method
pto_count = getattr(loss_handler, "_pto_count", 0)
# Each PTO event typically indicates 1+ lost packets
estimated_packets_lost = pto_count
actual_packets_received = max(0, actual_packets_sent - estimated_packets_lost)
```

### Files Changed
- `metrics/collector.py:137-172` - Updated `calculate_metrics()` to use PTO count

---

## Issue 4: Initial Congestion Window Not RFC 9002 Compliant

### How It Was Configured
```python
initial_cw: int = 12000  # ~10 packets
```

### The Problem
- RFC 9002 Section 7.2 specifies: `max(10 × max_datagram_size, max(14720, 2 × max_datagram_size))`
- With 1200-byte datagrams: `max(12000, max(14720, 2400))` = `max(12000, 14720)` = **14720**
- The old value of 12000 was not RFC compliant

### Fix Applied
- Changed initial congestion window from 12000 to 14720 bytes
- Now RFC 9002 Section 7.2 compliant

### Files Changed
- `config/connection_config.py:102,158` - Updated default and docstring
- `config/multi_connection_config.py:81,132` - Updated default and docstring

---

## Summary of Fixes

| Metric/Parameter | Before | After |
|------------------|--------|-------|
| Throughput | Only offered load | Offered + ACK-verified (`throughput_acked`) |
| Jitter | Used send timestamps | RTT jitter with RFC 3550 EWMA smoothing |
| Packet Loss | Always 0% | Uses PTO count as loss indicator |
| Initial CW | 12000 bytes | 14720 bytes (RFC 9002 Section 7.2) |
| Per-connection actual | Not available | `acked_throughput_median_mbps` per connection |

---

## Issue 5: No ACK-Verified Throughput Per Connection

### The Problem
- Only "offered throughput" (bytes sent to QUIC buffers) was measured
- No way to see how much data actually made it through the network
- File transfer showed 230 Mbps on a 5 Mbps link (misleading)

### Fix Applied
- Added ACK-verified throughput tracking using aioquic's `bytes_in_flight`
- Formula: `bytes_acked = bytes_sent - bytes_in_flight`
- `throughput_acked = bytes_acked / duration`

### New Metrics Added
| Metric | Description |
|--------|-------------|
| `throughput_acked` | Bytes/sec confirmed delivered via ACKs |
| `bytes_acked` | Total bytes acknowledged |
| `avg_cwnd` | Average congestion window |
| `avg_bytes_in_flight` | Average bytes in flight |

### Files Changed
- `metrics/collector.py` - Added `bytes_acked`, `cwnd_samples`, `bytes_in_flight_samples` fields and `sample_network_metrics()` method
- `metrics/calculator.py` - Added ACK-verified fields to `MetricsResult`, updated `calculate_all()`
- `simulation/worker_process.py` - Added `_sample_network_metrics()` method
- `simulation/result.py` - Added `acked_throughput_median_mbps` to outputs

---

## Files Modified

1. `metrics/calculator.py` - Added `calculate_jitter_rfc3550()` method, ACK-verified throughput fields
2. `metrics/collector.py` - Added network metrics sampling, PTO count for packet loss
3. `simulation/worker_process.py` - Added `_sample_network_metrics()` method
4. `simulation/result.py` - Added per-connection ACK-verified throughput to exports
5. `config/connection_config.py` - Updated initial_cw default to 14720 (RFC 9002)
6. `config/multi_connection_config.py` - Updated shared_initial_cw default to 14720 (RFC 9002)

---

## Validation

After fixes, verify:
1. Jitter reflects RTT variation (should be ~1-5ms with network delay)
2. Packet loss shows non-zero when network has configured loss
3. Throughput metrics clearly distinguish offered vs actual
