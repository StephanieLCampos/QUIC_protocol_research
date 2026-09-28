"""
Example: every application type across every wireless scenario.

Sweeps the three workloads (video streaming, file transfer, conference call)
through the predefined scenarios, showing how each application's characteristic
metric responds to different link conditions.

This is the example that demonstrates the project's central comparison: the
same link affects a throughput-oriented workload very differently from a
latency- or jitter-sensitive one.

Runs against the loopback interface and so is illustrative rather than
precisely shaped; see run_app_with_real_bottleneck.py for the veth variant.

Connections:
    Imports from: wireless_bottleneck (WirelessBottleneck, get_scenario,
                  list_scenarios), simulation.runner (SimulationRunner)
    Invoked by:   run directly, inside the project's privileged container
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from wireless_bottleneck import WirelessBottleneck, get_scenario, list_scenarios
from simulation.runner import SimulationRunner


async def run_app_through_scenario(app_type: str, scenario_name: str):
    """
    Run a specific application type through a wireless scenario.
    
    Args:
        app_type: One of "video_streaming", "file_transfer", "conference_call"
        scenario_name: One of the predefined scenarios (stable_high, congested_low, etc.)
    """
    scenario = get_scenario(scenario_name)
    
    print("\n" + "=" * 70)
    print(f"Running {app_type.upper()} through {scenario_name.upper()}")
    print("=" * 70)
    print(f"Description: {scenario.description}")
    print(f"Capacity: {scenario.config.capacity_bps / 1_000_000:.1f} Mbps")
    print(f"RTT: {scenario.config.propagation_delay * 2000:.1f} ms")
    print(f"Loss: {scenario.config.loss_rate * 100:.1f}%")
    print()
    
    # Set up bottleneck (use "lo" for loopback, or "veth0" if you set up veth pair)
    with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
        
        # Run QUIC simulation with the specified application type
        runner = SimulationRunner(
            application_type=app_type,
            initial_cw=12000,
            max_ack_delay=0.025,
            loss_reduction_factor=0.5,
        )
        
        print(f"Running {app_type} simulation...")
        
        try:
            result = await runner.run()
        except Exception as e:
            print(f"\n✗ Exception during simulation: {e}")
            import traceback
            traceback.print_exc()
            return
        
        if result.success:
            print("\n✓ QUIC Simulation Results:")
            print(f"  Throughput: {result.metrics.throughput / 1_000_000:.2f} Mbps")
            print(f"  RTT: {result.metrics.rtt * 1000:.2f} ms")
            print(f"  Latency: {result.metrics.latency * 1000:.2f} ms")
            print(f"  Jitter: {result.metrics.jitter * 1000:.2f} ms")
            print(f"  Packet loss: {result.metrics.packet_loss_rate * 100:.2f}%")
            print(f"  Connection time: {result.metrics.connection_establishment_time * 1000:.2f} ms")
            
            # Show bottleneck metrics
            metrics = bottleneck.get_metrics()
            summary = metrics.summary()
            
            print("\n✓ Bottleneck Metrics:")
            print(f"  Queue avg: {summary['queue']['avg_occupancy_packets']:.1f} packets")
            print(f"  Queue max: {summary['queue']['max_occupancy_packets']} packets")
            print(f"  Packets dropped: {summary['total_packets']['dropped']}")
            print(f"  Actual loss: {summary['total_packets']['loss_rate'] * 100:.2f}%")
            
            # Warning about loopback limitations
            if summary['total_packets']['transmitted'] == 0:
                print(f"\n  ⚠ Note: Using loopback interface - tc statistics may not reflect actual traffic.")
                print(f"         For accurate bottleneck metrics, use veth interface (run_app_with_real_bottleneck.py)")
        else:
            print(f"\n✗ Simulation failed: {result.error_message}")


async def compare_apps_in_scenario(scenario_name: str):
    """
    Compare how different applications perform in the same scenario.
    """
    print("\n" + "=" * 70)
    print(f"COMPARING APPLICATIONS IN '{scenario_name}' SCENARIO")
    print("=" * 70)
    
    apps = ["video_streaming", "file_transfer", "conference_call"]
    
    for app in apps:
        await run_app_through_scenario(app, scenario_name)
        print()


async def test_app_across_scenarios(app_type: str):
    """
    Test one application across all wireless scenarios.
    """
    print("\n" + "=" * 70)
    print(f"TESTING {app_type.upper()} ACROSS ALL SCENARIOS")
    print("=" * 70)
    
    for scenario_name in list_scenarios():
        await run_app_through_scenario(app_type, scenario_name)


async def main():
    """
    Main entry point - run various experiments.
    """
    print("\n╔════════════════════════════════════════════════════════════════════╗")
    print("║  Application-Specific Wireless Bottleneck Tests                   ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    
    import argparse
    parser = argparse.ArgumentParser(description="Run applications through wireless bottleneck")
    parser.add_argument("--app", 
                       choices=["video_streaming", "file_transfer", "conference_call"],
                       help="Application type to test")
    parser.add_argument("--scenario",
                       choices=list_scenarios(),
                       help="Scenario to use")
    parser.add_argument("--compare-apps", 
                       choices=list_scenarios(),
                       metavar="SCENARIO",
                       help="Compare all apps in a scenario")
    parser.add_argument("--test-all-scenarios",
                       choices=["video_streaming", "file_transfer", "conference_call"],
                       metavar="APP",
                       help="Test one app across all scenarios")
    
    args = parser.parse_args()
    
    # Run based on arguments
    if args.app and args.scenario:
        # Run specific app through specific scenario
        await run_app_through_scenario(args.app, args.scenario)
    elif args.compare_apps:
        # Compare all apps in one scenario
        await compare_apps_in_scenario(args.compare_apps)
    elif args.test_all_scenarios:
        # Test one app across all scenarios
        await test_app_across_scenarios(args.test_all_scenarios)
    else:
        # Default: Run file_transfer through congested_low scenario
        print("\nNo arguments provided. Running default example:")
        print("  file_transfer through congested_low scenario\n")
        await run_app_through_scenario("file_transfer", "congested_low")
        
        print("\n" + "=" * 70)
        print("TIP: Run with --help to see all options")
        print("=" * 70)
        print("\nExamples:")
        print("  # Test video streaming on lossy network")
        print("  python3 examples/run_app_through_bottleneck.py --app video_streaming --scenario stable_high")
        print()
        print("  # Compare all apps in varying capacity scenario")
        print("  python3 examples/run_app_through_bottleneck.py --compare-apps varying")
        print()
        print("  # Test conference calls across all scenarios")
        print("  python3 examples/run_app_through_bottleneck.py --test-all-scenarios conference_call")
        print()
        print("NOTE: Using loopback interface for quick testing.")
        print("      RTT and throughput are affected by bottleneck, but tc statistics show 0")
        print("      because loopback traffic bypasses tc packet processing.")
        print("      For real bottleneck metrics, use: run_app_with_real_bottleneck.py")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
