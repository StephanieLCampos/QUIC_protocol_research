"""
Connection Configuration Module
===============================

Defines the configuration structure for a single QUIC connection.

This module contains:
    - ConnectionConfig: Dataclass holding all parameters for one connection
    - DYNAMIC_PARAMETERS: List of parameters that can be tuned mid-simulation
    - START_ONLY_PARAMETERS: List of parameters fixed at simulation start

Parameter Categories
--------------------
There are two categories of parameters:

1. **Dynamic Parameters** (can be changed via UI during simulation):
   These affect the CUBIC congestion control algorithm behavior.

2. **Start-Only Parameters** (fixed at simulation start):
   These affect QUIC protocol settings and cannot be changed mid-connection.

How Parameters Affect Performance
---------------------------------
Dynamic parameters are tuned per-connection to optimize for different goals:

- **loss_reduction_factor** (0.1-0.9):
    How much to reduce cwnd on packet loss. Lower = more aggressive reduction.
    Video/Conference prefer lower values (faster recovery).

- **cubic_c** (0.1-1.0):
    CUBIC's aggressiveness constant. Higher = faster cwnd growth.
    File transfer prefers higher values (maximize throughput).

- **minimum_window** (1-10):
    Minimum congestion window in packets. Higher = never go below this.
    Conference calls prefer higher values (maintain minimum quality).

- **packet_threshold** (1-5):
    Number of duplicate ACKs before fast retransmit.
    Lower = faster loss detection but more false positives.

- **time_threshold** (1.0-2.0):
    RTT multiplier for time-based loss detection.
    Lower = faster detection but more aggressive.

- **cubic_max_idle_time** (0.5-5.0):
    Seconds of idle before resetting cwnd.
    Real-time traffic (video/conference) prefers lower values.
"""

from dataclasses import dataclass
from typing import Dict, Any


# =============================================================================
# PARAMETER DEFINITIONS
# =============================================================================

# Parameters that can be changed mid-connection via the UI
# Each connection has its own isolated copy of these parameters
DYNAMIC_PARAMETERS = [
    "loss_reduction_factor",  # cwnd reduction on loss (0.1-0.9)
    "cubic_c",                # CUBIC aggressiveness (0.1-1.0)
    "minimum_window",         # Min cwnd in packets (1-10)
    "packet_threshold",       # Dup ACKs for fast retransmit (1-5)
    "time_threshold",         # RTT multiplier for loss (1.0-2.0)
    "cubic_max_idle_time",    # Idle timeout before cwnd reset (0.5-5.0)
]

# Parameters that are set once at simulation start
# These are SHARED across all 3 connections and cannot be changed mid-run
START_ONLY_PARAMETERS = [
    "initial_cw",       # Initial congestion window (bytes)
    "max_ack_delay",    # Maximum ACK delay (seconds)
    "max_data",         # Connection-level flow control (bytes)
    "max_stream_data",  # Stream-level flow control (bytes)
]


# =============================================================================
# CONNECTION CONFIGURATION DATACLASS
# =============================================================================

@dataclass
class ConnectionConfig:
    """
    Configuration for a single QUIC connection.

    Each of the 3 connections (video, file transfer, conference) has its own
    ConnectionConfig instance. Start-only parameters are shared across all
    connections, while dynamic parameters can differ and be tuned individually.

    Attributes
    ----------
    connection_id : int
        Unique identifier (1, 2, or 3) for this connection.

    application_type : str
        Type of traffic: "video_streaming", "file_transfer", or "conference_call".

    initial_cw : int
        Initial congestion window in bytes. Default: 12000 (~10 packets).

    max_ack_delay : float
        Maximum time (seconds) receiver waits before sending ACK. Default: 0.025.

    max_data : int
        Connection-level flow control limit in bytes. Default: 1MB.

    max_stream_data : int
        Per-stream flow control limit in bytes. Default: 1MB.

    max_datagram_size : int
        Maximum UDP datagram size in bytes. Default: 1200 (safe for most networks).

    loss_reduction_factor : float
        Multiplier for cwnd on packet loss (0.1-0.9). Default: 0.7.
        Lower values = more aggressive reduction, faster recovery.

    cubic_c : float
        CUBIC algorithm aggressiveness constant (0.1-1.0). Default: 0.4.
        Higher values = faster cwnd growth after loss.

    minimum_window : int
        Minimum congestion window in packets (1-10). Default: 2.
        Floor for cwnd, prevents complete stalls.

    packet_threshold : int
        Duplicate ACKs needed to trigger fast retransmit (1-5). Default: 3.

    time_threshold : float
        RTT multiplier for time-based loss detection (1.0-2.0). Default: 1.125.

    cubic_max_idle_time : float
        Seconds of idle before resetting cwnd (0.5-5.0). Default: 2.0.

    Example
    -------
        # Create a video streaming config optimized for low latency
        video_config = ConnectionConfig(
            connection_id=1,
            application_type="video_streaming",
            loss_reduction_factor=0.6,  # Quick recovery
            cubic_c=0.4,                # Moderate growth
            minimum_window=4,           # Maintain some throughput
        )
    """

    # -------------------------------------------------------------------------
    # Connection Identity
    # -------------------------------------------------------------------------
    connection_id: int                    # 1, 2, or 3
    application_type: str                 # "video_streaming", "file_transfer", "conference_call"

    # -------------------------------------------------------------------------
    # Start-Only Parameters (CONSTANT - same for all 3 connections)
    # -------------------------------------------------------------------------
    initial_cw: int = 12000               # Initial congestion window (bytes)
    max_ack_delay: float = 0.025          # Max ACK delay (25ms)
    max_data: int = 1_048_576             # Connection flow control (1 MB)
    max_stream_data: int = 1_048_576      # Stream flow control (1 MB)
    max_datagram_size: int = 1200         # Max UDP datagram size (bytes)

    # -------------------------------------------------------------------------
    # Dynamic Parameters (can be tuned per-connection via UI)
    # -------------------------------------------------------------------------
    loss_reduction_factor: float = 0.3    # cwnd *= this on loss
    cubic_c: float = 0.2                  # CUBIC aggressiveness
    minimum_window: int = 2               # Min cwnd (packets)
    packet_threshold: int = 2             # Dup ACKs for fast retransmit
    time_threshold: float = 1.125         # RTT multiplier for loss detection
    cubic_max_idle_time: float = 2.0      # Idle timeout before cwnd reset (sec)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary for IPC serialization.

        Used when passing config to worker processes via multiprocessing.

        Returns
        -------
        dict
            All configuration values as a dictionary.
        """
        return {
            "connection_id": self.connection_id,
            "application_type": self.application_type,
            "initial_cw": self.initial_cw,
            "max_ack_delay": self.max_ack_delay,
            "max_data": self.max_data,
            "max_stream_data": self.max_stream_data,
            "max_datagram_size": self.max_datagram_size,
            "loss_reduction_factor": self.loss_reduction_factor,
            "cubic_c": self.cubic_c,
            "minimum_window": self.minimum_window,
            "packet_threshold": self.packet_threshold,
            "time_threshold": self.time_threshold,
            "cubic_max_idle_time": self.cubic_max_idle_time,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConnectionConfig":
        """
        Create ConnectionConfig from dictionary.

        Used when deserializing config received via IPC or loaded from JSON.

        Parameters
        ----------
        data : dict
            Dictionary containing configuration values.

        Returns
        -------
        ConnectionConfig
            New instance with values from dictionary.
        """
        return cls(**data)
