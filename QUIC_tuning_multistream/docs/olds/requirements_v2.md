# QUIC Multi-Stream Research Project - Technical Requirements & Implementation Plan

## Project Overview
This research project aims to investigate how QUIC protocol parameters affect performance metrics for different data transmission types using the aioquic library in Python.

## Technical Requirements

### Core Functionality
1. **QUIC Connection Management**
   - Establish QUIC client-server connection using aioquic library
   - Support multiple concurrent streams (minimum 3)
   - Configure QUIC parameters via source code modification and configuration API

2. **Configurable QUIC Parameters** (Selected for Research)

   | Parameter | Location | Default | Impact |
   |-----------|----------|---------|--------|
   | **Initial Congestion Window** | `recovery.py` | 12,000 bytes | Startup speed |
   | **Max ACK Delay** | `configuration.py` | 25ms | Latency & jitter |
   | **Loss Reduction Factor** | `recovery.py` | 0.5 | Throughput recovery |

3. **Data Transmission Types**
   - **Video Streaming**: Continuous data flow with emphasis on low latency
   - **File Transfer**: Bulk data transfer prioritizing throughput
   - **Conference Calls**: Bidirectional real-time communication requiring minimal jitter

4. **Performance Metrics**
   - **Throughput**: Data transfer rate (bytes/second)
   - **Round-Trip Time (RTT)**: Latency measurement (accessible via `QuicConnection._loss._rtt`)
   - **Jitter**: Variation in packet delay
   - **Packet Loss Rate**: Percentage of lost packets
   - **Connection Establishment Time**: Initial handshake duration

### System Architecture

```
┌─────────────┐         ┌─────────────┐
│   Client    │         │   Server    │
├─────────────┤         ├─────────────┤
│ Stream 1    │◄───────►│ Stream 1    │ (Video)
│ Stream 2    │◄───────►│ Stream 2    │ (File)
│ Stream 3    │◄───────►│ Stream 3    │ (Conference)
└─────────────┘         └─────────────┘
```

### Dependencies
- Python 3.8+
- aioquic (forked for parameter modification)
- cryptography (required by aioquic for TLS)
- TLS certificates (self-signed acceptable for research)

---

## Selected Parameters - Technical Details

### Parameter 1: Initial Congestion Window

**Purpose**: Controls how many bytes can be sent immediately after connection establishment, before receiving any ACKs.

| Attribute | Value |
|-----------|-------|
| Location | `src/aioquic/quic/recovery.py` |
| Constant | `K_INITIAL_WINDOW` |
| Default | `10 * MAX_DATAGRAM_SIZE` (12,000 bytes) |
| Test Range | 2,400 – 120,000 bytes (2–100 packets) |
| Modification | Change constant value |

**Impact on Transmission Types**:
- **File Transfer**: Larger IW reduces slow-start phase, achieving full throughput faster
- **Video Streaming**: Faster first-frame delivery, reduced initial buffering
- **Conference Calls**: Quicker bidirectional flow establishment

**Implementation**:
```python
# In recovery.py
K_INITIAL_WINDOW = 10 * MAX_DATAGRAM_SIZE  # Default
K_INITIAL_WINDOW = 50 * MAX_DATAGRAM_SIZE  # 60KB - larger initial window
```

---

### Parameter 2: Max ACK Delay

**Purpose**: Maximum time the receiver waits before sending an acknowledgment. Lower values mean more frequent ACKs.

| Attribute | Value |
|-----------|-------|
| Location | `src/aioquic/quic/configuration.py` |
| Variable | `max_ack_delay` |
| Default | 0.025 seconds (25ms) |
| Test Range | 0.001 – 0.100 seconds (1–100ms) |
| Modification | QuicConfiguration API (no source edit needed) |

**Impact on Transmission Types**:
- **File Transfer**: Lower delay = faster congestion window growth
- **Video Streaming**: Directly reduces end-to-end latency
- **Conference Calls**: Critical for meeting <20ms jitter target

**Implementation**:
```python
from aioquic.quic.configuration import QuicConfiguration

config = QuicConfiguration(
    is_client=True,
    max_ack_delay=0.005,  # 5ms instead of default 25ms
)
```

