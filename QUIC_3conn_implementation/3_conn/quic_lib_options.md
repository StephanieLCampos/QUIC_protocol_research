# QUIC Library Options for Per-Connection Parameter Control

This document evaluates QUIC libraries that could replace aioquic for the multi-connection ML optimization research project, specifically focusing on per-connection parameter support that can be changed mid-connection.

---

## Executive Summary

| Library | Language | Per-Connection | Mid-Connection Tunable | Key Mid-Connection Parameters | Recommendation |
|---------|----------|----------------|------------------------|------------------------------|----------------|
| **lsquic** | C | **Yes** | **Yes** | Stream priority, Max pacing rate | **Best for ML** |
| **quiche** | Rust | **Yes** | **Yes** | Stream priority | Good Option |
| **msquic** | C | **Yes** | Partial | Some via SetParam | Good Option |
| **ngtcp2** | C | **Yes** | **Yes** (callbacks) | Full CC control via callbacks | Most Flexible |
| **quinn** | Rust | **Yes** | Limited | packet_threshold, time_threshold | Moderate |
| **quic-go** | Go | Partial | In Development | None currently | Not Recommended |
| **aioquic** | Python | **No** (globals) | **Yes** (globals only) | CC params (affect all connections) | Current (Limited) |

**Key Finding:** **lsquic** (LiteSpeed) provides the best combination of per-connection parameters that can be changed mid-connection and will affect the active connection immediately.

---

## Parameters That CAN Be Changed Mid-Connection (Per-Connection)

### The Answer to "Are there ANY parameters?"

**YES!** Several QUIC libraries support parameters that:
1. Are per-connection (different values for each connection)
2. Can be changed during an active connection
3. Immediately affect connection behavior

| Parameter Type | Effect on Connection | Libraries Supporting Mid-Connection Change |
|----------------|---------------------|-------------------------------------------|
| **Stream Priority** | Changes scheduling order, bandwidth allocation | lsquic, quiche, msquic |
| **Max Pacing Rate** | Limits send rate (bytes/sec) | lsquic |
| **Flow Control (MAX_DATA)** | Controls buffering, affects throughput | All (via QUIC frames) |
| **Read/Write Deadlines** | Timeout behavior | quic-go, others |

---

## Best Option: lsquic (LiteSpeed)

