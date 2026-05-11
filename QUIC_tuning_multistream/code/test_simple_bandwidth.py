"""
Simple test to verify bottleneck actually limits traffic through veth.

Uses basic UDP traffic to test bandwidth limiting.
"""

import subprocess
import time
import signal
import sys


def setup_veth():
    """Create veth pair."""
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
    
    for cmd in commands:
        subprocess.run(cmd, check=True, capture_output=True)
    
    print("✓ veth pair created")


def apply_bottleneck(rate_mbps=10, delay_ms=20):
    """Apply tc bottleneck to veth0."""
    rate_kbps = rate_mbps * 1000
    
    commands = [
        ["tc", "qdisc", "add", "dev", "veth0", "root", "handle", "1:", "tbf",
         "rate", f"{rate_kbps}kbit", "burst", "2250", "latency", "50ms"],
        ["tc", "qdisc", "add", "dev", "veth0", "parent", "1:", "handle", "10:", "netem",
         "delay", f"{delay_ms}ms", "limit", "100"],
    ]
    
    for cmd in commands:
        subprocess.run(cmd, check=True, capture_output=True)
    
    print(f"✓ Bottleneck applied: {rate_mbps} Mbps, {delay_ms}ms delay")


def show_tc_config():
    """Show tc configuration."""
    result = subprocess.run(
        ["tc", "qdisc", "show", "dev", "veth0"],
        capture_output=True,
        text=True,
        check=True
    )
    print("\nTC Configuration:")
    print(result.stdout)


def test_bandwidth():
    """Test bandwidth through bottleneck using iperf3."""
    print("Testing bandwidth...")
    print("Starting iperf3 server in namespace...")
    
    # Start iperf3 server in namespace
    server_proc = subprocess.Popen(
        ["ip", "netns", "exec", "bottleneck_ns", "iperf3", "-s", "-1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    time.sleep(1)  # Give server time to start
    
    try:
        # Run iperf3 client
        print("Running iperf3 client...")
        result = subprocess.run(
            ["iperf3", "-c", "10.200.1.2", "-t", "5"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        print("\n" + "=" * 70)
        print("BANDWIDTH TEST RESULTS")
        print("=" * 70)
        print(result.stdout)
        
        # Parse throughput from output
        for line in result.stdout.split("\n"):
            if "sender" in line or "receiver" in line:
                parts = line.split()
                for i, part in enumerate(parts):
                    if "Mbits/sec" in part or "Gbits/sec" in part:
                        throughput = float(parts[i-1])
                        if "Gbits" in part:
                            throughput *= 1000
                        return throughput
        
    finally:
        server_proc.terminate()
        server_proc.wait()
    
    return None


def cleanup():
    """Clean up network namespace."""
    print("\nCleaning up...")
    subprocess.run(["ip", "netns", "delete", "bottleneck_ns"], 
                   capture_output=True, check=False)
    subprocess.run(["ip", "link", "delete", "veth0"],
                   capture_output=True, check=False)
    print("✓ Cleanup complete")


def main():
    print("\n" + "=" * 70)
    print("Simple Bandwidth Test Through Bottleneck")
    print("=" * 70)
    print()
    
    try:
        # Check if iperf3 is available
        try:
            subprocess.run(["iperf3", "--version"], 
                          capture_output=True, check=True)
        except FileNotFoundError:
            print("✗ iperf3 not found. Installing...")
            subprocess.run(["apt-get", "update"], check=True)
            subprocess.run(["apt-get", "install", "-y", "iperf3"], check=True)
            print("✓ iperf3 installed")
        
        # Set up network
        setup_veth()
        
        # Test without bottleneck
        print("\n" + "=" * 70)
        print("TEST 1: No Bottleneck (baseline)")
        print("=" * 70)
        throughput_baseline = test_bandwidth()
        
        # Apply bottleneck
        print("\n" + "=" * 70)
        print("TEST 2: With 10 Mbps Bottleneck")
        print("=" * 70)
        apply_bottleneck(rate_mbps=10, delay_ms=20)
        show_tc_config()
        throughput_limited = test_bandwidth()
        
        # Summary
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        if throughput_baseline and throughput_limited:
            print(f"Baseline throughput: {throughput_baseline:.1f} Mbps")
            print(f"Limited throughput:  {throughput_limited:.1f} Mbps")
            print(f"Reduction: {(1 - throughput_limited/throughput_baseline) * 100:.1f}%")
            print()
            if throughput_limited < 12:  # Allow some overhead
                print("✓ Bottleneck is working correctly!")
            else:
                print("⚠ WARNING: Bottleneck may not be working properly")
        else:
            print("Could not parse throughput results")
        
    except subprocess.CalledProcessError as e:
        print(f"\n✗ Error: {e}")
        print(f"  stdout: {e.stdout}")
        print(f"  stderr: {e.stderr}")
        return 1
    except KeyboardInterrupt:
        print("\n\nTest interrupted")
        return 1
    finally:
        cleanup()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
