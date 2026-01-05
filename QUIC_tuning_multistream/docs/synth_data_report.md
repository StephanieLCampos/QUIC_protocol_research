# Synthesized vs. Real Application Data for QUIC Research

## Executive Summary

**Question**: Can I use synthesized (fake) data instead of real video frames, audio packets, and file contents for my QUIC parameter research?

**Answer**: **Yes, absolutely.** For QUIC parameter tuning research, synthesized data is not only acceptable but often **preferable** to real data. The QUIC protocol and its parameters operate on bytes and timing patterns—the actual content of those bytes is irrelevant to protocol behavior.

---

## Why Synthesized Data Works

### What QUIC Sees

After your application calls `send_stream_data()`, QUIC processes the data through several layers:

```
┌─────────────────────────────────────────────────────────────┐
│ Application Data (Real or Synthetic)                        │
│ "Real H.264 frame" or "bytes(50000)" ← QUIC doesn't care   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ TLS Encryption                                              │
│ Both become indistinguishable encrypted bytes               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ QUIC Packetization                                          │
│ Split into ~1200 byte packets regardless of content         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Network Transmission                                        │
│ UDP datagrams - content is encrypted and meaningless        │
└─────────────────────────────────────────────────────────────┘
```

### What Matters vs. What Doesn't

| Aspect | Matters for QUIC? | Why |
|--------|:-----------------:|-----|
| **Byte count** | ✅ Yes | Determines packets generated, congestion window usage |
| **Timing pattern** | ✅ Yes | Affects burstiness, ACK timing, jitter |
| **Send frequency** | ✅ Yes | Impacts steady-state vs. bursty behavior |
| **Actual content** | ❌ No | QUIC sees bytes, not meaning |
| **Data validity** | ❌ No | Invalid H.264 vs. valid H.264 = same bytes to QUIC |
| **Compression ratio** | ❌ No | QUIC doesn't compress; TLS makes all data look random |

---

## Proof: Why Content Doesn't Matter

### 1. TLS Encryption Erases Content Differences

All QUIC data is encrypted before transmission:

```python
# These produce identical behavior at the QUIC layer:

# Real video frame
real_frame = load_h264_frame("video.mp4", frame_number=100)
protocol._quic.send_stream_data(stream_id, real_frame)

# Synthetic frame (same size)
fake_frame = bytes(len(real_frame))  # All zeros
protocol._quic.send_stream_data(stream_id, fake_frame)

# Random bytes (same size)
random_frame = os.urandom(len(real_frame))
protocol._quic.send_stream_data(stream_id, random_frame)
```

After TLS encryption, a network observer (or QUIC itself) cannot distinguish between them.

### 2. QUIC Parameters Operate on Metadata, Not Content

The three parameters you're researching affect:

| Parameter | What It Controls | Content Dependency |
|-----------|------------------|:------------------:|
| **Initial Congestion Window** | Bytes in flight at startup | None |
| **Max ACK Delay** | Time before sending ACKs | None |
| **Loss Reduction Factor** | Window reduction on loss | None |

None of these parameters examine or depend on data content.

### 3. Network Behavior Depends on Patterns, Not Payload

The network sees:
- Packet sizes (~1200 bytes each)
- Packet timing (when sent)
- Packet count (how many)

It does not see:
- Whether bytes are video, audio, or file data
- Whether the data is "real" or "synthetic"

---

## What You MUST Simulate Correctly

While content doesn't matter, **patterns do**. Your synthetic data must match real-world characteristics:

### 1. Message Sizes

| Transmission Type | Real Sizes | Synthetic Requirement |
|-------------------|------------|----------------------|
| Video I-frame | 30-80 KB (variable) | Simulate range or use fixed 50KB |
| Video P-frame | 2-10 KB (variable) | Simulate range or use fixed 5KB |
| File chunk | Fixed 64 KB | Use fixed 64KB |
| Audio packet | Fixed 320 bytes | Use fixed 320 bytes |

