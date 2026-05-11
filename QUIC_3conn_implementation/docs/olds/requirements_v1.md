# QUIC Multi-Stream Research Project - Technical Requirements & Implementation Plan

## Project Overview
This research project aims to investigate how QUIC protocol parameters affect performance metrics for different data transmission types using the aioquic library in Python.

## Technical Requirements

### Core Functionality
1. **QUIC Connection Management**
   - Establish QUIC client-server connection using aioquic library
   - Support multiple concurrent streams (minimum 3)
   - Configure QUIC parameters via source code modification (aioquic does not support runtime parameter changes for congestion control)

2. **Configurable QUIC Parameters**
   - **ACK Delay Exponent**: Controls the encoding of acknowledgment delays (not to be confused with ACK frequency)
   - **ACK Frequency**: Controls how often acknowledgments are sent (requires custom implementation or ACK_FREQUENCY extension)
   - **Initial Congestion Window**: Starting congestion window size in bytes
   - **Max Congestion Window**: Maximum bytes in flight (requires custom implementation—aioquic is unbounded by default)

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
│ Stream 2    │◆───────►│ Stream 2    │ (File)
│ Stream 3    │◄───────►│ Stream 3    │ (Conference)
└─────────────┘         └─────────────┘
```

### Dependencies
- Python 3.8+
- aioquic (forked for parameter modification)
- cryptography (required by aioquic for TLS)
- TLS certificates (self-signed acceptable for research)

## aioquic Library Technical Details

### Key Classes
- `QuicConfiguration`: Connection settings (TLS, ALPN, timeouts)
- `QuicConnection`: Core connection state machine
- `QuicConnectionProtocol`: Asyncio protocol wrapper
- `QuicStreamEvent`: Stream data events

### Source Files for Parameter Modification

| Parameter | File Location | Variable/Constant |
|-----------|---------------|-------------------|
| Initial Congestion Window | `src/aioquic/quic/recovery.py` | `K_INITIAL_WINDOW` (default: 10 * 1200 bytes) |
| Minimum Congestion Window | `src/aioquic/quic/recovery.py` | `K_MINIMUM_WINDOW` (default: 2 * 1200 bytes) |
| Loss Reduction Factor | `src/aioquic/quic/recovery.py` | `K_LOSS_REDUCTION_FACTOR` (default: 0.5) |
| Packet Threshold | `src/aioquic/quic/recovery.py` | `K_PACKET_THRESHOLD` (default: 3) |
| Time Threshold | `src/aioquic/quic/recovery.py` | `K_TIME_THRESHOLD` (default: 9/8) |
| Granularity | `src/aioquic/quic/recovery.py` | `K_GRANULARITY` (default: 0.001s) |
| ACK Delay Exponent | `src/aioquic/quic/configuration.py` | `ack_delay_exponent` (default: 3) |
| Max ACK Delay | `src/aioquic/quic/configuration.py` | `max_ack_delay` (default: 0.025s) |
| Idle Timeout | `src/aioquic/quic/configuration.py` | `idle_timeout` (configurable via API) |

### Implementing Custom Parameters

To add a **Max Congestion Window** cap, modify `recovery.py`:

```python
# Add constant at top of recovery.py
K_MAX_WINDOW = 1000000  # 1MB max congestion window

# Modify the on_packet_acked method in QuicPacketRecovery class
# After congestion window increase, add:
self.congestion_window = min(self.congestion_window, K_MAX_WINDOW)
```

To modify **ACK Frequency**, edit `connection.py`:
- Locate the `_write_application` method
- Modify ACK generation logic in `_write_ack_frame` calls

### Accessing Internal Metrics

```python
# RTT metrics (from QuicConnection instance)
conn._loss._rtt_smoothed      # Smoothed RTT
conn._loss._rtt_min           # Minimum RTT observed
conn._loss._rtt_latest        # Most recent RTT sample

# Congestion window
conn._loss.congestion_window  # Current congestion window in bytes
conn._loss.bytes_in_flight    # Current bytes in flight