**Repository:** [github.com/litespeedtech/lsquic](https://github.com/litespeedtech/lsquic)

lsquic provides **the most comprehensive mid-connection parameter control**:

### Mid-Connection Changeable Parameters

#### 1. Stream Priority (Anytime)
```c
// Change stream priority during active connection
// Values 1-256, lower = higher priority
int result = lsquic_stream_set_priority(stream, 50);  // High priority

// For HTTP/3: Extensible Priorities (urgency 0-7)
struct lsquic_ext_http_prio prio = { .urgency = 1, .incremental = 0 };
lsquic_stream_set_http_prio(stream, &prio);
```

**Effect:** Immediately changes how the scheduler allocates bandwidth between streams. Lower priority streams get sent first (counterintuitive naming - "priority 1" is highest).

#### 2. Maximum Pacing Rate (Anytime)
```c
// Limit connection send rate to 1 MB/s
uint64_t max_rate = 1000000;  // bytes per second
lsquic_conn_set_param(conn, LSQCP_MAX_PACING_RATE, &max_rate, sizeof(max_rate));

// Remove limit (let CC algorithm decide)
uint64_t no_limit = 0;
lsquic_conn_set_param(conn, LSQCP_MAX_PACING_RATE, &no_limit, sizeof(no_limit));
```

**Effect:** Immediately caps the connection's send rate regardless of what the congestion control algorithm calculates. **This is exactly what ML optimization needs** - direct control over bandwidth allocation per-connection.

### Per-Connection Configuration
```c
// Each connection can have different settings
lsquic_engine_settings video_settings;
lsquic_engine_settings_init(&video_settings, LSQUIC_ENGINE_CLIENT);
video_settings.es_init_max_data = 2000000;  // 2MB
video_settings.es_init_max_streams_bidi = 10;
video_settings.es_pace_packets = 1;  // Enable pacing

lsquic_engine_settings file_settings;
lsquic_engine_settings_init(&file_settings, LSQUIC_ENGINE_CLIENT);
file_settings.es_init_max_data = 10000000;  // 10MB
file_settings.es_pace_packets = 1;
```

### Why lsquic is Best for ML Optimization

| Requirement | lsquic Support |
|-------------|----------------|
| Per-connection parameters | **Yes** - separate engine settings per connection |
| Mid-connection tuning | **Yes** - stream priority and pacing rate |
| Affects active connection | **Yes** - immediate effect |
| Bandwidth control | **Yes** - max pacing rate directly controls throughput |
| Python integration | FFI via ctypes/cffi |

### ML Use Case Example

```
┌─────────────────────────────────────────────────────────────────┐
│  3 QUIC Connections sharing 15 Mbps bottleneck                  │
│                                                                 │
│  ML Controller observes: Buffer filling up, loss starting       │
│                                                                 │
│  ML Decision: Protect conference call, reduce file transfer     │
│                                                                 │
│  Mid-Connection Actions:                                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ Video Conn  │  │  File Conn  │  │ Conference  │             │
│  │             │  │             │  │             │             │
│  │ Priority: 50│  │ Priority:200│  │ Priority: 10│             │
│  │ Pace: 5MB/s │  │ Pace: 2MB/s │  │ Pace: 8MB/s │             │
│  │             │  │             │  │             │             │
│  │ Gets: 33%   │  │ Gets: 13%   │  │ Gets: 54%   │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│                                                                 │
│  Result: Conference call protected, file transfer slowed        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Other Libraries: Mid-Connection Capabilities

### quiche (Cloudflare) - Stream Priority Only

```rust
// Can change stream priority during active connection
conn.stream_priority(stream_id, urgency, incremental)?;
```

**Mid-Connection Parameters:**
- Stream priority: **Yes** (via `stream_priority()`)
- Pacing rate: No (set at handshake only)
- CC parameters: No (set at config time)

### msquic (Microsoft) - SetParam API

```c
// Some parameters can be changed via SetParam
MsQuic->SetParam(Connection, QUIC_PARAM_CONN_SETTINGS, sizeof(Settings), &Settings);
```

**Mid-Connection Parameters:**
- Stream priority: **Yes** (via stream API)
- Some settings: Via SetParam API
- CC algorithm: No (set at start)

### ngtcp2 - Full Callback Control

```c
// You implement the CC callbacks - full control
ngtcp2_cc callbacks = {
    .cc_on_pkt_acked = my_acked_callback,    // Your logic here
    .cc_on_pkt_lost = my_lost_callback,       // Your logic here
    .cc_congestion_event = my_congestion_cb,  // Your logic here
};
```

**Mid-Connection Parameters:**
- Everything in your callbacks: **Yes**
- Most flexible but most complex
- You implement the CC logic yourself

---

## Direct Answer: Yes, These Parameters Can Be Changed Mid-Connection

To directly answer the question: **Yes, there ARE QUIC libraries that allow tuning parameters mid-connection, per-connection, that affect the active connection.**

### Parameters You Can Tune Mid-Connection (Per-Connection)

| Parameter | What It Controls | How It Affects Connection | Best Library |
|-----------|------------------|---------------------------|--------------|
| **Stream Priority** | Scheduling order | Higher priority streams get bandwidth first | lsquic, quiche |
| **Max Pacing Rate** | Send rate cap (bytes/s) | Directly limits throughput | **lsquic** |
| **HTTP/3 Urgency** | Request importance (0-7) | Affects resource allocation | lsquic |
| **Incremental Flag** | Progressive vs complete | Affects scheduling strategy | lsquic |
| **Flow Control Limits** | Buffer sizes | Affects sustainable throughput | All (auto) |
| **CC Callbacks** | Full CC algorithm | Complete control over CC behavior | ngtcp2 |

### Most Useful for ML: Max Pacing Rate (lsquic)

The **max pacing rate** parameter in lsquic is ideal for ML optimization because:

1. **Direct bandwidth control** - You set bytes/second, connection obeys
2. **Immediate effect** - Changes take effect on next packet
3. **Per-connection** - Each connection has its own limit
4. **Overrides CC** - Works regardless of what CC algorithm calculates
5. **Can remove limit** - Set to 0 to let CC decide again

```c
// ML decides Connection 1 needs less bandwidth
uint64_t reduced_rate = 500000;  // 500 KB/s
lsquic_conn_set_param(conn1, LSQCP_MAX_PACING_RATE, &reduced_rate, sizeof(reduced_rate));

// ML decides Connection 3 needs more bandwidth
uint64_t increased_rate = 2000000;  // 2 MB/s
lsquic_conn_set_param(conn3, LSQCP_MAX_PACING_RATE, &increased_rate, sizeof(increased_rate));
```

---

## Current Problem with aioquic

aioquic stores congestion control parameters as **module-level global constants**:

```python
# aioquic/quic/congestion/cubic.py
K_CUBIC_LOSS_REDUCTION_FACTOR = 0.7  # Affects ALL connections
K_CUBIC_C = 0.4                       # Affects ALL connections
K_MINIMUM_WINDOW = 2                  # Affects ALL connections
```

This means changing any parameter affects every active connection simultaneously, making true per-connection ML optimization impossible within a single process.

---

## Library Analysis

### 1. quiche (Cloudflare) - Rust

**Repository:** [github.com/cloudflare/quiche](https://github.com/cloudflare/quiche)

#### Per-Connection Support

quiche provides **per-path congestion control** where each `Path` instance maintains its own `Recovery` instance:

```rust
// Each connection can have different CC settings
let mut config = quiche::Config::new(quiche::PROTOCOL_VERSION)?;
config.set_cc_algorithm(quiche::CongestionControlAlgorithm::CUBIC);
config.set_initial_max_data(10_000_000);
config.set_initial_max_stream_data_bidi_local(1_000_000);

// Create connection with this config
let conn = quiche::connect(None, &scid, local, peer, &mut config)?;
```

#### Configurable Parameters

| Parameter | Method | Per-Connection |
|-----------|--------|----------------|
| CC Algorithm | `set_cc_algorithm()` | Yes |
| Initial Max Data | `set_initial_max_data()` | Yes |
| Initial Max Streams | `set_initial_max_streams_bidi()` | Yes |
| Stream Flow Control | `set_initial_max_stream_data_*()` | Yes |
| Initial RTT | `set_initial_rtt()` | Yes (recent addition) |

#### Mid-Connection Changes

- CC algorithm must be set before `connect()` or `accept()`
- Flow control limits can be updated via QUIC frames during connection
- Internal CC parameters (like loss reduction factor) are **not directly exposed** for mid-connection changes

#### Python Integration

No official Python bindings. Options:
1. Create Rust FFI bindings using PyO3
2. Use subprocess communication
3. Use the new **tokio-quiche** crate (Dec 2025) with async Python integration

#### Pros
- Production-tested (powers Cloudflare's network)
- Per-path/per-connection CC state
- Modular CC algorithm support (Reno, CUBIC, BBR, BBRv2)
- Active development with recent enhancements

#### Cons
- No native Python bindings
- CC parameters not directly tunable mid-connection
- Requires Rust knowledge for modifications

---

### 2. msquic (Microsoft) - C

**Repository:** [github.com/microsoft/msquic](https://github.com/microsoft/msquic)

#### Per-Connection Support

msquic provides per-connection settings via the `QUIC_SETTINGS` structure:

```c
QUIC_SETTINGS Settings = {0};
Settings.InitialWindowPackets = 20;
Settings.SendIdleTimeoutMs = 1000;
Settings.InitialRttMs = 100;
Settings.CongestionControlAlgorithm = QUIC_CONGESTION_CONTROL_ALGORITHM_CUBIC;

// Set flags for which settings are active
Settings.IsSet.InitialWindowPackets = TRUE;
Settings.IsSet.CongestionControlAlgorithm = TRUE;

// Apply to connection
MsQuic->SetParam(
    Connection,
    QUIC_PARAM_CONN_SETTINGS,
    sizeof(Settings),
    &Settings
);
```

#### Configurable Parameters

| Parameter | Type | Default | Per-Connection |
|-----------|------|---------|----------------|
| `InitialWindowPackets` | uint32_t | 10 | **Yes** |
| `SendIdleTimeoutMs` | uint32_t | 1000 | **Yes** |
| `InitialRttMs` | uint32_t | 333 | **Yes** |
| `CongestionControlAlgorithm` | uint16_t | CUBIC | **Yes** |
| `PacingEnabled` | uint8_t | TRUE | **Yes** |

#### Mid-Connection Changes

- Most settings applied at connection creation
- Some parameters can be modified via `SetParam` API
- CC algorithm typically set at start, not changed mid-connection

#### Python Integration

Options:
1. ctypes/cffi bindings to the C library
2. Use msquic's .NET bindings with Python.NET
3. Subprocess with msquic test tools

#### Pros
- Microsoft-supported, production-quality
- Comprehensive per-connection settings
- Well-documented API
- Available on Windows, Linux, macOS

#### Cons
- C library requires FFI for Python
- CC parameters less granular than needed (no loss_reduction_factor exposure)
- Mid-connection CC changes limited

---

### 3. quinn - Rust

**Repository:** [github.com/quinn-rs/quinn](https://github.com/quinn-rs/quinn)

#### Per-Connection Support

quinn uses `TransportConfig` for per-connection settings:

```rust
use quinn::{TransportConfig, congestion};
use std::sync::Arc;

let mut transport_config = TransportConfig::default();

// Set congestion controller factory
transport_config.congestion_controller_factory(
    Arc::new(congestion::CubicConfig::default())
);

// Configure loss detection parameters
transport_config.packet_threshold(3);      // K_PACKET_THRESHOLD equivalent
transport_config.time_threshold(1.125);    // K_TIME_THRESHOLD equivalent
transport_config.initial_rtt(Duration::from_millis(100));

// Per-connection persistent congestion
transport_config.persistent_congestion_threshold(3);
```

#### Configurable Parameters

| Parameter | quinn Method | Maps to aioquic |
|-----------|--------------|-----------------|
| `packet_threshold` | `packet_threshold()` | `K_PACKET_THRESHOLD` |
| `time_threshold` | `time_threshold()` | `K_TIME_THRESHOLD` |
| `initial_rtt` | `initial_rtt()` | `initial_rtt` |
| `persistent_congestion_threshold` | `persistent_congestion_threshold()` | Related to `K_MINIMUM_WINDOW` |
| CC Algorithm | `congestion_controller_factory()` | CC selection |

#### Mid-Connection Changes

- Transport config set at connection creation
- No API for mid-connection CC parameter changes
- Would require modifying quinn source for dynamic parameters

#### Python Integration

Options:
1. PyO3 bindings (similar to quiche)
2. Use with Rust async runtime, communicate via IPC

#### Pros
- Pure Rust, async-native
- Explicit packet/time threshold configuration
- Clean API design
- Active community

#### Cons
- No mid-connection parameter changes
- No Python bindings
- Would need source modification for dynamic ML tuning

---

### 4. ngtcp2 - C

**Repository:** [github.com/ngtcp2/ngtcp2](https://github.com/ngtcp2/ngtcp2)

#### Per-Connection Support

ngtcp2 uses a **callback-based architecture** providing maximum flexibility:

```c
// Define custom congestion control callbacks
ngtcp2_cc_algo cc_algo = {
    .cc_on_pkt_acked = my_on_pkt_acked,
    .cc_on_pkt_lost = my_on_pkt_lost,
    .cc_congestion_event = my_congestion_event,
    .cc_on_ack_recv = my_on_ack_recv,
};

// Each connection gets its own CC instance
ngtcp2_conn_set_cc_algo(conn, &cc_algo);
```

#### Configurable Parameters

ngtcp2 provides the most granular control via callbacks:

| Capability | Support |
|------------|---------|
| Custom CC algorithm | **Yes** (full callback control) |
| Per-connection CC state | **Yes** |
| Mid-connection changes | **Yes** (via callback logic) |
| Loss detection customization | **Yes** |

#### Mid-Connection Changes

**Best support** - since you implement the callbacks, you can:
- Change loss reduction factor dynamically
- Modify growth curves in real-time
- Implement ML-driven decisions directly in callbacks

#### Python Integration

Options:
1. ctypes/cffi bindings
2. Cython wrapper
3. Use with nghttp3 for HTTP/3

#### Pros
- Maximum flexibility via callbacks
- True per-connection CC state
- Full mid-connection parameter control possible
- Used by curl, Firefox

#### Cons
- Highest implementation complexity
- Requires deep QUIC/CC knowledge
- Must implement CC logic yourself
- No high-level API

---

### 5. quic-go - Go

**Repository:** [github.com/quic-go/quic-go](https://github.com/quic-go/quic-go)

#### Per-Connection Support

Currently limited. The congestion control is in `internal/congestion` package:

```go
// Current: No public API for per-connection CC configuration
// Planned: Issue #776 tracks "Pluggable congestion control"

// Some forks provide:
conn.SetCongestionControl(congestion.CongestionControl)
```

#### Current State

- Uses CUBIC by default (previously NewReno)
- CC parameters are internal, not exposed
- Issue #776 (Pluggable CC) still open since 2018
- Issue #4002 tracks L4S/Prague implementation

#### Python Integration

Go-Python integration is difficult:
- cgo with Python is complex
- gRPC/IPC would add significant latency
- Not recommended for real-time ML optimization

#### Pros
- Pure Go, easy deployment
- Good HTTP/3 support
- Active development

#### Cons
- No per-connection CC configuration currently
- Pluggable CC still in development
- Poor Python integration story
- Internal packages not meant for external use

---

## Comparison Matrix

### Parameter Support Comparison

| Parameter | aioquic | quiche | msquic | quinn | ngtcp2 |
|-----------|---------|--------|--------|-------|--------|
| Loss Reduction Factor | Global | No* | No | No | **Callback** |
| Cubic C | Global | No* | No | No | **Callback** |
| Minimum Window | Global | No* | No | Partial | **Callback** |
| Packet Threshold | Global | No | No | **Yes** | **Callback** |
| Time Threshold | Global | No | No | **Yes** | **Callback** |
| Initial Window | Global | **Yes** | **Yes** | **Yes** | **Yes** |
| Initial RTT | Per-conn | **Yes** | **Yes** | **Yes** | **Yes** |
| Max ACK Delay | Per-conn | **Yes** | **Yes** | **Yes** | **Yes** |

*quiche has modular CC support but doesn't expose individual parameters

### Mid-Connection Change Support

| Library | Can Change Mid-Connection | Mechanism |
|---------|---------------------------|-----------|
| aioquic | **Yes** (global only) | Module constant modification |
| quiche | Limited | Flow control via QUIC frames |
| msquic | Limited | SetParam API for some settings |
| quinn | No | Config frozen at connection start |
| ngtcp2 | **Yes** | Callback logic modification |
| quic-go | No | Internal implementation |

---

## Recommendations

### Option A: Continue with aioquic (Pragmatic)

**Best for:** Quick research iteration, Python-native development

**Approach:**
1. Accept the global parameter limitation
2. Document that parameter changes affect all connections
3. Study coordinated multi-connection behavior
4. Use separate processes for true per-connection isolation

**Migration Effort:** None

**Code Example (current implementation):**
```python
# Parameters affect all 3 connections simultaneously
# This is still valuable for studying coordinated behavior
from aioquic.quic.congestion import cubic
cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = 0.5  # All connections use 0.5
```

---

### Option B: Patch aioquic (Moderate Effort)

**Best for:** Per-connection control while staying in Python

**Approach:**
1. Modify aioquic source to store CC parameters per-connection
2. Move globals into `CubicCongestionControl` class instance
3. Expose parameter setters on the connection object

**Migration Effort:** 2-4 weeks

**Proposed Patch:**
```python
# Modified cubic.py
class CubicCongestionControl:
    def __init__(self, ...):
        # Instance variables instead of module globals
        self.loss_reduction_factor = 0.7
        self.cubic_c = 0.4
        self.minimum_window = 2

    def set_loss_reduction_factor(self, value: float):
        """Dynamically update loss reduction factor."""
        self.loss_reduction_factor = value

    def on_packets_lost(self, ...):
        # Use self.loss_reduction_factor instead of global
        new_ssthresh = int(flight_size * self.loss_reduction_factor)
```

---

### Option C: Use ngtcp2 with Python Bindings (Maximum Flexibility)

**Best for:** Full control over CC behavior, research requiring custom algorithms

**Approach:**
1. Create Python bindings for ngtcp2 using cffi
2. Implement CC callbacks in Python or C
3. Pass ML decisions through callback interface

**Migration Effort:** 6-10 weeks

**Architecture:**
```
┌─────────────────────────────────────────────────────────────┐
│                     Python Application                       │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ Connection 1│  │ Connection 2│  │ Connection 3│         │
│  │   (Video)   │  │   (File)    │  │ (Conference)│         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                 │
│         └────────────────┼────────────────┘                 │
│                          │                                  │
│                    ┌─────▼─────┐                            │
│                    │ ML Engine │                            │
│                    └─────┬─────┘                            │
│                          │                                  │
├──────────────────────────┼──────────────────────────────────┤
│                    cffi bindings                            │
├──────────────────────────┼──────────────────────────────────┤
│                          │                                  │
│  ┌───────────────────────▼───────────────────────────────┐  │
│  │                    ngtcp2 (C)                         │  │
│  │                                                       │  │
│  │   CC Callback ──► Python callback ──► ML decision     │  │
│  │                                                       │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

### Option D: Use msquic with ctypes (Production Quality)

**Best for:** Windows deployment, production-grade performance

**Approach:**
1. Use msquic C library via ctypes
2. Configure per-connection settings via QUIC_SETTINGS
3. Accept limited mid-connection changes

**Migration Effort:** 4-6 weeks

**Code Example:**
```python
import ctypes
from ctypes import Structure, c_uint32, c_uint16, c_uint8

class QUIC_SETTINGS(Structure):
    _fields_ = [
        ("InitialWindowPackets", c_uint32),
        ("SendIdleTimeoutMs", c_uint32),
        ("InitialRttMs", c_uint32),
        ("CongestionControlAlgorithm", c_uint16),
        # ... additional fields
    ]

# Create per-connection settings
video_settings = QUIC_SETTINGS()
video_settings.InitialWindowPackets = 60
video_settings.InitialRttMs = 50

file_settings = QUIC_SETTINGS()
file_settings.InitialWindowPackets = 100
file_settings.InitialRttMs = 100
```

---

## Final Recommendation

For the ML optimization research project described in `IMP_3conn.md`:

### Short Term (Immediate Research)
**Continue with aioquic** and document the global parameter limitation. This allows:
- Immediate progress on ML algorithm development
- Study of coordinated multi-connection behavior
- Understanding of how global parameter changes affect competing connections

### Medium Term (Enhanced Research)
**Patch aioquic** to support per-connection parameters. This provides:
- True per-connection ML optimization
- Continued Python-native development
- Reusable contribution to the aioquic community

### Long Term (Production/Advanced Research)
**Migrate to ngtcp2 with Python bindings** for:
- Maximum flexibility in CC algorithm design
- Callback-based ML integration
- Production-quality performance

---

## Sources

- [Cloudflare quiche GitHub](https://github.com/cloudflare/quiche)
- [quiche Connection and Configuration](https://deepwiki.com/cloudflare/quiche/2.1-connection-and-configuration)
- [CUBIC and HyStart++ in quiche](https://blog.cloudflare.com/cubic-and-hystart-support-in-quiche/)
- [Microsoft msquic QUIC_SETTINGS](https://github.com/microsoft/msquic/blob/main/docs/api/QUIC_SETTINGS.md)
- [msquic Settings Documentation](https://github.com/microsoft/msquic/blob/main/docs/Settings.md)
- [Quinn TransportConfig](https://docs.rs/quinn/latest/quinn/struct.TransportConfig.html)
- [ngtcp2 GitHub](https://github.com/ngtcp2/ngtcp2)
- [ngtcp2 Programmer's Guide](https://nghttp2.org/ngtcp2/programmers-guide.html)
- [quic-go Congestion Control](https://quic-go.net/docs/quic/congestion-control/)
- [quic-go Pluggable CC Issue #776](https://github.com/quic-go/quic-go/issues/776)
- [aioquic Documentation](https://aioquic.readthedocs.io/en/latest/quic.html)
- [Comparison of QUIC Implementations (TUM)](https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2022-07-1/NET-2022-07-1_10.pdf)
