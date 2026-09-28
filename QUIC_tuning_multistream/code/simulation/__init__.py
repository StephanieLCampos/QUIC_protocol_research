"""
Simulation package for the QUIC Multi-Stream Research Project.

Provides the QUIC endpoints and the orchestration around a single measured run:

    SimulationRunner  starts a server, connects a client, drives one workload
                      to completion and returns the collected metrics
    QuicClient        sends synthesizer output over QUIC streams
    QuicServer        receives and drains that traffic

Connections:
    Imports from: .runner, .client, .server
    Imported by:  grid_search.executor, examples/, the test_* diagnostic scripts
"""

from .runner import SimulationRunner, SimulationResult
from .client import QuicClient
from .server import QuicServer

__all__ = [
    "SimulationRunner",
    "SimulationResult",
    "QuicClient",
    "QuicServer",
]
