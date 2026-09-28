# Container image for the QUIC Multi-Stream Research Project (Generation 1).
#
# Provides a Linux environment in which tc (Traffic Control) is available and
# usable, which is what the wireless bottleneck emulation requires. On macOS
# and Windows this image is the only way to run shaped experiments at all.
#
# Contents:
#   iproute2       supplies the `tc` command that performs the actual shaping
#   iputils-ping   used by the namespace setup script's connectivity check
#   aioquic        the QUIC implementation under study
#   pandas         results analysis
#
# Run privileged (or with NET_ADMIN) so that tc may modify qdiscs; without
# those capabilities the container starts but every shaping command fails.
#
# Build:  docker build -t quic-wireless .
# Run:    docker run -it --rm --privileged -v "$(pwd):/app" quic-wireless

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
