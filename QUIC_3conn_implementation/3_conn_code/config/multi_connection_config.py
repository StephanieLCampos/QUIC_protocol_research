"""
Multi-Connection Configuration Module
======================================

Manages configuration for all 3 concurrent QUIC connections in the simulation.

This module provides the MultiConnectionConfig class, which serves as the
top-level configuration container for the entire simulation.

Architecture
------------
The configuration hierarchy looks like this:

    MultiConnectionConfig
    ├── Server settings (host, port)
    ├── Simulation settings (duration, metrics interval)
    ├── Shared start-only parameters (applied to all connections)
    └── Per-connection configs:
        ├── video_config (ConnectionConfig for connection 1)
        ├── file_config (ConnectionConfig for connection 2)
        └── conference_config (ConnectionConfig for connection 3)

Default Connection Settings
---------------------------
Each connection type has different default dynamic parameters optimized
for its traffic pattern:

**Video Streaming (Connection 1):**
    - Optimized for low latency
    - loss_reduction_factor=0.6 (quick recovery)
    - minimum_window=4 (maintain some throughput for smooth playback)

**File Transfer (Connection 2):**
    - Optimized for high throughput
    - loss_reduction_factor=0.7 (standard recovery)
    - cubic_c=0.5 (moderate aggressiveness)

**Conference Call (Connection 3):**
    - Optimized for low jitter (consistent latency)
    - loss_reduction_factor=0.5 (very quick recovery)
    - minimum_window=6 (never drop too low)
    - packet_threshold=2 (faster loss detection)
"""

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

from .connection_config import ConnectionConfig


