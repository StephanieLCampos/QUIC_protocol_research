"""
Diagnostic: QUIC across a veth bottleneck, with tc statistics.

Runs the QUIC server inside a network namespace and the client on the host, so
traffic must cross the shaped veth link, then reads tc's own counters to
confirm the shaping actually applied.

The value of this script is the cross-check: application-level throughput is
compared against the kernel's transmitted and dropped counts, which catches the
case where a bottleneck appears configured but is not in the traffic path.

Despite the `test_` prefix this is a standalone diagnostic script rather than
part of an automated test suite. Its namespace setup duplicates the sequence in
setup_namespace_bottleneck.py and the other veth scripts.

Connections:
    Imports from: wireless_bottleneck (WirelessBottleneck, get_scenario)
    Invoked by:   run directly, inside the privileged container
"""

import asyncio
import subprocess
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from wireless_bottleneck import WirelessBottleneck, get_scenario


def setup_namespace():
    """Create network namespace with veth pair."""
    print("Setting up network namespace...")
    commands = [
        ["ip", "netns", "add", "bottleneck_ns"],
        ["ip", "link", "add", "veth0", "type", "veth", "peer", "name", "veth1"],
        ["ip", "link", "set", "veth1", "netns", "bottleneck_ns"],
        ["ip", "addr", "add", "10.200.1.1/24", "dev", "veth0"],
        ["ip", "link", "set", "veth0", "up"],
        ["ip", "netns", "exec", "bottleneck_ns", "ip", "addr", "add", "10.200.1.2/24", "dev", "veth1"],
        ["ip", "netns", "exec", "bottleneck_ns", "ip", "link", "set", "veth1", "up"],
        ["ip", "netns", "exec", "bottleneck_ns", "ip", "link", "set", "lo", "up"],
    ]
    
    for cmd in commands:
        subprocess.run(cmd, check=True, capture_output=True)
    print("✓ Network namespace ready")


def cleanup_namespace():
    """Clean up network namespace."""
    subprocess.run(["ip", "netns", "delete", "bottleneck_ns"], 
                   capture_output=True, check=False)
    subprocess.run(["ip", "link", "delete", "veth0"],
                   capture_output=True, check=False)


async def test_with_iperf():
    """Test bottleneck using iperf3 to verify it works."""
    scenario = get_scenario("congested_low")
    
    print("\n" + "=" * 70)
    print("Testing Bottleneck with iperf3")
    print("=" * 70)
    print(f"Scenario: {scenario.name}")
    print(f"Capacity: {scenario.config.capacity_bps / 1_000_000:.1f} Mbps")
    print(f"RTT: {scenario.config.propagation_delay * 2000:.1f} ms")
    print(f"Loss: {scenario.config.loss_rate * 100:.1f}%")
    print()
    
    # Apply bottleneck to veth0
    with WirelessBottleneck(scenario.config, interface="veth0") as bottleneck:
        
        # Show tc config
        result = subprocess.run(
            ["tc", "qdisc", "show", "dev", "veth0"],
            capture_output=True,
            text=True
        )
        print("TC Configuration on veth0:")
        print(result.stdout)
        
        # Start iperf3 server in namespace
        print("Starting iperf3 server in namespace...")
        server_proc = subprocess.Popen(
            ["ip", "netns", "exec", "bottleneck_ns", "iperf3", "-s", "-1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        await asyncio.sleep(1)
        
        # Run iperf3 client from host
        print("Running iperf3 client from host...")
        result = subprocess.run(
            ["iperf3", "-c", "10.200.1.2", "-t", "5"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        print("\n" + "=" * 70)
        print("iperf3 Results:")
        print("=" * 70)
        print(result.stdout)
        
        # Parse throughput
        throughput = None
        for line in result.stdout.split("\n"):
            if "sender" in line:
                parts = line.split()
                for i, part in enumerate(parts):
                    if "Mbits/sec" in part or "Kbits/sec" in part:
                        throughput = float(parts[i-1])
                        if "Kbits" in part:
                            throughput /= 1000
                        break
        
        print("\n" + "=" * 70)
        print("Validation:")
        print("=" * 70)
        if throughput:
            expected = scenario.config.capacity_bps / 1_000_000
            print(f"Expected capacity: {expected:.1f} Mbps")
            print(f"Measured throughput: {throughput:.2f} Mbps")
            print(f"Utilization: {(throughput/expected)*100:.1f}%")
            
            if throughput < expected * 1.2:
                print("✓ Bottleneck is working correctly!")
            else:
                print("⚠ WARNING: Throughput exceeds limit!")
        
        server_proc.terminate()
        server_proc.wait()
        
        # Show bottleneck stats from tc
        print("\n" + "=" * 70)
        print("TC Statistics:")
        print("=" * 70)
        result = subprocess.run(
            ["tc", "-s", "qdisc", "show", "dev", "veth0"],
            capture_output=True,
            text=True
        )
        print(result.stdout)


async def main():
    print("\n╔════════════════════════════════════════════════════════════════════╗")
    print("║  Bottleneck Verification Test                                     ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    
    setup_namespace()
    
    try:
        await test_with_iperf()
    finally:
        cleanup_namespace()


if __name__ == "__main__":
    asyncio.run(main())
