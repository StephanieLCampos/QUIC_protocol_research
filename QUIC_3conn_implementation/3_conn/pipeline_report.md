# QUIC Multi-Connection Pipeline: Detailed Technical Report

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [File Structure and Responsibilities](#3-file-structure-and-responsibilities)
4. [Packet Generation Pipeline](#4-packet-generation-pipeline)
5. [Packet Transmission Path](#5-packet-transmission-path)
6. [Buffer Architecture](#6-buffer-architecture)
7. [Metrics Collection Pipeline](#7-metrics-collection-pipeline)
8. [Multi-Connection Orchestration](#8-multi-connection-orchestration)
9. [Parameter Management](#9-parameter-management)
10. [Complete Data Flow Diagram](#10-complete-data-flow-diagram)

---

## 1. Executive Summary

This report documents the complete pipeline of the QUIC Multi-Stream Research Project. The codebase implements:

- **3 concurrent QUIC connections** for different application types (video streaming, file transfer, conference call)
- **Synthesized traffic patterns** that mimic real application behavior
- **Metrics collection** for throughput, RTT, jitter, packet loss, and latency
- **Runtime-adjustable parameters** for ML optimization research

**Key Technologies:**
- Python 3.12 with asyncio
- aioquic library for QUIC protocol implementation
- CUBIC congestion control algorithm

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MAIN ENTRY POINT                               │
│                                 main.py                                      │
│                                                                              │
│   Commands: run, multi, status, analyze, report, clear, multi-config        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                     ┌────────────────┴────────────────┐
                     ▼                                 ▼
        ┌─────────────────────┐           ┌─────────────────────┐
        │   Grid Search Mode   │           │  Multi-Connection   │
        │   (Single Stream)    │           │   Mode (3 Streams)  │
        │                      │           │                      │
        │   simulation/        │           │   simulation/        │
        │   runner.py          │           │   multi_connection_  │
        │                      │           │   runner.py          │
        └─────────────────────┘           └─────────────────────┘
                     │                                 │
                     └────────────────┬────────────────┘
                                      ▼
                     ┌─────────────────────────────────┐
                     │        QUIC Client/Server        │
                     │                                  │
                     │   simulation/client.py           │
                     │   simulation/server.py           │
                     └─────────────────────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
     ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
     │   Synthesizers   │    │     Metrics      │    │     Config       │
     │                  │    │                  │    │                  │
     │ video_streaming  │    │  collector.py    │    │  settings.py     │
     │ file_transfer    │    │  calculator.py   │    │  parameters.py   │
     │ conference_call  │    │  aggregated.py   │    │  connection_.py  │
     └─────────────────┘    └─────────────────┘    └─────────────────┘
```

---

## 3. File Structure and Responsibilities

### 3.1 Entry Point

| File | Purpose | Key Functions |
|------|---------|---------------|
| `main.py` | CLI entry point | `cmd_run()`, `cmd_multi()`, `cmd_analyze()` |

### 3.2 Simulation Directory

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `runner.py` | Single simulation orchestration | `SimulationRunner`, `SimulationResult` |
| `client.py` | QUIC client implementation | `QuicClient`, `ClientProtocol` |
| `server.py` | QUIC server implementation | `QuicServer`, `ServerProtocol` |
| `multi_connection_runner.py` | 3-connection orchestration | `MultiConnectionRunner` |
| `connection_handler.py` | Per-connection management | `ConnectionHandler` |
| `parameter_controller.py` | ML integration interface | `ParameterController` |
| `multi_connection_result.py` | Result data structures | `MultiConnectionResult`, `ConnectionResult` |

### 3.3 Synthesizers Directory

| File | Purpose | Traffic Pattern |
|------|---------|-----------------|
| `base.py` | Abstract base class | `DataPacket`, `BaseSynthesizer`, `SynthesizerFactory` |
| `video_streaming.py` | H.264-like frames | I-frames (50KB) + P-frames (5KB) at 30 FPS |
| `file_transfer.py` | Bulk transfer | 64KB chunks, no timing delay |
| `conference_call.py` | VoIP audio | 320 bytes every 20ms (128kbps) |

### 3.4 Metrics Directory

| File | Purpose | Key Functions |
|------|---------|---------------|
| `collector.py` | Real-time data collection | `MetricsCollector` |
| `calculator.py` | Metric calculations | `MetricsCalculator`, `MetricsResult` |
| `aggregated_metrics.py` | Multi-connection aggregation | `AggregatedMetrics` |
| `exporter.py` | CSV export | `MetricsExporter` |

### 3.5 Config Directory

| File | Purpose | Key Classes |
|------|---------|-------------|
| `settings.py` | Global settings | `Settings`, `DEFAULT_SETTINGS` |
| `parameters.py` | Grid search parameters | `GridSearchParams`, `ParameterPresets` |
| `connection_config.py` | Per-connection config | `ConnectionConfig`, `DYNAMIC_PARAMETERS` |
| `multi_connection_config.py` | 3-connection config | `MultiConnectionConfig` |

---

## 4. Packet Generation Pipeline

### 4.1 Synthesizer Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SYNTHESIZER FACTORY                               │
│                           synthesizers/base.py                              │
│                                                                              │
│   SynthesizerFactory.create(application_type, duration_seconds)             │
│                                                                              │
│   Returns: VideoStreamingSynthesizer | FileTransferSynthesizer |            │
│            ConferenceCallSynthesizer                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        ▼                             ▼                             ▼
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│ Video Streaming │         │  File Transfer  │         │ Conference Call │
│                 │         │                 │         │                 │
│ Pattern:        │         │ Pattern:        │         │ Pattern:        │
│ - 30 FPS        │         │ - 64KB chunks   │         │ - 20ms interval │
│ - I-frame: 50KB │         │ - No delay      │         │ - 320 bytes     │
│ - P-frame: 5KB  │         │ - Total: 10MB   │         │ - 128kbps       │
│ - I every 60    │         │                 │         │                 │
│   frames        │         │                 │         │                 │
└─────────────────┘         └─────────────────┘         └─────────────────┘
```

### 4.2 DataPacket Structure

**Location:** `synthesizers/base.py:18-32`

```python
@dataclass
class DataPacket:
    data: bytes        # Actual bytes to send (zero-filled)
    size: int          # Size in bytes
    timestamp: float   # When packet was generated
    packet_type: str   # "I-frame", "P-frame", "chunk", "audio"
    sequence: int      # Sequence number
    metadata: Dict     # Additional info (frame_number, etc.)
```

### 4.3 Video Streaming Generation

**Location:** `synthesizers/video_streaming.py:58-105`

```
Frame Generation Timeline (10 seconds at 30 FPS = 300 frames):

Time 0.000s:  I-frame (50KB)  ← Keyframe
Time 0.033s:  P-frame (5KB)
Time 0.067s:  P-frame (5KB)
...
Time 1.967s:  P-frame (5KB)
Time 2.000s:  I-frame (50KB)  ← Keyframe (every 60 frames)
Time 2.033s:  P-frame (5KB)
...

Total: ~5 I-frames + ~295 P-frames = ~1.7MB for 10 seconds
```

**Key Code:**
```python
# synthesizers/video_streaming.py:73-95
while frame_number < total_frames:
    if frame_number % self.i_frame_interval == 0:
        frame_type = "I-frame"
        frame_size = self.i_frame_size  # 50000 bytes
    else:
        frame_type = "P-frame"
        frame_size = self.p_frame_size  # 5000 bytes

    packet = self._create_packet(size=frame_size, ...)
    yield packet

    # Maintain FPS timing
    await asyncio.sleep(sleep_time)
```

### 4.4 File Transfer Generation

**Location:** `synthesizers/file_transfer.py:50-91`

```
Chunk Generation (10MB file, 64KB chunks):

Chunk 0:  65536 bytes  offset=0
Chunk 1:  65536 bytes  offset=65536
Chunk 2:  65536 bytes  offset=131072
...
Chunk 152: 65536 bytes
Chunk 153: 40960 bytes  ← Last chunk (remaining)

Total: 154 chunks, NO timing delay (as fast as possible)
```

**Key Code:**
```python
# synthesizers/file_transfer.py:62-86
while bytes_sent < self.total_size:
    remaining = self.total_size - bytes_sent
    current_chunk_size = min(self.chunk_size, remaining)  # 64KB or less

    packet = self._create_packet(size=current_chunk_size, ...)
    yield packet

    bytes_sent += current_chunk_size
    # NO asyncio.sleep() - send as fast as congestion window allows
```

### 4.5 Conference Call Generation

**Location:** `synthesizers/conference_call.py:57-96`

```
Audio Packet Generation (10 seconds at 50 packets/second):

Time 0.000s:  Audio packet (320 bytes)
Time 0.020s:  Audio packet (320 bytes)
Time 0.040s:  Audio packet (320 bytes)
...
Time 9.980s:  Audio packet (320 bytes)

Total: 500 packets, 160KB for 10 seconds (128kbps)
```

**Key Code:**
```python
# synthesizers/conference_call.py:72-96
while packet_number < total_packets:
    packet = self._create_packet(
        size=self.packet_size,  # 320 bytes
        packet_type="audio",
        ...
    )
    yield packet

    # Precise 20ms timing for low jitter
    await asyncio.sleep(sleep_time)
```

---

## 5. Packet Transmission Path

### 5.1 Complete Transmission Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PACKET TRANSMISSION PIPELINE                        │
└─────────────────────────────────────────────────────────────────────────────┘

 STEP 1: Synthesizer generates DataPacket
         ┌──────────────────────────────────────────────────────────────────┐
         │  synthesizer.generate() yields DataPacket(data=bytes, size=N)    │
         │  Location: synthesizers/*.py                                      │
         └──────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
 STEP 2: Client iterates and sends each packet
         ┌──────────────────────────────────────────────────────────────────┐
         │  client.send_synthesized_data(stream_id, data_generator, ...)    │
         │  Location: simulation/client.py:180-220                           │
         │                                                                   │
         │  async for packet in data_generator:                              │
         │      self._protocol.send_data(stream_id, packet.data)            │
         │      metrics_collector.record_packet_sent(packet.size)           │
         └──────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
 STEP 3: ClientProtocol sends to QUIC connection
         ┌──────────────────────────────────────────────────────────────────┐
         │  protocol.send_data(stream_id, data, end_stream=False)           │
         │  Location: simulation/client.py:60-69                             │
         │                                                                   │
         │  Internally calls: self._quic.send_stream_data(stream_id, data)  │
         └──────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
 STEP 4: aioquic QUIC Connection processes data
         ┌──────────────────────────────────────────────────────────────────┐
         │  aioquic.quic.connection.QuicConnection.send_stream_data()       │
         │  Location: aioquic library (external)                            │
         │                                                                   │
         │  - Fragments data into QUIC frames                               │
         │  - Adds to stream buffer                                          │
         │  - Applies congestion control (CUBIC)                            │
         │  - Encrypts with TLS 1.3                                         │
         └──────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
 STEP 5: aioquic creates UDP datagrams
         ┌──────────────────────────────────────────────────────────────────┐
         │  QuicConnection packages QUIC packets into UDP datagrams         │
         │  Max datagram size: 1200 bytes (typical)                         │
         │                                                                   │
         │  - Adds QUIC header                                              │
         │  - Includes stream frames                                         │
         │  - Adds ACK frames if needed                                     │
         └──────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
 STEP 6: asyncio UDP transport sends to OS
         ┌──────────────────────────────────────────────────────────────────┐
         │  QuicConnectionProtocol.transmit()                               │
         │  → transport.sendto(datagram, addr)                              │
         │                                                                   │
         │  Data enters OS kernel UDP send buffer                           │
         └──────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
 STEP 7: Network stack delivers to server
         ┌──────────────────────────────────────────────────────────────────┐
         │  localhost: Loopback interface (instant)                         │
         │  Network: Through tc/netem if configured                         │
         │                                                                   │
         │  Server's UDP socket receives datagram                           │
         └──────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
 STEP 8: Server processes received data
         ┌──────────────────────────────────────────────────────────────────┐
         │  ServerProtocol.quic_event_received(StreamDataReceived)          │
         │  Location: simulation/server.py:41-64                            │
         │                                                                   │
         │  - Accumulates data in self.streams[stream_id]                   │
         │  - Updates total_bytes_received                                  │
         │  - Sends ACK back (handled by aioquic)                           │
         │  - Optionally echoes data for bidirectional streams              │
         └──────────────────────────────────────────────────────────────────┘
```

### 5.2 Key Code Locations for Transmission

**Client sending loop:**
```python
# simulation/client.py:203-218
async for packet in data_generator:
    # Send the packet
    self._protocol.send_data(stream_id, packet.data)
    total_bytes += packet.size

    # Record metrics
    if metrics_collector:
        metrics_collector.record_packet_sent(packet.size)

        # Sample RTT periodically
        rtt = self._protocol.get_rtt()
        if rtt is not None and rtt > 0:
            metrics_collector.record_rtt_sample(rtt)

    # Allow event loop to process
    await asyncio.sleep(0)
```

**Server receiving:**
```python
# simulation/server.py:48-64
elif isinstance(event, StreamDataReceived):
    stream_id = event.stream_id
    if stream_id not in self.streams:
        self.streams[stream_id] = b""
    self.streams[stream_id] += event.data
    self.total_bytes_received += len(event.data)

    # Notify callback
    if self._data_received_callback:
        self._data_received_callback(stream_id, len(event.data))
```

---

## 6. Buffer Architecture

### 6.1 Buffer Hierarchy Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          BUFFER ARCHITECTURE                                │
│                    (From Application to Network)                            │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 1: Application Buffer (Synthesizer)                                   │
│                                                                              │
│ Location: synthesizers/*.py (async generator state)                         │
│ Type: Python generator buffer (internal)                                    │
│ Size: 1 packet at a time (no explicit buffer)                              │
│                                                                              │
│ Description: The synthesizer yields one packet at a time. No buffering     │
│ at application level - packets are created on-demand.                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 2: QUIC Stream Buffer                                                 │
│                                                                              │
│ Location: aioquic/quic/stream.py (QuicStream)                              │
│ Type: Per-stream send/receive buffer                                        │
│ Size: Controlled by max_stream_data (default: 1MB)                         │
│       Configurable via ConnectionConfig.max_stream_data                     │
│                                                                              │
│ Flow Control: QUIC MAX_STREAM_DATA frames                                  │
│ - Receiver advertises how much data it can accept                          │
│ - Sender blocks if stream buffer limit reached                             │
│                                                                              │
│ Code Reference (config):                                                    │
│   config/connection_config.py:93                                           │
│   max_stream_data: int = 1_048_576  # 1MB default                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 3: QUIC Connection Buffer                                             │
│                                                                              │
│ Location: aioquic/quic/connection.py                                        │
│ Type: Aggregate buffer for all streams                                      │
│ Size: Controlled by max_data (default: 1MB)                                │
│       Configurable via ConnectionConfig.max_data                            │
│                                                                              │
│ Flow Control: QUIC MAX_DATA frames                                         │
│ - Total bytes across all streams                                           │
│ - Connection-level flow control                                             │
│                                                                              │
│ Code Reference (config):                                                    │
│   config/connection_config.py:92                                           │
│   max_data: int = 1_048_576  # 1MB default                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 4: Congestion Window (cwnd)                                           │
│                                                                              │
│ Location: aioquic/quic/congestion/cubic.py                                  │
│ Type: Bytes allowed in flight (unacknowledged)                              │
│ Size: Dynamic, starts at initial_cw (default: 12000 bytes = 10 packets)   │
│                                                                              │
│ Behavior:                                                                   │
│ - Grows according to CUBIC algorithm                                        │
│ - Reduced by loss_reduction_factor on packet loss                          │
│ - Never goes below minimum_window * max_datagram_size                      │
│                                                                              │
│ Key Parameters:                                                             │
│   K_INITIAL_WINDOW = 10  (packets)                                         │
│   K_CUBIC_LOSS_REDUCTION_FACTOR = 0.7                                      │
│   K_MINIMUM_WINDOW = 2  (packets)                                          │
│                                                                              │
│ Code Reference (apply):                                                     │
│   simulation/connection_handler.py:95-124                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 5: OS Kernel UDP Send Buffer                                          │
│                                                                              │
│ Location: Operating system kernel                                           │
│ Type: Socket send buffer (SO_SNDBUF)                                        │
│ Size: OS-dependent (typically 64KB-256KB)                                   │
│                                                                              │
│ Behavior:                                                                   │
│ - Queues UDP datagrams for transmission                                    │
│ - Drops packets if full (rare with QUIC CC)                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 6: Network Queue (tc/netem - if configured)                           │
│                                                                              │
│ Location: Linux kernel traffic control                                      │
│ Type: Packet queue with delay/loss simulation                               │
│ Size: Configured via tc commands                                            │
│                                                                              │
│ Example Configuration:                                                      │
│   tc qdisc add dev lo root netem delay 50ms 10ms loss 1%                   │
│                                                                              │
│ Behavior:                                                                   │
│ - Adds artificial delay (latency simulation)                               │
│ - Introduces packet loss (congestion simulation)                           │
│ - Applies to ALL traffic on the interface                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Buffer Sizes by Application Type

| Application | max_data | max_stream_data | initial_cw | Reason |
|-------------|----------|-----------------|------------|--------|
| Video Streaming | 2MB | 1MB | 72KB | Moderate buffering for smooth playback |
| File Transfer | 10MB | 5MB | 120KB | Large buffers for bulk throughput |
| Conference Call | 500KB | 100KB | 12KB | Small buffers for real-time, low latency |

**Code Reference:** `config/connection_config.py:231-314`

---

## 7. Metrics Collection Pipeline

### 7.1 Metrics Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        METRICS COLLECTION PIPELINE                          │
└─────────────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────┐
                    │      MetricsCollector           │
                    │      metrics/collector.py       │
                    │                                 │
                    │  Collects raw data during       │
                    │  simulation execution           │
                    └─────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│ record_packet_    │   │ record_rtt_       │   │ sample_connection │
│ sent(size)        │   │ sample(rtt)       │   │ _rtt()            │
│                   │   │                   │   │                   │
│ - packets_sent++  │   │ - rtt_samples     │   │ - Reads from      │
│ - bytes_sent +=   │   │   .append(rtt)    │   │   aioquic         │
│   size            │   │                   │   │   _loss.          │
│ - send_timestamps │   │                   │   │   _rtt_smoothed   │
│   .append(now)    │   │                   │   │                   │
└───────────────────┘   └───────────────────┘   └───────────────────┘
        │                          │                          │
        └──────────────────────────┼──────────────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────────┐
                    │     MetricsCalculator           │
                    │     metrics/calculator.py       │
                    │                                 │
                    │  calculate_all() → MetricsResult│
                    └─────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│    Throughput     │   │      RTT          │   │      Jitter       │
│                   │   │                   │   │                   │
│ bytes_sent /      │   │ mean(rtt_samples) │   │ stdev(inter-      │
│ duration          │   │                   │   │ packet delays)    │
└───────────────────┘   └───────────────────┘   └───────────────────┘

┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│  Packet Loss Rate │   │     Latency       │   │ Connection Time   │
│                   │   │                   │   │                   │
│ (sent - received) │   │ RTT / 2           │   │ ready_time -      │
│ / sent            │   │ (estimated)       │   │ start_time        │
└───────────────────┘   └───────────────────┘   └───────────────────┘
```

### 7.2 Where Each Metric is Measured

#### 7.2.1 Throughput

**Formula:** `total_bytes / duration_seconds`

**Data Source:**
- `bytes_sent`: Counted in `MetricsCollector.record_packet_sent()` (metrics/collector.py:65-74)
- `duration`: `end_time - start_time` in `MetricsCollector` (metrics/collector.py:117-123)

**Calculation Location:** `metrics/calculator.py:49-66`

```python
@staticmethod
def calculate_throughput(total_bytes: int, duration_seconds: float) -> float:
    if duration_seconds <= 0:
        return 0.0
    return total_bytes / duration_seconds
```

#### 7.2.2 RTT (Round-Trip Time)

**Formula:** `mean(rtt_samples)`

**Data Source:** aioquic internal RTT tracking

**Collection Location:** `simulation/client.py:71-76`

```python
def get_rtt(self) -> Optional[float]:
    try:
        return self._quic._loss._rtt_smoothed
    except AttributeError:
        return None
```

**Recording:** `simulation/client.py:213-215`

```python
rtt = self._protocol.get_rtt()
if rtt is not None and rtt > 0:
    metrics_collector.record_rtt_sample(rtt)
```

**Calculation Location:** `metrics/calculator.py:184-187`

```python
if rtt_samples:
    rtt = statistics.mean(rtt_samples)
else:
    rtt = 0.0
```

#### 7.2.3 Jitter

**Formula:** `stdev(inter_packet_delays)`

**Data Source:** Timestamps recorded when packets are sent

**Collection Location:** `metrics/collector.py:65-74`

```python
def record_packet_sent(self, size: int):
    self.packets_sent += 1
    self.bytes_sent += size
    self.send_timestamps.append(time.time())  # ← Timestamp for jitter
```

**Calculation Location:** `metrics/calculator.py:68-103`

```python
@staticmethod
def calculate_jitter(packet_timestamps: List[float], ...) -> float:
    if len(packet_timestamps) < 2:
        return 0.0

    # Calculate inter-packet delays
    delays = []
    for i in range(1, len(packet_timestamps)):
        delay = packet_timestamps[i] - packet_timestamps[i - 1]
        delays.append(delay)

    # Jitter is the standard deviation of delays
    return statistics.stdev(delays)
```

#### 7.2.4 Packet Loss Rate

**Formula:** `(packets_sent - packets_received) / packets_sent`

**Data Source:** aioquic internal loss tracking

**Collection Location:** `metrics/collector.py:139-157`

```python
def calculate_metrics(self) -> MetricsResult:
    if self.connection is not None:
        try:
            loss_handler = getattr(self.connection, "_loss", None)
            if loss_handler is not None:
                # Get packets lost from aioquic's internal tracking
                actual_packets_lost = getattr(loss_handler, "_packets_lost", 0)
```

**Calculation Location:** `metrics/calculator.py:105-127`

```python
@staticmethod
def calculate_packet_loss_rate(packets_sent: int, packets_received: int) -> float:
    if packets_sent <= 0:
        return 0.0
    packets_lost = packets_sent - packets_received
    return packets_lost / packets_sent
```

#### 7.2.5 Latency

**Formula:** `RTT / 2` (estimated one-way latency)

**Calculation Location:** `metrics/calculator.py:129-151`

```python
@staticmethod
def calculate_latency(rtt: float) -> float:
    if rtt <= 0:
        return 0.0
    return rtt / 2
```

#### 7.2.6 Connection Establishment Time

**Formula:** `connection_ready_time - start_time`

**Data Source:** Timestamps recorded at simulation start and handshake completion

**Collection Location:** `metrics/collector.py:61-63`

```python
def record_connection_ready(self):
    self.connection_ready_time = time.time()
```

**Called From:** `simulation/runner.py:166-167`

```python
# Record connection ready
self._metrics_collector.record_connection_ready()
```

### 7.3 Metrics Result Structure

**Location:** `metrics/calculator.py:14-33`

```python
@dataclass
class MetricsResult:
    throughput: float                    # bytes per second
    rtt: float                           # round-trip time in seconds
    latency: float                       # one-way latency (RTT / 2)
    jitter: float                        # jitter in seconds
    packet_loss_rate: float              # percentage (0.0 to 1.0)
    connection_establishment_time: float  # seconds
```

---

## 8. Multi-Connection Orchestration

### 8.1 Multi-Connection Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    MULTI-CONNECTION ORCHESTRATION                           │
│                 simulation/multi_connection_runner.py                       │
└─────────────────────────────────────────────────────────────────────────────┘

 STEP 1: Setup
         ┌──────────────────────────────────────────────────────────────────┐
         │  runner.setup()                                                   │
         │                                                                   │
         │  1. Start QuicServer (shared by all connections)                 │
         │  2. Create 3 ConnectionHandler objects                            │
         │  3. Create ParameterController (for ML integration)              │
         └──────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
 STEP 2: Concurrent Connection
         ┌──────────────────────────────────────────────────────────────────┐
         │  await asyncio.gather(*[handler.connect() for handler])          │
         │                                                                   │
         │  For each handler:                                                │
         │    1. Apply global parameters (_apply_global_parameters)         │
         │    2. Create QuicClient                                           │
         │    3. Perform QUIC handshake                                      │
         │    4. Open 3 streams                                              │
         │    5. Select active stream based on application type             │
         └──────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
 STEP 3: Concurrent Data Transmission
         ┌──────────────────────────────────────────────────────────────────┐
         │  await asyncio.gather(*[handler.start_sending(duration)])        │
         │                                                                   │
         │  For each handler:                                                │
         │    1. Create synthesizer for application type                    │
         │    2. Send synthesized data via client                           │
         │    3. Collect metrics during transmission                        │
         └──────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
 STEP 4: Result Collection
         ┌──────────────────────────────────────────────────────────────────┐
         │  _collect_results()                                               │
         │                                                                   │
         │  For each handler:                                                │
         │    1. Close connection                                            │
         │    2. Calculate final metrics                                     │
         │    3. Create ConnectionResult                                     │
         │                                                                   │
         │  Aggregate:                                                       │
         │    1. Combine per-connection metrics                             │
         │    2. Calculate fairness index                                    │
         │    3. Return MultiConnectionResult                               │
         └──────────────────────────────────────────────────────────────────┘
```

### 8.2 Connection Handler Lifecycle

**Location:** `simulation/connection_handler.py`

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     CONNECTION HANDLER LIFECYCLE                            │
└─────────────────────────────────────────────────────────────────────────────┘

                     ┌─────────────────────────────────┐
                     │  ConnectionHandler.__init__()   │
                     │                                 │
                     │  - Store config                 │
                     │  - Initialize metrics collector │
                     │  - is_active = False            │
                     └─────────────────────────────────┘
                                      │
                                      ▼
                     ┌─────────────────────────────────┐
                     │     handler.connect()           │
                     │                                 │
                     │  1. _apply_global_parameters()  │
                     │     - Patch aioquic modules     │
                     │     - K_INITIAL_WINDOW = ...    │
                     │     - K_CUBIC_LOSS_REDUCTION... │
                     │                                 │
                     │  2. Create QuicClient           │
                     │  3. client.connect()            │
                     │  4. client.open_streams(3)      │
                     │  5. is_active = True            │
                     └─────────────────────────────────┘
                                      │
                                      ▼
                     ┌─────────────────────────────────┐
                     │   handler.start_sending()       │
                     │                                 │
                     │  1. Create synthesizer          │
                     │  2. client.send_synthesized_    │
                     │     data(stream_id, generator,  │
                     │          metrics_collector)     │
                     │  3. Packets sent via QUIC       │
                     └─────────────────────────────────┘
                                      │
                     ┌────────────────┴────────────────┐
                     │                                 │
                     ▼                                 ▼
        ┌─────────────────────────┐     ┌─────────────────────────┐
        │  update_dynamic_        │     │  get_current_metrics()  │
        │  parameter()            │     │                         │
        │                         │     │  Returns MetricsResult  │
        │  - ML can change        │     │  for monitoring         │
        │    parameters           │     │                         │
        │  - Records history      │     │                         │
        └─────────────────────────┘     └─────────────────────────┘
                     │                                 │
                     └────────────────┬────────────────┘
                                      ▼
                     ┌─────────────────────────────────┐
                     │      handler.close()            │
                     │                                 │
                     │  1. Stop metrics collection     │
                     │  2. Close client connection     │
                     │  3. Calculate final metrics     │
                     │  4. Return ConnectionResult     │
                     │  5. is_active = False           │
                     └─────────────────────────────────┘
```

---

## 9. Parameter Management

### 9.1 Parameter Categories

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PARAMETER CATEGORIES                                 │
│                      config/connection_config.py                            │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ START-ONLY PARAMETERS (Must be set BEFORE connection starts)               │
│                                                                              │
│ Parameter            │ Default  │ Description                               │
│ ─────────────────────┼──────────┼─────────────────────────────────────────│
│ initial_cw           │ 12000    │ Initial congestion window (bytes)        │
│ max_ack_delay        │ 0.025    │ Maximum ACK delay (seconds)              │
│                                                                              │
│ Applied at: Connection establishment (cannot change after)                  │
│ Code: connection_handler.py:107-108                                         │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ DYNAMIC PARAMETERS (Can change MID-CONNECTION)                              │
│                                                                              │
│ Parameter               │ Default │ aioquic Constant                        │
│ ────────────────────────┼─────────┼───────────────────────────────────────│
│ loss_reduction_factor   │ 0.7     │ K_CUBIC_LOSS_REDUCTION_FACTOR          │
│ cubic_c                 │ 0.4     │ K_CUBIC_C                               │
│ minimum_window          │ 2       │ K_MINIMUM_WINDOW                        │
│ packet_threshold        │ 3       │ K_PACKET_THRESHOLD                      │
│ time_threshold          │ 1.125   │ K_TIME_THRESHOLD                        │
│ cubic_max_idle_time     │ 2.0     │ K_CUBIC_MAX_IDLE_TIME                  │
│                                                                              │
│ Applied at: Runtime (takes effect on next CC event)                         │
│ Code: connection_handler.py:235-298                                         │
│                                                                              │
│ WARNING: These are MODULE-LEVEL GLOBALS in aioquic.                        │
│ Changing them affects ALL connections in the process.                       │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ PER-CONNECTION PARAMETERS (Set via QuicConfiguration)                       │
│                                                                              │
│ Parameter            │ Default    │ Description                             │
│ ─────────────────────┼────────────┼───────────────────────────────────────│
│ max_data             │ 1,048,576  │ Max bytes for entire connection        │
│ max_stream_data      │ 1,048,576  │ Max bytes per stream                   │
│ idle_timeout         │ 60.0       │ Connection idle timeout (seconds)      │
│ initial_rtt          │ 0.1        │ Initial RTT estimate (seconds)         │
│ max_datagram_size    │ 1200       │ Max datagram size (bytes)              │
│                                                                              │
│ Applied at: Connection establishment (per-connection, no conflict)          │
│ Code: connection_handler.py:126-143                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 9.2 Parameter Application Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PARAMETER APPLICATION FLOW                             │
└─────────────────────────────────────────────────────────────────────────────┘

         ConnectionHandler.connect()
                    │
                    ▼
         ┌─────────────────────────────────────────────────────────────────┐
         │  _apply_global_parameters()                                     │
         │  Location: connection_handler.py:95-124                         │
         │                                                                 │
         │  # Convert initial_cw from bytes to packets                    │
         │  initial_window_packets = self.config.initial_cw // 1200       │
         │                                                                 │
         │  # Patch aioquic modules                                        │
         │  aioquic_cubic.K_INITIAL_WINDOW = initial_window_packets       │
         │  aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = ...             │
         │  aioquic_cubic.K_CUBIC_C = ...                                 │
         │  aioquic_cubic.K_MINIMUM_WINDOW = ...                          │
         │  aioquic_cubic.K_CUBIC_MAX_IDLE_TIME = ...                     │
         │  aioquic_recovery.K_PACKET_THRESHOLD = ...                     │
         │  aioquic_recovery.K_TIME_THRESHOLD = ...                       │
         └─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
         ┌─────────────────────────────────────────────────────────────────┐
         │  _create_quic_configuration()                                   │
         │  Location: connection_handler.py:126-143                        │
         │                                                                 │
         │  configuration = QuicConfiguration(is_client=True, ...)        │
         │  configuration.max_ack_delay = self.config.max_ack_delay       │
         │  # These are truly per-connection                              │
         └─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
         ┌─────────────────────────────────────────────────────────────────┐
         │  QuicClient.connect() establishes connection                    │
         │                                                                 │
         │  - New QUIC connection uses current module globals             │
         │  - Congestion controller initialized with K_INITIAL_WINDOW     │
         └─────────────────────────────────────────────────────────────────┘
```

### 9.3 ML Integration via ParameterController

**Location:** `simulation/parameter_controller.py`

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       ML INTEGRATION INTERFACE                              │
│                    simulation/parameter_controller.py                       │
└─────────────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────┐
                    │     ParameterController         │
                    │                                 │
                    │  Primary interface for ML       │
                    │  to interact with connections   │
                    └─────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│   Read Methods    │   │   Write Methods   │   │  Helper Methods   │
│                   │   │                   │   │                   │
│ get_parameter()   │   │ set_parameter()   │   │ compute_fairness_ │
│ get_all_params()  │   │ set_multiple_     │   │ index()           │
│ get_current_      │   │ parameters()      │   │ get_total_        │
│ metrics()         │   │ set_all_conns_    │   │ throughput()      │
│ get_all_metrics() │   │ parameter()       │   │ suggest_params_   │
│ get_metrics_      │   │                   │   │ for_congestion()  │
│ snapshot()        │   │                   │   │                   │
└───────────────────┘   └───────────────────┘   └───────────────────┘

Example ML Callback Usage:
─────────────────────────
def my_ml_callback(controller, metrics):
    for conn_id, m in metrics.items():
        if m['packet_loss_rate'] > 0.05:
            # High loss - be more conservative
            current = controller.get_parameter(conn_id, 'loss_reduction_factor')
            controller.set_parameter(conn_id, 'loss_reduction_factor',
                                     max(0.3, current - 0.1))

result = await run_multi_connection_with_ml_callback(my_ml_callback)
```

---

## 10. Complete Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        COMPLETE DATA FLOW DIAGRAM                           │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────┐
│     main.py         │
│   cmd_multi()       │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐     ┌─────────────────────────────────────────────────┐
│ MultiConnectionConfig│     │ Configuration from:                            │
│                     │◄────│ - create_default() presets                      │
│ - video_config      │     │ - create_baseline() defaults                    │
│ - file_config       │     │ - JSON file                                     │
│ - conference_config │     └─────────────────────────────────────────────────┘
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ MultiConnectionRunner│
│     .setup()        │
└─────────┬───────────┘
          │
          ├───────────────────────────────────────────┐
          │                                           │
          ▼                                           ▼
┌─────────────────────┐                   ┌─────────────────────┐
│    QuicServer       │                   │  ConnectionHandler  │ x3
│    (shared)         │                   │                     │
│                     │                   │  Each has:          │
│ - Listens on :4433  │                   │  - QuicClient       │
│ - Receives data     │                   │  - MetricsCollector │
│ - Sends ACKs        │                   │  - Synthesizer      │
└─────────────────────┘                   └─────────┬───────────┘
          ▲                                         │
          │                                         │
          │                     ┌───────────────────┼───────────────────┐
          │                     │                   │                   │
          │                     ▼                   ▼                   ▼
          │         ┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐
          │         │ VideoStreaming    │ │ FileTransfer      │ │ ConferenceCall    │
          │         │ Synthesizer       │ │ Synthesizer       │ │ Synthesizer       │
          │         │                   │ │                   │ │                   │
          │         │ 30 FPS            │ │ 64KB chunks       │ │ 20ms packets      │
          │         │ I: 50KB           │ │ No delay          │ │ 320 bytes         │
          │         │ P: 5KB            │ │                   │ │                   │
          │         └─────────┬─────────┘ └─────────┬─────────┘ └─────────┬─────────┘
          │                   │                     │                     │
          │                   └─────────────────────┼─────────────────────┘
          │                                         │
          │                                         ▼
          │                             ┌─────────────────────┐
          │                             │ QuicClient.send_    │
          │                             │ synthesized_data()  │
          │                             │                     │
          │                             │ async for packet:   │
          │                             │   send_data()       │
          │                             │   record_metrics()  │
          │                             └─────────┬───────────┘
          │                                       │
          │                                       ▼
          │                             ┌─────────────────────┐
          │                             │  aioquic QUIC       │
          │                             │                     │
          │                             │ - Stream buffering  │
          │                             │ - CUBIC CC          │
          │                             │ - TLS encryption    │
          │                             │ - UDP packaging     │
          │                             └─────────┬───────────┘
          │                                       │
          │                                       ▼
          │                             ┌─────────────────────┐
          │                             │  Network Stack      │
          │                             │                     │
          │◄────────────────────────────│  UDP datagrams      │
          │         (localhost)         │  to server          │
          │                             └─────────────────────┘
          │
          ▼
┌─────────────────────┐
│ ServerProtocol      │
│ .quic_event_received│
│                     │
│ - StreamDataReceived│
│ - Accumulate data   │
│ - Track bytes       │
└─────────────────────┘
          │
          │ (After simulation ends)
          ▼
┌─────────────────────┐
│ MetricsCollector    │
│ .calculate_metrics()│
│                     │
│ Returns:            │
│ - throughput        │
│ - rtt               │
│ - latency           │
│ - jitter            │
│ - packet_loss_rate  │
│ - connection_time   │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ AggregatedMetrics   │
│                     │
│ Combines metrics    │
│ from all 3          │
│ connections:        │
│                     │
│ - total_throughput  │
│ - fairness_index    │
│ - average_rtt       │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ MultiConnectionResult│
│                     │
│ - Per-connection    │
│   results           │
│ - Aggregated        │
│   metrics           │
│ - Success status    │
└─────────────────────┘
```

---

## Summary

This codebase implements a sophisticated QUIC research platform with:

1. **Synthesizers** that generate realistic traffic patterns without actual media content
2. **Asynchronous client/server** architecture using aioquic
3. **Comprehensive metrics collection** at multiple points in the pipeline
4. **Buffer management** at 6 different layers from application to network
5. **Runtime parameter adjustment** capability for ML integration
6. **Multi-connection orchestration** for concurrent testing

The key insight is that **packets flow from synthesizers through QUIC's congestion control and buffering systems**, with metrics being collected both from application-level counters and aioquic's internal state.
