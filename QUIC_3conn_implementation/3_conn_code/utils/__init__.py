"""
Utility modules for the 3-connection QUIC simulation.

Connections
-----------
Imports from : .debug
Imported by  : main.py, and worker processes via utils.debug
"""

from .debug import is_debug_enabled, debug_print, set_debug_mode

__all__ = ["is_debug_enabled", "debug_print", "set_debug_mode"]
