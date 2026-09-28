"""
Example: full wireless experiment with combined metrics.

The most complete example in this directory. Sets up a scenario, runs QUIC
traffic through it, and then reports metrics from *both* sides: the protocol's
own view (throughput, RTT, jitter, loss) and the bottleneck's view (queue
occupancy, drops, per-flow shares, fairness).

Reading both together is the point: it shows whether an observed throughput
figure was limited by the protocol's behaviour or simply by the link, which a
one-sided measurement cannot distinguish.

Connections:
    Imports from: wireless_bottleneck (WirelessBottleneck, get_scenario),
                  simulation.runner (SimulationRunner),
                  config.parameters (ParameterSet)
    Invoked by:   run directly, on Linux or inside the container
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from wireless_bottleneck import WirelessBottleneck, get_scenario
from simulation.runner import SimulationRunner
from config.parameters import ParameterSet


async def single_flow_experiment():
    """
    Example 1: Single QUIC flow through wireless bottleneck.
    """
    print("=" * 70)
    print("EXAMPLE 1: Single QUIC Flow Through Wireless Bottleneck")
    print("=" * 70)
    print()
    
    # Choose a wireless scenario
    scenario = get_scenario("congested_low")
    print(f"Scenario: {scenario.name}")
    print(f"Description: {scenario.description}")
    print(f"Capacity: {scenario.config.capacity_bps / 1_000_000:.1f} Mbps")
    print(f"RTT: {scenario.config.propagation_delay * 2000:.1f} ms")
    print(f"Loss: {scenario.config.loss_rate * 100:.1f}%")
    print()
    
    # Set up the bottleneck
    with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
        print("Wireless bottleneck active!")
        print()
        
        # Configure QUIC parameters
        print("Running QUIC file transfer simulation...")
        runner = SimulationRunner(
            application_type="file_transfer",
            initial_cw=12000,
            max_ack_delay=0.025,
            loss_reduction_factor=0.5,
        )
        
        result = await runner.run()
        
        # Show QUIC results
        print("\n--- QUIC Simulation Results ---")
        if result.success:
            print(f"✓ Simulation completed successfully")
            print(f"  Throughput: {result.metrics.throughput / 1_000_000:.2f} Mbps")
            print(f"  RTT: {result.metrics.rtt * 1000:.2f} ms")
            print(f"  Jitter: {result.metrics.jitter * 1000:.2f} ms")
            print(f"  Packet loss: {result.metrics.packet_loss_rate * 100:.2f}%")
            print(f"  Goodput: {result.metrics.goodput / 1_000_000:.2f} Mbps")
        else:
            print(f"✗ Simulation failed: {result.error}")
            return
        
        # Show bottleneck metrics
        bottleneck_metrics = bottleneck.get_metrics()
        summary = bottleneck_metrics.summary()
        
        print("\n--- Bottleneck Metrics ---")
        print(f"  Packets arrived: {summary['total_packets']['arrived']}")
        print(f"  Packets transmitted: {summary['total_packets']['transmitted']}")
        print(f"  Packets dropped: {summary['total_packets']['dropped']}")
        print(f"  Actual loss rate: {summary['total_packets']['loss_rate'] * 100:.2f}%")
        print(f"  Avg queue occupancy: {summary['queue']['avg_occupancy_packets']:.1f} packets")
        print(f"  Max queue occupancy: {summary['queue']['max_occupancy_packets']} packets")
        print(f"  Avg queue delay: {summary['queue']['avg_delay_ms']:.2f} ms")
        print(f"  Max queue delay: {summary['queue']['max_delay_ms']:.2f} ms")
    
    print("\n✓ Experiment complete!\n")


async def multi_flow_experiment():
    """
    Example 2: Multiple concurrent QUIC flows competing for bandwidth.
    """
    print("=" * 70)
    print("EXAMPLE 2: Multiple Concurrent QUIC Flows")
    print("=" * 70)
    print()
    
    scenario = get_scenario("congested_low")
    print(f"Testing {scenario.name} with 3 concurrent flows...")
    print()
    
    with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
        # Create 3 different application types
        flows = [
            ("file_transfer", SimulationRunner("file_transfer", 12000, 0.025, 0.5)),
            ("video_streaming", SimulationRunner("video_streaming", 10000, 0.020, 0.6)),
            ("conference_call", SimulationRunner("conference_call", 8000, 0.015, 0.7)),
        ]
        
        print("Running 3 flows concurrently...")
        runners = [runner for _, runner in flows]
        results = await asyncio.gather(*[r.run() for r in runners])
        
        # Show per-flow results
        print("\n--- Per-Flow Results ---")
        for (app_type, _), result in zip(flows, results):
            if result.success:
                print(f"{app_type:20s}: {result.metrics.throughput / 1_000_000:6.2f} Mbps, "
                      f"RTT: {result.metrics.rtt * 1000:5.1f} ms, "
                      f"Loss: {result.metrics.packet_loss_rate * 100:4.1f}%")
        
        # Check fairness
        metrics = bottleneck.get_metrics()
        fairness_index = metrics.get_flow_fairness_index()
        
        print(f"\n--- Fairness Analysis ---")
        print(f"Jain's Fairness Index: {fairness_index:.3f}")
        print("(1.0 = perfectly fair, lower values indicate unfairness)")
        
        summary = metrics.summary()
        if summary['flows']:
            print("\nBandwidth shares:")
            for flow_id, stats in summary['flows'].items():
                print(f"  {flow_id}: {stats['share'] * 100:5.1f}% "
                      f"({stats['bytes_transmitted']:,} bytes)")
    
    print("\n✓ Multi-flow experiment complete!\n")


async def scenario_comparison():
    """
    Example 3: Compare QUIC performance across different wireless scenarios.
    """
    print("=" * 70)
    print("EXAMPLE 3: QUIC Performance Across Wireless Scenarios")
    print("=" * 70)
    print()
    
    # Test scenarios
    scenarios_to_test = ["stable_high", "congested_low", "lossy", "varying"]
    
    results_table = []
    
    for scenario_name in scenarios_to_test:
        scenario = get_scenario(scenario_name)
        print(f"Testing {scenario.name}...")
        
        with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
            runner = SimulationRunner(
                application_type="file_transfer",
                initial_cw=12000,
                max_ack_delay=0.025,
                loss_reduction_factor=0.5,
            )
            
            result = await runner.run()
            
            if result.success:
                results_table.append({
                    "scenario": scenario.name,
                    "throughput": result.metrics.throughput / 1_000_000,
                    "rtt": result.metrics.rtt * 1000,
                    "loss": result.metrics.packet_loss_rate * 100,
                    "goodput": result.metrics.goodput / 1_000_000,
                })
    
    # Display comparison table
    print("\n--- Performance Comparison ---")
    print(f"{'Scenario':<20s} {'Throughput':>12s} {'RTT':>8s} {'Loss':>8s} {'Goodput':>12s}")
    print("-" * 70)
    for row in results_table:
        print(f"{row['scenario']:<20s} "
              f"{row['throughput']:10.2f} Mbps "
              f"{row['rtt']:6.1f} ms "
              f"{row['loss']:6.1f}% "
              f"{row['goodput']:10.2f} Mbps")
    
    print("\n✓ Scenario comparison complete!\n")


async def main():
    """Run all examples."""
    print("\n")
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  Wireless Bottleneck Examples for QUIC Research                   ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    
    try:
        # Run example 1: Single flow
        await single_flow_experiment()
        
        # Run example 2: Multiple flows
        await multi_flow_experiment()
        
        # Run example 3: Scenario comparison
        await scenario_comparison()
        
        print("=" * 70)
        print("All examples completed successfully!")
        print("=" * 70)
        print()
        print("Next steps:")
        print("  - Modify parameters in the examples above")
        print("  - Create custom scenarios in scenarios.py")
        print("  - Integrate with grid_search for parameter optimization")
        print("  - Analyze results in output/ directory")
        print()
        
    except KeyboardInterrupt:
        print("\n\nExperiment interrupted by user.")
    except Exception as e:
        print(f"\n\nError running experiment: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
