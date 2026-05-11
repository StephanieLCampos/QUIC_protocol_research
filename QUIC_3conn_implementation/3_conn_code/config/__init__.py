"""
Config Package - QUIC 3-Connection System
==========================================

This package manages configuration for the QUIC multi-connection simulation.

Overview
--------
The simulation runs 3 concurrent QUIC connections, each with different traffic patterns:
    - Connection 1: Video Streaming (prioritizes low latency)
    - Connection 2: File Transfer (prioritizes high throughput)
    - Connection 3: Conference Call (prioritizes low jitter)

Module Contents
---------------
ConnectionConfig : dataclass
    Configuration for a single QUIC connection, including both static
    and dynamic (tunable) parameters.

MultiConnectionConfig : dataclass
    Container for all 3 connection configurations plus simulation settings.

DYNAMIC_PARAMETERS : list
    Names of parameters that can be changed mid-simulation via the UI.
    These affect CUBIC congestion control behavior.

START_ONLY_PARAMETERS : list
    Names of parameters that are set once at startup and cannot change.

Example Usage
-------------
    from config import MultiConnectionConfig, ConnectionConfig

    # Create default configuration
    config = MultiConnectionConfig()

    # Access individual connection configs
    video = config.video_config
    print(f"Video cubic_c: {video.cubic_c}")

    # Load from JSON file
    config = MultiConnectionConfig.from_json("my_config.json")
"""

from .connection_config import ConnectionConfig, DYNAMIC_PARAMETERS, START_ONLY_PARAMETERS
from .multi_connection_config import MultiConnectionConfig

__all__ = [
    "ConnectionConfig",
    "MultiConnectionConfig",
    "DYNAMIC_PARAMETERS",
    "START_ONLY_PARAMETERS",
]
