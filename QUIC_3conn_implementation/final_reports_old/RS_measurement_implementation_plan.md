# Receiver-Side Measurement Implementation Plan

## Comprehensive Technical Specification

---

## CRITICAL REVIEW NOTES (Added After Review)

### Issues Found and Corrections Required

After thorough review of the codebase, the following issues were identified:

#### Issue 1: simulation_id Mismatch (CRITICAL)

**Problem:** Server and clients generate independent simulation_ids based on their startup timestamps. Files won't match.

**Solution:** Use fixed filename `server_metrics_latest.json` that gets overwritten each run. Clients read this file regardless of their simulation_id.

#### Issue 2: Clients Don't Wait for Server Metrics (CRITICAL)

**Problem:** In `cmd_clients()` (main.py), results are exported immediately after `orchestrator.run()` completes. Server exports at t=40, clients finish at t=30.

**Solution:** Add explicit wait/poll loop in `cmd_clients()` BEFORE exporting results:
```python
# After orchestrator.run() completes, wait for server metrics
server_metrics_file = output_path / "server_metrics_latest.json"
max_wait = 15.0  # Server runs 10s longer than clients
waited = 0.0
while not server_metrics_file.exists() and waited < max_wait:
    time.sleep(0.5)
    waited += 0.5
```

#### Issue 3: Connection ID Correlation (CRITICAL)

**Problem:** Server assigns IDs based on protocol creation order, but clients might connect in different order. No reliable correlation.

**Solution:** Use bytes-based matching:
- Server reports metrics with `bytes_received` per protocol
- Clients have `bytes_sent` per connection
- Match where `server.bytes_received ≈ client.bytes_sent`

**Alternative (Simpler):** Just report server-side totals, not per-connection breakdown. Sum should ≈ tc_observed.

#### Issue 4: Class Name Inconsistency (MEDIUM)

**Problem:** Plan refers to `class Orchestrator`, code uses `class ProcessOrchestrator`.

**Correction:** All references should use `ProcessOrchestrator`.

#### Issue 5: Missing output_dir in Orchestrator (MEDIUM)

**Problem:** Plan's code uses `self.output_dir` but `ProcessOrchestrator` doesn't have this attribute.

**Solution:** Pass output_dir as parameter to the orchestrator, OR read from environment variable, OR use hardcoded "output" path.

#### Issue 6: Server Metrics Export Location (MEDIUM)

**Problem:** Plan shows export code but doesn't specify WHERE in `cmd_server()` to add it.

**Solution:** Add at the end of `cmd_server()`:
```python
# In main.py cmd_server(), after orchestrator.run() completes:
if orchestrator.server:
    output_path = Path("output")
    output_path.mkdir(parents=True, exist_ok=True)
    orchestrator.server.export_server_metrics(str(output_path))
```

#### Issue 7: Container Names (MINOR)

