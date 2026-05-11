"""
Run 3-connection simulations through wireless bottleneck scenarios.

This demonstrates how to test the 3-connection setup under different
wireless conditions (capacity, delay, loss).

Usage:
    docker run -it --rm --privileged -v $(pwd):/workspace quic-wireless \
        bash -c "cd /workspace/3_conn_code && python3 examples/run_3conn_through_bottleneck.py --scenario congested_low"
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from wireless_bottleneck import get_scenario, list_scenarios, WirelessBottleneck
from config.multi_connection_config import MultiConnectionConfig
from simulation.process_orchestrator import ProcessOrchestrator


async def run_3conn_through_scenario(scenario_name: str, duration: float = 10.0):
    """
    Run 3-connection simulation through a wireless bottleneck scenario.
    
    Args:
        scenario_name: Name of wireless scenario
        duration: Simulation duration in seconds
    """
    scenario = get_scenario(scenario_name)
    
    print("\n" + "=" * 70)
    print(f"3-Connection Simulation through {scenario_name.upper()}")
    print("=" * 70)
    print(f"Description: {scenario.description}")
    print(f"Capacity: {scenario.config.capacity_bps / 1_000_000:.1f} Mbps")
    print(f"RTT: {scenario.config.propagation_delay * 2000:.1f} ms")
    print(f"Loss: {scenario.config.loss_rate * 100:.1f}%")
    print(f"Duration: {duration}s")
    print()
    
    # Set up bottleneck
    with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
        print("✓ Bottleneck active on lo")
        
        # Create 3-connection config
        config = MultiConnectionConfig()
        config.simulation_duration = duration
        
        # Create orchestrator
        orchestrator = ProcessOrchestrator(
            config=config,
            network_scenario=scenario_name,
        )
        
        print("Starting 3-connection simulation...")
        print()
        
        try:
            await orchestrator.run()
            
            print("\n" + "=" * 70)
            print("Simulation Results")
            print("=" * 70)
            
            # The orchestrator logs results to files
            # Check output/epoch_history_*.json for detailed metrics
            print("✓ Simulation completed successfully")
            print("  Check output/ directory for detailed epoch metrics")
            
        except Exception as e:
            print(f"✗ Simulation failed: {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    return 0


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Run 3-connection simulation through wireless bottleneck"
    )
    parser.add_argument(
        "--scenario",
        choices=list_scenarios(),
        default="stable_high",
        help="Wireless scenario to use"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Simulation duration in seconds"
    )
    
    args = parser.parse_args()
    
    print("\n╔════════════════════════════════════════════════════════════════════╗")
    print("║  3-Connection QUIC Simulation with Wireless Bottleneck            ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    
    return await run_3conn_through_scenario(args.scenario, args.duration)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
