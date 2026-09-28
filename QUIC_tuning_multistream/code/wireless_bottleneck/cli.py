"""
Command-line interface for the wireless bottleneck module.

Lets a bottleneck be inspected and applied without writing any Python, which
is how scenarios are checked and how a link is held open while another process
runs traffic across it.

Commands:
    list      enumerate the predefined scenarios with their key settings
    show      print one scenario's full configuration
    test      apply a scenario and hold it until interrupted
    custom    build a bottleneck from explicit capacity/delay/loss arguments
    validate  run the module self-check (delegates to .validate)

Unit convention: arguments are accepted in the units an operator thinks in
(Mbps, milliseconds, percent) and converted to the module's internal base units
(bps, seconds, fraction) at the boundary.

The `test` and `custom` commands block until Ctrl+C and tear the bottleneck down
on exit via the context manager, so an interrupted session does not leave tc
rules applied to the interface.

Connections:
    Imports from: wireless_bottleneck (WirelessBottleneck, BottleneckConfig,
                  get_scenario, list_scenarios), .validate (lazily)
    Invoked by:   .__main__, i.e. `python -m wireless_bottleneck`
"""

import argparse
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


def cmd_list_scenarios(args):
    """List all available wireless scenarios."""
    print("Available wireless scenarios:")
    print()
    
    for name in list_scenarios():
        scenario = get_scenario(name)
        config = scenario.config
        
        print(f"  {scenario.name}")
        print(f"    Description: {scenario.description}")
        print(f"    Capacity: {config.capacity_bps / 1_000_000:.1f} Mbps")
        print(f"    RTT: {config.propagation_delay * 2000:.1f} ms")
        print(f"    Loss rate: {config.loss_rate * 100:.2f}%")
        print(f"    Loss model: {config.loss_model.value}")
        print(f"    Queue: {config.queue_size_packets} packets ({config.queue_discipline.value})")
        print(f"    Time-varying: {config.time_varying}")
        if config.time_varying:
            print(f"    Variation: ±{config.variation_amplitude * 100:.0f}% every {config.variation_period:.1f}s")
        print()
    
    return 0


def cmd_show_scenario(args):
    """Show details of a specific scenario."""
    try:
        scenario = get_scenario(args.scenario)
        config = scenario.config
        
        print(f"Scenario: {scenario.name}")
        print(f"Description: {scenario.description}")
        print()
        print("Configuration:")
        print(f"  Capacity: {config.capacity_bps / 1_000_000:.1f} Mbps")
        print(f"  Propagation delay: {config.propagation_delay * 1000:.1f} ms (RTT: {config.propagation_delay * 2000:.1f} ms)")
        print(f"  Loss rate: {config.loss_rate * 100:.2f}%")
        print(f"  Loss model: {config.loss_model.value}")
        
        if config.loss_model.value == "gilbert_elliott":
            print(f"    Good→Bad: {config.ge_good_to_bad:.3f}")
            print(f"    Bad→Good: {config.ge_bad_to_good:.3f}")
            print(f"    Loss in bad state: {config.ge_loss_in_bad:.3f}")
        
        print(f"  Queue size: {config.queue_size_packets} packets")
        print(f"  Queue discipline: {config.queue_discipline.value}")
        
        if config.queue_discipline.value == "red":
            print(f"    Min threshold: {config.red_min_threshold} packets")
            print(f"    Max threshold: {config.red_max_threshold} packets")
            print(f"    Max probability: {config.red_max_probability:.2f}")
        elif config.queue_discipline.value == "codel":
            print(f"    Target delay: {config.codel_target_delay * 1000:.1f} ms")
            print(f"    Interval: {config.codel_interval * 1000:.1f} ms")
        
        print(f"  Time-varying: {config.time_varying}")
        if config.time_varying:
            print(f"    Period: {config.variation_period:.1f} s")
            print(f"    Amplitude: ±{config.variation_amplitude * 100:.0f}%")
        
        if config.uplink_capacity_bps or config.downlink_capacity_bps:
            up = config.uplink_capacity_bps or config.capacity_bps
            down = config.downlink_capacity_bps or config.capacity_bps
            print(f"  Asymmetric:")
            print(f"    Uplink: {up / 1_000_000:.1f} Mbps")
            print(f"    Downlink: {down / 1_000_000:.1f} Mbps")
        
        return 0
    except KeyError:
        print(f"Error: Unknown scenario '{args.scenario}'")
        print(f"Available scenarios: {', '.join(list_scenarios())}")
        return 1


