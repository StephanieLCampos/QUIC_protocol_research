"""
Wireless bottleneck enforcement via Linux Traffic Control (tc).

Translates a `BottleneckConfig` into concrete tc queueing disciplines on a
network interface, so that traffic crossing that interface really is rate
limited, delayed and dropped as configured. This is genuine kernel-level
shaping rather than a simulation inside the application.

Qdisc layout
------------
A two-level hierarchy is installed on the target interface:

    root  handle 1:   TBF    token bucket, enforces the link rate
    child handle 10:  netem  adds propagation delay and packet loss

TBF is placed at the root and netem beneath it. The ordering matters: rate
limiting must be applied before the delay/loss stage so that queueing builds up
behind the token bucket, which is what produces realistic bufferbloat.

Superseded methods
------------------
`_setup_qdisc`, `_setup_netem` and `_setup_rate_limit` are earlier
implementations of this setup, retained but no longer called by `setup()`.
They placed TBF beneath netem and configured the queue discipline directly,
an arrangement that proved unreliable with classless qdiscs. `_setup_qdisc`
is explicitly marked deprecated in its own docstring. They are the only
consumers of the RED, CoDel and PIE tuning fields on BottleneckConfig, so
those settings have no effect on the path that currently runs.

Time-varying capacity
---------------------
When a scenario sets `time_varying`, a background thread re-applies the link
rate every 500ms by calling `_update_rate_limit`, which edits the root TBF in
place with `tc qdisc change`.

In-place modification is required rather than convenient. Deleting a root qdisc
removes the whole hierarchy beneath it, so a delete-and-re-add cycle would tear
down the netem child (delay and loss) on every tick. `change` leaves children
untouched.

Historical note: earlier revisions of this method addressed `parent 10:` /
`handle 20:`, the handles of the superseded layout below, and so never touched
the root TBF at `1:`. The `varying` scenario consequently ran at a fixed rate
despite reporting otherwise. Results produced before this was corrected should
not be read as performance under oscillating capacity. Verify a live run with
`tc -s qdisc show dev <iface>`; the root TBF rate should sweep between roughly
12 and 28 Mbps.

Privileges: tc requires elevated permissions. `_run_tc_command` first attempts
the command directly and retries under sudo only when the kernel reports a
permissions failure, which keeps it usable both as root in a container and as a
normal user on a workstation.

Connections:
    Imports from: .config (BottleneckConfig, LossModel, QueueDiscipline),
                  .monitor (BottleneckMonitor, BottleneckMetrics)
    Imported by:  wireless_bottleneck/__init__.py, .cli, .validate, examples/
    Requires:     Linux, iproute2 (tc), and root or sudo
"""

