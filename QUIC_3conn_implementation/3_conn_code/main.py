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
import os
import signal
import atexit
import json
import re
import statistics
import subprocess
from pathlib import Path

from config.multi_connection_config import MultiConnectionConfig
from simulation.process_orchestrator import ProcessOrchestrator

# Import wireless bottleneck scenarios
try:
    from wireless_bottleneck import get_scenario, SCENARIOS
    HAS_WIRELESS_BOTTLENECK = True
except ImportError:
    HAS_WIRELESS_BOTTLENECK = False
    SCENARIOS = {}

# Global reference for cleanup on exit
_orchestrator = None


def _cleanup_on_exit():
    """Cleanup function called at exit (via atexit)."""
    if _orchestrator:
        for process in _orchestrator.workers.values():
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()


def _signal_handler(signum, frame):
    """Handle Ctrl+C and other signals."""
    print("\n[Main] Received interrupt signal, shutting down gracefully...")
    _cleanup_on_exit()
    sys.exit(0)


def cmd_run(args):
    """Run 3 concurrent connections."""
    global _orchestrator
    
    print("QUIC 3-Connection Simulation")
    print("=" * 50)

    # Setup signal handlers for Ctrl+C
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    atexit.register(_cleanup_on_exit)

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
    scenario = None

    try:
        from wireless_bottleneck import get_scenario, WirelessBottleneck
        scenario = get_scenario(scenario_name)
        if scenario:
            network_config = scenario.config.to_dict() if hasattr(scenario.config, 'to_dict') else {}
    except ImportError:
        if not args.bandwidth_cap:
            print("Warning: wireless_bottleneck module not found. Running without network simulation.")
            print("  Tip: use --bandwidth-cap <Mbps> (ex. --bandwidth-cap 30) to simulate a shared")
            print("  bandwidth limit so connections compete & Q-learning has something to optimize.")
        else:
            print(f"Note: wireless_bottleneck module not found. Using app-level cap: {args.bandwidth_cap} Mbps.")
        scenario = None

    # Setup ML callback
    ml_callback = None
    if args.with_ml:
        if args.ml_callback:
            module_name, func_name = args.ml_callback.split(":")
            module = __import__(module_name)
            ml_callback = getattr(module, func_name)
        else:
            from ml_callbacks.q_learning_agent import q_learning_callback
            ml_callback = q_learning_callback

    bandwidth_cap_bps = args.bandwidth_cap * 1e6 if args.bandwidth_cap else None

    # Create orchestrator (store globally for signal handler)
    _orchestrator = ProcessOrchestrator(
        config=config,
        ml_callback=ml_callback,
        metrics_interval=args.metrics_interval,
        network_scenario=scenario_name,
        network_config=network_config,
        scenario=scenario,  # Pass full scenario object for bottleneck setup
        bandwidth_cap_bps=bandwidth_cap_bps,
        loss_rate=args.loss_rate,
        delay_ms=args.delay_ms,
    )

    # Run with or without UI
    try:
        if args.ui:
            asyncio.run(run_with_ui(_orchestrator, args))
        else:
            asyncio.run(run_headless(_orchestrator, args, scenario))
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        # Ensure cleanup happens
        _cleanup_on_exit()

    return 0


