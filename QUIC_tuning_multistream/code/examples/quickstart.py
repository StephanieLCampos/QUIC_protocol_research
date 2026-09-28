"""
Example: minimal wireless bottleneck run.

The smallest complete demonstration of the workflow: pick a scenario, apply it
as a context manager, and run one QUIC simulation across it. Intended as the
first example to read.

Uses the loopback interface, so it verifies that the pieces connect but does
not produce accurately shaped traffic; see run_app_with_real_bottleneck.py for
the veth-based variant that enforces the link properly.

Connections:
    Imports from: wireless_bottleneck (WirelessBottleneck, get_scenario),
                  simulation.runner (SimulationRunner)
    Invoked by:   run directly (`sudo python3 examples/quickstart.py`)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from wireless_bottleneck import WirelessBottleneck, get_scenario
from simulation.runner import SimulationRunner


async def main():
    # Step 1: Choose a wireless scenario
    scenario = get_scenario("congested_low")
    
    print(f"Setting up: {scenario.description}")
    
    # Step 2: Set up bottleneck and run simulation
    with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
        # Step 3: Run QUIC simulation
        runner = SimulationRunner(
            application_type="file_transfer",
            initial_cw=12000,
            max_ack_delay=0.025,
            loss_reduction_factor=0.5,
        )
        
        result = await runner.run()
        
        # Step 4: Print results
        if result.success:
            print(f"\n✓ Throughput: {result.metrics.throughput / 1_000_000:.2f} Mbps")
            print(f"✓ RTT: {result.metrics.rtt * 1000:.2f} ms")
            print(f"✓ Loss: {result.metrics.packet_loss_rate * 100:.2f}%")
        else:
            print(f"\n✗ Failed: {result.error}")
        
        # Step 5: Get bottleneck metrics
        metrics = bottleneck.get_metrics()
        summary = metrics.summary()
        print(f"\nBottleneck dropped {summary['total_packets']['dropped']} packets")
        print(f"Average queue: {summary['queue']['avg_occupancy_packets']:.1f} packets")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted")
    except Exception as e:
        print(f"\n\nError: {e}")
        sys.exit(1)