**Correction:** Actual container names are `server`, `clients`, `prober` (not `quic-server`, `quic-clients`).

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture Analysis](#2-current-architecture-analysis)
3. [Implementation Strategy](#3-implementation-strategy)
4. [Detailed File Changes](#4-detailed-file-changes)
5. [Phase 1: Server-Side Tracking](#5-phase-1-server-side-tracking)
6. [Phase 2: Metrics Export Mechanism](#6-phase-2-metrics-export-mechanism)
7. [Phase 3: Orchestrator Integration](#7-phase-3-orchestrator-integration)
8. [Phase 4: Results Integration](#8-phase-4-results-integration)
9. [Phase 5: Testing & Validation](#9-phase-5-testing--validation)
10. [Docker Considerations](#10-docker-considerations)
11. [Risk Assessment](#11-risk-assessment)
12. [Implementation Checklist](#12-implementation-checklist)

---

## 1. Executive Summary

### Goal

Implement receiver-side throughput measurement to accurately measure per-connection network throughput by tracking bytes received at the server.

### Current State

```
Client (Worker) ──► Network (Bottleneck) ──► Server
      │                                        │
      ▼                                        ▼
  bytes_sent                            bytes_received
  (measured) ✓                          (tracked but NOT reported) ✗
```

### Target State

```
Client (Worker) ──► Network (Bottleneck) ──► Server
      │                                        │
      ▼                                        ▼
  bytes_sent                            bytes_received
  (measured) ✓                          (measured & reported) ✓
      │                                        │
      └────────────► Orchestrator ◄────────────┘
                          │
                          ▼
                  receiver_throughput_mbps
                  (per connection)
```

### Approach

Use **shared volume** mechanism:
1. Server writes per-connection metrics to JSON file
2. Orchestrator reads file after simulation
3. Merge with client-side metrics in results

---

## 2. Current Architecture Analysis

### 2.1 Docker Container Structure

```
┌─────────────────────────────────────────────────────────────────┐
│                      Docker Compose Setup                        │
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │  quic-server    │  │  quic-clients   │  │  quic-prober    │ │
│  │                 │  │                 │  │                 │ │
│  │ 192.168.200.10  │  │ 192.168.200.20  │  │ 192.168.200.30  │ │
│  │                 │  │                 │  │                 │ │
│  │ RUN_MODE=server │  │ RUN_MODE=clients│  │ (RTT probe)     │ │
│  └────────┬────────┘  └────────┬────────┘  └─────────────────┘ │
│           │                    │                                │
│           │     Shared Volume: ./results:/app/3_conn_code/output│
│           │                    │                                │
│           └────────────────────┴────────────────────────────────│
│                                │                                │
│                     ┌──────────▼──────────┐                    │
│                     │   Host Filesystem   │                    │
│                     │   ./results/        │                    │
│                     └─────────────────────┘                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Current Server Data Reception

**File:** `3_conn_code/simulation/server.py`

```python
class ServerProtocol(QuicConnectionProtocol):
    def __init__(self, ...):
        self.streams: Dict[int, int] = {}      # stream_id → bytes
        self.total_bytes_received: int = 0
        self.handshake_complete: bool = False

    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            stream_id = event.stream_id
            if stream_id not in self.streams:
                self.streams[stream_id] = 0
            self.streams[stream_id] += len(event.data)
            self.total_bytes_received += len(event.data)
```

**Key Finding:** Server already tracks bytes per stream, but:
- No connection ID correlation (only stream IDs)
- No timing information for throughput calculation
- No export mechanism to share with orchestrator

### 2.3 Current Metrics Flow

```
Worker Process                    Orchestrator
     │                                 │
     │ ─── IPCMessage(METRICS) ──────► │
     │     payload: {                  │
     │       throughput,               │  metrics_history.append()
     │       rtt, jitter, ...          │
     │     }                           │
     │                                 │
     │ ─── IPCMessage(FINISHED) ─────► │
     │     payload: {                  │  final_results[conn_id] = ...
     │       final_metrics,            │
     │       epoch_history             │
     │     }                           │
     │                                 │
```

**Gap:** Server has no channel to report metrics.

### 2.4 Existing Shared Volume

From `docker-compose.yml`:

```yaml
services:
  clients:  # Note: actual name is "clients", not "quic-clients"
    volumes:
      - ./results:/app/3_conn_code/output
      - ./results:/app/3_conn_code/reports

  server:  # Note: actual name is "server", not "quic-server"
    # Currently NO volume mount!
```

**Action Required:** Add volume mount to server container.

**Note:** Container names are `server`, `clients`, `prober` (not `quic-server`, `quic-clients`).

---

## 3. Implementation Strategy

### 3.1 Chosen Approach: Shared File

**Why Shared File over Alternatives:**

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| **Shared File** | Simple, works with Docker, no code coupling | Slight delay at end | **Selected** |
| In-band QUIC | Elegant, real-time | Complex protocol changes | Rejected |
| HTTP endpoint | Standard pattern | Adds dependency, complexity | Rejected |
| Stdout parsing | No file I/O | Fragile, hard to parse | Rejected |

### 3.2 Data Flow Design

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA FLOW                                 │
│                                                                 │
│  DURING SIMULATION:                                             │
│                                                                 │
│  Client 1 ─────┐                                                │
│  Client 2 ─────┼───► Server receives data ───► Track per-conn  │
│  Client 3 ─────┘                               bytes_received   │
│                                                                 │
│  AT END OF SIMULATION:                                          │
│                                                                 │
│  Server ───► Write server_metrics.json ───► Shared Volume       │
│                                                    │            │
│                                                    ▼            │
│  Orchestrator ◄─── Read server_metrics.json ◄─────┘            │
│       │                                                         │
│       ▼                                                         │
│  Merge with client metrics                                      │
│       │                                                         │
│       ▼                                                         │
│  Final Results with receiver_throughput_mbps                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 Connection Identification Strategy

**Challenge:** Server sees stream IDs per protocol, not client connection IDs. Connections may arrive in different order than clients expect.

**Solution: Bytes-Based Matching (Recommended)**

After simulation, match server protocols to client connections based on bytes:

```python
def match_connections(client_metrics, server_metrics):
    """
    Match server protocols to client connections based on bytes sent/received.

    Each client connection has bytes_sent.
    Each server protocol has bytes_received.
    Match where: server.bytes_received ≈ client.bytes_sent (within 5% tolerance)
    """
    matches = {}
    used_server_ids = set()

    # Sort clients by bytes_sent descending (file transfer first - most distinct)
    sorted_clients = sorted(
        client_metrics.items(),
        key=lambda x: x[1].get("bytes_sent", 0),
        reverse=True
    )

    for conn_id, client_data in sorted_clients:
        client_bytes = client_data.get("bytes_sent", 0)
        best_match = None
        best_diff = float("inf")

        for server_id, server_data in server_metrics.items():
            if server_id in used_server_ids:
                continue
            server_bytes = server_data.get("bytes_received", 0)
            diff = abs(client_bytes - server_bytes)
            # Allow 5% tolerance for protocol overhead
            if diff < client_bytes * 0.05 and diff < best_diff:
                best_diff = diff
                best_match = server_id

        if best_match:
            matches[conn_id] = best_match
            used_server_ids.add(best_match)

    return matches  # {client_conn_id: server_protocol_id}
```

**Alternative (Simpler):** Report aggregate server throughput only:
- Sum of all server bytes_received / duration
- Should ≈ tc_observed throughput
- No per-connection breakdown needed for Q-learning reward

---

## 4. Detailed File Changes

### 4.1 Files to Modify

| File | Changes | Priority |
|------|---------|----------|
| `simulation/server.py` | Add per-connection tracking, timing, export | **HIGH** |
| `docker-compose.yml` | Add volume mount to server | **HIGH** |
| `simulation/process_orchestrator.py` | Read server metrics file | **HIGH** |
| `simulation/result.py` | Add receiver_throughput to output | **HIGH** |
| `main.py` | Pass output directory to server | MEDIUM |

### 4.2 New Files to Create

| File | Purpose |
|------|---------|
| `simulation/server_metrics.py` | Data structures for server metrics |

### 4.3 Files Unchanged

| File | Reason |
|------|--------|
| `simulation/worker_process.py` | Client-side, no changes needed |
| `simulation/client.py` | Client-side, no changes needed |
| `metrics/collector.py` | Client-side metrics collection |
| `metrics/calculator.py` | Client-side calculations |

---

## 5. Phase 1: Server-Side Tracking

### 5.1 Enhanced ServerProtocol

**File:** `3_conn_code/simulation/server.py`

**Add to `__init__`:**

```python
class ServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Existing
        self.streams: Dict[int, int] = {}
        self.total_bytes_received: int = 0
        self.handshake_complete: bool = False

        # NEW: Per-connection tracking
        self.connection_id: Optional[int] = None  # Set from first packet
        self.first_data_time: Optional[float] = None
        self.last_data_time: Optional[float] = None
        self.bytes_received_timeline: List[Tuple[float, int]] = []  # (timestamp, cumulative_bytes)
```

**Modify `quic_event_received`:**

```python
def quic_event_received(self, event):
    if isinstance(event, HandshakeCompleted):
        self.handshake_complete = True
        if self._connection_callback:
            self._connection_callback(True)

    elif isinstance(event, StreamDataReceived):
        stream_id = event.stream_id
        data_len = len(event.data)
        current_time = time.time()

        # Track timing
        if self.first_data_time is None:
            self.first_data_time = current_time
            # Extract connection_id from first data packet (if encoded)
            self._extract_connection_id(event.data)
        self.last_data_time = current_time

        # Track bytes
        if stream_id not in self.streams:
            self.streams[stream_id] = 0
        self.streams[stream_id] += data_len
        self.total_bytes_received += data_len

        # Timeline for analysis (sample every 100ms)
        if not self.bytes_received_timeline or \
           (current_time - self.bytes_received_timeline[-1][0]) >= 0.1:
            self.bytes_received_timeline.append(
                (current_time, self.total_bytes_received)
            )

        # Existing callback
        if self._data_received_callback:
            self._data_received_callback(stream_id, data_len)
```

**Add new methods:**

```python
def _extract_connection_id(self, first_data: bytes) -> None:
    """Extract connection_id from first data packet header."""
    # Option 1: Encoded in first 4 bytes
    if len(first_data) >= 4:
        try:
            self.connection_id = int.from_bytes(first_data[:4], 'big')
        except:
            pass

    # Option 2: Use source address hash as fallback
    if self.connection_id is None:
        # Will be set by QuicServer based on connection order
        pass

def get_duration(self) -> float:
    """Get connection duration in seconds."""
    if self.first_data_time is None or self.last_data_time is None:
        return 0.0
    return self.last_data_time - self.first_data_time

def get_receiver_throughput_bps(self) -> float:
    """Calculate receiver-side throughput in bits per second."""
    duration = self.get_duration()
    if duration <= 0:
        return 0.0
    return (self.total_bytes_received * 8) / duration

def get_metrics(self) -> Dict[str, Any]:
    """Get all receiver-side metrics for this connection."""
    duration = self.get_duration()
    throughput_bps = self.get_receiver_throughput_bps()

    return {
        "connection_id": self.connection_id,
        "bytes_received": self.total_bytes_received,
        "duration_seconds": duration,
        "throughput_bps": throughput_bps,
        "throughput_mbps": throughput_bps / 1_000_000,
        "first_data_time": self.first_data_time,
        "last_data_time": self.last_data_time,
        "stream_count": len(self.streams),
        "streams": dict(self.streams),  # stream_id → bytes
    }
```

### 5.2 Enhanced QuicServer

**Add to `QuicServer` class:**

```python
class QuicServer:
    def __init__(self, ...):
        # Existing
        self._protocols: list = []

        # NEW
        self._output_dir: str = "output"
        self._simulation_id: str = ""
        self._connection_counter: int = 0

    def set_output_config(self, output_dir: str, simulation_id: str):
        """Set output configuration for metrics export."""
        self._output_dir = output_dir
        self._simulation_id = simulation_id

    def _assign_connection_id(self, protocol: ServerProtocol) -> int:
        """Assign connection ID based on connection order."""
        self._connection_counter += 1
        return self._connection_counter

    def get_all_connection_metrics(self) -> Dict[int, Dict[str, Any]]:
        """Get metrics for all connections."""
        metrics = {}
        for protocol in self._protocols:
            if protocol.connection_id is not None:
                metrics[protocol.connection_id] = protocol.get_metrics()
            else:
                # Assign ID if not set
                conn_id = self._assign_connection_id(protocol)
                protocol.connection_id = conn_id
                metrics[conn_id] = protocol.get_metrics()
        return metrics

    def export_server_metrics(self, output_dir: str = "output") -> str:
        """Export server-side metrics to JSON file."""
        import json
        from pathlib import Path

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Use fixed filename for easy discovery by clients
        filename = "server_metrics_latest.json"
        filepath = output_path / filename

        metrics = {
            "total_connections": len(self._protocols),
            "total_bytes_received": self.get_total_bytes_received(),
            "per_connection": self.get_all_connection_metrics(),
            "export_timestamp": time.time(),
        }

        # Atomic write: write to temp file, then rename
        temp_filepath = filepath.with_suffix(".tmp")
        with open(temp_filepath, "w") as f:
            json.dump(metrics, f, indent=2)
        temp_filepath.rename(filepath)  # Atomic on most filesystems

        print(f"[Server] Exported metrics to {filepath}")
        return str(filepath)
```

---

## 6. Phase 2: Metrics Export Mechanism

### 6.1 Server Shutdown Hook

**Modify `cmd_server()` in `main.py` to export metrics on shutdown:**

```python
# In main.py, modify cmd_server() function (around line 305-314):

def cmd_server(args):
    """Run server only - waits for client connections and applies bottleneck."""
    # ... existing setup code ...

    try:
        loop.run_until_complete(orchestrator.run(args.duration))
        print("\nServer run completed successfully")

        # NEW: Export server metrics before shutdown
        if orchestrator.server:
            output_path = Path("output")  # Must match clients' volume mount
            output_path.mkdir(parents=True, exist_ok=True)
            orchestrator.server.export_server_metrics(str(output_path))

    except Exception as e:
        print(f"\nError running server: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0
```

**IMPORTANT:** The output path must be `/app/3_conn_code/output` inside the container, which maps to `./results` on the host via the Docker volume mount.

### 6.2 Docker Volume Configuration

**Modify `docker-compose.yml`:**

```yaml
services:
  quic-server:
    image: quic-wireless
    container_name: quic-server
    hostname: server
    networks:
      quic-net:
        ipv4_address: 192.168.200.10
    environment:
      - RUN_MODE=server
      - NETWORK_SCENARIO=${NETWORK_SCENARIO:-baseline}
    cap_add:
      - NET_ADMIN
    # NEW: Add volume mount for metrics export
    volumes:
      - ./results:/app/3_conn_code/output
    command: ["python", "-m", "main", "server", "--duration", "40"]
```

### 6.3 Server Metrics File Format

**File:** `results/server_metrics_latest.json` (fixed name, overwritten each run)

```json
{
  "simulation_id": "04-04-2026_10-30-00AM",
  "total_connections": 3,
  "total_bytes_received": 14250000,
  "per_connection": {
    "1": {
      "connection_id": 1,
      "bytes_received": 5200000,
      "duration_seconds": 30.5,
      "throughput_bps": 1363934.43,
      "throughput_mbps": 1.36,
      "first_data_time": 1712234100.123,
      "last_data_time": 1712234130.623,
      "stream_count": 12,
      "streams": {
        "0": 2600000,
        "4": 2600000
      }
    },
    "2": {
      "connection_id": 2,
      "bytes_received": 8500000,
      "duration_seconds": 30.2,
      "throughput_bps": 2251655.63,
      "throughput_mbps": 2.25,
      "first_data_time": 1712234100.234,
      "last_data_time": 1712234130.434,
      "stream_count": 8,
      "streams": {
        "0": 8500000
      }
    },
    "3": {
      "connection_id": 3,
      "bytes_received": 550000,
      "duration_seconds": 30.4,
      "throughput_bps": 144736.84,
      "throughput_mbps": 0.14,
      "first_data_time": 1712234100.345,
      "last_data_time": 1712234130.745,
      "stream_count": 15,
      "streams": {
        "0": 275000,
        "4": 275000
      }
    }
  },
  "export_timestamp": 1712234131.000
}
```

---

## 7. Phase 3: Orchestrator Integration

### 7.1 Read Server Metrics

**Add to `process_orchestrator.py`:**

```python
class ProcessOrchestrator:  # Note: Correct class name
    def __init__(self, ...):
        # Existing
        self.final_results: Dict[int, dict] = {}

        # NEW
        self.server_metrics: Dict[int, Dict[str, Any]] = {}
        self.output_dir: str = "output"  # NEW: Add output_dir attribute

    def _load_server_metrics(self) -> bool:
        """Load server-side metrics from exported file."""
        import json
        from pathlib import Path

        # Use fixed filename (doesn't depend on simulation_id)
        metrics_file = Path(self.output_dir) / "server_metrics_latest.json"

        # Wait for file with timeout (server runs longer than clients)
        max_wait = 15.0  # Server runs 10s longer, plus buffer
        wait_interval = 0.5
        elapsed = 0.0

        while elapsed < max_wait:
            if metrics_file.exists():
                try:
                    with open(metrics_file, "r") as f:
                        data = json.load(f)

                    # Extract per-connection metrics
                    per_conn = data.get("per_connection", {})
                    for conn_id_str, metrics in per_conn.items():
                        conn_id = int(conn_id_str)
                        self.server_metrics[conn_id] = metrics

                    print(f"Loaded server metrics for {len(self.server_metrics)} connections")
                    return True

                except json.JSONDecodeError:
                    # File may still be writing, wait and retry
                    pass

            time.sleep(wait_interval)
            elapsed += wait_interval

        print(f"Warning: Could not load server metrics from {metrics_file}")
        return False
```

**IMPORTANT:** Also add `output_dir` parameter to `__init__`:
```python
def __init__(
    self,
    config: MultiConnectionConfig,
    ...
    output_dir: str = "output",  # NEW parameter
):
    ...
    self.output_dir = output_dir
```

### 7.2 Client Wait and Load Logic

**Modify `cmd_clients()` in `main.py` to wait for and load server metrics:**

```python
# In main.py cmd_clients(), AFTER orchestrator.run() completes but BEFORE exporting results:

if result:
    # NEW: Wait for and load server metrics
    output_path = Path(args.output_dir)
    server_metrics_file = output_path / "server_metrics_latest.json"

    print("[Clients] Waiting for server metrics...")
    max_wait = 15.0  # Server runs 10s longer + buffer
    waited = 0.0

    while not server_metrics_file.exists() and waited < max_wait:
        time.sleep(0.5)
        waited += 0.5

    if server_metrics_file.exists():
        try:
            server_data = json.loads(server_metrics_file.read_text())
            # Match server protocols to client connections
            matched_metrics = match_server_to_client_metrics(
                result.connection_results,
                server_data.get("per_connection", {})
            )
            # Merge into result
            for conn_id, server_metrics in matched_metrics.items():
                if conn_id in result.connection_results:
                    result.connection_results[conn_id].final_metrics.update({
                        "receiver_throughput_mbps": server_metrics.get("throughput_mbps", 0),
                        "receiver_bytes": server_metrics.get("bytes_received", 0),
                    })
            print(f"[Clients] Loaded server metrics: {len(matched_metrics)} connections matched")
        except Exception as e:
            print(f"[Clients] Warning: Failed to load server metrics: {e}")
    else:
        print(f"[Clients] Warning: Server metrics not found after {max_wait}s")

    # ... existing result export code ...
```

### 7.3 Integrate into Result Building

**Modify `_build_results` method:**

```python
def _build_results(self) -> MultiConnectionResult:
    """Build final result object from collected data."""

    # Load server metrics first
    self._load_server_metrics(self.simulation_id)

    connection_results = {}

    for conn_id in [1, 2, 3]:
        if conn_id in self.final_results:
            result_data = self.final_results[conn_id]

            # Get server-side metrics for this connection
            server_data = self.server_metrics.get(conn_id, {})

            # Add receiver throughput to final_metrics
            final_metrics = result_data.get("final_metrics", {})
            final_metrics["receiver_throughput"] = server_data.get("throughput_bps", 0) / 8  # bytes/sec
            final_metrics["receiver_throughput_mbps"] = server_data.get("throughput_mbps", 0)
            final_metrics["receiver_bytes"] = server_data.get("bytes_received", 0)

            connection_results[conn_id] = ConnectionResult(
                connection_id=conn_id,
                application_type=self.config.get_config(conn_id).application_type,
                final_metrics=final_metrics,
                param_history=result_data.get("param_history", []),
                epoch_history=epochs_list,
                metrics_history=per_conn_metrics.get(conn_id, []),
                network_scenario=self.config.network_scenario,
                network_config={
                    **self.network_config,
                    "server_metrics": server_data,  # Include server data
                },
                success=result_data.get("success", True),
            )

    # ... rest of method
```

---

## 8. Phase 4: Results Integration

### 8.1 Update Result Export

**Modify `result.py` - `get_bottleneck_summary`:**

```python
def get_bottleneck_summary(self) -> Dict[str, Any]:
    """Build a bottleneck-focused summary that is easy to interpret."""

    # ... existing code ...

    # Calculate per-connection throughput using RECEIVER-SIDE data
    per_connection_throughput = {}

    for conn_id, result in self.connection_results.items():
        # Offered throughput (client-side)
        offered_Bps = result.final_metrics.get("throughput", 0)
        offered_bps = offered_Bps * 8
        offered_mbps = offered_bps / 1_000_000

        # Receiver throughput (server-side) - NEW
        receiver_mbps = result.final_metrics.get("receiver_throughput_mbps", 0)
        receiver_bytes = result.final_metrics.get("receiver_bytes", 0)

        # Calculate delivery ratio
        bytes_sent = result.final_metrics.get("bytes_sent", 0)
        delivery_ratio = (receiver_bytes / bytes_sent * 100) if bytes_sent > 0 else 0

        per_connection_throughput[str(conn_id)] = {
            "application_type": result.application_type,
            "offered_throughput_mbps": offered_mbps,
            "receiver_throughput_mbps": receiver_mbps,  # NEW: Actual network throughput
            "delivery_ratio_percent": delivery_ratio,   # NEW: % of data delivered
        }

    return {
        # ... existing fields ...
        "per_connection_throughput": per_connection_throughput,
    }
```

### 8.2 Update Median Metrics Export

**Modify `export_median_metrics_summary`:**

```python
def export_median_metrics_summary(self, output_dir: str = "output") -> str:
    """Export only trimmed-median metrics for quick comparison."""

    # ... existing setup ...

    # Get receiver throughput from bottleneck summary
    bottleneck_summary = self.get_bottleneck_summary()
    per_conn_throughput = bottleneck_summary.get("per_connection_throughput", {})

    compact_connections: Dict[str, Any] = {}
    for conn_id, conn_data in per_connection.items():
        med = conn_data.get("trimmed_medians", {})

        # Get receiver throughput (server-side measurement)
        receiver_mbps = per_conn_throughput.get(str(conn_id), {}).get(
            "receiver_throughput_mbps", 0.0
        )
        delivery_ratio = per_conn_throughput.get(str(conn_id), {}).get(
            "delivery_ratio_percent", 0.0
        )

        compact_connections[str(conn_id)] = {
            "application_type": conn_data.get("application_type", ""),
            "offered_throughput_median_mbps": med.get("offered_throughput_median_mbps", 0.0),
            "receiver_throughput_mbps": receiver_mbps,  # NEW
            "delivery_ratio_percent": delivery_ratio,    # NEW
            "rtt_median_ms": med.get("rtt_median_ms", 0.0),
            "latency_median_ms": med.get("latency_median_ms", 0.0),
            "jitter_median_ms": med.get("jitter_median_ms", 0.0),
            "packet_loss_rate_median": med.get("packet_loss_rate_median", 0.0),
            "samples_used": med.get("samples_used", 0),
            "samples_total": med.get("samples_total", 0),
        }

    # ... rest of method ...
```

### 8.3 Expected Output Format

**File:** `median_metrics_summary_{simulation_id}.json`

```json
{
  "simulation_id": "04-04-2026_10-30-00AM",
  "network_scenario": "congested_low",
  "connections": {
    "1": {
      "application_type": "video_streaming",
      "offered_throughput_median_mbps": 1.33,
      "receiver_throughput_mbps": 1.30,
      "delivery_ratio_percent": 97.7,
      "rtt_median_ms": 38.05,
      "latency_median_ms": 19.02,
      "jitter_median_ms": 0.84,
      "packet_loss_rate_median": 0.0
    },
    "2": {
      "application_type": "file_transfer",
      "offered_throughput_median_mbps": 226.77,
      "receiver_throughput_mbps": 2.15,
      "delivery_ratio_percent": 0.95,
      "rtt_median_ms": 42.59,
      "latency_median_ms": 21.30,
      "jitter_median_ms": 0.11,
      "packet_loss_rate_median": 0.0
    },
    "3": {
      "application_type": "conference_call",
      "offered_throughput_median_mbps": 0.11,
      "receiver_throughput_mbps": 0.10,
      "delivery_ratio_percent": 90.9,
      "rtt_median_ms": 38.08,
      "latency_median_ms": 19.04,
      "jitter_median_ms": 0.29,
      "packet_loss_rate_median": 0.0
    }
  }
}
```

---

## 9. Phase 5: Testing & Validation

### 9.1 Unit Tests

**Test 1: Server Metrics Collection**

```python
def test_server_protocol_metrics():
    """Test that ServerProtocol correctly tracks bytes received."""
    protocol = ServerProtocol(...)

    # Simulate receiving data
    event1 = StreamDataReceived(stream_id=0, data=b"x" * 1000)
    event2 = StreamDataReceived(stream_id=0, data=b"x" * 500)

    protocol.quic_event_received(event1)
    protocol.quic_event_received(event2)

    assert protocol.total_bytes_received == 1500
    assert protocol.streams[0] == 1500
    assert protocol.get_duration() > 0
```

**Test 2: Metrics Export**

```python
def test_server_metrics_export():
    """Test that server metrics are correctly exported to JSON."""
    server = QuicServer(...)
    server.set_output_config("/tmp/test", "test_sim")

    # Add mock protocol with data
    protocol = MockServerProtocol(bytes_received=1000)
    server._protocols.append(protocol)

    filepath = server.export_server_metrics()

    assert os.path.exists(filepath)
    with open(filepath) as f:
        data = json.load(f)
    assert data["total_bytes_received"] == 1000
```

**Test 3: Orchestrator Integration**

```python
def test_orchestrator_loads_server_metrics():
    """Test that orchestrator correctly loads server metrics."""
    orchestrator = Orchestrator(...)

    # Create mock server metrics file
    metrics = {"per_connection": {"1": {"throughput_mbps": 1.5}}}
    with open("output/server_metrics_test.json", "w") as f:
        json.dump(metrics, f)

    orchestrator._load_server_metrics("test")

    assert 1 in orchestrator.server_metrics
    assert orchestrator.server_metrics[1]["throughput_mbps"] == 1.5
```

### 9.2 Integration Tests

**Test 4: End-to-End Validation**

```bash
# Run simulation
docker-compose up

# Check server metrics file exists
ls -la results/server_metrics_*.json

# Verify content
cat results/server_metrics_*.json | jq '.per_connection'

# Verify sum matches tc observed
cat results/bottleneck_summary_*.json | jq '.per_connection_throughput'
```

### 9.3 Validation Criteria

| Check | Expected | Tolerance |
|-------|----------|-----------|
| Sum of receiver_throughput ≈ tc_observed | ~3.6 Mbps | ±10% |
| receiver_throughput ≤ offered_throughput | Always true | 0% |
| delivery_ratio for small flows | >80% | - |
| delivery_ratio for file transfer | <5% | - |

---

## 10. Docker Considerations

### 10.1 Volume Permissions

Ensure both containers can write to shared volume:

```yaml
services:
  quic-server:
    volumes:
      - ./results:/app/3_conn_code/output
    user: "${UID:-1000}:${GID:-1000}"  # Match host user
```

### 10.2 Timing Synchronization

Server must export metrics BEFORE clients container exits:

```
Timeline:
  t=0      Server starts
  t=0.5    Clients start
  t=30     Clients finish sending
  t=30.5   Server exports metrics  ← Must happen before orchestrator reads
  t=31     Clients container collects results
  t=32     All containers stop
```

**Solution:** Add small delay in clients before reading server metrics.

### 10.3 File Locking

Prevent partial reads:

```python
# Server-side: Write to temp file, then rename (atomic)
def export_server_metrics(self):
    temp_file = filepath.with_suffix(".tmp")
    with open(temp_file, "w") as f:
        json.dump(metrics, f, indent=2)
    temp_file.rename(filepath)  # Atomic on most filesystems
```

---

## 11. Risk Assessment

### 11.1 Identified Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Connection ID mismatch | Medium | High | Use deterministic ID assignment |
| File not found | Low | Medium | Add timeout/retry logic |
| Timing race condition | Medium | Medium | Server exports before shutdown |
| Docker volume permissions | Low | Low | Set proper user/group |

### 11.2 Fallback Strategy

If server metrics unavailable:
1. Log warning
2. Fall back to proportional estimation
3. Mark results as "estimated"

```python
if not self._load_server_metrics(simulation_id):
    print("Warning: Using estimated receiver throughput")
    self._use_estimated_throughput = True
```

---

## 12. Implementation Checklist (UPDATED)

### Phase 1: Server-Side Tracking (`server.py`)
- [ ] Add timing fields to `ServerProtocol.__init__`:
  - `first_data_time: Optional[float]`
  - `last_data_time: Optional[float]`
- [ ] Modify `quic_event_received` to track timing on `StreamDataReceived`
- [ ] Add `get_duration()` method
- [ ] Add `get_receiver_throughput_bps()` method
- [ ] Add `get_metrics()` method returning dict with all metrics
- [ ] Add `get_all_connection_metrics()` to `QuicServer`
- [ ] Add `export_server_metrics(output_dir)` to `QuicServer` with atomic write

### Phase 2: Metrics Export (`main.py` + `docker-compose.yml`)
- [ ] Modify `cmd_server()` to call `orchestrator.server.export_server_metrics("output")` after run
- [ ] Use fixed filename `server_metrics_latest.json` (not simulation_id based)
- [ ] Update `docker-compose.yml`: Add volume mount to server container:
  ```yaml
  server:
    volumes:
      - ./results:/app/3_conn_code/output
  ```

### Phase 3: Orchestrator Integration (`process_orchestrator.py`)
- [ ] Add `output_dir: str = "output"` parameter to `__init__`
- [ ] Add `server_metrics: Dict[int, Dict[str, Any]] = {}` attribute
- [ ] Implement `_load_server_metrics()` method with:
  - Fixed filename `server_metrics_latest.json`
  - 15-second timeout (server runs 10s longer than clients)
  - Retry loop with 0.5s interval
- [ ] Implement `_match_connections()` for bytes-based matching
- [ ] Integrate into `_build_results()` method

### Phase 4: Results Integration (`result.py`)
- [ ] Add `receiver_throughput_mbps` to `ConnectionResult.final_metrics`
- [ ] Add `receiver_bytes` to `ConnectionResult.final_metrics`
- [ ] Update `get_bottleneck_summary()` to include `receiver_throughput_mbps`
- [ ] Update `export_median_metrics_summary()` output
- [ ] Add `delivery_ratio_percent` field

### Phase 5: Client Wait Logic (`main.py`)
- [ ] In `cmd_clients()`, add wait loop for server metrics BEFORE exporting results
- [ ] Load and merge server metrics into result object

### Phase 6: Testing
- [ ] Unit test: `ServerProtocol` tracks bytes and timing correctly
- [ ] Unit test: `export_server_metrics()` creates valid JSON
- [ ] Unit test: `_load_server_metrics()` handles missing file gracefully
- [ ] Integration test: End-to-end Docker test
- [ ] Validate: sum(receiver_throughput) ≈ tc_observed (±10%)
- [ ] Validate: receiver_throughput ≤ offered_throughput for each connection

### Documentation
- [ ] Update `FINAL_THROUGHPUT_CALCULATION.md` with receiver-side approach
- [ ] Update `Receiver-side_throughput_measurement.md` if needed
- [ ] Add inline code comments explaining the matching algorithm

---

## Summary

This implementation plan provides a complete roadmap for adding receiver-side throughput measurement to the QUIC 3-connection simulation. The approach uses a shared Docker volume to transfer server-side metrics to the orchestrator, enabling accurate measurement of per-connection network throughput.

**Key Benefits:**
- Accurate per-connection throughput measurement
- Direct feedback for Q-learning optimization
- Minimal changes to existing architecture
- Works with Docker multi-container setup

**Estimated Effort:**
- Phase 1-2: Core implementation
- Phase 3-4: Integration
- Phase 5: Testing and validation
