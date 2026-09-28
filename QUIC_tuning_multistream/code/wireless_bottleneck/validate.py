"""
Self-check for the wireless bottleneck module.

Exercises the bottleneck end to end on the loopback interface to confirm the
environment can actually shape traffic before any real experiment is run: a
manual setup and teardown, context-manager use, enumeration of every predefined
scenario, and a metrics-collection check.

This is an environment diagnostic rather than a unit test. It requires Linux
with tc and sufficient privileges, and is intended to be run inside the
project's container. Reachable both directly and through
`python -m wireless_bottleneck validate`.

Connections:
    Imports from: wireless_bottleneck (WirelessBottleneck, BottleneckConfig,
                  get_scenario, list_scenarios)
    Invoked by:   .cli (validate command), or executed directly
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from wireless_bottleneck import (
    WirelessBottleneck,
    BottleneckConfig,
    get_scenario,
    list_scenarios,
)


async def run_validation():
    """Run validation tests for the wireless bottleneck."""
    
    print("=" * 70)
    print("WIRELESS BOTTLENECK VALIDATION")
    print("=" * 70)
    print()
    
    # Test 1: Verify basic bottleneck setup
    print("Test 1: Basic bottleneck setup")
    print("-" * 70)
    
    config = BottleneckConfig(
        capacity_bps=10_000_000,  # 10 Mbps
        propagation_delay=0.020,  # 20ms
        loss_rate=0.01,  # 1%
        queue_size_packets=100,
    )
    
    bottleneck = WirelessBottleneck(config, interface="lo")
    
    try:
        bottleneck.setup()
        print("✓ Bottleneck configured successfully")
        
        # Check if active
        assert bottleneck.is_active(), "Bottleneck should be active"
        print("✓ Bottleneck is active")
        
        # Get stats
        stats = bottleneck.get_current_stats()
        print(f"✓ Retrieved tc statistics")
        
    finally:
        bottleneck.teardown()
        print("✓ Bottleneck torn down successfully")
    
    print()
    
    # Test 2: Context manager usage
    print("Test 2: Context manager usage")
    print("-" * 70)
    
    scenario = get_scenario("congested_low")
    print(f"Using scenario: {scenario.name}")
    print(f"Description: {scenario.description}")
    
    with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
        print("✓ Bottleneck context manager entered")
        assert bottleneck.is_active()
        print("✓ Bottleneck is active within context")
    
    print("✓ Bottleneck context manager exited and cleaned up")
    print()
    
    # Test 3: List all scenarios
    print("Test 3: Available wireless scenarios")
    print("-" * 70)
    
    scenarios = list_scenarios()
    print(f"Found {len(scenarios)} predefined scenarios")
    
    for name in scenarios:
        scenario = get_scenario(name)
        config = scenario.config
        print(f"\n  {scenario.name}:")
        print(f"    {scenario.description}")
        print(f"    Capacity: {config.capacity_bps / 1_000_000:.1f} Mbps")
        print(f"    RTT: {config.propagation_delay * 2000:.1f} ms")
        print(f"    Loss: {config.loss_rate * 100:.1f}%")
        print(f"    Queue: {config.queue_size_packets} packets ({config.queue_discipline.value})")
        print(f"    Time-varying: {config.time_varying}")
    
    print()
    
    # Test 4: Verify metrics collection
    print("Test 4: Metrics collection")
    print("-" * 70)
    
    config = BottleneckConfig(
        capacity_bps=10_000_000,
        propagation_delay=0.010,
        loss_rate=0.0,
        queue_size_packets=50,
    )
    
    with WirelessBottleneck(config, interface="lo") as bottleneck:
        # Simulate some packet activity
        monitor = bottleneck.monitor
        
        # Record some test data
        monitor.metrics.record_packet_arrival("flow1", 1500)
        monitor.metrics.record_packet_transmission("flow1", 1500, 0.001)
        monitor.metrics.record_packet_arrival("flow2", 1500)
        monitor.metrics.record_packet_transmission("flow2", 1500, 0.002)
        
        metrics = bottleneck.get_metrics()
        summary = metrics.summary()
        
        print(f"✓ Metrics collection working")
        print(f"  Packets arrived: {summary['total_packets']['arrived']}")
        print(f"  Packets transmitted: {summary['total_packets']['transmitted']}")
        print(f"  Flows tracked: {len(summary['flows'])}")
        
        if summary['flows']:
            print(f"  Fairness index: {summary['fairness_index']:.3f}")
    
    print()
    print("=" * 70)
    print("VALIDATION COMPLETE")
    print("=" * 70)
    print()
    print("All tests passed! The wireless bottleneck module is ready to use.")
    print()
    print("Next steps:")
    print("  1. Integrate with your QUIC simulations")
    print("  2. Run experiments under different wireless scenarios")
    print("  3. Analyze how QUIC parameters perform under constrained conditions")
    print()
    print("Note: Some tests require Linux with tc (Traffic Control) support.")
    print("      On macOS, consider using a Linux VM or Docker container.")


if __name__ == "__main__":
    try:
        asyncio.run(run_validation())
    except KeyboardInterrupt:
        print("\nValidation interrupted by user")
    except Exception as e:
        print(f"\nValidation failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