async def run_headless(orchestrator, args, scenario):
    """Run simulation without UI."""
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
        return await orchestrator.run()

    # Run server and simulation concurrently
    port = getattr(args, 'port', 8000)
    print(f"Starting browser UI at http://localhost:{port}")
    print("Press Ctrl+C to stop")

    settling_time = getattr(args, 'settling_time', 2.0)
    server_holder = []
    server_task = asyncio.create_task(run_server(orchestrator, port=port, settling_time=settling_time, _server_holder=server_holder))
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
        # Signal uvicorn to exit gracefully (avoids CancelledError noise in logs)
        if server_holder:
            server_holder[0].should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
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

    bottleneck_file = result.export_bottleneck_summary(str(output_path))
    print(f"Bottleneck summary saved to: {bottleneck_file}")

    median_file = result.export_median_metrics_summary(str(output_path))
    print(f"Median metrics summary saved to: {median_file}")

    # Summary
    print(f"\nSimulation Complete")
    print(f"Network Scenario: {args.scenario}")
    print(f"Duration: {args.duration}s")
    print(f"Fairness Index: {result.fairness_index:.3f}")
    print(f"Total Offered Throughput (app): {(result.total_throughput * 8) / 1e6:.2f} Mbps")
    bottleneck = result.get_bottleneck_summary()
    if bottleneck.get("bottleneck_applied"):
        print(f"Observed Link Throughput (tc): {bottleneck.get('observed_link_throughput_mbps', 0):.2f} Mbps")
        print(f"Bottleneck limiting traffic: {bottleneck.get('bottleneck_limiting_traffic', False)}")
    print()

    for conn_id, conn_result in result.connection_results.items():
        print(f"  Connection {conn_id} ({conn_result.application_type}):")
        print(f"    Offered Throughput (app): {(conn_result.final_metrics.get('throughput', 0) * 8) / 1e6:.2f} Mbps")
        print(f"    RTT: {conn_result.final_metrics.get('rtt', 0) * 1000:.1f} ms")
        print(f"    Epochs: {conn_result.get_epoch_count()}")


