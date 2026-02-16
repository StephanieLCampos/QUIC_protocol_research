"""
Test wireless bottleneck on veth interface inside Docker container.

This script should be run inside the Docker container where network
namespaces can be properly created and managed.

Usage:
    docker run -it --rm --cap-add=NET_ADMIN -v $(pwd):/workspace quic-wireless \\
        bash -c "cd /workspace/code && python3 test_veth_bottleneck.py"
"""

import sys
import subprocess
import asyncio
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from wireless_bottleneck import WirelessBottleneck, get_scenario
from simulation.runner import SimulationRunner


def setup_veth_pair():
    """Create veth pair inside the container."""
    print("Setting up veth pair...")
    
    commands = [
        # Create network namespace
        ["ip", "netns", "add", "bottleneck_ns"],
        
        # Create veth pair
        ["ip", "link", "add", "veth0", "type", "veth", "peer", "name", "veth1"],
        
        # Move veth1 to namespace
        ["ip", "link", "set", "veth1", "netns", "bottleneck_ns"],
        
        # Configure veth0 (host side)
        ["ip", "addr", "add", "10.200.1.1/24", "dev", "veth0"],
        ["ip", "link", "set", "veth0", "up"],
        
        # Configure veth1 (namespace side)
        ["ip", "netns", "exec", "bottleneck_ns", "ip", "addr", "add", "10.200.1.2/24", "dev", "veth1"],
        ["ip", "netns", "exec", "bottleneck_ns", "ip", "link", "set", "veth1", "up"],
        ["ip", "netns", "exec", "bottleneck_ns", "ip", "link", "set", "lo", "up"],
    ]
    
    try:
        for cmd in commands:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✓ veth pair created: veth0 (10.200.1.1) <-> veth1 (10.200.1.2)")
        
        # Test connectivity
        result = subprocess.run(
            ["ping", "-c", "2", "-W", "1", "10.200.1.2"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("✓ Connectivity test passed")
            return True
        else:
            print("✗ Connectivity test failed")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to set up veth pair: {e}")
        print(f"  stdout: {e.stdout}")
        print(f"  stderr: {e.stderr}")
        return False


def cleanup_veth_pair():
    """Clean up veth pair and namespace."""
    print("\nCleaning up...")
    try:
        subprocess.run(["ip", "netns", "delete", "bottleneck_ns"], 
                      capture_output=True, check=False)
        subprocess.run(["ip", "link", "delete", "veth0"], 
                      capture_output=True, check=False)
        print("✓ Cleanup complete")
    except:
        pass


async def test_with_bottleneck():
    """Run QUIC simulation with bottleneck on veth interface."""
    
    # Use varying scenario for interesting dynamics
    scenario = get_scenario("varying")
    
    print("\n" + "=" * 70)
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
        print("✓ Bottleneck active on veth0")
        print()
        
        # Get tc stats to show it's actually configured
        stats = bottleneck.get_current_stats()
        if stats.get("raw_output"):
            print("TC Configuration:")
            for line in stats["raw_output"].split("\n")[:10]:  # First 10 lines
                if line.strip():
                    print(f"  {line}")
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
            print(f"  Jitter: {result.metrics.jitter * 1000:.2f} ms")
            print()
            
            # Compare to expected values
            expected_throughput = scenario.config.capacity_bps / 1_000_000
            throughput_ratio = result.metrics.throughput / scenario.config.capacity_bps
            
            print(f"Expected vs Actual:")
            print(f"  Throughput: {expected_throughput:.1f} Mbps (expected) vs "
                  f"{result.metrics.throughput / 1_000_000:.2f} Mbps (actual)")
            print(f"  RTT: {scenario.config.propagation_delay * 2000:.1f} ms (expected) vs "
                  f"{result.metrics.rtt * 1000:.2f} ms (actual)")
            print(f"  Loss: {scenario.config.loss_rate * 100:.1f}% (expected) vs "
                  f"{result.metrics.packet_loss_rate * 100:.2f}% (actual)")
            print()
            
            # Validation
            if throughput_ratio > 0.9:
                print("⚠ WARNING: Throughput > 90% of limit - bottleneck may not be working!")
            else:
                print("✓ Bottleneck constraints appear to be working")
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
    
    # Set up veth pair
    if not setup_veth_pair():
        print("\n✗ Failed to set up network namespace")
        return 1
    
    try:
        # Run the test
        return asyncio.run(test_with_bottleneck())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        cleanup_veth_pair()


if __name__ == "__main__":
    sys.exit(main())
