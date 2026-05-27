"""
Wireless bottleneck implementation using Linux tc (Traffic Control).

This module uses the `tc` command to configure network emulation
with precise control over bandwidth, delay, loss, and queueing.

Note: Requires Linux with root/sudo access and iproute2 package installed.
For macOS/Windows, consider using network namespaces in Docker or
a Linux VM.
"""

import subprocess
import time
import threading
import shutil
from typing import Optional
from pathlib import Path

from .config import BottleneckConfig, LossModel, QueueDiscipline
from .monitor import BottleneckMonitor, BottleneckMetrics


class WirelessBottleneck:
    """
    Wireless bottleneck using Linux tc (Traffic Control).
    
    This class configures a network interface to emulate wireless
    link conditions including bandwidth limits, delay, loss, and
    queue management.
    """
    
    def __init__(
        self,
        config: BottleneckConfig,
        interface: str = "lo",  # loopback for localhost testing
        monitor: Optional[BottleneckMonitor] = None,
        apply_ingress: bool = False,  # Apply ingress policing instead of egress shaping
    ):
        """
        Initialize the wireless bottleneck.
        
        Args:
            config: Bottleneck configuration
            interface: Network interface to apply rules to
            monitor: Optional monitor for instrumentation
            apply_ingress: If True, apply ingress policing instead of egress shaping
        """
        self.config = config
        self.interface = interface
        self.monitor = monitor or BottleneckMonitor()
        self.apply_ingress = apply_ingress
        
        self._active = False
        self._variation_thread: Optional[threading.Thread] = None
        self._stop_variation = threading.Event()
    
    def setup(self):
        """
        Set up the bottleneck using tc commands.
        
        This configures:
        - netem for delay, loss, and rate limiting (all in one qdisc)
        """
        # First, clear any existing tc rules
        self.teardown()
        
        if self.apply_ingress:
            print(f"Setting up INGRESS policing on {self.interface}...")
            self._setup_ingress_policing()
        else:
            print(f"Setting up EGRESS shaping on {self.interface}...")
            # Use simplified netem-only approach (works better on veth)
            self._setup_netem_with_rate()
        
        # Start time-varying behavior if enabled
        if self.config.time_varying:
            self._start_capacity_variation()
        
        # Start monitoring
        self.monitor.start()
        
        self._active = True
        direction = "INGRESS" if self.apply_ingress else "EGRESS"
        print(f"Bottleneck active ({direction}): {self.config.capacity_bps / 1_000_000:.1f} Mbps, "
              f"{self.config.propagation_delay * 1000:.1f}ms delay, "
              f"{self.config.loss_rate * 100:.1f}% loss")
    
    def _setup_netem_with_rate(self):
        """Set up netem with HTB for rate limiting (more reliable approach)."""
        # Convert values to tc format
        delay_ms = int(self.config.propagation_delay * 1000)
        rate_kbps = self.config.capacity_bps // 1000
        loss_pct = self.config.loss_rate * 100
        
        # Step 1: Create HTB root qdisc for rate limiting
        htb_params = [
            "tc", "qdisc", "add", "dev", self.interface,
            "root", "handle", "1:", "htb", "default", "11"
        ]
        
        try:
            self._run_tc_command(htb_params)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Failed to set up HTB root: {e}")
            raise
        
        # Step 2: Create HTB class for rate limiting
        htb_class = [
            "tc", "class", "add", "dev", self.interface,
            "parent", "1:", "classid", "1:11", "htb",
            "rate", f"{rate_kbps}kbit",
            "ceil", f"{rate_kbps}kbit",  # Hard limit
            "burst", "15k"  # Allow small bursts
        ]
        
        try:
            self._run_tc_command(htb_class)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Failed to set up HTB class: {e}")
            raise
        
        # Step 3: Add netem for delay and loss under HTB
        netem_params = [
            "tc", "qdisc", "add", "dev", self.interface,
            "parent", "1:11", "handle", "10:", "netem",
            "delay", f"{delay_ms}ms",
            "limit", str(self.config.queue_size_packets)
        ]
        
        # Add loss if configured
        if self.config.loss_rate > 0:
            netem_params.extend(["loss", f"{loss_pct}%"])
        
        try:
            self._run_tc_command(netem_params)
            print(f"Successfully configured bottleneck: {rate_kbps} kbit/s, {delay_ms}ms delay, {loss_pct}% loss")
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Failed to set up netem: {e}")
            raise
    
    def _setup_ingress_policing(self):
        """Set up ingress policing for rate limiting incoming traffic."""
        rate_kbps = self.config.capacity_bps // 1000
        burst_bytes = self.config.capacity_bps // 8  # 1 second worth of data
        
        # Remove any existing ingress qdisc
        try:
            self._run_tc_command(["tc", "qdisc", "del", "dev", self.interface, "ingress"])
        except subprocess.CalledProcessError:
            pass  # No existing ingress qdisc
        
        # Add ingress qdisc
        ingress_qdisc = [
            "tc", "qdisc", "add", "dev", self.interface,
            "ingress"
        ]
        
        try:
            self._run_tc_command(ingress_qdisc)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Failed to set up ingress qdisc: {e}")
            raise
        
        # Add ingress policing with rate limit
        police_filter = [
            "tc", "filter", "add", "dev", self.interface,
            "parent", "ffff:", "protocol", "ip", "prio", "1",
            "u32", "match", "u32", "0", "0",
            "police", "rate", f"{rate_kbps}kbit",
            "burst", f"{burst_bytes}",
            "drop", "flowid", ":1"
        ]
        
        try:
            self._run_tc_command(police_filter)
            print(f"Successfully configured ingress policing: {rate_kbps} kbit/s")
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Failed to set up ingress policing: {e}")
            raise
    
    def _setup_qdisc(self):
        """Set up the queueing discipline."""
        qdisc = self.config.queue_discipline.value
        
        if qdisc == "fifo":
            # pfifo: packet-based FIFO
            cmd = [
                "tc", "qdisc", "add", "dev", self.interface,
                "root", "handle", "1:", "pfifo",
                "limit", str(self.config.queue_size_packets)
            ]
        elif qdisc == "red":
            # RED: Random Early Detection
            cmd = [
                "tc", "qdisc", "add", "dev", self.interface,
                "root", "handle", "1:", "red",
                "limit", str(self.config.queue_size_packets),
                "min", str(self.config.red_min_threshold),
                "max", str(self.config.red_max_threshold),
                "probability", str(self.config.red_max_probability),
                "avpkt", "1500"
            ]
        elif qdisc == "codel":
            # CoDel: Controlled Delay
            cmd = [
                "tc", "qdisc", "add", "dev", self.interface,
                "root", "handle", "1:", "codel",
                "limit", str(self.config.queue_size_packets),
                "target", f"{int(self.config.codel_target_delay * 1000)}ms",
                "interval", f"{int(self.config.codel_interval * 1000)}ms"
            ]
        elif qdisc == "pie":
            # PIE: Proportional Integral controller Enhanced
            cmd = [
                "tc", "qdisc", "add", "dev", self.interface,
                "root", "handle", "1:", "pie",
                "limit", str(self.config.queue_size_packets)
            ]
        else:
            raise ValueError(f"Unknown queue discipline: {qdisc}")
        
        try:
            self._run_tc_command(cmd)
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to set up qdisc: {e}")
            print("Continuing with default qdisc...")
    
    def _setup_netem(self):
        """Set up netem for delay and loss emulation."""
        # Convert propagation delay to ms
        delay_ms = int(self.config.propagation_delay * 1000)
        
        netem_params = [
            "tc", "qdisc", "add", "dev", self.interface,
            "parent", "1:", "handle", "10:", "netem",
            "delay", f"{delay_ms}ms"
        ]
        
        # Add loss model
        if self.config.loss_rate > 0:
            if self.config.loss_model == LossModel.RANDOM:
                loss_pct = self.config.loss_rate * 100
                netem_params.extend(["loss", f"{loss_pct}%"])
            elif self.config.loss_model == LossModel.GILBERT_ELLIOTT:
                # Gilbert-Elliott model parameters
                p = self.config.ge_good_to_bad * 100  # Good to bad
                r = self.config.ge_bad_to_good * 100  # Bad to good
                h = (1.0 - self.config.ge_loss_in_bad) * 100  # 1-h = loss in bad
                k = 100.0  # No loss in good state
                netem_params.extend([
                    "loss", "gemodel", f"{p}%", f"{r}%", f"{h}%", f"{k}%"
                ])
        
        try:
            self._run_tc_command(netem_params)
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to set up netem: {e}")
    
    def _setup_rate_limit(self):
        """Set up rate limiting using TBF (Token Bucket Filter)."""
        # Convert capacity to kbps for tc
        rate_kbps = self.config.capacity_bps // 1000
        
        # Burst size: allow 1.5x MTU
        burst_bytes = int(1500 * 1.5)
        
        # Buffer size: enough for BDP (Bandwidth-Delay Product)
        buffer_bytes = int((self.config.capacity_bps * self.config.propagation_delay) / 8)
        buffer_bytes = max(buffer_bytes, 3000)  # Minimum 3KB
        
        tbf_params = [
            "tc", "qdisc", "add", "dev", self.interface,
            "parent", "10:", "handle", "20:", "tbf",
            "rate", f"{rate_kbps}kbit",
            "burst", str(burst_bytes),
            "latency", "50ms"  # Maximum queueing delay
        ]
        
        try:
            self._run_tc_command(tbf_params)
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to set up rate limit: {e}")
    
    def _start_capacity_variation(self):
        """Start thread for time-varying capacity (or realistic multi-param variation)."""
        self._stop_variation.clear()
        target = (
            self._vary_realistic_conditions
            if self.config.channel_quality_variation
            else self._vary_capacity
        )
        self._variation_thread = threading.Thread(target=target, daemon=True)
        self._variation_thread.start()
    
    def _vary_capacity(self):
        """Thread function to vary capacity over time."""
        start_time = time.time()
        update_interval = 0.5  # Update every 500ms
        
        while not self._stop_variation.is_set():
            elapsed = time.time() - start_time
            new_capacity = self.config.get_capacity_at_time(elapsed)
            
            # Update rate limit
            self._update_rate_limit(new_capacity)
            
            time.sleep(update_interval)
    
    def _update_htb_rate(self, new_capacity_bps: int):
        """Update the HTB class rate limit dynamically."""
        rate_kbps = new_capacity_bps // 1000
        try:
            self._run_tc_command([
                "tc", "class", "change", "dev", self.interface,
                "parent", "1:", "classid", "1:11", "htb",
                "rate", f"{rate_kbps}kbit",
                "ceil", f"{rate_kbps}kbit",
                "burst", "15k"
            ])
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to update HTB rate: {e}")

    def _update_netem(self, delay_ms: int, jitter_ms: int, loss_pct: float):
        """Update netem delay, jitter, and loss dynamically via tc qdisc change."""
        try:
            self._run_tc_command([
                "tc", "qdisc", "change", "dev", self.interface,
                "parent", "1:11", "handle", "10:", "netem",
                "delay", f"{delay_ms}ms", f"{jitter_ms}ms",
                "loss", f"{loss_pct:.3f}%",
                "limit", str(self.config.queue_size_packets)
            ])
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to update netem: {e}")

    def _vary_realistic_conditions(self):
        """
        Thread function: evolve all link parameters together via a single
        channel-quality proxy q ∈ [0, 1] using an Ornstein-Uhlenbeck
        (mean-reverting random walk) process.

        Parameter mappings (calibrated against LTE/802.11 field data):
          bandwidth ∝ q^0.8          (sub-linear — MCS step function approximation)
          loss      ∝ (1-q)^1.5      (super-linear — rare at high SNR, severe at low)
          delay, jitter: linear in q
        """
        import random
        rng = random.Random(self.config.channel_quality_seed)
        q = float(self.config.channel_quality_initial)
        cfg = self.config
        update_interval = 0.5   # seconds per tick
        theta = 0.08            # mean-reversion strength
        mu = 0.65               # long-run mean quality (slightly below mid-range)

        while not self._stop_variation.is_set():
            # Ornstein-Uhlenbeck step: dq = θ(μ − q) + σ·N(0,1)
            dq = theta * (mu - q) + cfg.channel_quality_step * rng.gauss(0, 1)
            q = max(0.0, min(1.0, q + dq))

            # Derive parameters from q
            capacity = int(
                cfg.cqv_min_capacity_bps
                + (cfg.cqv_max_capacity_bps - cfg.cqv_min_capacity_bps) * (q ** 0.8)
            )
            delay_ms = int(
                cfg.cqv_max_delay_ms
                - (cfg.cqv_max_delay_ms - cfg.cqv_min_delay_ms) * q
            )
            jitter_ms = max(1, int(
                cfg.cqv_max_jitter_ms
                - (cfg.cqv_max_jitter_ms - cfg.cqv_min_jitter_ms) * q
            ))
            loss_pct = (
                cfg.cqv_min_loss_rate
                + (cfg.cqv_max_loss_rate - cfg.cqv_min_loss_rate) * ((1.0 - q) ** 1.5)
            ) * 100.0

            self._update_htb_rate(capacity)
            self._update_netem(delay_ms, jitter_ms, loss_pct)

            print(
                f"[RealisticChannel] q={q:.2f}  "
                f"bw={capacity // 1_000_000:.1f}Mbps  "
                f"delay={delay_ms}ms  jitter={jitter_ms}ms  loss={loss_pct:.2f}%"
            )
            time.sleep(update_interval)

    def _update_rate_limit(self, new_capacity_bps: int):
        """Update the rate limit dynamically."""
        # First delete existing TBF
        try:
            self._run_tc_command([
                "tc", "qdisc", "del", "dev", self.interface,
                "parent", "10:", "handle", "20:"
            ])
        except subprocess.CalledProcessError:
            pass  # Ignore if doesn't exist
        
        # Add new TBF with updated rate
        rate_kbps = new_capacity_bps // 1000
        burst_bytes = int(1500 * 1.5)
        
        try:
            self._run_tc_command([
                "tc", "qdisc", "add", "dev", self.interface,
                "parent", "10:", "handle", "20:", "tbf",
                "rate", f"{rate_kbps}kbit",
                "burst", str(burst_bytes),
                "latency", "50ms"
            ])
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to update rate limit: {e}")
    
    def teardown(self):
        """Remove all tc rules and restore normal networking."""
        if self.config.time_varying and self._variation_thread:
            self._stop_variation.set()
            self._variation_thread.join(timeout=1.0)
        
        try:
            self._run_tc_command([
                "tc", "qdisc", "del", "dev", self.interface, "root"
            ])
            print(f"Bottleneck removed from {self.interface}")
        except subprocess.CalledProcessError:
            pass  # Ignore if no rules exist
        
        self._active = False
    
    def _run_tc_command(self, cmd: list[str]):
        """
        Run a tc command with sudo if needed.
        
        Args:
            cmd: Command to run (list of strings)
        """
        # Check if we need sudo
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
        except subprocess.CalledProcessError as e:
            # Try with sudo if permission denied
            if "Operation not permitted" in e.stderr or "Permission denied" in e.stderr:
                if shutil.which("sudo") is None:
                    raise
                cmd_with_sudo = ["sudo"] + cmd
                subprocess.run(cmd_with_sudo, check=True)
            else:
                raise
    
    def get_current_stats(self) -> dict:
        """
        Get current tc statistics.
        
        Returns:
            Dictionary with queue statistics
        """
        try:
            result = subprocess.run(
                ["tc", "-s", "qdisc", "show", "dev", self.interface],
                capture_output=True,
                text=True,
                check=True
            )
            return {"raw_output": result.stdout}
        except subprocess.CalledProcessError:
            return {}
    
    def is_active(self) -> bool:
        """Check if bottleneck is currently active."""
        return self._active
    
    def get_metrics(self) -> BottleneckMetrics:
        """Get collected metrics from monitor."""
        return self.monitor.get_metrics()
    
    def __enter__(self):
        """Context manager entry."""
        self.setup()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.teardown()