# Loss statistics
conn._loss._packets_lost      # Count of lost packets (if tracked)
```

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
1. **QUIC Parameter Interface**
   - Create configuration module that modifies aioquic constants before connection
   - Implement parameter presets for different test scenarios
   - Validate parameter ranges before applying

2. **Metrics Collection**
   - Implement metric measurement functions accessing `QuicConnection._loss`
   - Create timestamped data storage format (CSV or JSON)
   - Build real-time monitoring using periodic sampling

### Phase 4: Testing & Analysis
1. **Test Suite Development**
   - Automated test scenarios with pytest
   - Parameter sweep testing (grid search over parameter combinations)
   - Performance benchmarking with statistical significance

2. **Data Analysis**
   - Result aggregation with pandas
   - Statistical analysis (mean, std dev, percentiles)
   - Optimal parameter identification per transmission type

## Key Technical Considerations

### QUIC Parameter Details

1. **ACK Delay Exponent**
   - Default: 3 (encodes delays in units of 8μs × 2^3 = 64μs)
   - Range: 0-20
   - Impact: Precision of reported ACK delays
   - Note: This is NOT the same as ACK frequency

2. **ACK Frequency** (Custom Implementation Required)
   - Default behavior: ACK every 2 packets or on timer
   - Modification: Edit `connection.py` ACK generation logic
   - Impact: Network utilization vs acknowledgment overhead
   - Consider: draft-ietf-quic-ack-frequency extension

3. **Initial Congestion Window**
   - Default: 12,000 bytes (10 × 1200 byte packets)
   - Recommended range: 2,400 - 120,000 bytes (2-100 packets)
   - Impact: Initial transfer speed, risk of early loss
   - Location: `K_INITIAL_WINDOW` in `recovery.py`

4. **Max Congestion Window** (Custom Implementation Required)
   - Default: Unlimited (grows until loss detected)
   - Recommended range: 10KB - 10MB depending on BDP
   - Impact: Maximum throughput ceiling, buffer bloat risk
   - Implementation: Add cap in `recovery.py` congestion control methods

### Data Simulation Strategies
- **Video**: H.264-like packet patterns
  - I-frames every 2 seconds (larger packets)
  - P-frames for remaining frames (smaller packets)
  - Variable bitrate: 2-8 Mbps typical

- **File**: Sequential chunks with reliability
  - Large sequential writes
  - Verify delivery via stream completion
  - Measure total transfer time

- **Conference**: Low-latency bidirectional packets
  - 20ms packet interval (50 packets/second)
  - Small fixed-size packets (~160-320 bytes)
  - Measure jitter between received packets

### Network Testing Considerations
- Use `tc` (traffic control) on Linux to simulate network conditions
- Consider using network namespaces for isolated testing
- Test scenarios: varying RTT (10ms, 50ms, 100ms, 200ms), packet loss (0%, 1%, 5%)

## Success Criteria
- Identify parameter combinations achieving:
  - File Transfer: >90% of available bandwidth utilization
  - Video Streaming: <50ms average latency
  - Conference Calls: <20ms jitter

**Note**: These metrics are relative comparisons between configurations. Absolute performance will be lower than C/Rust implementations due to Python overhead.

## Documentation Requirements
- Inline comments in modified aioquic source files explaining changes
- Function documentation with usage examples
- Parameter tuning guide with recommended ranges
- Performance analysis report with statistical methodology

## Deliverables
1. Complete source code with documentation
2. Forked aioquic with parameter modifications and comments
3. Configuration presets for different scenarios
4. Performance measurement and analysis tools
5. Research findings report
6. Parameter optimization recommendations per transmission type

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
    configuration = QuicConfiguration(is_client=True)
    configuration.verify_mode = False  # For self-signed certs

    async with connect("localhost", 4433, configuration=configuration) as protocol:
        stream_id = protocol._quic.get_next_available_stream_id()
        protocol._quic.send_stream_data(stream_id, b"Hello, QUIC!")
        await protocol.wait_closed()

asyncio.run(main())
```