```python
# Good: Realistic size simulation
class VideoFrameGenerator:
    def generate_i_frame(self) -> bytes:
        # Simulate variable I-frame sizes (30-80KB)
        size = random.randint(30000, 80000)
        return bytes(size)

    def generate_p_frame(self) -> bytes:
        # Simulate variable P-frame sizes (2-10KB)
        size = random.randint(2000, 10000)
        return bytes(size)
```

### 2. Timing Patterns

| Type | Real Timing | Synthetic Requirement |
|------|-------------|----------------------|
| Video | 33.33ms intervals (30fps) | Must maintain timing |
| Audio | 20ms intervals | Must maintain timing |
| File | Continuous (no delay) | Send as fast as possible |

```python
# Good: Correct timing simulation
async def simulate_video_stream(protocol, stream_id, duration):
    frame_interval = 1.0 / 30  # 30 fps = 33.33ms

    for frame_num in range(int(duration * 30)):
        if frame_num % 60 == 0:  # I-frame every 2 seconds
            data = bytes(50000)
        else:
            data = bytes(5000)

        protocol._quic.send_stream_data(stream_id, data)
        await asyncio.sleep(frame_interval)  # Critical: maintain timing
```

### 3. Burstiness

Real video sends I-frames as bursts, then smaller P-frames:

```
Time 0ms:    [50KB I-frame] → 42 QUIC packets burst
Time 33ms:   [5KB P-frame]  → 4 packets
Time 66ms:   [5KB P-frame]  → 4 packets
...
Time 2000ms: [50KB I-frame] → 42 packets burst (next I-frame)
```

Your synthetic data must replicate this burst pattern.

### 4. Bidirectionality (Conference Calls)

Conference calls require simultaneous send and receive:

```python
# Good: Bidirectional simulation
async def simulate_conference(protocol, send_stream, recv_callback):
    async def sender():
        while active:
            data = bytes(320)  # Synthetic audio packet
            protocol._quic.send_stream_data(send_stream, data)
            await asyncio.sleep(0.020)

    async def receiver():
        while active:
            # Process incoming data
            await recv_callback()

    # Both must run concurrently
    await asyncio.gather(sender(), receiver())
```

---

## Advantages of Synthesized Data

### 1. Perfect Reproducibility

```python
# Synthetic: Identical every run
def generate_test_data(seed=42):
    random.seed(seed)
    return [bytes(random.randint(30000, 80000)) for _ in range(100)]

# Real: Varies based on content
def load_real_video(path):
    # Frame sizes depend on video content complexity
    # Different videos = different size patterns
    pass
```

### 2. No External Dependencies

| Approach | Dependencies |
|----------|--------------|
| Real video | Video files, codecs, ffmpeg |
| Real audio | Audio files, audio libraries |
| Synthetic | None (just Python stdlib) |

### 3. Precise Experimental Control

```python
# Synthetic: Test exact edge cases
test_cases = [
    {"i_frame_size": 50000, "p_frame_size": 5000},   # Normal
    {"i_frame_size": 100000, "p_frame_size": 10000}, # High bitrate
    {"i_frame_size": 20000, "p_frame_size": 2000},   # Low bitrate
]

# Real: Limited by available video files
```

### 4. Isolation of QUIC Behavior

Real applications add processing time:

```
Real Video Pipeline:
  Decode frame (5ms) → Process (2ms) → Encode (5ms) → QUIC send → Network

Synthetic Pipeline:
  Generate bytes (0.01ms) → QUIC send → Network
```

With synthetic data, you measure **pure QUIC behavior**, not application overhead.

### 5. Faster Execution

| Operation | Real Data | Synthetic Data |
|-----------|-----------|----------------|
| Video frame generation | 5-20ms (encoding) | <0.1ms |
| Audio packet generation | 1-5ms (processing) | <0.01ms |
| File chunk reading | 1-10ms (disk I/O) | <0.1ms |

---

## Potential Concerns and Mitigations

### Concern 1: "Will results transfer to real applications?"

**Answer**: Yes, if patterns are realistic.