@dataclass
class MultiConnectionConfig:
    """
    Configuration container for 3 concurrent QUIC connections.

    This is the main configuration class used throughout the simulation.
    It holds settings for the server, simulation parameters, and individual
    connection configurations.

    IMPORTANT: Start-only parameters are SHARED across all connections.
    Only dynamic parameters can differ between connections and be changed
    during the simulation.

    Attributes
    ----------
    server_host : str
        Hostname for the QUIC server. Default: "localhost".

    server_port : int
        Port number for the QUIC server. Default: 4433 (standard QUIC port).

    simulation_duration : float
        How long to run the simulation in seconds. Default: 30.0.

    metrics_interval : float
        How often to collect metrics in seconds. Default: 0.1 (100ms).

    shared_initial_cw : int
        Initial congestion window for all connections (bytes). Default: 12000.

    shared_max_ack_delay : float
        Max ACK delay for all connections (seconds). Default: 0.025.

    shared_max_data : int
        Connection-level flow control for all connections (bytes). Default: 1MB.

    shared_max_stream_data : int
        Stream-level flow control for all connections (bytes). Default: 1MB.

    video_config : ConnectionConfig
        Configuration for connection 1 (video streaming).

    file_config : ConnectionConfig
        Configuration for connection 2 (file transfer).

    conference_config : ConnectionConfig
        Configuration for connection 3 (conference call).

    Example
    -------
        # Create default configuration
        config = MultiConnectionConfig()

        # Customize simulation duration
        config = MultiConnectionConfig(simulation_duration=60.0)

        # Load from JSON file
        config = MultiConnectionConfig.from_json("config.json")

        # Save to JSON file
        config.to_json("config.json")
    """

    # -------------------------------------------------------------------------
    # Server Settings
    # -------------------------------------------------------------------------
    server_host: str = "localhost"
    server_port: int = 4433            # Default QUIC port

    # -------------------------------------------------------------------------
    # Simulation Settings
    # -------------------------------------------------------------------------
    simulation_duration: float = 30.0  # Duration in seconds
    metrics_interval: float = 0.1      # Collect metrics every 100ms

    # -------------------------------------------------------------------------
    # SHARED Start-Only Parameters (CONSTANT for all 3 connections)
    # These cannot be changed mid-simulation
    # -------------------------------------------------------------------------
    shared_initial_cw: int = 12000           # Initial cwnd (~10 packets)
    shared_max_ack_delay: float = 0.025      # 25ms max ACK delay
    shared_max_data: int = 1_048_576         # 1 MB connection flow control
    shared_max_stream_data: int = 1_048_576  # 1 MB stream flow control

    # -------------------------------------------------------------------------
    # Per-Connection Configurations
    # Each has different dynamic parameters optimized for its traffic type
    # -------------------------------------------------------------------------
    video_config: Optional[ConnectionConfig] = field(default=None)
    file_config: Optional[ConnectionConfig] = field(default=None)
    conference_config: Optional[ConnectionConfig] = field(default=None)

    def __post_init__(self):
        """
        Initialize connection configs with optimized default parameters.

        Called automatically after dataclass initialization.
        Creates ConnectionConfig instances for each connection type
        if not already provided, then applies shared start-only parameters.
        
        Also checks for USE_VETH_INTERFACE environment variable and switches
        to veth0 IP (192.168.100.1) if running in Docker with veth.
        """
        # Use veth0 IP instead of localhost when in Docker
        if os.environ.get("USE_VETH_INTERFACE"):
            self.server_host = "192.168.100.1"
            print(f"[Config] Using veth0 interface: server will bind to {self.server_host}")
        
        # Create video streaming config (Connection 1)
        # Optimized for LOW LATENCY
        if self.video_config is None:
            self.video_config = ConnectionConfig(
                connection_id=1,
                application_type="video_streaming",
                loss_reduction_factor=0.6,  # Quick recovery from loss
                cubic_c=0.4,                # Moderate cwnd growth
                minimum_window=4,           # Keep some throughput for smooth playback
            )

        # Create file transfer config (Connection 2)
        # Optimized for HIGH THROUGHPUT
        if self.file_config is None:
            self.file_config = ConnectionConfig(
                connection_id=2,
                application_type="file_transfer",
                loss_reduction_factor=0.7,  # Standard recovery
                cubic_c=0.5,                # Slightly aggressive growth
                minimum_window=2,           # Can drop low, will recover
            )

        # Create conference call config (Connection 3)
        # Optimized for LOW JITTER (consistent latency)
        if self.conference_config is None:
            self.conference_config = ConnectionConfig(
                connection_id=3,
                application_type="conference_call",
                loss_reduction_factor=0.5,  # Very quick recovery
                cubic_c=0.3,                # Conservative growth (avoid spikes)
                minimum_window=6,           # Never drop too low (audio quality)
                packet_threshold=2,         # Fast loss detection
                time_threshold=1.0,         # Aggressive time-based detection
            )

        # Apply shared start-only parameters to all configs
        self._apply_shared_start_params()

    def _apply_shared_start_params(self):
        """
        Apply shared start-only parameters to all connection configs.

        This ensures all 3 connections use the same initial QUIC settings,
        while allowing dynamic parameters to differ.
        """
        for config in self.get_all_configs():
            config.initial_cw = self.shared_initial_cw
            config.max_ack_delay = self.shared_max_ack_delay
            config.max_data = self.shared_max_data
            config.max_stream_data = self.shared_max_stream_data

    def get_all_configs(self) -> List[ConnectionConfig]:
        """
        Get list of all connection configurations.

        Returns
        -------
        list of ConnectionConfig
            All 3 connection configs in order: [video, file, conference].
        """
        return [self.video_config, self.file_config, self.conference_config]

    def get_config(self, connection_id: int) -> Optional[ConnectionConfig]:
        """
        Get configuration for a specific connection by ID.

        Parameters
        ----------
        connection_id : int
            Connection ID (1, 2, or 3).

        Returns
        -------
        ConnectionConfig or None
            The configuration for the specified connection, or None if invalid ID.
        """
        configs = {
            1: self.video_config,
            2: self.file_config,
            3: self.conference_config
        }
        return configs.get(connection_id)

    @classmethod
    def from_json(cls, path: str) -> "MultiConnectionConfig":
        """
        Load configuration from a JSON file.

        Parameters
        ----------
        path : str
            Path to the JSON configuration file.

        Returns
        -------
        MultiConnectionConfig
            New instance with values loaded from the file.

        Example
        -------
            config = MultiConnectionConfig.from_json("my_config.json")
        """
        with open(path) as f:
            data = json.load(f)

        # Convert nested connection config dictionaries to ConnectionConfig objects
        if "video_config" in data and isinstance(data["video_config"], dict):
            data["video_config"] = ConnectionConfig.from_dict(data["video_config"])
        if "file_config" in data and isinstance(data["file_config"], dict):
            data["file_config"] = ConnectionConfig.from_dict(data["file_config"])
        if "conference_config" in data and isinstance(data["conference_config"], dict):
            data["conference_config"] = ConnectionConfig.from_dict(data["conference_config"])

        return cls(**data)

    def to_json(self, path: str):
        """
        Save configuration to a JSON file.

        Parameters
        ----------
        path : str
            Path where the JSON file will be saved.

        Example
        -------
            config = MultiConnectionConfig()
            config.to_json("my_config.json")
        """
        data = {
            "server_host": self.server_host,
            "server_port": self.server_port,
            "simulation_duration": self.simulation_duration,
            "metrics_interval": self.metrics_interval,
            "shared_initial_cw": self.shared_initial_cw,
            "shared_max_ack_delay": self.shared_max_ack_delay,
            "shared_max_data": self.shared_max_data,
            "shared_max_stream_data": self.shared_max_stream_data,
            "video_config": self.video_config.to_dict() if self.video_config else None,
            "file_config": self.file_config.to_dict() if self.file_config else None,
            "conference_config": self.conference_config.to_dict() if self.conference_config else None,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
