"""
Simulation package for QUIC 3-Connection System.

Provides core simulation components including server, client,
worker processes, and orchestration.
"""

from .ipc_messages import MessageType, IPCMessage
from .server import QuicServer, ServerProtocol
from .client import QuicClient, ClientProtocol
from .worker_process import ConnectionWorker, worker_process_entry
from .process_orchestrator import ProcessOrchestrator
from .ml_controller import MLController
from .result import ConnectionResult, MultiConnectionResult

__all__ = [
    "MessageType",
    "IPCMessage",
    "QuicServer",
    "ServerProtocol",
    "QuicClient",
    "ClientProtocol",
    "ConnectionWorker",
    "worker_process_entry",
    "ProcessOrchestrator",
    "MLController",
    "ConnectionResult",
    "MultiConnectionResult",
]