import subprocess
import time
import threading
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
    ):
        """
        Initialize the wireless bottleneck.
        
        Args:
            config: Bottleneck configuration
            interface: Network interface to apply rules to
            monitor: Optional monitor for instrumentation
        """
        self.config = config
        self.interface = interface
        self.monitor = monitor or BottleneckMonitor()
        
        self._active = False
        self._variation_thread: Optional[threading.Thread] = None
        self._stop_variation = threading.Event()
    
    def setup(self):
        """
        Set up the bottleneck using tc commands.
        
        This configures:
        - Token bucket filter (TBF) for rate limiting
        - netem for delay, loss, and jitter
        - Queue discipline (FIFO, RED, CoDel, PIE)
        """
        # Clear first: tc rejects adding a root qdisc where one already
        # exists, so a stale configuration from a previous crashed run would
        # otherwise make setup fail.
        self.teardown()
        
        print(f"Setting up wireless bottleneck on {self.interface}...")
        
        # TBF at the root with netem as its child. The reverse arrangement
        # (used by the superseded methods further down) proved unreliable,
        # because a classless qdisc cannot reliably parent another qdisc.
        self._setup_rate_limit_root()
        self._setup_netem_child()
        
        # Start time-varying behavior if enabled
        if self.config.time_varying:
            self._start_capacity_variation()
        
        # Start monitoring
        self.monitor.start()
        
        self._active = True
        print(f"Bottleneck active: {self.config.capacity_bps / 1_000_000:.1f} Mbps, "
              f"{self.config.propagation_delay * 1000:.1f}ms delay, "
              f"{self.config.loss_rate * 100:.1f}% loss")
    
    def _setup_rate_limit_root(self):
        """Set up TBF as root qdisc for rate limiting."""
        # Convert capacity to kbps for tc
        rate_kbps = self.config.capacity_bps // 1000
        
        # Burst is the token bucket depth: how much may be sent at once after
        # an idle period. One and a half MTUs is small enough to hold the link
        # close to its nominal rate while still allowing a full packet through.
        burst_bytes = int(1500 * 1.5)
        
        # Buffer sized to the bandwidth-delay product, the standard rule for
        # how much data is in flight on a link of this rate and delay. Floored
        # at 3KB so that very low-capacity scenarios still admit a few packets.
        #
        # Note: buffer_bytes is computed but not passed to tc below; the queue
        # depth actually enforced comes from netem's `limit` in the child qdisc.
        buffer_bytes = int((self.config.capacity_bps * self.config.propagation_delay) / 8)
        buffer_bytes = max(buffer_bytes, 3000)
        
        tbf_params = [
            "tc", "qdisc", "add", "dev", self.interface,
            "root", "handle", "1:", "tbf",
            "rate", f"{rate_kbps}kbit",
            "burst", str(burst_bytes),
            "latency", "50ms"  # Maximum queueing delay
        ]
        
        try:
            self._run_tc_command(tbf_params)
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to set up rate limit: {e}")
    
    def _setup_netem_child(self):
        """Set up netem as child of TBF for delay and loss."""
        # Convert propagation delay to ms
        delay_ms = int(self.config.propagation_delay * 1000)
        
        netem_params = [
            "tc", "qdisc", "add", "dev", self.interface,
            "parent", "1:", "handle", "10:", "netem",
            "delay", f"{delay_ms}ms",
            "limit", str(self.config.queue_size_packets)
        ]
        
        # Add loss model
        if self.config.loss_rate > 0:
            if self.config.loss_model == LossModel.RANDOM:
                loss_pct = self.config.loss_rate * 100
                netem_params.extend(["loss", f"{loss_pct}%"])
            elif self.config.loss_model == LossModel.GILBERT_ELLIOTT:
                # Gilbert-Elliott: a two-state burst-loss model, where the link
                # alternates between a "good" state that rarely drops and a
                # "bad" state that drops heavily. This produces the correlated
                # loss bursts characteristic of real radio links, which uniform
                # random loss cannot reproduce.
                #
                # netem's gemodel takes four percentages: p, r, 1-h, 1-k, where
                # p and r are the transition probabilities between states and
                # the remaining two describe loss within each state.
                p = self.config.ge_good_to_bad * 100   # good -> bad transition
                r = self.config.ge_bad_to_good * 100   # bad -> good transition
                h = (1.0 - self.config.ge_loss_in_bad) * 100  # loss while bad
                k = 100.0                              # no loss while good
                netem_params.extend([
                    "loss", "gemodel", f"{p}%", f"{r}%", f"{h}%", f"{k}%"
                ])
        
        try:
            self._run_tc_command(netem_params)
        except subprocess.CalledProcessError as e:
            # Warn rather than raise: a partially configured bottleneck is
            # reported loudly but still lets the caller proceed, which matters
            # on platforms where only some netem features are available.
            print(f"Warning: Failed to set up netem: {e}")
    
    # ------------------------------------------------------------------
    # Superseded setup path
    #
    # The three methods below are the original qdisc arrangement, in which the
    # queue discipline was installed at the root and TBF hung beneath netem.
    # They are no longer called by setup(); _setup_rate_limit_root and
    # _setup_netem_child replace them. They are retained for reference and are
    # the only readers of the RED/CoDel/PIE tuning fields on BottleneckConfig,
    # which therefore have no effect on the active configuration path.
    # ------------------------------------------------------------------
    
    def _setup_qdisc(self):
        """Set up the queueing discipline (DEPRECATED - now using TBF+netem)."""
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
        """Start thread for time-varying capacity."""
        self._stop_variation.clear()
        self._variation_thread = threading.Thread(
            target=self._vary_capacity,
            daemon=True
        )
        self._variation_thread.start()
    
    def _vary_capacity(self):
        """
        Background loop that re-applies the link rate as it changes over time.

        Samples the scenario's capacity curve every 500ms and pushes the new
        rate onto the root TBF via _update_rate_limit. Runs on a daemon thread
        so it cannot keep the process alive, and exits promptly when the stop
        event is set during teardown.
        """
        start_time = time.time()
        # 500ms is a compromise: frequent enough to track the sinusoid closely
        # (12 steps across the `varying` scenario's 6-second period), but not so
        # frequent that reconfiguring the qdisc disturbs the traffic being
        # measured.
        update_interval = 0.5
        
        while not self._stop_variation.is_set():
            elapsed = time.time() - start_time
            new_capacity = self.config.get_capacity_at_time(elapsed)
            
            # Update rate limit
            self._update_rate_limit(new_capacity)
            
            time.sleep(update_interval)
    
    def _update_rate_limit(self, new_capacity_bps: int):
        """
        Change the root token bucket's rate in place.

        Targets the root TBF at handle `1:`, which is the qdisc `setup()`
        installs and the one actually enforcing the link rate.

        Uses `tc qdisc change` rather than a delete-and-re-add pair. The
        distinction is not cosmetic: deleting a *root* qdisc removes the entire
        hierarchy beneath it, which would take the netem child (delay and loss)
        down with it on every tick. `change` edits the existing qdisc in place
        and leaves its children untouched.

        `burst` and `latency` are restated because `change` replaces the full
        parameter set; omitting them would silently reset them to defaults.

        A failed update is warned about rather than raised, so a transient tc
        error costs one tick of variation instead of killing the run.
        """
        rate_kbps = new_capacity_bps // 1000
        burst_bytes = int(1500 * 1.5)

        try:
            self._run_tc_command([
                "tc", "qdisc", "change", "dev", self.interface,
                "root", "handle", "1:", "tbf",
                "rate", f"{rate_kbps}kbit",
                "burst", str(burst_bytes),
                "latency", "50ms",
            ])
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to update rate limit: {e}")
    
    def teardown(self):
        """Remove all tc rules and restore normal networking."""
        if self.config.time_varying and self._variation_thread:
            self._stop_variation.set()
            self._variation_thread.join(timeout=1.0)
        
        # Deleting the root qdisc removes the whole hierarchy beneath it, so
        # one command clears both TBF and netem.
        try:
            self._run_tc_command([
                "tc", "qdisc", "del", "dev", self.interface, "root"
            ])
            print(f"Bottleneck removed from {self.interface}")
        except subprocess.CalledProcessError:
            # No rules present. teardown() is called defensively at the start
            # of setup() and again on exit, so this is the normal case rather
            # than an error.
            pass
        
        self._active = False
    
    def _run_tc_command(self, cmd: list[str]):
        """
        Run a tc command with sudo if needed.
        
        Args:
            cmd: Command to run (list of strings)
        """
        # Attempt unprivileged first and escalate only on a permissions
        # error. This lets the same code run as root inside the project's
        # container and as an ordinary user on a workstation, without
        # prompting for a password when it is not needed.
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
        except subprocess.CalledProcessError as e:
            if "Operation not permitted" in e.stderr or "Permission denied" in e.stderr:
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
        """
        Get collected metrics from monitor, enriched with tc statistics.
        """
        metrics = self.monitor.get_metrics()
        
        # Enrich with actual tc statistics
        try:
            result = subprocess.run(
                ["tc", "-s", "qdisc", "show", "dev", self.interface],
                capture_output=True,
                text=True,
                check=True
            )
            
            # tc reports statistics only as free-form text, so the counters are
            # recovered by scanning tokens rather than by any structured API.
            # The line of interest looks like:
            #   Sent 12345 bytes 67 pkt (dropped 8, overlimits 0 requeues 0)
            # Each field is parsed defensively: a format change degrades the
            # affected counter to its previous value instead of raising.
            for line in result.stdout.split('\n'):
                if 'Sent' in line and 'bytes' in line and 'pkt' in line:
                    # Split by spaces and find the indices
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == 'Sent' and i + 3 < len(parts):
                            try:
                                metrics.total_bytes_transmitted = int(parts[i + 1])
                                metrics.total_packets_transmitted = int(parts[i + 3])
                            except ValueError:
                                pass
                        if part == 'dropped' and i + 1 < len(parts):
                            try:
                                dropped_str = parts[i + 1].rstrip(',')
                                metrics.total_packets_dropped = int(dropped_str)
                            except ValueError:
                                pass
        except subprocess.CalledProcessError:
            pass
        
        # Arrivals are not reported by tc directly; anything the link either
        # forwarded or discarded must have arrived, so the two are summed.
        if metrics.total_packets_transmitted > 0 or metrics.total_packets_dropped > 0:
            metrics.total_packets_arrived = metrics.total_packets_transmitted + metrics.total_packets_dropped
        
        return metrics
    
    def __enter__(self):
        """Context manager entry."""
        self.setup()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.teardown()
