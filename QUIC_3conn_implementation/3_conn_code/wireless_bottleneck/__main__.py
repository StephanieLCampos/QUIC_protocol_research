"""
Make the wireless_bottleneck module executable as a CLI.

This allows running: python -m wireless_bottleneck
"""

from .cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