def cmd_test_setup(args):
    """Test bottleneck setup without running simulations."""
    try:
        scenario = get_scenario(args.scenario)
        print(f"Testing scenario: {scenario.name}")
        print(f"Interface: {args.interface}")
        print()
        
        with WirelessBottleneck(scenario.config, interface=args.interface) as bottleneck:
            print()
            print("Bottleneck is active. Checking statistics...")
            print()
            
            stats = bottleneck.get_current_stats()
            if stats.get("raw_output"):
                print("TC Statistics:")
                print(stats["raw_output"])
            
            print("Press Ctrl+C to stop...")
            try:
                import time
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nStopping...")
        
        print("Bottleneck cleaned up successfully.")
        return 0
    except KeyError:
        print(f"Error: Unknown scenario '{args.scenario}'")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def cmd_validate(args):
    """Run validation tests."""
    import asyncio
    from wireless_bottleneck.validate import run_validation
    
    try:
        asyncio.run(run_validation())
        return 0
    except Exception as e:
        print(f"Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


def cmd_custom(args):
    """Create and test a custom bottleneck configuration."""
    config = BottleneckConfig(
        capacity_bps=int(args.capacity * 1_000_000),  # Convert Mbps to bps
        propagation_delay=args.delay / 1000,  # Convert ms to seconds
        loss_rate=args.loss / 100,  # Convert percentage to fraction
        queue_size_packets=args.queue_size,
    )
    
    print("Custom bottleneck configuration:")
    print(f"  Capacity: {args.capacity} Mbps")
    print(f"  Delay: {args.delay} ms (RTT: {args.delay * 2} ms)")
    print(f"  Loss: {args.loss}%")
    print(f"  Queue: {args.queue_size} packets")
    print(f"  Interface: {args.interface}")
    print()
    
    try:
        with WirelessBottleneck(config, interface=args.interface) as bottleneck:
            print("Bottleneck active. Press Ctrl+C to stop...")
            try:
                import time
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nStopping...")
        
        print("Bottleneck cleaned up successfully.")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Wireless bottleneck experiments for QUIC research",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all predefined scenarios
  python -m wireless_bottleneck.cli list

  # Show details of a specific scenario
  python -m wireless_bottleneck.cli show --scenario congested_low

  # Test a scenario setup
  python -m wireless_bottleneck.cli test --scenario lossy --interface lo

  # Run validation tests
  python -m wireless_bottleneck.cli validate

  # Create custom bottleneck
  python -m wireless_bottleneck.cli custom --capacity 20 --delay 30 --loss 2

Note: Requires Linux with tc (Traffic Control) and root/sudo access.
      On macOS, use a Linux VM or Docker container.
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # List scenarios
    list_parser = subparsers.add_parser(
        "list",
        help="List available wireless scenarios"
    )
    list_parser.set_defaults(func=cmd_list_scenarios)
    
    # Show scenario details
    show_parser = subparsers.add_parser(
        "show",
        help="Show details of a specific scenario"
    )
    show_parser.add_argument(
        "--scenario",
        required=True,
        choices=list_scenarios(),
        help="Scenario name"
    )
    show_parser.set_defaults(func=cmd_show_scenario)
    
    # Test setup
    test_parser = subparsers.add_parser(
        "test",
        help="Test bottleneck setup (keeps running until Ctrl+C)"
    )
    test_parser.add_argument(
        "--scenario",
        required=True,
        choices=list_scenarios(),
        help="Scenario to test"
    )
    test_parser.add_argument(
        "--interface",
        default="lo",
        help="Network interface to apply bottleneck to (default: lo)"
    )
    test_parser.set_defaults(func=cmd_test_setup)
    
    # Validate
    validate_parser = subparsers.add_parser(
        "validate",
        help="Run validation tests"
    )
    validate_parser.set_defaults(func=cmd_validate)
    
    # Custom configuration
    custom_parser = subparsers.add_parser(
        "custom",
        help="Create and test a custom bottleneck configuration"
    )
    custom_parser.add_argument(
        "--capacity",
        type=float,
        default=10.0,
        help="Link capacity in Mbps (default: 10)"
    )
    custom_parser.add_argument(
        "--delay",
        type=float,
        default=20.0,
        help="One-way propagation delay in ms (default: 20)"
    )
    custom_parser.add_argument(
        "--loss",
        type=float,
        default=1.0,
        help="Packet loss rate in percentage (default: 1)"
    )
    custom_parser.add_argument(
        "--queue-size",
        type=int,
        default=100,
        help="Queue size in packets (default: 100)"
    )
    custom_parser.add_argument(
        "--interface",
        default="lo",
        help="Network interface (default: lo)"
    )
    custom_parser.set_defaults(func=cmd_custom)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
