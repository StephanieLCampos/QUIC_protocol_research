"""
Web UI package for QUIC 3-Connection Dashboard.

Provides a browser-based interface for real-time monitoring and control.

Two servers live here, serving different purposes:

    server.py          FastAPI dashboard on :8000. Streams live metrics over
                       WebSocket and accepts parameter and network changes.
    control_server.py  Minimal HTTP endpoint on :9001, internal to the Docker
                       network, used to relay bottleneck changes between the
                       clients and server containers.

Connections
-----------
Imports from : .server
Imported by  : main.py (lazily, only when --ui is requested, so that the
               FastAPI dependency is not required for headless runs)
"""

from .server import create_app, run_server, ConnectionManager

__all__ = ["create_app", "run_server", "ConnectionManager"]
