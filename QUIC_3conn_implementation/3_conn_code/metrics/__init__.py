"""
Metrics Package - QUIC 3-Connection System
===========================================

This package provides comprehensive metrics collection, calculation, and export
functionality for the QUIC multi-connection simulation.

Overview
--------
The metrics system measures 6 key performance indicators:

1. **Throughput** (bytes/sec): Data transfer rate
2. **RTT** (seconds): Round-trip time from aioquic
3. **Latency** (seconds): Estimated one-way delay (RTT / 2)
4. **Jitter** (seconds): Variation in inter-packet timing
5. **Packet Loss Rate** (0.0-1.0): Fraction of packets lost
6. **Connection Establishment Time** (seconds): QUIC handshake duration

Architecture
------------
The metrics system has 4 layers:

    Raw Events → Collection → Calculation → Export
         ↓            ↓            ↓           ↓
    (packets,    (Collector)  (Calculator)  (Exporter)
     ACKs, RTT)

Module Contents
---------------
MetricsCollector : class
    Real-time data collection during simulation. Records packets sent,
    RTT samples, timestamps, etc. Used by each worker process.

MetricsCalculator : class
    Pure calculation functions for computing metrics from raw data.
    Stateless - just math.

MetricsResult : dataclass
    Container for the 6 calculated metrics. Returned by MetricsCalculator.

EpochManager : class
    Manages epoch-based metrics with settling time support. Handles
    parameter change events and groups metrics by stable periods.

Epoch : dataclass
    Represents one stable period with fixed parameters.

EpochMetrics : dataclass
    Aggregated metrics for an epoch (avg, min, max values).

ParameterSnapshot : dataclass
    Snapshot of all parameters at a point in time.

ConnectionEpochHistory : dataclass
    Complete epoch history for a single connection.

EpochConfig : dataclass
    Configuration for epoch management (settling time, sample interval).

MetricsExporter : class
    Additional export utilities (CSV format) for analysis tools.

Data Flow
---------
During simulation, metrics flow through the system like this:

    Worker Process:
    ┌─────────────────────────────────────────────────────────┐
    │  Synthesizer generates data                             │
    │       ↓                                                 │
    │  QUIC sends packets                                     │
    │       ↓                                                 │
    │  MetricsCollector.record_packet_sent()                  │
    │  MetricsCollector.record_rtt_sample()                   │
    │       ↓                                                 │
    │  EpochManager.collect_sample() (every 100ms)            │
    │       ↓                                                 │
    │  Send via IPC Queue to main process                     │
    └─────────────────────────────────────────────────────────┘
                            ↓
    Main Process:
    ┌─────────────────────────────────────────────────────────┐
    │  ProcessOrchestrator receives metrics                   │
    │       ↓                                                 │
    │  Stores in metrics_history                              │
    │       ↓                                                 │
    │  At end: exports to JSON/CSV                            │
    └─────────────────────────────────────────────────────────┘

Example Usage
-------------
    # Basic metrics collection
    from metrics import MetricsCollector

    collector = MetricsCollector()
    collector.connection = quic_connection  # aioquic connection
    collector.start()

    # During simulation
    collector.record_packet_sent(1200)
    collector.record_rtt_sample(0.025)

    # Get results
    result = collector.calculate_metrics()
    print(f"Throughput: {result.throughput / 1e6:.2f} Mbps")

    # Epoch-based metrics
    from metrics import EpochManager, ParameterSnapshot

    manager = EpochManager(
        connection_id=1,
        application_type="video_streaming",
        network_scenario="local",
        network_config={},
        initial_params=ParameterSnapshot(...),
    )
    manager.start()
    manager.collect_sample()  # Call every 100ms
    manager.finalize()

Connections
-----------
Imports from : .calculator, .collector, .epoch, .exporter
Imported by  : simulation.worker_process (collector and epoch),
               simulation.result (metric field names)

Note: MetricsExporter is re-exported here but has no active caller; the files a
run produces are written by simulation.result. See metrics/exporter.py.
"""

from .calculator import MetricsCalculator, MetricsResult
from .collector import MetricsCollector
from .epoch import (
    ParameterSnapshot,
    EpochMetrics,
    Epoch,
    ConnectionEpochHistory,
    EpochManager,
    EpochConfig,
)
from .exporter import MetricsExporter

__all__ = [
    # Core calculation
    "MetricsCalculator",
    "MetricsResult",
    # Real-time collection
    "MetricsCollector",
    # Epoch-based metrics
    "ParameterSnapshot",
    "EpochMetrics",
    "Epoch",
    "ConnectionEpochHistory",
    "EpochManager",
    "EpochConfig",
    # Export utilities
    "MetricsExporter",
]