---

### Parameter 3: Loss Reduction Factor

**Purpose**: Determines how aggressively the congestion window is reduced when packet loss is detected.

| Attribute | Value |
|-----------|-------|
| Location | `src/aioquic/quic/recovery.py` |
| Constant | `K_LOSS_REDUCTION_FACTOR` |
| Default | 0.5 (halve congestion window on loss) |
| Test Range | 0.3 – 0.8 |
| Modification | Change constant value |

**Impact on Transmission Types**:
- **File Transfer**: Higher factor = faster recovery = higher sustained throughput
- **Video Streaming**: Affects bitrate stability after congestion
- **Conference Calls**: Smoother congestion response reduces jitter

**Implementation**:
```python
# In recovery.py
K_LOSS_REDUCTION_FACTOR = 0.5  # Default - halve on loss
K_LOSS_REDUCTION_FACTOR = 0.7  # Conservative - retain 70% on loss
```

**Behavior Table**:
| Factor | Congestion Window After Loss (from 100KB) |
|--------|-------------------------------------------|
| 0.3 | 30KB (aggressive) |
| 0.5 | 50KB (default) |
| 0.7 | 70KB (conservative) |

---

## Parameter Presets

Pre-configured parameter combinations optimized for each transmission type:

```python
# parameter_presets.py
PRESETS = {
    "baseline": {
        "initial_cw_packets": 10,      # K_INITIAL_WINDOW multiplier
        "max_ack_delay": 0.025,        # seconds
        "loss_reduction_factor": 0.5,
    },
    "file_transfer": {
        "initial_cw_packets": 100,     # Fast ramp-up
        "max_ack_delay": 0.025,        # Standard ACK delay acceptable
        "loss_reduction_factor": 0.7,  # Quick recovery from loss
    },
    "video_streaming": {
        "initial_cw_packets": 50,      # Moderate startup
        "max_ack_delay": 0.005,        # Low latency critical
        "loss_reduction_factor": 0.5,  # Standard recovery
    },
    "conference": {
        "initial_cw_packets": 10,      # Standard startup (small packets)
        "max_ack_delay": 0.002,        # Minimal delay for low jitter
        "loss_reduction_factor": 0.5,  # Standard recovery
    },
}
```

---

## aioquic Library Technical Details

### Key Classes
- `QuicConfiguration`: Connection settings (TLS, ALPN, timeouts, max_ack_delay)
- `QuicConnection`: Core connection state machine
- `QuicConnectionProtocol`: Asyncio protocol wrapper
- `QuicStreamEvent`: Stream data events

### All Available Parameters in aioquic

| Parameter | File | Variable | Selected |
|-----------|------|----------|:--------:|
| Initial Congestion Window | `recovery.py` | `K_INITIAL_WINDOW` | ✅ |
| Max ACK Delay | `configuration.py` | `max_ack_delay` | ✅ |
| Loss Reduction Factor | `recovery.py` | `K_LOSS_REDUCTION_FACTOR` | ✅ |
| Minimum Congestion Window | `recovery.py` | `K_MINIMUM_WINDOW` | |
| Packet Threshold | `recovery.py` | `K_PACKET_THRESHOLD` | |
| Time Threshold | `recovery.py` | `K_TIME_THRESHOLD` | |
| Granularity | `recovery.py` | `K_GRANULARITY` | |
| ACK Delay Exponent | `configuration.py` | `ack_delay_exponent` | |
| Idle Timeout | `configuration.py` | `idle_timeout` | |

### Accessing Internal Metrics

```python
# RTT metrics (from QuicConnection instance)
conn._loss._rtt_smoothed      # Smoothed RTT
conn._loss._rtt_min           # Minimum RTT observed
conn._loss._rtt_latest        # Most recent RTT sample

# Congestion window
conn._loss.congestion_window  # Current congestion window in bytes
conn._loss.bytes_in_flight    # Current bytes in flight
```

---

## Implementation Plan

