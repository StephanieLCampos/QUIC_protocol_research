#!/bin/bash
#
# Open a bare privileged Linux container with the code mounted.
#
# Fallback for environments where run-bottleneck.sh cannot install packages
# (restrictive proxy, VPN, or offline). It performs no setup at all and simply
# drops into a shell, leaving the operator to install iproute2 and python3 by
# hand. Use run-bottleneck.sh in preference to this.

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
