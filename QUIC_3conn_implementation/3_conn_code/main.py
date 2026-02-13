"""
Main entry point for QUIC 3-Connection Simulation.

Usage:
    # Run basic simulation
    uv run python -m main run

    # Run with specific duration
    uv run python -m main run --duration 60

    # Run with browser UI dashboard
    uv run python -m main run --ui

    # Run with ML controller
    uv run python -m main run --with-ml

    # Run with network scenario
    uv run python -m main run --scenario congested_low
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add parent directory to path for wireless_bottleneck import
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.multi_connection_config import MultiConnectionConfig
from simulation.process_orchestrator import ProcessOrchestrator


def cmd_run(args):
    """Run 3 concurrent connections."""
    print("QUIC 3-Connection Simulation")
    print("=" * 50)

    # Load config
    if args.config:
        config = MultiConnectionConfig.from_json(args.config)
    else:
        config = MultiConnectionConfig()

    config.simulation_duration = args.duration

    # Validate duration is sufficient for epoch collection
    settling_time = 2.0  # Must match EpochConfig.settling_time
    min_epoch_duration = 2.0  # Minimum useful epoch
    min_duration = settling_time + min_epoch_duration
    if args.duration < min_duration:
        print(f"Warning: duration {args.duration}s < {min_duration}s (settling + min epoch)")
        print("No valid epochs will be collected. Consider increasing --duration.")
        print()

    # Setup network scenario
    network_config = {}
    scenario_name = args.scenario

    try:
        from wireless_bottleneck import get_scenario, WirelessBottleneck
        scenario = get_scenario(scenario_name)
        if scenario:
            network_config = scenario.config.to_dict() if hasattr(scenario.config, 'to_dict') else {}
    except ImportError:
        print("Warning: wireless_bottleneck module not found. Running without network simulation.")
        scenario = None

    # Setup ML callback
    ml_callback = None
    if args.with_ml:
        if args.ml_callback:
            module_name, func_name = args.ml_callback.split(":")
            module = __import__(module_name)
            ml_callback = getattr(module, func_name)
        else:
            from ml_callbacks.fairness_optimizer import fairness_optimizer
            ml_callback = fairness_optimizer

    # Create orchestrator
    orchestrator = ProcessOrchestrator(
        config=config,
        ml_callback=ml_callback,
        metrics_interval=args.metrics_interval,
        network_scenario=scenario_name,
        network_config=network_config,
    )

    # Run with or without UI
    try:
        if args.ui:
            asyncio.run(run_with_ui(orchestrator, args))
        else:
            asyncio.run(run_headless(orchestrator, args, scenario))
    except KeyboardInterrupt:
        print("\nInterrupted by user")

    return 0


async def run_headless(orchestrator, args, scenario):
    """Run simulation without UI."""
    try:
        from wireless_bottleneck import WirelessBottleneck
        if scenario:
            with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
                result = await orchestrator.run()
        else:
            result = await orchestrator.run()
    except (ImportError, Exception):
        result = await orchestrator.run()

    # Export results
    export_results(result, args)


async def run_with_ui(orchestrator, args):
    """Run simulation with browser UI."""
    import asyncio
    import signal
    from web.server import run_server

    # Start orchestrator in background
    async def run_simulation():
        try:
            from wireless_bottleneck import get_scenario, WirelessBottleneck
            scenario = get_scenario(args.scenario)
            if scenario:
                with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
                    return await orchestrator.run()
        except (ImportError, Exception):
            pass
        return await orchestrator.run()

    # Run server and simulation concurrently
    port = getattr(args, 'port', 8000)
    print(f"Starting browser UI at http://localhost:{port}")
    print("Press Ctrl+C to stop")

    settling_time = getattr(args, 'settling_time', 2.0)
    server_task = asyncio.create_task(run_server(orchestrator, port=port, settling_time=settling_time))
    sim_task = asyncio.create_task(run_simulation())

    try:
        # Wait for simulation to complete
        result = await sim_task
        export_results(result, args)

        print("\nSimulation complete. Server stopping in 3 seconds...")
        print("(Press Ctrl+C to stop immediately)")
        await asyncio.sleep(3)

    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        # Cancel server task
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


def export_results(result, args):
    """Export simulation results."""
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Export all formats
    result_file = result.export_json(str(output_path))
    print(f"Results saved to: {result_file}")

    metrics_file = result.export_metrics_history(str(output_path))
    print(f"Metrics history saved to: {metrics_file}")

    epoch_file = result.export_epoch_histories(str(output_path))
    print(f"Epoch histories saved to: {epoch_file}")

    # Summary
    print(f"\nSimulation Complete")
    print(f"Network Scenario: {args.scenario}")
    print(f"Duration: {args.duration}s")
    print(f"Fairness Index: {result.fairness_index:.3f}")
    print(f"Total Throughput: {result.total_throughput / 1e6:.2f} Mbps")
    print()

    for conn_id, conn_result in result.connection_results.items():
        print(f"  Connection {conn_id} ({conn_result.application_type}):")
        print(f"    Throughput: {conn_result.final_metrics.get('throughput', 0) / 1e6:.2f} Mbps")
        print(f"    RTT: {conn_result.final_metrics.get('rtt', 0) * 1000:.1f} ms")
        print(f"    Epochs: {conn_result.get_epoch_count()}")


def main():
    parser = argparse.ArgumentParser(description="QUIC 3-Connection Simulation")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run simulation")
    run_parser.add_argument("--duration", type=float, default=30.0,
                           help="Simulation duration in seconds")
    run_parser.add_argument("--metrics-interval", type=float, default=0.1,
                           help="Metrics collection interval in seconds")
    run_parser.add_argument("--output-dir", default="output",
                           help="Output directory for results")
    run_parser.add_argument("--config", help="Path to JSON config file")
    run_parser.add_argument("--scenario", default="congested_low",
                           help="Network scenario (stable_high, congested_low, varying, lossy, asymmetric)")
    run_parser.add_argument("--with-ml", action="store_true",
                           help="Enable ML controller")
    run_parser.add_argument("--ml-callback", help="Custom ML callback (module:function)")
    run_parser.add_argument("--ui", action="store_true",
                           help="Enable browser UI dashboard")
    run_parser.add_argument("--port", type=int, default=8000,
                           help="Port for browser UI (default: 8000)")
    run_parser.add_argument("--settling-time", type=float, default=2.0,
                           help="Settling time in seconds after parameter changes (default: 2.0, use 5-10 for network simulation)")
    run_parser.set_defaults(func=cmd_run)

    args = parser.parse_args()
    if hasattr(args, "func"):
        return args.func(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    exit(main())