QUIC parameter effects depend on:
- How many bytes are sent
- When bytes are sent
- How bursty the traffic is

If your synthetic data matches these patterns, results will transfer.

**Mitigation**: Validate synthetic patterns against real traffic profiles.

```python
# Validate your synthetic generator produces realistic distributions
def validate_video_generator(generator, num_samples=1000):
    sizes = [len(generator.generate_frame()) for _ in range(num_samples)]

    print(f"Mean size: {statistics.mean(sizes)}")      # Should be ~15KB avg
    print(f"Std dev: {statistics.stdev(sizes)}")       # Should show variation
    print(f"Max size: {max(sizes)}")                   # I-frames ~50KB
    print(f"Min size: {min(sizes)}")                   # P-frames ~5KB
```

### Concern 2: "Real video has complex size distributions"

**Answer**: You can simulate this.

```python
import numpy as np

class RealisticVideoGenerator:
    """Generate frames with realistic H.264-like size distribution."""

    def __init__(self):
        # Based on studies of real H.264 streams
        self.i_frame_mean = 50000
        self.i_frame_std = 15000
        self.p_frame_mean = 5000
        self.p_frame_std = 2000

    def generate_i_frame(self) -> bytes:
        size = int(np.random.normal(self.i_frame_mean, self.i_frame_std))
        size = max(20000, min(100000, size))  # Clamp to realistic range
        return bytes(size)

    def generate_p_frame(self) -> bytes:
        size = int(np.random.normal(self.p_frame_mean, self.p_frame_std))
        size = max(1000, min(15000, size))
        return bytes(size)
```

### Concern 3: "What about content-aware network behavior?"

**Answer**: Doesn't exist at the QUIC/network layer.

- QUIC doesn't inspect content (it's encrypted)
- Routers don't inspect content (they route based on headers)
- The network treats all encrypted bytes identically

The only exception would be deep packet inspection (DPI) that specifically targets QUIC, which is beyond the scope of parameter tuning research.

### Concern 4: "Is synthetic data 'cheating' in research?"

**Answer**: No, it's standard practice.

Published network research commonly uses:
- `iperf` for bandwidth testing (sends synthetic data)
- Packet generators for protocol testing
- Traffic generators for congestion research

What matters is:
1. Your methodology is documented
2. Traffic patterns are realistic
3. Results are interpreted correctly

---

## Recommended Synthetic Data Implementation

### Complete Generator for Your Project

