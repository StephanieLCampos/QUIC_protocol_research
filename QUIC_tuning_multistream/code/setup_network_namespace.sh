#!/bin/bash
# Setup virtual network namespace for realistic bottleneck testing
# This creates a proper network interface where tc rules actually work

set -e

echo "Setting up virtual network namespace for bottleneck testing..."
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Error: This script must be run as root (it already is in Docker)"
fi

# Cleanup function
cleanup() {
    echo ""
    echo "Cleaning up network namespace..."
    ip netns del bottleneck_ns 2>/dev/null || true
    ip link del veth0 2>/dev/null || true
    echo "✓ Cleanup complete"
}

# Register cleanup on exit
trap cleanup EXIT

# Create network namespace
echo "1. Creating network namespace 'bottleneck_ns'..."
ip netns add bottleneck_ns

# Create veth pair (virtual ethernet)
echo "2. Creating virtual ethernet pair (veth0 <-> veth1)..."
ip link add veth0 type veth peer name veth1

# Move veth1 to namespace
echo "3. Moving veth1 to namespace..."
ip link set veth1 netns bottleneck_ns

# Configure veth0 (host side)
echo "4. Configuring veth0 (host side)..."
ip addr add 10.200.1.1/24 dev veth0
ip link set veth0 up

# Configure veth1 (namespace side)
echo "5. Configuring veth1 (namespace side)..."
ip netns exec bottleneck_ns ip addr add 10.200.1.2/24 dev veth1
ip netns exec bottleneck_ns ip link set veth1 up
ip netns exec bottleneck_ns ip link set lo up

# Test connectivity
echo "6. Testing connectivity..."
if ping -c 1 -W 1 10.200.1.2 >/dev/null 2>&1; then
    echo "✓ Connectivity test passed"
else
    echo "✗ Connectivity test failed"
    exit 1
fi

echo ""
echo "=========================================="
echo "✓ Network namespace setup complete!"
echo "=========================================="
echo ""
echo "Network configuration:"
echo "  Host interface:      veth0 (10.200.1.1)"
echo "  Namespace interface: veth1 (10.200.1.2)"
echo "  Namespace name:      bottleneck_ns"
echo ""
echo "To use the bottleneck on this interface:"
echo "  python3 setup_namespace_bottleneck.py"
echo ""
echo "To run commands in the namespace:"
echo "  ip netns exec bottleneck_ns <command>"
echo ""
echo "Press Ctrl+C to tear down the namespace..."
echo ""

# Keep the namespace alive
while true; do
    sleep 1
done
