#!/bin/bash
# Run wireless bottleneck without needing to install packages
# Uses a manual workaround for Docker network issues

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Starting container (manual setup required)..."
echo ""

docker run -it --rm \
    --privileged \
    -v "${PROJECT_DIR}/code:/app/code" \
    -w /app/code \
    ubuntu:22.04 bash

echo ""
echo "Container exited."