### Phase 1: Foundation Setup
1. **Environment Setup**
   - Install Python development environment
   - Fork aioquic repository: `git clone https://github.com/aiortc/aioquic.git`
   - Install in editable mode: `pip install -e .`
   - Generate self-signed TLS certificates for testing

2. **Basic Client-Server Implementation**
   - Create simple QUIC server using `QuicConnectionProtocol`
   - Implement client connection logic
   - Establish single stream communication
   - Verify TLS handshake succeeds

### Phase 2: Multi-Stream Support
1. **Stream Management**
   - Implement stream multiplexing using `create_stream()`
   - Create stream identification system (stream IDs are auto-assigned by aioquic)
   - Handle concurrent stream operations with asyncio

2. **Data Simulators**
   - Video: Send frames at 30fps with variable bitrate (I-frame: ~50KB, P-frame: ~5KB)
   - File: Transfer chunks with checksums (chunk size: 64KB recommended)
   - Conference: Bidirectional audio-like packets at 20ms intervals (~320 bytes/packet for 128kbps)

### Phase 3: Parameter Configuration
1. **Parameter Modification System**
   - Create script to modify `recovery.py` constants before testing
   - Use `QuicConfiguration` API for `max_ack_delay`
   - Implement parameter preset loader from configuration file

2. **Metrics Collection**
   - Implement metric measurement functions accessing `QuicConnection._loss`
   - Create timestamped data storage format (CSV or JSON)
   - Build real-time monitoring using periodic sampling

### Phase 4: Testing & Analysis
1. **Test Matrix Execution**
   - Run 27 parameter combinations (3 × 3 × 3)
   - Execute each combination for all 3 transmission types (81 total scenarios)
   - Collect metrics for statistical analysis

2. **Data Analysis**
   - Result aggregation with pandas
   - Statistical analysis (mean, std dev, percentiles)
   - Optimal parameter identification per transmission type

---

## Test Matrix

### Parameter Values

| Parameter | Conservative | Moderate | Aggressive |
|-----------|--------------|----------|------------|
| Initial CW | 12KB (10 pkts) | 60KB (50 pkts) | 120KB (100 pkts) |
| Max ACK Delay | 25ms | 10ms | 2ms |
| Loss Reduction Factor | 0.5 | 0.6 | 0.7 |

### Priority Test Scenarios (9 combinations)

| # | Initial CW | ACK Delay | Loss Factor | Target |
|---|------------|-----------|-------------|--------|
| 1 | 12KB | 25ms | 0.5 | Baseline |
| 2 | 120KB | 25ms | 0.7 | File Transfer |
| 3 | 60KB | 2ms | 0.5 | Video Streaming |
| 4 | 12KB | 2ms | 0.5 | Conference Calls |
| 5 | 120KB | 2ms | 0.7 | Maximum Performance |
| 6 | 60KB | 10ms | 0.6 | Balanced |
| 7 | 12KB | 10ms | 0.7 | Conservative + Fast Recovery |
| 8 | 120KB | 10ms | 0.5 | Fast Start + Standard Recovery |
| 9 | 60KB | 25ms | 0.7 | Moderate Start + Fast Recovery |

---

## Data Simulation Strategies

### Video Streaming
- H.264-like packet patterns
- I-frames every 2 seconds (~50KB)
- P-frames for remaining frames (~5KB)
- Variable bitrate: 2-8 Mbps typical
- 30 fps frame rate

### File Transfer
- Sequential chunks (64KB recommended)
- Large file simulation (10MB – 1GB)
- Verify delivery via stream completion
- Measure total transfer time and throughput

### Conference Calls
- Bidirectional communication
- 20ms packet interval (50 packets/second)
- Small fixed-size packets (~160-320 bytes)
- Measure jitter between received packets

---

## Network Testing Considerations
- Use `tc` (traffic control) on Linux to simulate network conditions
- Consider using network namespaces for isolated testing
- Test scenarios:
  - RTT: 10ms, 50ms, 100ms, 200ms
  - Packet loss: 0%, 1%, 5%

---

## Success Criteria

