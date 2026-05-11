"""
Web UI package for QUIC 3-Connection Dashboard.

Provides a browser-based interface for real-time monitoring and control.
"""

from .server import create_app, run_server, ConnectionManager

__all__ = ["create_app", "run_server", "ConnectionManager"]