```python
"""
synthetic_traffic.py - Traffic generators for QUIC parameter research
"""
import asyncio
import random
import time
from dataclasses import dataclass
from typing import AsyncIterator, Dict, Any

@dataclass
class TrafficConfig:
    """Configuration for traffic generation."""
    duration_seconds: float = 30.0
    random_seed: int = 42

class VideoStreamGenerator:
    """
    Generates synthetic video traffic matching H.264 patterns.

    Characteristics:
    - 30 fps (33.33ms intervals)
    - I-frames every 60 frames (2 seconds)
    - I-frames: 30-80KB (mean 50KB)
    - P-frames: 2-10KB (mean 5KB)
    """

    def __init__(self, config: TrafficConfig):
        self.config = config
        self.fps = 30
        self.i_frame_interval = 60
        random.seed(config.random_seed)

    async def generate(self) -> AsyncIterator[Dict[str, Any]]:
        frame_interval = 1.0 / self.fps
        frame_count = 0
        start_time = time.time()

        while time.time() - start_time < self.config.duration_seconds:
            if frame_count % self.i_frame_interval == 0:
                # I-frame: variable size 30-80KB
                size = random.randint(30000, 80000)
                frame_type = "I"
            else:
                # P-frame: variable size 2-10KB
                size = random.randint(2000, 10000)
                frame_type = "P"

            yield {
                "data": bytes(size),
                "size": size,
                "frame_type": frame_type,
                "frame_number": frame_count,
                "timestamp": time.time(),
            }

            frame_count += 1
            await asyncio.sleep(frame_interval)


class FileTransferGenerator:
    """
    Generates synthetic file transfer traffic.

    Characteristics:
    - Fixed 64KB chunks
    - No timing delay (send as fast as possible)
    - Configurable total size
    """

    def __init__(self, config: TrafficConfig, total_size: int = 10_000_000):
        self.config = config
        self.total_size = total_size
        self.chunk_size = 65536

    async def generate(self) -> AsyncIterator[Dict[str, Any]]:
        bytes_sent = 0
        chunk_number = 0

        while bytes_sent < self.total_size:
            remaining = self.total_size - bytes_sent
            size = min(self.chunk_size, remaining)

            yield {
                "data": bytes(size),
                "size": size,
                "chunk_number": chunk_number,
                "offset": bytes_sent,
                "timestamp": time.time(),
            }

            bytes_sent += size
            chunk_number += 1
            await asyncio.sleep(0)  # Yield control but no delay


class ConferenceCallGenerator:
    """
    Generates synthetic conference call traffic.

    Characteristics:
    - 20ms packet intervals (50 packets/second)
    - Fixed 320-byte packets (128kbps audio)
    - Bidirectional (generator for one direction)
    """

    def __init__(self, config: TrafficConfig):
        self.config = config
        self.packet_interval = 0.020  # 20ms
        self.packet_size = 320  # bytes

    async def generate(self) -> AsyncIterator[Dict[str, Any]]:
        packet_count = 0
        start_time = time.time()

        while time.time() - start_time < self.config.duration_seconds:
            yield {
                "data": bytes(self.packet_size),
                "size": self.packet_size,
                "sequence": packet_count,
                "timestamp": time.time(),
            }

            packet_count += 1
            await asyncio.sleep(self.packet_interval)


# Usage example
async def run_test(protocol, stream_id, traffic_type: str):
    config = TrafficConfig(duration_seconds=30.0, random_seed=42)

    if traffic_type == "video":
        generator = VideoStreamGenerator(config)
    elif traffic_type == "file":
        generator = FileTransferGenerator(config)
    elif traffic_type == "conference":
        generator = ConferenceCallGenerator(config)

    async for packet in generator.generate():
        protocol._quic.send_stream_data(stream_id, packet["data"])
```

---

## Comparison: Synthetic vs. Real Data Approach

| Aspect | Synthetic Data | Real Data |
|--------|---------------|-----------|
| **Setup complexity** | Low | High (files, codecs, etc.) |
| **Reproducibility** | Perfect | Variable |
| **Execution speed** | Fast | Slower |
| **Control over patterns** | Complete | Limited |
| **Dependencies** | None | Many |
| **Validity for QUIC research** | ✅ High | ✅ High |
| **Validity for app research** | Medium | High |
| **Recommended for this project** | ✅ **Yes** | Optional |

---

## Conclusion

### Key Findings

1. **Synthesized data is fully valid** for QUIC parameter research
2. **Content is irrelevant** — QUIC operates on bytes and timing, not meaning
3. **Patterns must be realistic** — sizes, timing, and burstiness matter
4. **Synthetic data offers advantages** — reproducibility, control, speed, simplicity

### Recommendation for Your Project

**Use synthesized data** for your QUIC parameter tuning research:

1. Implement generators matching real traffic patterns (provided above)
2. Document your synthetic traffic characteristics
3. Validate that patterns match real-world profiles
4. Focus on measuring QUIC behavior, not application behavior

### What to Document in Your Research

When publishing results, include:

```
Data Generation: Synthetic traffic generators simulating:
- Video: 30fps H.264-like patterns, I-frames (30-80KB) every 2s,
         P-frames (2-10KB) between
- File: 64KB sequential chunks, no pacing
- Conference: 320-byte packets at 20ms intervals, bidirectional

Rationale: QUIC parameter effects depend on traffic patterns
(size, timing, burstiness), not payload content. Synthetic data
provides reproducible, controlled experiments isolating QUIC
behavior from application processing overhead.
```

This approach is scientifically sound and commonly used in network protocol research.
