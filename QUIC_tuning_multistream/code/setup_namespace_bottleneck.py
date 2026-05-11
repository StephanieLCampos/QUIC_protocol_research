"""
Setup and test wireless bottleneck on virtual network interface.

This script creates a bottleneck on a veth interface where tc rules
actually work (unlike loopback).

Usage:
    # First, set up the network namespace (in another terminal):
    bash setup_network_namespace.sh
    
    # Then run this script:
    python3 setup_namespace_bottleneck.py
"""

import sys
import subprocess
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from wireless_bottleneck import WirelessBottleneck, get_scenario
from simulation.runner import SimulationRunner


def check_namespace_exists():
    """Check if the network namespace is set up."""
    try:
        result = subprocess.run(
            ["ip", "netns", "list"],
            capture_output=True,
            text=True,
            check=True
        )
        return "bottleneck_ns" in result.stdout
    except:
        return False


def check_veth_exists():
    """Check if veth0 interface exists."""
    try:
        result = subprocess.run(
            ["ip", "link", "show", "veth0"],
            capture_output=True,
            text=True,
            check=True
        )
        return "veth0" in result.stdout
    except:
        return False


async def test_with_bottleneck():
    """Run QUIC simulation with bottleneck on veth interface."""
    
    # Choose scenario
    scenario = get_scenario("congested_low")
    
    print("=" * 70)
    print("Testing Bottleneck on Virtual Network Interface")
    print("=" * 70)
    print()
    print(f"Scenario: {scenario.name}")
    print(f"Description: {scenario.description}")
    print()
    print("Configuration:")
    print(f"  Capacity: {scenario.config.capacity_bps / 1_000_000:.1f} Mbps")
    print(f"  RTT: {scenario.config.propagation_delay * 2000:.1f} ms")
    print(f"  Loss: {scenario.config.loss_rate * 100:.1f}%")
    print(f"  Interface: veth0 (virtual ethernet)")
    print()
    
    # Set up bottleneck on veth0
    with WirelessBottleneck(scenario.config, interface="veth0") as bottleneck:
        print("Bottleneck active on veth0")
        print()
        
        # Get tc stats to show it's actually configured
        stats = bottleneck.get_current_stats()
        if stats.get("raw_output"):
            print("TC Configuration:")
            print(stats["raw_output"])
            print()
        
        # Run QUIC simulation
        print("Running QUIC simulation...")
        runner = SimulationRunner(
            application_type="file_transfer",
            initial_cw=12000,
            max_ack_delay=0.025,
            loss_reduction_factor=0.5,
        )
        
        result = await runner.run()
        
        # Show results
        print()
        print("=" * 70)
        print("RESULTS")
        print("=" * 70)
        print()
        
        if result.success:
            print("✓ QUIC Simulation Results:")
            print(f"  Throughput: {result.metrics.throughput / 1_000_000:.2f} Mbps")
            print(f"  RTT: {result.metrics.rtt * 1000:.2f} ms")
            print(f"  Loss: {result.metrics.packet_loss_rate * 100:.2f}%")
            print(f"  Goodput: {result.metrics.goodput / 1_000_000:.2f} Mbps")
            print()
            
            # Compare to expected values
            expected_throughput = scenario.config.capacity_bps / 1_000_000
            print(f"Expected vs Actual:")
            print(f"  Throughput: {expected_throughput:.1f} Mbps (expected) vs "
                  f"{result.metrics.throughput / 1_000_000:.2f} Mbps (actual)")
            print(f"  RTT: {scenario.config.propagation_delay * 2000:.1f} ms (expected) vs "
                  f"{result.metrics.rtt * 1000:.2f} ms (actual)")
            print(f"  Loss: {scenario.config.loss_rate * 100:.1f}% (expected) vs "
                  f"{result.metrics.packet_loss_rate * 100:.2f}% (actual)")
        else:
            print(f"✗ Simulation failed: {result.error}")
            return 1
        
        # Show bottleneck metrics
        metrics = bottleneck.get_metrics()
        summary = metrics.summary()
        
        print()
        print("✓ Bottleneck Metrics:")
        print(f"  Packets arrived: {summary['total_packets']['arrived']}")
        print(f"  Packets dropped: {summary['total_packets']['dropped']}")
        print(f"  Loss rate: {summary['total_packets']['loss_rate'] * 100:.2f}%")
        print(f"  Avg queue: {summary['queue']['avg_occupancy_packets']:.1f} packets")
        print(f"  Max queue: {summary['queue']['max_occupancy_packets']} packets")
        
        if summary['queue']['avg_delay_ms'] > 0:
            print(f"  Avg queue delay: {summary['queue']['avg_delay_ms']:.2f} ms")
    
    print()
    print("=" * 70)
    print("✓ Test complete!")
    print("=" * 70)
    return 0


def main():
    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  Virtual Network Interface Bottleneck Test                        ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    
    # Check prerequisites
    print("Checking prerequisites...")
    print()
    
    if not check_namespace_exists():
        print("✗ Network namespace 'bottleneck_ns' not found")
        print()
        print("Please set up the network namespace first:")
        print("  bash setup_network_namespace.sh")
        print()
        print("Run that in a separate terminal/tmux pane and leave it running.")
        return 1
    
    print("✓ Network namespace exists")
    
    if not check_veth_exists():
        print("✗ veth0 interface not found")
        print()
        print("The network namespace might not be properly configured.")
        print("Try running: bash setup_network_namespace.sh")
        return 1
    
    print("✓ veth0 interface exists")
    print()
    
    # Run the test
    try:
        return asyncio.run(test_with_bottleneck())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
