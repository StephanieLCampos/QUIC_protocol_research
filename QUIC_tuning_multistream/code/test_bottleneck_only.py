"""
Diagnostic: bottleneck module in isolation, without QUIC.

Exercises setup, teardown, scenario loading and metrics collection with no
QUIC traffic involved, so that a failure can be attributed to the tc layer
rather than to the protocol stack.

This is the check to run after `diagnose.py` and before any QUIC example: if
these tests pass but a QUIC example fails, the problem lies in the simulation
code rather than in network emulation.

Despite the `test_` prefix this is a standalone diagnostic script, not part of
an automated test suite; the project has no pytest configuration.

Connections:
    Imports from: wireless_bottleneck (WirelessBottleneck, BottleneckConfig,
                  get_scenario, list_scenarios)
    Invoked by:   run directly, inside the container
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from wireless_bottleneck import (
    WirelessBottleneck,
    BottleneckConfig,
    get_scenario,
    list_scenarios,
)


def test_basic_setup():
    """Test 1: Basic bottleneck setup and teardown."""
    print("=" * 70)
    print("TEST 1: Basic Bottleneck Setup")
    print("=" * 70)
    print()
    
    config = BottleneckConfig(
        capacity_bps=10_000_000,  # 10 Mbps
        propagation_delay=0.020,  # 20ms
        loss_rate=0.01,  # 1%
        queue_size_packets=100,
    )
    
    print(f"Creating bottleneck with:")
    print(f"  Capacity: {config.capacity_bps / 1_000_000:.1f} Mbps")
    print(f"  Delay: {config.propagation_delay * 1000:.1f} ms")
    print(f"  Loss: {config.loss_rate * 100:.1f}%")
    print()
    
    bottleneck = WirelessBottleneck(config, interface="lo")
    
    try:
        bottleneck.setup()
        print("✓ Bottleneck setup successful")
        
        if bottleneck.is_active():
            print("✓ Bottleneck is active")
        else:
            print("✗ Bottleneck is not active")
            return False
        
        # Get stats
        stats = bottleneck.get_current_stats()
        if stats:
            print("✓ Retrieved tc statistics")
            if stats.get("raw_output"):
                print("\nTC output:")
                print(stats["raw_output"])
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        bottleneck.teardown()
        print("\n✓ Bottleneck torn down")
    
    print()
    return True


def test_scenarios():
    """Test 2: List and test predefined scenarios."""
    print("=" * 70)
    print("TEST 2: Predefined Scenarios")
    print("=" * 70)
    print()
    
    scenarios = list_scenarios()
    print(f"Found {len(scenarios)} predefined scenarios:")
    for name in scenarios:
        print(f"  - {name}")
    print()
    
    # Test one scenario
    scenario_name = "congested_low"
    print(f"Testing scenario: {scenario_name}")
    
    try:
        scenario = get_scenario(scenario_name)
        print(f"✓ Loaded scenario: {scenario.description}")
        print(f"  Capacity: {scenario.config.capacity_bps / 1_000_000:.1f} Mbps")
        print(f"  RTT: {scenario.config.propagation_delay * 2000:.1f} ms")
        print(f"  Loss: {scenario.config.loss_rate * 100:.1f}%")
        print(f"  Queue discipline: {scenario.config.queue_discipline.value}")
        print()
        
        # Try to set it up briefly
        with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
            print("✓ Scenario bottleneck active (using context manager)")
            print("✓ Context manager working correctly")
        
        print("✓ Context manager cleanup successful")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    return True


def test_metrics():
    """Test 3: Metrics collection."""
    print("=" * 70)
    print("TEST 3: Metrics Collection")
    print("=" * 70)
    print()
    
    config = BottleneckConfig(
        capacity_bps=10_000_000,
        propagation_delay=0.010,
        loss_rate=0.0,
        queue_size_packets=50,
    )
    
    try:
        with WirelessBottleneck(config, interface="lo") as bottleneck:
            print("✓ Bottleneck active")
            
            # Get monitor and simulate some packet activity
            monitor = bottleneck.monitor
            
            # Record some test data
            monitor.metrics.record_packet_arrival("flow1", 1500)
            monitor.metrics.record_packet_transmission("flow1", 1500, 0.001)
            monitor.metrics.record_packet_arrival("flow2", 1500)
            monitor.metrics.record_packet_transmission("flow2", 1500, 0.002)
            
            print("✓ Recorded test packet events")
            
            # Get metrics
            metrics = bottleneck.get_metrics()
            summary = metrics.summary()
            
            print("\nMetrics summary:")
            print(f"  Packets arrived: {summary['total_packets']['arrived']}")
            print(f"  Packets transmitted: {summary['total_packets']['transmitted']}")
            print(f"  Flows tracked: {len(summary['flows'])}")
            
            if summary['flows']:
                print(f"  Fairness index: {summary['fairness_index']:.3f}")
                print("\n  Per-flow stats:")
                for flow_id, stats in summary['flows'].items():
                    print(f"    {flow_id}: {stats['bytes_transmitted']} bytes, "
                          f"{stats['share'] * 100:.1f}% share")
            
            print("\n✓ Metrics collection working")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    return True


def main():
    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║         Wireless Bottleneck Module - Standalone Tests             ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    print("This tests the wireless bottleneck module without QUIC simulation.")
    print("It verifies that the Linux tc (Traffic Control) integration works.")
    print()
    
    results = []
    
    # Run tests
    results.append(("Basic Setup", test_basic_setup()))
    results.append(("Scenarios", test_scenarios()))
    results.append(("Metrics", test_metrics()))
    
    # Summary
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print()
    
    all_passed = True
    for test_name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{test_name:20s}: {status}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("✓ All tests passed! The wireless bottleneck module is working.")
        print()
        print("Next steps:")
        print("  - Try: python3 examples/quickstart.py")
        print("  - Or: python3 -m wireless_bottleneck list")
        return 0
    else:
        print("✗ Some tests failed. Check the errors above.")
        print()
        print("Common issues:")
        print("  - Not running in Docker container (tc needs Linux)")
        print("  - No root/sudo access (tc needs privileges)")
        print("  - iproute2 not installed (apt-get install iproute2)")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nTests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
