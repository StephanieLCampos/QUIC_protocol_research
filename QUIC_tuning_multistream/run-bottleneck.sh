#!/bin/bash
#
# Launch the wireless bottleneck module inside a Linux container.
#
# Purpose
#   tc exists only on Linux, so on macOS or Windows every bottleneck experiment
#   must run in a container. This wrapper starts one with the privileges tc
#   needs (--privileged for NET_ADMIN, --network host so shaping applies to
#   real interfaces) and mounts the code directory so edits on the host take
#   effect immediately without rebuilding.
#
# Usage
#   ./run-bottleneck.sh                        # interactive shell
#   ./run-bottleneck.sh list                   # list scenarios
#   ./run-bottleneck.sh validate               # run module validation
#   ./run-bottleneck.sh test --scenario lossy  # apply one scenario
#
# With no arguments an interactive shell is opened; with arguments they are
# passed through to `python3 -m wireless_bottleneck`.
#
# Note: this uses a stock ubuntu:22.04 image and installs iproute2 and python3
# on each start, rather than the project Dockerfile. Package installation is
# therefore the common failure point behind a proxy or VPN, and the script
# prints recovery guidance instead of exiting when it fails.

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo "Error: Docker is not running. Please start Docker Desktop."
    exit 1
fi

echo "Starting Linux container for wireless bottleneck..."
echo "Project directory: $PROJECT_DIR"
echo ""

# If no arguments, start interactive shell
if [ $# -eq 0 ]; then
    echo "Starting interactive shell (type 'exit' to quit)..."
    echo ""
    docker run -it --rm \
        --privileged \
        --network host \
        -v "${PROJECT_DIR}/code:/app/code" \
        -w /app/code \
        ubuntu:22.04 bash -c '
            # Unset proxy if set
            unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
            
            echo "Installing dependencies..."
            
            # Try normal repositories first
            if apt-get update 2>/dev/null && apt-get install -y iproute2 python3 2>/dev/null; then
                echo "✓ Dependencies installed successfully"
            else
                echo "⚠ Network issues detected. Trying alternative approach..."
                echo ""
                echo "This might be due to:"
                echo "  - VPN or proxy settings"
                echo "  - Docker Desktop network configuration"
                echo "  - Firewall blocking Docker"
                echo ""
                echo "Manual fix: Inside this container, run:"
                echo "  apt-get update && apt-get install -y iproute2 python3"
                echo ""
            fi
            
            echo ""
            echo "==================================="
            echo "Wireless Bottleneck - Docker Shell"
            echo "==================================="
            echo ""
            
            if command -v python3 >/dev/null 2>&1; then
                echo "Installed tools:"
                python3 --version
                command -v tc >/dev/null && tc -Version 2>&1 | head -1 || echo "tc: not installed"
                echo ""
                echo "Quick start commands:"
                echo "  python3 diagnose.py"
                echo "  python3 test_bottleneck_only.py"
                echo "  python3 -m wireless_bottleneck list"
            else
                echo "⚠ Python not installed due to network issues."
                echo ""
                echo "To install manually:"
                echo "  apt-get update && apt-get install -y iproute2 python3"
                echo ""
                echo "Or troubleshoot Docker network:"
                echo "  - Check Docker Desktop network settings"
                echo "  - Disable VPN temporarily"
                echo "  - Check firewall settings"
            fi
            
            echo ""
            exec bash
        '
else
    # Run with provided command
    COMMAND="$@"
    echo "Running: python3 -m wireless_bottleneck $COMMAND"
    echo ""
    docker run -it --rm \
        --privileged \
        --network host \
        -v "${PROJECT_DIR}/code:/app/code" \
        -w /app/code \
        ubuntu:22.04 bash -c "
            unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
            apt-get update -qq && apt-get install -y -qq iproute2 python3
            python3 -m wireless_bottleneck $COMMAND
        "
fi
