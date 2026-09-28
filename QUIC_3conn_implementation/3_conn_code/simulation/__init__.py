"""
Simulation package for QUIC 3-Connection System.

Provides core simulation components including server, client,
worker processes, and orchestration.

Architecture
------------
Three QUIC connections run concurrently against one shared server, each in its
own OS process:

    ProcessOrchestrator (main process)
        |-- QuicServer                    single shared endpoint
        |-- MLController                  optional Q-learning control loop
        |-- worker process 1  video streaming     \\
        |-- worker process 2  file transfer        > one aioquic per process
        \\-- worker process 3  conference call     /

Why separate processes: aioquic stores its congestion-control tuning in
module-level globals, so all connections inside one process are forced to share
one parameter set. Giving each connection its own process gives each its own
copy of those globals, which is what makes genuinely independent per-connection
tuning possible. This is the defining difference from the Generation 1 design.

Coordination between the processes uses:
    - a command pipe per worker  (orchestrator -> worker, parameter updates)
    - one shared metrics queue   (workers -> orchestrator, telemetry)
    - a start barrier            so all three begin competing simultaneously
    - an optional shared token bucket enforcing a common bandwidth budget

Connections
-----------
Imports from : .ipc_messages, .server, .client, .worker_process,
               .process_orchestrator, .ml_controller, .result
Imported by  : main.py, examples/run_3conn_through_bottleneck.py
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
