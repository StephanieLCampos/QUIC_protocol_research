# Dockerfile for QUIC 3-Connection System with Wireless Bottleneck
#
# This container provides a Linux environment with tc (traffic control)
# for simulating wireless network conditions on macOS/Windows hosts.
#
# Build:
#   docker build -t quic-3conn .
#
# Run (with browser UI on port 8000):
#   docker run -it --privileged -p 8000:8000 --rm quic-3conn
#
# Run (specific scenario):
#   docker run -it --privileged -p 8000:8000 --rm quic-3conn \
#       python -m main run --ui --scenario congested_low --duration 30
#
# Run (headless, no UI):
#   docker run -it --privileged --rm quic-3conn \
#       python -m main run --scenario congested_low --duration 30
#
# IMPORTANT: --privileged flag is REQUIRED for tc commands to work
# IMPORTANT: -p 8000:8000 is needed to access the browser UI from host

FROM python:3.12-slim-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Traffic Control (tc) for network emulation
    iproute2 \
    # For generating TLS certificates
    openssl \
    # Useful for debugging
    iputils-ping \
    net-tools \
    curl \
    # Clean up
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for Docker layer caching)
COPY 3_conn_code/pyproject.toml /app/3_conn_code/
COPY wireless_bottleneck/ /app/wireless_bottleneck/

# Install Python dependencies
# Note: We install in the 3_conn_code directory context
WORKDIR /app/3_conn_code

# Install uv for fast package management (optional, can use pip)
RUN pip install --no-cache-dir uv

# Create pyproject.toml if it doesn't exist with required dependencies
RUN if [ ! -f pyproject.toml ]; then \
    echo '[project]' > pyproject.toml && \
    echo 'name = "quic-3conn"' >> pyproject.toml && \
    echo 'version = "0.1.0"' >> pyproject.toml && \
    echo 'requires-python = ">=3.12"' >> pyproject.toml && \
    echo 'dependencies = [' >> pyproject.toml && \
    echo '    "aioquic>=1.0.0",' >> pyproject.toml && \
    echo '    "fastapi>=0.109.0",' >> pyproject.toml && \
    echo '    "uvicorn>=0.27.0",' >> pyproject.toml && \
    echo ']' >> pyproject.toml; \
    fi

# Install dependencies
RUN uv pip install --system aioquic fastapi uvicorn

# Expose port for browser UI
EXPOSE 8000

# Copy the rest of the application code
WORKDIR /app
COPY 3_conn_code/ /app/3_conn_code/

# Generate self-signed TLS certificates for QUIC
RUN mkdir -p /app/3_conn_code/certs && \
    openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout /app/3_conn_code/certs/key.pem \
    -out /app/3_conn_code/certs/cert.pem \
    -days 365 \
    -subj "/CN=localhost"

# Set working directory for running the application
WORKDIR /app/3_conn_code

# Add wireless_bottleneck to Python path
ENV PYTHONPATH="/app:${PYTHONPATH}"

# Create entrypoint script
RUN echo '#!/bin/bash' > /entrypoint.sh && \
    echo 'set -e' >> /entrypoint.sh && \
    echo '' >> /entrypoint.sh && \
    echo '# Verify tc is available' >> /entrypoint.sh && \
    echo 'if ! command -v tc &> /dev/null; then' >> /entrypoint.sh && \
    echo '    echo "ERROR: tc command not found. Install iproute2."' >> /entrypoint.sh && \
    echo '    exit 1' >> /entrypoint.sh && \
    echo 'fi' >> /entrypoint.sh && \
    echo '' >> /entrypoint.sh && \
    echo '# Check if running with --privileged' >> /entrypoint.sh && \
    echo 'if ! tc qdisc show dev lo &> /dev/null; then' >> /entrypoint.sh && \
    echo '    echo "WARNING: Cannot access tc. Run container with --privileged flag:"' >> /entrypoint.sh && \
    echo '    echo "  docker run -it --privileged quic-3conn"' >> /entrypoint.sh && \
    echo 'fi' >> /entrypoint.sh && \
    echo '' >> /entrypoint.sh && \
    echo '# Run the command' >> /entrypoint.sh && \
    echo 'exec "$@"' >> /entrypoint.sh && \
    chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

# Default command: run with UI
CMD ["python", "-m", "main", "run", "--ui"]
