"""
Package entry point enabling `python -m wireless_bottleneck`.

Delegates directly to the CLI's main() and propagates its exit code, so the
module can be invoked as a command without a separate console script.

Connections:
    Imports from: .cli (main)
    Invoked by:   `python -m wireless_bottleneck <command>`
"""

from .cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