| Transmission Type | Metric | Target |
|-------------------|--------|--------|
| File Transfer | Bandwidth Utilization | >90% |
| Video Streaming | Average Latency | <50ms |
| Conference Calls | Jitter | <20ms |

**Expected Parameter Mapping**:
| Goal | Primary Parameter | Supporting Parameter |
|------|-------------------|----------------------|
| File Transfer >90% BW | Loss Reduction Factor | Initial CW |
| Video <50ms latency | Max ACK Delay | Initial CW |
| Conference <20ms jitter | Max ACK Delay | Loss Reduction Factor |

**Note**: These metrics are relative comparisons between configurations. Absolute performance will be lower than C/Rust implementations due to Python overhead.

---

## Documentation Requirements
- Inline comments in modified aioquic source files explaining parameter changes
- Function documentation with usage examples
- Parameter tuning guide with recommended ranges per transmission type
- Performance analysis report with statistical methodology

## Deliverables
1. Complete source code with documentation
2. Forked aioquic with parameter modifications and comments
3. Parameter preset configuration files
4. Performance measurement and analysis tools
5. Research findings report
6. Parameter optimization recommendations per transmission type

---

## Appendix: Quick Start

### Generate Self-Signed Certificates
```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost"
```

### Install Forked aioquic
```bash
git clone https://github.com/aiortc/aioquic.git
cd aioquic
pip install -e .
```

### Modify Parameters in recovery.py
```python
# At the top of src/aioquic/quic/recovery.py, modify these constants:

# Parameter 1: Initial Congestion Window
K_INITIAL_WINDOW = 50 * MAX_DATAGRAM_SIZE  # 60KB (default: 10 *)

# Parameter 3: Loss Reduction Factor
K_LOSS_REDUCTION_FACTOR = 0.7  # Conservative (default: 0.5)
```

### Basic Server Template
```python
import asyncio
from aioquic.asyncio import serve
from aioquic.quic.configuration import QuicConfiguration

async def main():
    configuration = QuicConfiguration(
        is_client=False,
        certificate="cert.pem",
        private_key="key.pem",
        max_ack_delay=0.010,  # Parameter 2: 10ms
    )
    await serve("localhost", 4433, configuration=configuration)
    await asyncio.Future()  # Run forever

asyncio.run(main())
```

### Basic Client Template
```python
import asyncio
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

async def main():
    configuration = QuicConfiguration(
        is_client=True,
        max_ack_delay=0.010,  # Parameter 2: 10ms
    )
    configuration.verify_mode = False  # For self-signed certs

    async with connect("localhost", 4433, configuration=configuration) as protocol:
        stream_id = protocol._quic.get_next_available_stream_id()
        protocol._quic.send_stream_data(stream_id, b"Hello, QUIC!")
        await protocol.wait_closed()

asyncio.run(main())
```

### Parameter Loader Example
```python
# parameter_loader.py
import importlib
import sys

PRESETS = {
    "baseline": {"initial_cw_packets": 10, "max_ack_delay": 0.025, "loss_reduction_factor": 0.5},
    "file_transfer": {"initial_cw_packets": 100, "max_ack_delay": 0.025, "loss_reduction_factor": 0.7},
    "video_streaming": {"initial_cw_packets": 50, "max_ack_delay": 0.005, "loss_reduction_factor": 0.5},
    "conference": {"initial_cw_packets": 10, "max_ack_delay": 0.002, "loss_reduction_factor": 0.5},
}

def get_quic_config(preset_name: str) -> QuicConfiguration:
    """Get QuicConfiguration with preset max_ack_delay."""
    preset = PRESETS[preset_name]
    return QuicConfiguration(
        is_client=True,
        max_ack_delay=preset["max_ack_delay"],
    )

def print_recovery_constants(preset_name: str):
    """Print the recovery.py constants that need to be modified."""
    preset = PRESETS[preset_name]
    print(f"# Modify in recovery.py for '{preset_name}' preset:")
    print(f"K_INITIAL_WINDOW = {preset['initial_cw_packets']} * MAX_DATAGRAM_SIZE")
    print(f"K_LOSS_REDUCTION_FACTOR = {preset['loss_reduction_factor']}")
```
