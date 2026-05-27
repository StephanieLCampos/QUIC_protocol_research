"""
Debug utilities for controlling verbose output.

Uses QUIC_DEBUG environment variable to communicate debug mode
across process boundaries (main process -> worker processes).
"""

import os

# Environment variable name for debug mode
DEBUG_ENV_VAR = "QUIC_DEBUG"


def is_debug_enabled() -> bool:
    """Check if debug mode is enabled via environment variable."""
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
