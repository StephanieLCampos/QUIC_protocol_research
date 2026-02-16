FROM ubuntu:22.04

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    iproute2 \
    iputils-ping \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip3 install --no-cache-dir \
    aioquic>=1.0.0 \
    cryptography>=41.0.0 \
    pandas>=2.0.0

# Set working directory
WORKDIR /app/code

# Default command
CMD ["/bin/bash"]
