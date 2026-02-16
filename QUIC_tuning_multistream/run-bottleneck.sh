#!/bin/bash
# Helper script to run wireless bottleneck module in Docker on macOS
#
# Usage:
#   ./run-bottleneck.sh                    # Interactive shell
#   ./run-bottleneck.sh list               # List scenarios
#   ./run-bottleneck.sh validate           # Run validation
#   ./run-bottleneck.sh test --scenario lossy  # Test a scenario

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
