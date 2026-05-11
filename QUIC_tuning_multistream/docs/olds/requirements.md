# QUIC Multi-Stream Research Project - Technical Requirements & Implementation Plan

## Project Overview
This research project aims to investigate how QUIC protocol parameters affect performance metrics for different data transmission types using the aioquic library in python.

## Technical Requirements

### Core Functionality
1. **QUIC Connection Management**
   - Establish QUIC client-server connection using aioquic library
   - Support multiple concurrent streams (minimum 3)
   - Enable runtime modification of QUIC parameters

2. **Configurable QUIC Parameters**
   - **ACK Frequency**: Controls how often acknowledgments are sent
   - **Max Congestion Window**: Maximum number of bytes in flight
   - **Initial Congestion Window**: Starting congestion window size

3. **Data Transmission Types**
   - **Video Streaming**: Continuous data flow with emphasis on low latency
   - **File Transfer**: Bulk data transfer prioritizing throughput
   - **Conference Calls**: Bidirectional real-time communication requiring minimal jitter

4. **Performance Metrics**
   - **Throughput**: Data transfer rate (bytes/second)
   - **Round-Trip Time (RTT)**: Latency measurement
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

## Implementation Plan

### Phase 1: Foundation Setup (Week 1-2)
1. **Environment Setup**
   - Install Python development environment
   - Import aioquic library
   - Set up project structure

2. **Basic Client-Server Implementation**
   - Create simple QUIC server
   - Implement client connection logic
   - Establish single stream communication

### Phase 2: Multi-Stream Support (Week 3-4)
1. **Stream Management**
   - Implement stream multiplexing
   - Create stream identification system
   - Handle concurrent stream operations

2. **Data Simulators**
   - Video: Send frames at 30fps with variable bitrate
   - File: Transfer chunks with checksums
   - Conference: Bidirectional audio-like packets at 20ms intervals

### Phase 3: Parameter Configuration (Week 5-6)
1. **QUIC Parameter Interface**
   - Create configuration structure
   - Implement parameter modification API
   - Validate parameter ranges

2. **Metrics Collection**
   - Implement metric measurement functions
   - Create data storage format
   - Build real-time monitoring

### Phase 4: Testing & Analysis (Week 7-8)
1. **Test Suite Development**
   - Automated test scenarios
   - Parameter sweep testing
   - Performance benchmarking

2. **Data Analysis**
   - Result aggregation
   - Statistical analysis
   - Optimal parameter identification

## Key Technical Considerations

### QUIC Parameter Details
1. **ACK Frequency (ack-delay-exponent)**
   - Default: 3 (8ms)
   - Range: 0-20
   - Impact: Network utilization vs acknowledgment overhead

2. **Initial Congestion Window**
   - Default: 10 packets
   - Range: 2-100 packets
   - Impact: Initial transfer speed

3. **Max Congestion Window**
   - Default: Unlimited
   - Range: 10KB-10MB
   - Impact: Maximum throughput ceiling

### Data Simulation Strategies
- **Video**: H.264-like packet patterns (I-frames, P-frames)
- **File**: Sequential chunks with TCP-like behavior
- **Conference**: Low-latency bidirectional packets

## Success Criteria
- Identify parameter combinations achieving:
  - File Transfer: >90% of available bandwidth utilization
  - Video Streaming: <50ms average latency
  - Conference Calls: <20ms jitter

## Documentation Requirements
- Comments about modifiying the parameters on the source code of aioquic
- Function documentation with examples
- Parameter tuning guide
- Performance analysis report

## Deliverables
1. Complete source code with documentation
2. Configuration files for different scenarios
3. Performance measurement tools
4. Research findings report
5. Parameter optimization recommendations