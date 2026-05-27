#!/usr/bin/env python3
"""
Experiment runner for uniform QUIC configuration research.

This script runs the 3-connection simulation with uniform parameters
applied to all connections, enabling fair comparison across app types.

Usage:
    # Run single config
    python experiment_runner.py --config ft_friendly --duration 60

    # Run all 3 configs sequentially
    python experiment_runner.py --all --duration 60

    # List available presets
    python experiment_runner.py --list
"""

import argparse
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add 3_conn_code to path for its modules
conn_code_path = Path(__file__).parent.parent / "3_conn_code"
sys.path.insert(0, str(conn_code_path))

# Import from 3_conn_code
from config.connection_config import ConnectionConfig
from config.multi_connection_config import MultiConnectionConfig
from simulation.process_orchestrator import ProcessOrchestrator

# Import local config (research_code/config) using direct import
import importlib.util
spec = importlib.util.spec_from_file_location(
    "uniform_presets",
    Path(__file__).parent / "config" / "uniform_presets.py"
)
uniform_presets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uniform_presets)
get_preset = uniform_presets.get_preset
list_presets = uniform_presets.list_presets
UniformPreset = uniform_presets.UniformPreset
print_preset_summary = uniform_presets.print_preset_summary


def create_uniform_config(preset: UniformPreset, duration: float) -> MultiConnectionConfig:
    """
    Create a MultiConnectionConfig where ALL connections use identical parameters.

    Parameters
    ----------
    preset : UniformPreset
        The uniform preset to apply to all connections.
    duration : float
        Simulation duration in seconds.

    Returns
    -------
    MultiConnectionConfig
        Configuration with uniform parameters across all 3 connections.
    """
    # Create base config with uniform shared (start-only) parameters
    config = MultiConnectionConfig(
        simulation_duration=duration,
        shared_initial_cw=preset.initial_cw,
        shared_max_ack_delay=preset.max_ack_delay,
        shared_max_data=preset.max_data,
        shared_max_stream_data=preset.max_stream_data,
    )

    # Apply SAME dynamic parameters to ALL 3 connections
    for conn_config in config.get_all_configs():
        conn_config.loss_reduction_factor = preset.loss_reduction_factor
        conn_config.cubic_c = preset.cubic_c
        conn_config.minimum_window = preset.minimum_window
        conn_config.packet_threshold = preset.packet_threshold
        conn_config.time_threshold = preset.time_threshold
        conn_config.cubic_max_idle_time = preset.cubic_max_idle_time

    return config


async def run_experiment(preset_name: str, duration: float, output_dir: Path):
    """
    Run a single experiment with the given preset.

    All 3 connections (video, file, conference) run CONCURRENTLY
    in SEPARATE PROCESSES, all using the SAME uniform parameters.
    """
    preset = get_preset(preset_name)
    config = create_uniform_config(preset, duration)

    print(f"\n{'='*60}")
    print(f"Running Experiment: {preset.description}")
    print(f"{'='*60}")
    print(f"Config: {preset_name}")
    print(f"Duration: {duration}s")
    print(f"Output: {output_dir}")
    print()

    # Print uniform parameters (same for all 3 connections)
    print("Uniform Parameters (applied to ALL 3 connections):")
    print(f"  loss_reduction_factor: {preset.loss_reduction_factor}")
    print(f"  cubic_c:               {preset.cubic_c}")
    print(f"  minimum_window:        {preset.minimum_window}")
    print(f"  packet_threshold:      {preset.packet_threshold}")
    print(f"  time_threshold:        {preset.time_threshold}")
    print(f"  cubic_max_idle_time:   {preset.cubic_max_idle_time}")
    print()

    # Create orchestrator with stable_high scenario (minimal network effects)
    orchestrator = ProcessOrchestrator(
        config=config,
        ml_callback=None,
        metrics_interval=0.1,
        network_scenario="stable_high",  # Use stable scenario
        network_config={},
    )

    # Run simulation - all 3 connections start simultaneously via Barrier
    print("Starting 3 concurrent connections...")
    print("  - Connection 1: Video Streaming")
    print("  - Connection 2: File Transfer")
    print("  - Connection 3: Conference Call")
    print()

    result = await orchestrator.run()

    # Set config name for filename
    result.config_name = preset_name

    # Export results
    output_dir.mkdir(parents=True, exist_ok=True)
    result_file = result.export_json(str(output_dir))
    metrics_file = result.export_metrics_history(str(output_dir))
    epoch_file = result.export_epoch_histories(str(output_dir))

    print(f"\nResults saved to: {result_file}")

    # Print summary with the 9 values from this experiment
    print(f"\n{'='*60}")
    print(f"Results Summary: {preset_name} (9 of 27 values)")
    print(f"{'='*60}")
    print(f"{'Application':<20} {'Throughput':<15} {'Latency':<12} {'Jitter':<12}")
    print(f"{'':<20} {'(Mbps)':<15} {'(ms)':<12} {'(ms)':<12}")
    print("-" * 60)

    for conn_id, conn_result in result.connection_results.items():
        throughput_mbps = (conn_result.final_metrics.get('throughput', 0) * 8) / 1e6
        latency_ms = conn_result.final_metrics.get('latency', 0) * 1000
        jitter_ms = conn_result.final_metrics.get('jitter', 0) * 1000
        app_type = conn_result.application_type
        print(f"{app_type:<20} {throughput_mbps:<15.2f} {latency_ms:<12.2f} {jitter_ms:<12.2f}")

    print("-" * 60)
    print()

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run uniform QUIC configuration experiments to collect 27 metric values",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run single config
    python experiment_runner.py --config ft_friendly --duration 60

    # Run all 3 configs sequentially (collect all 27 values)
    python experiment_runner.py --all --duration 60

    # List available presets
    python experiment_runner.py --list

    # After running all experiments, extract results:
    python results_extractor.py
        """
    )
    parser.add_argument(
        "--config",
        choices=["ft_friendly", "vc_friendly", "mm_friendly"],
        help="Which uniform config to use"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all 3 configs sequentially to collect all 27 values"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Simulation duration in seconds (default: 60)"
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Base output directory (default: output)"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available presets and exit"
    )

    args = parser.parse_args()

    if args.list:
        print_preset_summary()
        return 0

    if not args.config and not args.all:
        parser.error("Must specify --config or --all (use --list to see available presets)")

    base_output = Path(args.output_dir)

    if args.all:
        # Run all 3 configs sequentially
        print("=" * 60)
        print("RUNNING ALL 3 EXPERIMENTS")
        print("This will collect all 27 metric values")
        print("=" * 60)

        for preset_name in list_presets():
            output_dir = base_output / preset_name
            asyncio.run(run_experiment(preset_name, args.duration, output_dir))

        print(f"\n{'='*60}")
        print("ALL EXPERIMENTS COMPLETE!")
        print(f"{'='*60}")
        print(f"Results saved to: {base_output}/")
        print()
        print("Next step - extract all 27 values and calculate ranges:")
        print("  python results_extractor.py")
        print(f"{'='*60}")
    else:
        # Run single config
        output_dir = base_output / args.config
        asyncio.run(run_experiment(args.config, args.duration, output_dir))

    return 0


if __name__ == "__main__":
    sys.exit(main())
