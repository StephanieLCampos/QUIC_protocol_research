"""
Debug utilities for controlling verbose output.

Uses QUIC_DEBUG environment variable to communicate debug mode
across process boundaries (main process -> worker processes).

Why an environment variable rather than a module flag
-----------------------------------------------------
This simulation runs each connection in a separate OS process. A module-level
boolean set in the parent would not be visible to a child spawned with the
"spawn" start method, since that child imports modules afresh rather than
inheriting parent memory. Environment variables *are* inherited across the
process boundary, so setting QUIC_DEBUG in the parent before workers start
propagates the setting to all of them.

Connections
-----------
Imports from : standard library only (os)
Imported by  : utils/__init__.py, main.py, simulation.worker_process
"""

import os

# Environment variable name for debug mode
DEBUG_ENV_VAR = "QUIC_DEBUG"


def is_debug_enabled() -> bool:
    """
    Report whether debug output is enabled.

    Read on every call rather than cached, so that a worker process started
    after the flag was set still observes it.
    """
    return os.environ.get(DEBUG_ENV_VAR, "").lower() in ("1", "true", "yes")


def set_debug_mode(enabled: bool) -> None:
    """Set debug mode via environment variable."""
    if enabled:
        os.environ[DEBUG_ENV_VAR] = "1"
    else:
        os.environ.pop(DEBUG_ENV_VAR, None)


def debug_print(*args, **kwargs) -> None:
    """Print only if debug mode is enabled."""
    if is_debug_enabled():
        print(*args, **kwargs)