def cmd_server(args):
    """Run server only - waits for client connections and applies bottleneck."""
    print(f"\n{'='*70}")
    print("QUIC SERVER MODE - Multi-Container Setup")
    print(f"{'='*70}\n")
    
    # Load scenario
    if not HAS_WIRELESS_BOTTLENECK:
        print("Error: wireless_bottleneck module not found. Install wireless_bottleneck package.")
        return 1
    
    scenario = SCENARIOS.get(args.scenario)
    if not scenario:
        print(f"Error: Unknown scenario '{args.scenario}'")
        print(f"Available scenarios: {', '.join(SCENARIOS.keys())}")
        return 1
    
    print(f"Network Scenario: {args.scenario}")
    print(f"Duration: {args.duration}s")
    print(f"Bottleneck: {scenario.config.capacity_bps / 1e6:.1f} Mbps, "
          f"{scenario.config.propagation_delay * 2000:.0f}ms RTT, "
          f"{scenario.config.loss_rate * 100:.2f}% loss\n")
    
    # Create server-only config - listen on docker network IP or localhost
    # In multi-container setup, docker will expose this to the network
    config = MultiConnectionConfig(
        server_host="0.0.0.0",  # Listen on all interfaces
        server_port=4433,
    )
    
    # Run server with bottleneck on eth0 (inter-container interface)
    orchestrator = ProcessOrchestrator(
        config=config,
        network_scenario=args.scenario,
        network_config=scenario.config.to_dict() if hasattr(scenario.config, "to_dict") else {},
        scenario=scenario,
        server_only=True,  # New parameter
    )
    
    loop = asyncio.get_event_loop()
    
    def signal_handler(sig, frame):
        print("\nShutting down server...")
        orchestrator.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        loop.run_until_complete(orchestrator.run(args.duration))
        print("\nServer run completed successfully")
    except Exception as e:
        print(f"\nError running server: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


def cmd_clients(args):
    """Run clients only - connects to remote server."""
    print(f"\n{'='*70}")
    print("QUIC CLIENTS MODE - Multi-Container Setup")
    print(f"{'='*70}\n")
    
    print(f"[DEBUG] cmd_clients called with args: {args}")
    
    print(f"Server: {args.server}:4433")
    print(f"Duration: {args.duration}s")
    print(f"Scenario: {args.scenario}\n")
    
    # Load scenario for client-side shaping
    if not HAS_WIRELESS_BOTTLENECK:
        print("Warning: wireless_bottleneck module not found. Client-side shaping disabled.")
        scenario = None
    else:
        scenario = SCENARIOS.get(args.scenario)
        if not scenario:
            print(f"Warning: Unknown scenario '{args.scenario}', client-side shaping disabled")
            scenario = None
        else:
            print(f"Network Scenario: {args.scenario}")
            print(f"Client egress shaping: {scenario.config.capacity_bps / 1e6:.1f} Mbps\n")
    
    # Create clients-only config pointing to remote server
    config = MultiConnectionConfig(
        server_host=args.server,  # Remote server IP
        server_port=4433,
    )
    
    # Set RUN_MODE for clients to enable client-side shaping on eth0
    os.environ["RUN_MODE"] = "clients"

    ml_callback = None
    if getattr(args, "with_ml", False):
        if getattr(args, "ml_callback", None):
            module_name, func_name = args.ml_callback.split(":")
            module = __import__(module_name)
            ml_callback = getattr(module, func_name)
        else:
            from ml_callbacks.q_learning_agent import q_learning_callback
            ml_callback = q_learning_callback
        print(f"[Clients] ML controller enabled: {ml_callback.__name__ if ml_callback else 'None'}")

    # Run clients with client-side shaping
    orchestrator = ProcessOrchestrator(
        config=config,
        ml_callback=ml_callback,
        network_scenario=args.scenario,
        network_config=scenario.config.to_dict() if scenario and hasattr(scenario.config, "to_dict") else {},
        scenario=scenario,  # Enable ingress policing
        clients_only=True,  # New parameter
    )
    
    loop = asyncio.get_event_loop()
    
    # Track if we should stop early
    should_stop = False
    
    def signal_handler(sig, frame):
        nonlocal should_stop
        should_stop = True
        print("\n[Clients] Received stop signal, finishing up...")
        # Don't call sys.exit() - let the code complete naturally
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("[DEBUG] Starting orchestrator.run()...")
    try:
        result = loop.run_until_complete(orchestrator.run(args.duration))
        print(f"[DEBUG] orchestrator.run() completed with result: {result}")
        print(f"[DEBUG] Result type: {type(result)}")
        
        if result:
            # Merge sidecar probe output if available
            output_path = Path(args.output_dir)
            probe_latest_path = output_path / f"network_probe_{args.scenario}_latest.json"
            if probe_latest_path.exists():
                try:
                    probe_data = json.loads(probe_latest_path.read_text())
                    probe_summary = probe_data.get("network_only_rtt_probe", {})
                    if isinstance(result.network_config, dict) and isinstance(probe_summary, dict) and probe_summary:
                        result.network_config["network_rtt_probe"] = probe_summary
                        print(f"[Clients] Loaded sidecar probe: {probe_latest_path.name}")
                except Exception as e:
                    print(f"[Clients] Warning: failed to load sidecar probe: {e}")

            # Export results to files
            output_path.mkdir(parents=True, exist_ok=True)
            
            result_file = result.export_json(str(output_path))
            metrics_file = result.export_metrics_history(str(output_path))
            epoch_file = result.export_epoch_histories(str(output_path))
            bottleneck_file = result.export_bottleneck_summary(str(output_path))
            median_file = result.export_median_metrics_summary(str(output_path))
            
            print(f"\n✓ Results exported to: {output_path}/")
            print(f"  - {Path(result_file).name}")
            print(f"  - {Path(metrics_file).name}")
            print(f"  - {Path(epoch_file).name}")
            print(f"  - {Path(bottleneck_file).name}")
            print(f"  - {Path(median_file).name}")
            
            # Display results
            print("\n" + "="*70)
            print("RESULTS")
            print("="*70)
            print(f"Total Offered Throughput (app): {(result.total_throughput * 8) / 1e6:.2f} Mbps")
            tc_observed = result.network_config.get("tc_observed_throughput_bps", 0) if isinstance(result.network_config, dict) else 0
            if tc_observed > 0:
                print(f"Observed Link Throughput (tc): {tc_observed / 1e6:.2f} Mbps")
            bottleneck = result.get_bottleneck_summary()
            print(f"Bottleneck limiting traffic: {bottleneck.get('bottleneck_limiting_traffic', False)}")
            print()
            
            for conn_id, conn_result in result.connection_results.items():
                print(f"  Connection {conn_id} ({conn_result.application_type}):")
                print(f"    Offered Throughput (app): {(conn_result.final_metrics.get('throughput', 0) * 8) / 1e6:.2f} Mbps")
                print(f"    RTT: {conn_result.final_metrics.get('rtt', 0) * 1000:.1f} ms")
                print(f"    Epochs: {conn_result.get_epoch_count()}")
        else:
            print("\n[Clients] No results object returned (server may not have completed)")
        
    except Exception as e:
        print(f"\nError running clients: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        print("[DEBUG] cmd_clients finally block executed")
    
    return 0


def cmd_probe(args):
    """Run a standalone network RTT probe and export compact JSON output."""
    print(f"\n{'='*70}")
    print("NETWORK PROBE MODE - Sidecar RTT Probe")
    print(f"{'='*70}\n")

    target = args.target
    duration = float(args.duration)
    interval = float(args.interval)
    count = max(5, int(duration / interval))
    deadline = max(5, int(duration) + 5)

    print(f"Target: {target}")
    print(f"Scenario: {args.scenario}")
    print(f"Duration: {duration}s (count={count}, interval={interval}s)\n")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    probe_summary = {
        "available": False,
        "error": "not_run",
    }

    cmd = [
        "ping",
        "-n",
        "-i", str(interval),
        "-c", str(count),
        "-w", str(deadline),
        target,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output = (result.stdout or "") + "\n" + (result.stderr or "")

        rtt_samples_ms = [float(v) for v in re.findall(r"time[=<]([0-9]*\.?[0-9]+)\s*ms", output)]
        packet_loss_match = re.search(r"([0-9]*\.?[0-9]+)%\s*packet loss", output)
        packet_loss_pct = float(packet_loss_match.group(1)) if packet_loss_match else None

        if rtt_samples_ms:
            sorted_samples = sorted(rtt_samples_ms)
            p95_index = max(0, min(len(sorted_samples) - 1, int(0.95 * (len(sorted_samples) - 1))))
            if len(rtt_samples_ms) >= 2:
                deltas = [abs(b - a) for a, b in zip(rtt_samples_ms[:-1], rtt_samples_ms[1:])]
                jitter_ms = float(statistics.mean(deltas)) if deltas else 0.0
            else:
                jitter_ms = 0.0

            probe_summary = {
                "available": True,
                "target_host": target,
                "sample_count": len(rtt_samples_ms),
                "rtt_min_ms": float(min(rtt_samples_ms)),
                "rtt_median_ms": float(statistics.median(rtt_samples_ms)),
                "rtt_avg_ms": float(statistics.mean(rtt_samples_ms)),
                "rtt_p95_ms": float(sorted_samples[p95_index]),
                "rtt_max_ms": float(max(rtt_samples_ms)),
                "jitter_ms": float(jitter_ms),
                "packet_loss_percent": float(packet_loss_pct) if packet_loss_pct is not None else None,
            }
        else:
            probe_summary = {
                "available": False,
                "error": "no_rtt_samples",
                "target_host": target,
                "packet_loss_percent": float(packet_loss_pct) if packet_loss_pct is not None else None,
            }
    except FileNotFoundError:
        probe_summary = {"available": False, "error": "ping_not_found", "target_host": target}
    except Exception as e:
        probe_summary = {"available": False, "error": f"probe_failed: {e}", "target_host": target}

    payload = {
        "network_scenario": args.scenario,
        "network_only_rtt_probe": probe_summary,
    }

    # Use same timestamp format as results IDs for easier grouping
    from datetime import datetime
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    out_file = output_dir / f"network_probe_{args.scenario}_{run_id}.json"
    latest_file = output_dir / f"network_probe_{args.scenario}_latest.json"

    out_file.write_text(json.dumps(payload, indent=2))
    latest_file.write_text(json.dumps(payload, indent=2))

    print(f"Probe output: {out_file}")
    print(f"Probe latest: {latest_file}")
    print(f"Probe available: {probe_summary.get('available', False)}")
    if probe_summary.get("available"):
        print(f"RTT median: {probe_summary.get('rtt_median_ms', 0):.2f} ms")
        print(f"RTT p95: {probe_summary.get('rtt_p95_ms', 0):.2f} ms")
        print(f"Jitter: {probe_summary.get('jitter_ms', 0):.2f} ms")
        print(f"Packet loss: {probe_summary.get('packet_loss_percent', 0):.2f}%")
    else:
        print(f"Probe error: {probe_summary.get('error', 'unknown')}")

    return 0
    
    return 0


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
    run_parser.add_argument("--bandwidth-cap", type=float, default=0.0, metavar="MBPS",
                           help="Shared bandwidth cap in Mbps across all connections (e.g. 30). "
                                "Forces real competition between connections so Q-learning has "
                                "something to optimize. Recommended when wireless_bottleneck is unavailable.")
    run_parser.add_argument("--loss-rate", type=float, default=0.0, metavar="RATE",
                           help="Simulated packet loss rate 0.0-1.0 (ex. 0.02 = 2%%). "
                                "Triggers QUIC loss recovery, making loss_reduction_factor and "
                                "packet_threshold observable to the Q-agent.")
    run_parser.add_argument("--delay-ms", type=float, default=0.0, metavar="MS",
                           help="Simulated one-way propagation delay in ms (ex. 25). "
                                "Raises RTT into the Q-agent latency bins and makes cubic_c observable.")
    run_parser.set_defaults(func=cmd_run)

    # Server-only mode for multi-container setup
    server_parser = subparsers.add_parser("server", help="Run server only (multi-container mode)")
    server_parser.add_argument("--duration", type=float, default=60.0,
                              help="Server run duration in seconds")
    server_parser.add_argument("--scenario", default="congested_low",
                              help="Network scenario for bottleneck")
    server_parser.set_defaults(func=cmd_server)

    # Clients-only mode for multi-container setup
    clients_parser = subparsers.add_parser("clients", help="Run clients only (multi-container mode)")
    clients_parser.add_argument("--server", required=True,
                               help="Server IP address")
    clients_parser.add_argument("--duration", type=float, default=30.0,
                               help="Client run duration in seconds")
    clients_parser.add_argument("--scenario", default="congested_low",
                               help="Network scenario (for display only)")
    clients_parser.add_argument("--output-dir", default="output",
                               help="Output directory for results")
    clients_parser.add_argument("--with-ml", action="store_true",
                               help="Enable ML controller (Q-learning agent)")
    clients_parser.add_argument("--ml-callback",
                               help="Custom ML callback (module:function)")
    clients_parser.set_defaults(func=cmd_clients)

    probe_parser = subparsers.add_parser("probe", help="Run standalone network RTT probe")
    probe_parser.add_argument("--target", required=True, help="Probe target host/IP")
    probe_parser.add_argument("--duration", type=float, default=30.0, help="Probe duration in seconds")
    probe_parser.add_argument("--interval", type=float, default=0.5, help="Ping interval in seconds")
    probe_parser.add_argument("--scenario", default="congested_low", help="Scenario label for output")
    probe_parser.add_argument("--output-dir", default="output", help="Output directory for probe files")
    probe_parser.set_defaults(func=cmd_probe)

    args = parser.parse_args()
    if hasattr(args, "func"):
        return args.func(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    exit(main())
