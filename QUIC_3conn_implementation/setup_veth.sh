#!/bin/bash
# Setup veth pair for wireless bottleneck simulation
#
# This script creates a virtual ethernet pair (veth0 <-> veth1)
# that allows tc (traffic control) to properly limit bandwidth.
# The loopback interface (lo) does not support full tc capabilities.

set -e

echo "Setting up veth pair for bottleneck simulation..."

# Check if running with sufficient privileges
if ! ip link show &> /dev/null; then
    echo "ERROR: Need elevated privileges. Run container with --privileged flag."
    exit 1
fi

# Remove existing veth pair if it exists
ip link del veth0 2>/dev/null || true

# Create veth pair
ip link add veth0 type veth peer name veth1

# Bring up both interfaces
ip link set veth0 up
ip link set veth1 up

# Assign IP addresses
# veth0: 192.168.100.1 (server will bind here, bottleneck applied here)
# veth1: 192.168.100.2 (clients will use this as source)
ip addr add 192.168.100.1/24 dev veth0
ip addr add 192.168.100.2/24 dev veth1

# Add routing rule: traffic to 192.168.100.1 should go through veth1 -> veth0
# This ensures traffic actually crosses the veth pair where bottleneck is applied
ip rule add from 192.168.100.2 table 100 2>/dev/null || true
ip route add default via 192.168.100.1 dev veth1 table 100 2>/dev/null || true

# Make veth1 the preferred interface for outbound connections
# This way clients source from 192.168.100.2 and target 192.168.100.1
ip route add 192.168.100.1 via 192.168.100.2 dev veth1 2>/dev/null || true

echo "veth pair configured:"
echo "  veth0: 192.168.100.1 (server endpoint, bottleneck applied)"
echo "  veth1: 192.168.100.2 (client endpoint)"
echo ""
echo "Traffic will flow: client (veth1:192.168.100.2) -> (veth0:192.168.100.1) server"
echo "Bottleneck tc rules will be applied on veth0"
