# QUIC Multi-Stream Research: Parameter and Metric Ranges

## Parameter Ranges (Grid Search Space)

| Parameter | Min | Max | All Values | Unit |
|-----------|-----|-----|------------|------|
| Initial Congestion Window | 12,000 | 120,000 | 12000, 36000, 72000, 120000 | bytes |
| Max ACK Delay | 2 | 50 | 2, 10, 25, 50 | ms |
| Loss Reduction Factor | 0.4 | 0.7 | 0.4, 0.5, 0.6, 0.7 | - |

## Metric Ranges at Optimal Configurations

### Throughput

| Application Type | Value | Unit |
|------------------|-------|------|
| File Transfer | 41.21 | MB/s |
| Video Streaming | 169.21 | KB/s |
| Conference Call | 15.72 | KB/s |

**Range**: 15.72 KB/s - 41.21 MB/s

### Round-Trip Time (RTT)

| Application Type | Value | Unit |
|------------------|-------|------|
| Video Streaming | 2.45 | ms |
| Conference Call | 3.47 | ms |
| File Transfer | 6.95 | ms |

**Range**: 2.45 ms - 6.95 ms

### Latency (Estimated as RTT/2)

| Application Type | Value | Unit |
|------------------|-------|------|
| Video Streaming | 1.22 | ms |
| Conference Call | 1.74 | ms |
| File Transfer | 3.48 | ms |

**Range**: 1.22 ms - 3.48 ms

### Jitter

| Application Type | Value | Unit |
|------------------|-------|------|
| File Transfer | 0.101 | ms |
| Conference Call | 0.547 | ms |
| Video Streaming | 0.705 | ms |

**Range**: 0.101 ms - 0.705 ms

### Packet Loss Rate

| Application Type | Value | Unit |
|------------------|-------|------|
| Video Streaming | 0.00 | % |
| File Transfer | 0.00 | % |
| Conference Call | 0.00 | % |

**Range**: 0.00% (no packet loss observed)

### Connection Establishment Time

| Application Type | Value | Unit |
|------------------|-------|------|
| Conference Call | 174.92 | ms |
| Video Streaming | 193.28 | ms |
| File Transfer | 205.98 | ms |

**Range**: 174.92 ms - 205.98 ms

## Aggregate Throughput Statistics (Across All 192 Configurations)

### By Initial Congestion Window

| ICW (bytes) | Mean Throughput | Std Dev |
|-------------|-----------------|---------|
| 12,000 | 12.24 MB/s | 17.36 MB/s |
| 36,000 | 12.49 MB/s | 17.73 MB/s |
| 72,000 | 12.84 MB/s | 18.23 MB/s |
| 120,000 | 12.58 MB/s | 17.87 MB/s |

### By Max ACK Delay

| ACK Delay (ms) | Mean Throughput | Std Dev |
|----------------|-----------------|---------|
| 2 | 12.35 MB/s | 17.52 MB/s |
| 10 | 12.69 MB/s | 18.03 MB/s |
| 25 | 12.57 MB/s | 17.86 MB/s |
| 50 | 12.53 MB/s | 17.80 MB/s |

### By Loss Reduction Factor

| Loss Factor | Mean Throughput | Std Dev |
|-------------|-----------------|---------|
| 0.4 | 12.36 MB/s | 17.54 MB/s |
| 0.5 | 12.53 MB/s | 17.78 MB/s |
| 0.6 | 12.60 MB/s | 17.91 MB/s |
| 0.7 | 12.66 MB/s | 17.98 MB/s |

## Optimal Parameter Configurations Summary

| Application Type | ICW (bytes) | ACK Delay (ms) | Loss Factor | Optimized Metric | Latency |
|------------------|-------------|----------------|-------------|------------------|---------|
| Video Streaming | 36,000 | 50 | 0.5 | RTT: 2.45 ms | 1.22 ms |
| File Transfer | 120,000 | 10 | 0.6 | Throughput: 41.21 MB/s | 3.48 ms |
| Conference Call | 120,000 | 25 | 0.6 | Jitter: 0.547 ms | 1.74 ms |
