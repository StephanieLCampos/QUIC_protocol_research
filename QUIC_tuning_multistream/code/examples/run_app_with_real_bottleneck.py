"""
Example: application traffic across a genuinely shaped veth link.

The accurate counterpart to run_app_through_bottleneck.py. Rather than shaping
loopback, this creates a network namespace joined by a veth pair and applies
the bottleneck there, so that tc's rate, delay and loss settings are really
enforced and the resulting metrics are trustworthy.

    host namespace                      bottleneck_ns
      veth0  10.200.1.1/24  <------->  veth1  10.200.1.2/24
        ^ tc qdiscs applied here

Requires NET_ADMIN (run the container privileged). The namespace setup
performed here duplicates the sequence in setup_namespace_bottleneck.py and in
several of the test_* scripts; they were written independently as the veth
approach was developed.

Connections:
    Imports from: wireless_bottleneck (WirelessBottleneck, get_scenario,
                  list_scenarios), simulation.runner (SimulationRunner),
                  config.settings (Settings), simulation.server (QuicServer)
    Invoked by:   run directly, inside the project's privileged container
"""

import asyncio
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from wireless_bottleneck import WirelessBottleneck, get_scenario, list_scenarios
from simulation.runner import SimulationRunner
from config.settings import Settings


def setup_veth_namespace():
    """Create network namespace with veth pair."""
    print("Setting up network namespace...")
    commands = [
        ["ip", "netns", "add", "bottleneck_ns"],
        ["ip", "link", "add", "veth0", "type", "veth", "peer", "name", "veth1"],
        ["ip", "link", "set", "veth1", "netns", "bottleneck_ns"],
        ["ip", "addr", "add", "10.200.1.1/24", "dev", "veth0"],
        ["ip", "link", "set", "veth0", "up"],
        ["ip", "netns", "exec", "bottleneck_ns", "ip", "addr", "add", "10.200.1.2/24", "dev", "veth1"],
        ["ip", "netns", "exec", "bottleneck_ns", "ip", "link", "set", "veth1", "up"],
        ["ip", "netns", "exec", "bottleneck_ns", "ip", "link", "set", "lo", "up"],
    ]
    
    try:
        for cmd in commands:
            subprocess.run(cmd, check=True, capture_output=True)
        print("✓ Network namespace ready (veth0: 10.200.1.1 <-> veth1: 10.200.1.2)")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to set up veth: {e}")
        return False


def cleanup_namespace():
    """Clean up network namespace."""
    subprocess.run(["ip", "netns", "delete", "bottleneck_ns"], 
                   capture_output=True, check=False)
    subprocess.run(["ip", "link", "delete", "veth0"],
                   capture_output=True, check=False)


async def run_app_through_scenario(app_type: str, scenario_name: str):
    """
    Run application through wireless bottleneck on veth interface.
    
    Args:
        app_type: video_streaming, file_transfer, or conference_call
        scenario_name: Name of wireless scenario
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
    
    # Use veth0 interface (NOT loopback)
    # Apply bottleneck to veth0 on the host side
    with WirelessBottleneck(scenario.config, interface="veth0") as bottleneck:
        
        # Server runs in the namespace on 10.200.1.2
        # Client connects from host to 10.200.1.2
        # Traffic MUST go through veth0 with bottleneck
        
        print("Starting QUIC server in network namespace...")
        # Start server in namespace using subprocess
        server_cmd = [
            "ip", "netns", "exec", "bottleneck_ns",
            "python3", "-c",
            f"""
import asyncio
import sys
sys.path.insert(0, '/workspace/code')
from simulation.server import QuicServer

async def run_server():
    server = QuicServer(
        host='10.200.1.2',
        port=4433,
        cert_file='/workspace/code/certs/cert.pem',
        key_file='/workspace/code/certs/key.pem',
        max_ack_delay=0.025,
    )
    await server.start()
    print('Server started on 10.200.1.2:4433', flush=True)
    await asyncio.sleep(30)  # Run for 30 seconds
    await server.stop()

asyncio.run(run_server())
"""
        ]
        
        import subprocess
        server_proc = subprocess.Popen(
            server_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Wait for server to start
        await asyncio.sleep(2)
        
        # Create custom settings to connect to namespace IP
        settings = Settings()
        settings.server_host = "10.200.1.2"  # Connect to namespace
        
        # Run QUIC client from host
        runner = SimulationRunner(
            application_type=app_type,
            initial_cw=12000,
            max_ack_delay=0.025,
            loss_reduction_factor=0.5,
            settings=settings,
        )
        
        print(f"Running {app_type} simulation through bottleneck...")
        
        try:
            result = await runner.run()
        except Exception as e:
            print(f"\n✗ Exception during simulation: {e}")
            import traceback
            traceback.print_exc()
            server_proc.terminate()
            return
        finally:
            server_proc.terminate()
            server_proc.wait()
        
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
            
            print("\n✓ Bottleneck Metrics (from tc):")
            print(f"  Queue avg: {summary['queue']['avg_occupancy_packets']:.1f} packets")
            print(f"  Queue max: {summary['queue']['max_occupancy_packets']} packets")
            print(f"  Packets dropped: {summary['total_packets']['dropped']}")
            print(f"  Actual loss: {summary['total_packets']['loss_rate'] * 100:.2f}%")
            
            # Validation
            expected_throughput = scenario.config.capacity_bps / 1_000_000
            actual_throughput = result.metrics.throughput / 1_000_000
            throughput_ratio = actual_throughput / expected_throughput if expected_throughput > 0 else 0
            
            print(f"\n✓ Bottleneck Validation:")
            print(f"  Expected capacity: {expected_throughput:.1f} Mbps")
            print(f"  Actual throughput: {actual_throughput:.2f} Mbps")
            print(f"  Utilization: {throughput_ratio * 100:.1f}%")
            
            if throughput_ratio > 0.95:
                print("  ⚠ WARNING: Throughput suspiciously high - bottleneck may not be working!")
            elif throughput_ratio < 0.2:
                print("  ⚠ NOTE: Low utilization - connection may be limited by other factors")
            else:
                print("  ✓ Bottleneck appears to be working correctly")
        else:
            print(f"\n✗ Simulation failed: {result.error_message}")


async def main():
    """Main entry point."""
    print("\n╔════════════════════════════════════════════════════════════════════╗")
    print("║  Real Bottleneck Test (using veth interface)                      ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    
    import argparse
    parser = argparse.ArgumentParser(description="Run apps through real bottleneck")
    parser.add_argument("--app", 
                       choices=["video_streaming", "file_transfer", "conference_call"],
                       default="file_transfer",
                       help="Application type to test")
    parser.add_argument("--scenario",
                       choices=list_scenarios(),
                       default="congested_low",
                       help="Scenario to use")
    
    args = parser.parse_args()
    
    # Set up network namespace
    if not setup_veth_namespace():
        print("Failed to set up network namespace")
        return 1
    
    try:
        # Run the test
        await run_app_through_scenario(args.app, args.scenario)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 1
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        cleanup_namespace()
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
