# Server-Side Buffer Documentation

This document explains the server-side buffer implementation in detail, including its location in the code, how it works, and its purpose in the QUIC simulation framework.

---

## Table of Contents

1. [Buffer Location in Code](#buffer-location-in-code)
2. [How the Buffer Works](#how-the-buffer-works)
3. [Step-by-Step Buffer Growth](#step-by-step-buffer-growth)
4. [Buffer Characteristics](#buffer-characteristics)
5. [Purpose of the Buffer](#purpose-of-the-buffer)
6. [Memory Considerations](#memory-considerations)
7. [Application Buffer vs aioquic Internal Buffer](#application-buffer-vs-aioquic-internal-buffer)

---

## Buffer Location in Code

The buffer is located in `simulation/server.py` within the `ServerProtocol` class.

### Buffer Declaration (Line 27)

```python
class ServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.streams: Dict[int, bytes] = {}  # <-- THIS IS THE BUFFER
        self.total_bytes_received = 0
```

**What it is:** A Python dictionary that maps stream IDs (integers) to accumulated bytes (byte strings).

### Buffer Population (Lines 48-54)

```python
elif isinstance(event, StreamDataReceived):
    # Accumulate stream data
    stream_id = event.stream_id
    if stream_id not in self.streams:
        self.streams[stream_id] = b""          # Initialize empty buffer for new stream
    self.streams[stream_id] += event.data      # APPEND data to buffer
    self.total_bytes_received += len(event.data)
```

---

## How the Buffer Works

### Visual Representation

```
                         SERVER MEMORY
                    ┌─────────────────────────────────────────┐
                    │  ServerProtocol instance                │
                    │                                         │
                    │  self.streams = {                       │
                    │      0: b"<video data...>",   ← Stream 0 buffer (Video)
                    │      4: b"<file data...>",    ← Stream 4 buffer (File)
                    │      8: b"<audio data...>",   ← Stream 8 buffer (Conference)
                    │  }                                      │
                    │                                         │
                    │  self.total_bytes_received = 1,650,000  │
                    └─────────────────────────────────────────┘
```

### Data Flow

```
┌──────────────┐     UDP      ┌──────────────┐    Event     ┌──────────────┐
│              │   Packets    │              │   Callback   │              │
│    CLIENT    │ ──────────►  │   aioquic    │ ──────────►  │ self.streams │
│              │              │   (decrypt,  │              │   [stream]   │
│              │              │   reorder)   │              │   += data    │
└──────────────┘              └──────────────┘              └──────────────┘
```

---

## Step-by-Step Buffer Growth

Example for Stream 0 (Video Streaming):

```
TIME        EVENT                           self.streams[0]              SIZE
─────────────────────────────────────────────────────────────────────────────
T0          Connection established          (doesn't exist yet)          -

T1          First packet arrives            b""                          0
            (stream 0, 50KB I-frame)        += event.data
                                            b"<50KB of data>"            50,000

T2          Second packet arrives           b"<50KB>" += b"<5KB>"
            (stream 0, 5KB P-frame)         b"<55KB of data>"            55,000

T3          Third packet arrives            b"<55KB>" += b"<5KB>"
            (stream 0, 5KB P-frame)         b"<60KB of data>"            60,000

...         ... (continues for ~300 frames)

T300        Final packet                    b"<1.6MB of data>"           1,600,000
```

### Code Trace

```python
# Event 1: First I-frame arrives on stream 0
event = StreamDataReceived(stream_id=0, data=bytes(50000))

# Line 51: Check if stream exists in buffer
if stream_id not in self.streams:  # True - stream 0 is new
    self.streams[stream_id] = b""  # Initialize: self.streams = {0: b""}

# Line 53: Append data
self.streams[stream_id] += event.data  # self.streams = {0: b"<50KB>"}

# Line 54: Update counter
self.total_bytes_received += len(event.data)  # total_bytes_received = 50000
```

```python
# Event 2: First P-frame arrives on stream 0
event = StreamDataReceived(stream_id=0, data=bytes(5000))

# Line 51: Check if stream exists
if stream_id not in self.streams:  # False - stream 0 already exists

# Line 53: Append data
self.streams[stream_id] += event.data  # self.streams = {0: b"<55KB>"}

# Line 54: Update counter
self.total_bytes_received += len(event.data)  # total_bytes_received = 55000
```

---

## Buffer Characteristics

| Property | Value | Explanation |
|----------|-------|-------------|
| **Type** | `Dict[int, bytes]` | Dictionary mapping stream IDs to byte strings |
| **Scope** | Per-connection | Each `ServerProtocol` instance has its own buffer |
| **Isolation** | Per-stream | Data from stream 0 never mixes with stream 4 |
| **Growth** | Unbounded | No size limit - grows until connection ends |
| **Persistence** | Connection lifetime | Cleared when connection terminates |
| **Thread Safety** | Single-threaded | asyncio is single-threaded, no locks needed |

### Per-Stream Isolation

Each stream has its own independent buffer:

```python
self.streams = {
    0: b"<video data - 1.6MB>",      # Stream 0 - Video
    4: b"<file data - 10MB>",        # Stream 4 - File Transfer
    8: b"<audio data - 160KB>",      # Stream 8 - Conference
}
```

Data never crosses between streams - they are completely isolated.

---

## Purpose of the Buffer

### What the Buffer Is Used For

1. **Data Accumulation**: QUIC delivers data in chunks (via `StreamDataReceived` events), not as complete messages. The buffer reassembles the complete stream.

2. **Byte Counting**: `total_bytes_received` tracks total throughput for metrics.

3. **Stream Separation**: Keeps each stream's data isolated from others.

### What Happens to the Buffered Data

**Currently: Nothing!** The data is accumulated but never processed:

```python
# The buffer grows...
self.streams[stream_id] += event.data

# ...but is never read or processed afterward
# No code accesses self.streams[stream_id] for actual use
```

This is intentional for this simulation because:

- The goal is to **measure transfer performance**, not process data
- The synthesizers generate zero-filled bytes (`bytes(size)`) with no meaningful content
- Only the timing and throughput matter, not the data itself

### If You Wanted to Process the Data

You could add processing logic like this:

```python
elif isinstance(event, StreamDataReceived):
    stream_id = event.stream_id
    if stream_id not in self.streams:
        self.streams[stream_id] = b""
    self.streams[stream_id] += event.data
    self.total_bytes_received += len(event.data)

    # Example: Process complete messages (if using a delimiter)
    while b"\n" in self.streams[stream_id]:
        message, self.streams[stream_id] = self.streams[stream_id].split(b"\n", 1)
        self.process_message(stream_id, message)
```

---

## Memory Considerations

### Buffer Size Per Simulation

| Application | Duration | Data Rate | Buffer Size |
|-------------|----------|-----------|-------------|
| Video Streaming | 10 sec | ~160 KB/s | ~1.6 MB |
| File Transfer | 10 sec | 1 MB/s | ~10 MB |
| Conference Call | 10 sec | ~16 KB/s | ~160 KB |

### Memory Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         MEMORY LIFECYCLE                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. Connection Start                                                     │
│     └── ServerProtocol created                                          │
│     └── self.streams = {} (empty, ~64 bytes for dict overhead)          │
│                                                                          │
│  2. Data Transfer                                                        │
│     └── self.streams[0] grows: 0 → 50KB → 55KB → ... → 1.6MB            │
│     └── Memory usage increases linearly                                  │
│                                                                          │
│  3. Connection End                                                       │
│     └── ServerProtocol.quic_event_received(ConnectionTerminated)        │
│     └── ServerProtocol instance becomes unreferenced                     │
│     └── Python garbage collector frees self.streams                      │
│     └── Memory returned to OS                                            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Python `bytes` Concatenation Note

The buffer uses `+=` for concatenation:

```python
self.streams[stream_id] += event.data
```

**Performance consideration:** Python `bytes` are immutable, so each `+=` creates a new bytes object and copies all existing data. For a 10-second video stream with 300 frames:

```
Frame 1:   Copy 50KB                    → 50KB copied
Frame 2:   Copy 55KB                    → 55KB copied
Frame 3:   Copy 60KB                    → 60KB copied
...
Frame 300: Copy 1.6MB                   → 1.6MB copied
Total:     ~240MB of copying operations
```

For this simulation, this is acceptable because:
- Simulations are short (10 seconds)
- Data rates are modest (not gigabits/second)
- Simplicity is preferred over optimization

**For high-performance scenarios**, you would use `bytearray` or `io.BytesIO`:

```python
# More efficient alternative (not used in this codebase)
self.streams: Dict[int, bytearray] = {}

# In event handler:
if stream_id not in self.streams:
    self.streams[stream_id] = bytearray()
self.streams[stream_id].extend(event.data)  # No copying!
```

---

## Application Buffer vs aioquic Internal Buffer

There are **two distinct buffer layers**:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        TWO DIFFERENT BUFFERS                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  LAYER 1: aioquic RECEIVE BUFFER (internal, invisible to you)           │
│  ─────────────────────────────────────────────────────────────          │
│  Location: Inside aioquic library                                        │
│  Purpose:                                                                │
│     ├── Receives raw UDP packets from network                           │
│     ├── Decrypts QUIC packet payload (TLS 1.3)                          │
│     ├── Parses QUIC frames from packets                                 │
│     ├── Reorders out-of-order stream data                               │
│     ├── Handles retransmission requests                                 │
│     └── Delivers complete, ordered STREAM frames via events             │
│                                                                          │
│  You never see or interact with this buffer directly.                    │
│                                                                          │
│                              │                                           │
│                              ▼                                           │
│                   StreamDataReceived(stream_id, data)                    │
│                              │                                           │
│                              ▼                                           │
│                                                                          │
│  LAYER 2: APPLICATION BUFFER (self.streams in server.py)                │
│  ─────────────────────────────────────────────────────────────          │
│  Location: simulation/server.py line 27                                  │
│  Purpose:                                                                │
│     ├── Accumulates already-processed data from aioquic                 │
│     ├── Organizes data by stream ID                                     │
│     ├── Enables byte counting for metrics                               │
│     └── Would enable message parsing (if needed)                        │
│                                                                          │
│  This is what you see and control in the code.                          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### What Each Buffer Handles

| Responsibility | aioquic Buffer | Application Buffer |
|----------------|----------------|-------------------|
| UDP packet reception | Yes | No |
| Decryption | Yes | No |
| Packet reordering | Yes | No |
| Loss detection | Yes | No |
| Retransmission | Yes | No |
| Stream data accumulation | Partial | Yes |
| Byte counting | No | Yes |
| Application logic | No | Yes |

### Data Transformation

```
Raw UDP Packet (encrypted, possibly out of order)
        │
        ▼
┌─────────────────────────────────────┐
│         aioquic internal            │
│  • Decrypt                          │
│  • Verify integrity                 │
│  • Reorder if needed                │
│  • Extract STREAM frame             │
└─────────────────────────────────────┘
        │
        ▼
StreamDataReceived(stream_id=0, data=b"<clean, ordered data>")
        │
        ▼
┌─────────────────────────────────────┐
│    self.streams[0] += event.data    │
│    (application buffer)             │
└─────────────────────────────────────┘
```

By the time data reaches `self.streams`, it has already been:
- Decrypted
- Verified (integrity check)
- Reordered (if packets arrived out of order)
- Extracted from QUIC framing

The application buffer receives **clean, reliable, ordered byte streams** - exactly what QUIC promises to deliver.

---

## Summary

| Aspect | Details |
|--------|---------|
| **Location** | `simulation/server.py`, line 27 |
| **Type** | `Dict[int, bytes]` |
| **Population** | Lines 48-54, on `StreamDataReceived` events |
| **Purpose** | Accumulate stream data, count bytes |
| **Usage** | Data is stored but not processed (metrics only) |
| **Lifetime** | Exists for duration of connection |
| **Memory** | 160KB - 10MB depending on application type |
