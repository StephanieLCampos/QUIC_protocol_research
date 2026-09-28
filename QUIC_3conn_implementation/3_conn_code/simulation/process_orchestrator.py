"""
Process orchestrator for managing multiple QUIC connection processes.

Coordinates worker processes, handles IPC, and manages simulation lifecycle.

This is the control centre of the Generation 2 system. It owns the shared QUIC
server, spawns one worker process per connection, relays parameter changes,
collects telemetry, applies the network bottleneck, and assembles the final
result set.

Run sequence
------------
    1. apply the wireless bottleneck (interface chosen by deployment mode)
    2. start the shared QUIC server
    3. spawn three worker processes, one per connection
    4. release the start barrier so all three begin together
    5. drive either the ML control loop or a plain metrics loop for `duration`
    6. signal STOP, drain results, join and then terminate stragglers
    7. read tc counters, await the RTT probe, export Q-learning history
    8. build and return the combined result

Deployment modes
----------------
The same class serves three topologies, selected by constructor flags and the
RUN_MODE environment variable:

    normal        server and all three clients in one process tree
    server_only   only the QUIC server, for the docker-compose server container
    clients_only  only the workers, connecting to a server container

Interface selection follows from this: `eth0` under docker-compose, `veth0` in
a single privileged container, and `lo` when running locally on macOS. Only the
first two shape traffic accurately; loopback applies RTT but not true rate
limiting.

Shutdown design
---------------
Shutdown is deliberately concurrent rather than sequential. FINISHED messages
are drained on a daemon thread that runs *while* workers are still exiting,
because a worker terminated mid-write can leave a partial pipe write that would
block a reader indefinitely. Joins are likewise performed on threads with
bounded timeouts, and any worker still alive afterwards is terminated. The goal
is that a hung connection degrades that connection's results rather than
hanging the whole run.

Connections
-----------
Imports from : config.multi_connection_config, .worker_process
               (worker_process_entry), .server, .ml_controller, .result,
               .ipc_messages, .token_bucket, wireless_bottleneck (optional)
Imported by  : main.py, simulation/__init__.py, web.control_server,
               examples/run_3conn_through_bottleneck.py
Environment  : SERVER_CONTROL_URL, RUN_MODE, SKIP_VETH, USE_VETH_INTERFACE,
               ENABLE_NETWORK_RTT_PROBE
"""

import asyncio
import json
import queue as _queue
import threading
import time
import os
import re
import statistics
import urllib.request
from multiprocessing import Process, Pipe, Queue, Barrier
from typing import Dict, List, Optional, Callable

# URL of the server container's internal bottleneck control endpoint.
# Set SERVER_CONTROL_URL=http://192.168.200.10:9001 in the clients container
# so slider commands are forwarded to the download-side bottleneck.
_SERVER_CONTROL_URL: str = os.environ.get("SERVER_CONTROL_URL", "")


def _forward_to_server(url: str, payload: bytes) -> None:
    """
    Post a control command to the server container, ignoring the outcome.

    In the docker-compose topology the two traffic directions are shaped by
    different containers: the clients container shapes upload, the server
    container shapes download. A UI slider change must therefore reach both.
    This is called on a daemon thread and swallows every error, because a
    failure to reach the peer container must never stall the simulation.
    """
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            _ = resp.read()  # drain
    except Exception as e:
        print(f"[Orchestrator] server-side forward failed: {e}")


from config.multi_connection_config import MultiConnectionConfig
from .worker_process import worker_process_entry
from .server import QuicServer
from .ml_controller import MLController
from .result import MultiConnectionResult, ConnectionResult
from .ipc_messages import IPCMessage, MessageType
from .token_bucket import SharedTokenBucket

# Optional wireless bottleneck import
try:
    from wireless_bottleneck import get_scenario, WirelessBottleneck
    HAS_WIRELESS_BOTTLENECK = True
except ImportError:
    HAS_WIRELESS_BOTTLENECK = False


class ProcessOrchestrator:
    """Orchestrates multiple QUIC connection processes."""

    # Accepted ranges for every tunable parameter. Enforced here, at the
    # orchestrator boundary, so that both UI sliders and Q-learning agents are
    # validated before a value is sent to a worker. Out-of-range values are
    # rejected rather than clamped, so a faulty controller fails visibly.
    PARAM_BOUNDS = {
        "loss_reduction_factor": (0.1, 0.9),
        "cubic_c": (0.1, 1.0),
        "minimum_window": (1, 10),
        "packet_threshold": (1, 10),
        "time_threshold": (1.0, 2.0),
        "cubic_max_idle_time": (0.5, 5.0),
    }

    def __init__(
        self,
        config: MultiConnectionConfig,
        ml_callback: Optional[Callable] = None,
        metrics_interval: float = 0.1,
        network_scenario: str = "",
        network_config: dict = None,
        scenario: Optional[object] = None,
        server_only: bool = False,
        clients_only: bool = False,
        bandwidth_cap_bps: Optional[float] = None,
        loss_rate: float = 0.0,
        delay_ms: float = 0.0,
        output_dir: str = "output",
        ml_agent_type: str = "default",  # "default" or "andy"
    ):
        self.config = config
        self.ml_callback = ml_callback
        self.metrics_interval = metrics_interval
        self.network_scenario = network_scenario
        self.network_config = network_config or {}
        self.scenario = scenario  # Full scenario object for bottleneck setup
        self.server_only = server_only
        self.clients_only = clients_only
        self.output_dir = output_dir
        self.ml_agent_type = ml_agent_type  # Track which agent is being used

        self.workers: Dict[int, Process] = {}
        self.command_pipes: Dict[int, Pipe] = {}
        # Bounded queue: three workers publishing every 100ms for a long
        # training run would otherwise grow without limit if the consumer
        # fell behind.
        self.metrics_queue: Queue = Queue(maxsize=10000)
        self.start_barrier: Optional[Barrier] = None
        self.server: Optional[QuicServer] = None
        self.ml_controller: Optional[MLController] = None
        self.metrics_history: List[Dict] = []
        self.final_results: Dict[int, dict] = {}
        self.epoch_histories: Dict[int, List[Dict]] = {}  # Per-connection epoch data
        self.bottleneck: Optional[object] = None  # Will hold WirelessBottleneck if used
        self.token_bucket: Optional[SharedTokenBucket] = (
            SharedTokenBucket(bandwidth_cap_bps) if bandwidth_cap_bps else None
        )
        self.loss_rate = loss_rate
        self.delay_ms = delay_ms

        # Initialize for UI access
        self._latest_metrics: Dict[int, dict] = {}
        self._buffer_states: Dict[int, dict] = {}

        # Server-side metrics for receiver-side throughput measurement
        self.server_metrics: Dict[int, Dict] = {}

        # Track Q-learning export directory for reporting
        self.qlearning_export_dir: Optional[str] = None

    async def setup(self):
        """Setup server and prepare for workers."""
        # Only start server in server-only or normal mode (not clients-only)
        if not self.clients_only:
            # In multi-container mode, use 0.0.0.0 to listen on all interfaces
            # In regular mode, use the configured host
            listen_host = self.config.server_host if self.config.server_host != "0.0.0.0" else "[::]"
            
            self.server = QuicServer(
                host=self.config.server_host,
                port=self.config.server_port,
                loss_rate=self.loss_rate,
                delay_ms=self.delay_ms,
            )
            await self.server.start()
            print(f"[Server] Started on {self.config.server_host}:{self.config.server_port} (listening on all interfaces)")
        
        # Only setup barrier and workers in normal or clients-only mode
        if not self.server_only:
            # Barrier party count is 4: the three workers plus the main
            # process, which waits on it too. That makes the orchestrator begin
            # collecting metrics at the same instant the connections start,
            # rather than some indeterminate time earlier.
            self.start_barrier = Barrier(4)

            if self.ml_callback:
                self.ml_controller = MLController(
                    decision_interval=self.metrics_interval,
                    ml_callback=self.ml_callback,
                    ml_agent_type=self.ml_agent_type,
                )
        
        # Create a background task to keep the server running
        if self.server and not self.server_only:
            self._server_task = asyncio.create_task(self._keep_server_running())

    async def _keep_server_running(self):
        """Keep the server running until stopped."""
        try:
            while self.server.is_running:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    def _spawn_workers(self, duration: float):
        """Spawn worker processes for each connection."""
        for conn_config in self.config.get_all_configs():
            main_pipe, worker_pipe = Pipe()
            self.command_pipes[conn_config.connection_id] = main_pipe

            process = Process(
                target=worker_process_entry,
                args=(
                    conn_config.to_dict(),
                    self.config.server_host,
                    self.config.server_port,
                    worker_pipe,
                    self.metrics_queue,
                    self.start_barrier,
                    duration,
                    self.network_scenario,
                    self.network_config,
                    self.token_bucket,
                ),
                name=f"QUIC-{conn_config.application_type}",
            )
            self.workers[conn_config.connection_id] = process

    async def _run_network_rtt_probe(self, host: str, duration: float) -> Dict[str, object]:
        """
        Measure path RTT independently of QUIC, using ICMP ping.

        QUIC's own RTT includes queueing delay caused by the connections
        themselves, so it cannot distinguish a slow path from self-inflicted
        bufferbloat. A concurrent ping gives an outside view of the same path
        for comparison.

        Every failure mode (ping absent, timeout, no parsable samples) returns
        a dict with available=False rather than raising, since the probe is
        supplementary and must never fail a run.
        """
        if not host:
            return {"available": False, "error": "missing_host"}

        interval_sec = 0.5
        ping_count = max(5, int(duration / interval_sec))
        ping_deadline = max(5, int(duration) + 5)

        try:
            proc = await asyncio.create_subprocess_exec(
                "ping",
                "-n",
                "-i",
                str(interval_sec),
                "-c",
                str(ping_count),
                "-w",
                str(ping_deadline),
                host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return {"available": False, "error": "ping_not_found"}
        except Exception as exc:
            return {"available": False, "error": f"ping_start_failed: {exc}"}

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=duration + 15)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {"available": False, "error": "ping_timeout"}

        output = (stdout or b"").decode(errors="ignore") + "\n" + (stderr or b"").decode(errors="ignore")

        rtt_samples_ms = [float(v) for v in re.findall(r"time[=<]([0-9]*\.?[0-9]+)\s*ms", output)]
        packet_loss_match = re.search(r"([0-9]*\.?[0-9]+)%\s*packet loss", output)
        packet_loss_pct = float(packet_loss_match.group(1)) if packet_loss_match else None

        if not rtt_samples_ms:
            return {
                "available": False,
                "error": "no_rtt_samples",
                "packet_loss_percent": packet_loss_pct,
            }

        sorted_samples = sorted(rtt_samples_ms)
        p95_index = max(0, min(len(sorted_samples) - 1, int(0.95 * (len(sorted_samples) - 1))))

        jitter_ms = 0.0
        if len(rtt_samples_ms) >= 2:
            deltas = [abs(b - a) for a, b in zip(rtt_samples_ms[:-1], rtt_samples_ms[1:])]
            jitter_ms = float(statistics.mean(deltas)) if deltas else 0.0

        return {
            "available": True,
            "target_host": host,
            "sample_count": len(rtt_samples_ms),
            "rtt_min_ms": float(min(rtt_samples_ms)),
            "rtt_median_ms": float(statistics.median(rtt_samples_ms)),
            "rtt_avg_ms": float(statistics.mean(rtt_samples_ms)),
            "rtt_p95_ms": float(sorted_samples[p95_index]),
            "rtt_max_ms": float(max(rtt_samples_ms)),
            "jitter_ms": float(jitter_ms),
            "packet_loss_percent": float(packet_loss_pct) if packet_loss_pct is not None else None,
        }

    @staticmethod
    def _extract_tc_sent_bytes(stats: dict) -> int:
        """
        Recover the byte count from tc's free-form statistics output.

        Preference is given to the root htb qdisc, whose counter reflects
        everything the shaper actually passed; any "Sent N bytes" line is
        accepted as a fallback. Returns 0 when nothing parses, which callers
        treat as "no tc measurement available" rather than as zero traffic.

        This figure is the independent, kernel-level check on the
        application's own throughput accounting.
        """
        raw = stats.get("raw_output", "") if isinstance(stats, dict) else ""
        if not raw:
            return 0

        lines = raw.splitlines()
        for idx, line in enumerate(lines):
            if line.strip().startswith("qdisc htb") and " root " in line and idx + 1 < len(lines):
                match = re.search(r"Sent\s+(\d+)\s+bytes", lines[idx + 1])
                if match:
                    return int(match.group(1))

        for line in lines:
            match = re.search(r"Sent\s+(\d+)\s+bytes", line)
            if match:
                return int(match.group(1))

        return 0

    async def run(self, duration: Optional[float] = None) -> Optional[MultiConnectionResult]:
        """Run all connections concurrently with bottleneck if available."""
        from datetime import datetime
        self._start_timestamp = datetime.now().isoformat()
        self._start_time_unix = time.time()  # For checking server metrics freshness
        duration = duration or self.config.simulation_duration

        # Setup bottleneck if scenario is provided
        if HAS_WIRELESS_BOTTLENECK and self.scenario:
            # Persist core scenario parameters for downstream reporting
            scenario_cfg = getattr(self.scenario, "config", None)
            if scenario_cfg is not None:
                # Primary parameters (displayed on UI)
                if hasattr(scenario_cfg, "capacity_bps"):
                    self.network_config["capacity_bps"] = getattr(scenario_cfg, "capacity_bps")
                if hasattr(scenario_cfg, "propagation_delay"):
                    self.network_config["propagation_delay"] = getattr(scenario_cfg, "propagation_delay")
                if hasattr(scenario_cfg, "loss_rate"):
                    self.network_config["loss_rate"] = getattr(scenario_cfg, "loss_rate")
                if hasattr(scenario_cfg, "queue_size_packets"):
                    self.network_config["queue_size_packets"] = getattr(scenario_cfg, "queue_size_packets")
                if hasattr(scenario_cfg, "queue_discipline"):
                    qd = getattr(scenario_cfg, "queue_discipline")
                    self.network_config["queue_discipline"] = qd.value if hasattr(qd, "value") else str(qd)
                if hasattr(scenario_cfg, "time_varying"):
                    self.network_config["time_varying"] = getattr(scenario_cfg, "time_varying")
                # Secondary parameters (for time-varying scenarios)
                if hasattr(scenario_cfg, "variation_period"):
                    self.network_config["variation_period"] = getattr(scenario_cfg, "variation_period")
                if hasattr(scenario_cfg, "variation_amplitude"):
                    self.network_config["variation_amplitude"] = getattr(scenario_cfg, "variation_amplitude")

            # Determine which interface to use based on deployment mode
            run_mode = os.environ.get("RUN_MODE", "")
            skip_veth = os.environ.get("SKIP_VETH", "0")
            
            if run_mode == "server":
                # Multi-container docker-compose: use eth0 (docker network interface)
                # Apply EGRESS shaping on server side
                interface = "eth0"
                apply_ingress = False
                print(f"[Orchestrator] Multi-container Docker mode (SERVER): applying EGRESS shaping on eth0")
            elif run_mode == "clients":
                # Multi-container docker-compose: use eth0 (docker network interface)
                # Apply EGRESS shaping on client side (traffic is primarily client -> server)
                interface = "eth0"
                apply_ingress = False
                print(f"[Orchestrator] Multi-container Docker mode (CLIENTS): applying EGRESS shaping on eth0")
            elif os.environ.get("USE_VETH_INTERFACE"):
                # Single-container with veth: use veth0
                interface = "veth0"
                apply_ingress = False
                print(f"[Orchestrator] Single-container veth mode: applying bottleneck on veth0")
            else:
                # Local macOS mode
                interface = "lo"
                apply_ingress = False
                print(f"[Orchestrator] Local mode: applying bottleneck on lo (RTT only)")

            self.bottleneck = WirelessBottleneck(self.scenario.config, interface=interface, apply_ingress=apply_ingress)
            self.bottleneck.__enter__()
            print(f"[Orchestrator] Wireless bottleneck activated for scenario: {self.network_scenario}")

        try:
            probe_task = None
            if self.clients_only and os.environ.get("ENABLE_NETWORK_RTT_PROBE", "1") != "0":
                probe_task = asyncio.create_task(self._run_network_rtt_probe(self.config.server_host, duration))

            # Server-only mode: just wait for connections
            if self.server_only:
                print(f"[Orchestrator] Setting up QUIC server on {self.config.server_host}:{self.config.server_port}")
                await self.setup()
                print(f"[Orchestrator] Server ready and waiting for client connections...")
                print(f"[Orchestrator] Bottleneck active: {self.scenario.config.capacity_bps / 1e6:.1f} Mbps, "
                      f"{self.scenario.config.propagation_delay * 2000:.0f}ms RTT, {self.scenario.config.loss_rate * 100:.2f}% loss")

                # Just keep server running for the specified duration
                await asyncio.sleep(duration)
                print(f"[Orchestrator] Server run duration complete")
                return None
            
            # Normal mode (with or without server) or clients-only mode
            if not self.clients_only:
                print(f"[Orchestrator] Setting up QUIC server on {self.config.server_host}:{self.config.server_port}")
            else:
                print(f"[Orchestrator] Clients-only mode: connecting to {self.config.server_host}:{self.config.server_port}")

            await self.setup()

            if not self.clients_only:
                print(f"[Orchestrator] Server setup complete")
                # Give server time to fully initialize and start accepting connections
                await asyncio.sleep(0.5)

            self._spawn_workers(duration)
            print(f"[Orchestrator] Spawned {len(self.workers)} worker processes")

            for process in self.workers.values():
                process.start()
            print(f"[Orchestrator] All worker processes started")

            if self.ml_controller:
                self.ml_controller.set_ipc_channels(self.command_pipes, self.metrics_queue)

            # Wait for all workers to be ready (run in thread to not block event loop)
            try:
                print(f"[Orchestrator] Waiting for workers to synchronize...")
                await asyncio.to_thread(self.start_barrier.wait, 10.0)
                print(f"[Orchestrator] All workers synchronized, starting metric collection")
            except threading.BrokenBarrierError:
                # A broken barrier means at least one worker never reached the
                # start line, so the run would measure fewer than three
                # competing connections. Fail loudly instead of silently
                # producing unusable results.
                raise RuntimeError("Workers failed to start - barrier timeout after 10s")

            if self.ml_controller:
                await self.ml_controller.run_control_loop(duration)
                self.metrics_history = self.ml_controller.metrics_history
                #merge any FINISHED messages captured during the control loop _collect_metrics consumes all queue messages including FINISHED which would otherwise be lost by time _collect_final_results runs
                for conn_id, data in self.ml_controller.final_results.items():
                    self.final_results[conn_id] = data
                    if "epoch_history" in data:
                        self.epoch_histories[conn_id] = data["epoch_history"]
            else:
                await self._collect_metrics_loop(duration)

            print(f"[Orchestrator] Simulation duration complete, waiting for workers to finish...")

            # Send STOP message to all workers to signal clean shutdown
            for conn_id, pipe in self.command_pipes.items():
                try:
                    stop_msg = IPCMessage(
                        msg_type=MessageType.STOP,
                        connection_id=conn_id,
                        timestamp=time.time(),
                        payload={},
                    )
                    pipe.send(stop_msg.to_dict())
                except Exception:
                    pass  # Worker might already be finished

            # Drain and join run concurrently, and the ordering matters: the
            # workers write their FINISHED messages as they shut down, so a
            # drain that only began after joining would miss them and every
            # connection would report empty final results.
            drain_thread = threading.Thread(target=self._collect_final_results, daemon=True)
            drain_thread.start()

            join_threads = [
                threading.Thread(target=p.join, args=(6,), daemon=True)
                for p in self.workers.values()
            ]
            for t in join_threads:
                t.start()
            for t in join_threads:
                t.join(timeout=8)  #slightly longer than 6s worker join

            # Any worker still alive after the bounded join is terminated.
            # Results already drained from the queue are kept, so a single
            # unresponsive connection costs only its own final message.
            for conn_id, process in self.workers.items():
                if process.is_alive():
                    print(f"[Orchestrator] Terminating worker {conn_id}")
                    process.terminate()
                    process.join(timeout=2)

            drain_thread.join(timeout=2)  # wait for drain to finish (it runs for up to 4s but usually done by now)

            if self.bottleneck:
                tc_stats = self.bottleneck.get_current_stats()
                tc_sent_bytes = self._extract_tc_sent_bytes(tc_stats)
                if tc_sent_bytes > 0 and duration > 0:
                    self.network_config["tc_sent_bytes"] = tc_sent_bytes
                    self.network_config["tc_observed_throughput_bps"] = (tc_sent_bytes * 8) / duration

            if probe_task is not None:
                try:
                    probe_result = await probe_task
                    self.network_config["network_rtt_probe"] = probe_result
                except Exception as exc:
                    self.network_config["network_rtt_probe"] = {
                        "available": False,
                        "error": f"probe_failed: {exc}",
                    }

            # Export Q-learning history if ML controller was used
            if self.ml_controller:
                try:
                    self.qlearning_export_dir = self.ml_controller.export_qlearning_history(
                        output_dir=self.output_dir,
                        scenario=self.network_scenario
                    )
                except Exception as e:
                    print(f"[Orchestrator] Failed to export Q-learning history: {e}")

            return self._build_results()

        finally:
            # Cleanup bottleneck before other cleanup
            if self.bottleneck:
                self.bottleneck.__exit__(None, None, None)
                print(f"[Orchestrator] Wireless bottleneck deactivated")
            await self.cleanup()

    async def _collect_metrics_loop(self, duration: float):
        """Simple metrics collection without ML."""
        start_time = time.time()

        while (time.time() - start_time) < duration:
            current_metrics = {}

            while not self.metrics_queue.empty():
                try:
                    msg = self.metrics_queue.get_nowait()
                    if msg.msg_type == MessageType.METRICS:
                        current_metrics[msg.connection_id] = msg.payload
                        # Also store for UI access
                        self._latest_metrics[msg.connection_id] = msg.payload
                    elif msg.msg_type == MessageType.BUFFER_STATE:
                        self._buffer_states[msg.connection_id] = msg.payload
                    elif msg.msg_type == MessageType.FINISHED:
                        self.final_results[msg.connection_id] = msg.payload
                except Exception as e:
                    # Queue drained, or the far end closed. Either way, stop
                    # draining this tick and resume on the next interval.
                    break

            if current_metrics:
                self.metrics_history.append({
                    "timestamp": time.time() - start_time,
                    "metrics": current_metrics,
                })

            await asyncio.sleep(self.metrics_interval)

    def _collect_final_results(self):
        """Drain metrics queue collecting FINISHED messages called in a daemon thread so a partial pipe write from a terminated worker
        (which blocks recv_bytes forever) cannot stall the main process.
        """
        deadline = time.time() + 4.0
        while time.time() < deadline:
            if len(self.final_results) == len(self.workers):
                break  #got a FINISHED for every worker then done early
            try:
                msg = self.metrics_queue.get(timeout=0.2)
                if msg.msg_type == MessageType.FINISHED:
                    self.final_results[msg.connection_id] = msg.payload
                    if "epoch_history" in msg.payload:
                        self.epoch_histories[msg.connection_id] = msg.payload["epoch_history"]
            except _queue.Empty:
                continue  #keep waiting until deadline
            except Exception:
                break  #real error ex pipe broken by terminated worker

    def _load_server_metrics(self) -> bool:
        """
        Load server-side metrics from exported file.

        Waits for FRESH metrics (export_timestamp > simulation start time)
        to avoid loading stale data from a previous run.

        Returns True if successfully loaded, False otherwise.
        """
        import json
        from pathlib import Path

        metrics_file = Path(self.output_dir) / "server_metrics_latest.json"

        # Get simulation start time (set in run())
        start_time = getattr(self, '_start_time_unix', 0)

        # Wait for file with timeout (server runs longer than clients)
        max_wait = 20.0  # Increased to allow for server export delay
        wait_interval = 0.5
        elapsed = 0.0

        while elapsed < max_wait:
            if metrics_file.exists():
                try:
                    with open(metrics_file, "r") as f:
                        data = json.load(f)

                    # Check if this is fresh data (from current run)
                    export_timestamp = data.get("export_timestamp", 0)
                    if export_timestamp < start_time:
                        # Stale data from previous run, keep waiting
                        if elapsed < 1.0:  # Only print once
                            print(f"[Orchestrator] Found stale server metrics, waiting for fresh data...")
                        time.sleep(wait_interval)
                        elapsed += wait_interval
                        continue

                    # Extract per-connection metrics
                    per_conn = data.get("per_connection", {})
                    for conn_id_str, metrics in per_conn.items():
                        conn_id = int(conn_id_str)
                        self.server_metrics[conn_id] = metrics

                    print(f"[Orchestrator] Loaded fresh server metrics for {len(self.server_metrics)} connections")
                    return True

                except json.JSONDecodeError:
                    # File may still be writing, wait and retry
                    pass
                except Exception as e:
                    print(f"[Orchestrator] Error loading server metrics: {e}")

            time.sleep(wait_interval)
            elapsed += wait_interval

        print(f"[Orchestrator] Warning: Could not load fresh server metrics from {metrics_file}")
        return False

    def _match_server_to_client_connections(self) -> Dict[int, int]:
        """
        Match server protocols to client connections using bytes-based matching.

        Strategy:
        1. First pass: exact matching where bytes_sent ≈ bytes_received (within 10%)
        2. Second pass: for unmatched connections, match by throughput ranking
           (highest offered → highest received, etc.)

        This handles bottleneck scenarios where file transfer sends 100x more
        than arrives through the bottleneck.

        Why matching is needed at all: the server sees three anonymous QUIC
        connections and has no way to know which carries which application. The
        pairing must therefore be reconstructed after the fact from volume.

        Pass 1 matches on near-equal byte counts, working from the smallest
        sender upward because small, unthrottled flows arrive nearly intact and
        so match unambiguously. Pass 2 handles flows the bottleneck distorted
        too much for that, pairing what remains by rank on the assumption that
        relative ordering survives even when absolute volume does not.

        This is a heuristic. Two connections with near-identical volumes could
        in principle be transposed, which would misattribute receiver-side
        throughput between them.

        Returns dict mapping client_conn_id -> server_conn_id.
        """
        if not self.server_metrics or not self.final_results:
            return {}

        matches: Dict[int, int] = {}
        used_server_ids = set()

        # Get client bytes_sent from final_results
        client_bytes = {}
        for conn_id, result_data in self.final_results.items():
            final_metrics = result_data.get("final_metrics", {})
            # bytes_sent is tracked by MetricsCollector
            bytes_sent = final_metrics.get("bytes_sent", 0)
            if bytes_sent == 0:
                # Fallback: estimate from throughput * duration
                throughput_Bps = final_metrics.get("throughput", 0)
                duration = self.config.simulation_duration
                bytes_sent = int(throughput_Bps * duration)
            client_bytes[conn_id] = bytes_sent

        # PASS 1: Exact matching (bytes_sent ≈ bytes_received)
        # Sort clients by bytes_sent ascending (smallest first - more likely to match exactly)
        sorted_clients_asc = sorted(
            client_bytes.items(),
            key=lambda x: x[1],
            reverse=False
        )

        for client_id, client_sent in sorted_clients_asc:
            best_match = None
            best_diff = float("inf")

            for server_id, server_data in self.server_metrics.items():
                if server_id in used_server_ids:
                    continue

                server_received = server_data.get("bytes_received", 0)
                diff = abs(client_sent - server_received)

                # Allow 15% tolerance for protocol overhead and timing
                tolerance = max(client_sent * 0.15, 10000)  # At least 10KB tolerance
                if diff < tolerance and diff < best_diff:
                    best_diff = diff
                    best_match = server_id

            if best_match is not None:
                matches[client_id] = best_match
                used_server_ids.add(best_match)

        # PASS 2: Match remaining by throughput ranking
        # For bottlenecked flows, the highest sender should match highest receiver
        unmatched_clients = [cid for cid in client_bytes if cid not in matches]
        unmatched_servers = [sid for sid in self.server_metrics if sid not in used_server_ids]

        if unmatched_clients and unmatched_servers:
            # Sort unmatched clients by bytes_sent descending
            unmatched_clients_sorted = sorted(
                unmatched_clients,
                key=lambda cid: client_bytes[cid],
                reverse=True
            )

            # Sort unmatched servers by bytes_received descending
            unmatched_servers_sorted = sorted(
                unmatched_servers,
                key=lambda sid: self.server_metrics[sid].get("bytes_received", 0),
                reverse=True
            )

            # Match by rank: highest sender → highest receiver
            for client_id, server_id in zip(unmatched_clients_sorted, unmatched_servers_sorted):
                matches[client_id] = server_id
                print(f"[Orchestrator] Matched client {client_id} to server {server_id} by throughput ranking")

        return matches

    def _build_results(self) -> MultiConnectionResult:
        """Build final result object from collected data."""
        connection_results = {}

        # Try to load server metrics for receiver-side throughput
        if self.clients_only and not self.server_metrics:
            self._load_server_metrics()

        # Match server connections to client connections
        # _match_server_to_client_connections already returns a mapping keyed
        # by client id, which is the direction the code below needs.
        server_to_client_map = self._match_server_to_client_connections()
        # Note: the inverted mapping on the next line is computed but never
        # read; it is a leftover from an earlier revision, as the two trailing
        # comments record. Retained rather than removed to keep this pass
        # documentation-only.
        client_to_server_map = {v: k for k, v in server_to_client_map.items()}
        # Actually we want client_id -> server_id, so the original is correct
        # matches is client_id -> server_id

        #reconstruct per connection metrics_history from the orchestrator aggregated history metrics_history was removed from FINISHED payload to keep  message small enough to transit the IPC pipe reliably
        per_conn_metrics: Dict[int, list] = {1: [], 2: [], 3: []}
        for entry in self.metrics_history:
            ts = entry.get("timestamp", 0)
            for cid, m in entry.get("metrics", {}).items():
                per_conn_metrics[int(cid)].append({"timestamp": ts, **m})

        for conn_id in [1, 2, 3]:
            if conn_id in self.final_results:
                result_data = self.final_results[conn_id]

                # Extract epochs list from epoch_history dict
                epoch_history_data = self.epoch_histories.get(conn_id, {})
                epochs_list = epoch_history_data.get("epochs", []) if isinstance(epoch_history_data, dict) else []

                # Merge server-side metrics if available
                final_metrics = result_data.get("final_metrics", {}).copy()
                matched_server_id = server_to_client_map.get(conn_id)
                if matched_server_id is not None and matched_server_id in self.server_metrics:
                    server_data = self.server_metrics[matched_server_id]
                    final_metrics["receiver_throughput_bps"] = server_data.get("throughput_bps", 0)
                    final_metrics["receiver_throughput_mbps"] = server_data.get("throughput_mbps", 0)
                    final_metrics["receiver_bytes"] = server_data.get("bytes_received", 0)
                    final_metrics["receiver_duration"] = server_data.get("duration_seconds", 0)

                connection_results[conn_id] = ConnectionResult(
                    connection_id=conn_id,
                    application_type=self.config.get_config(conn_id).application_type,
                    final_metrics=final_metrics,
                    param_history=result_data.get("param_history", []),
                    epoch_history=epochs_list,
                    metrics_history=per_conn_metrics.get(conn_id, []),
                    network_scenario=self.network_scenario,
                    network_config=self.network_config,
                    success=result_data.get("success", False),
                )

        all_success = (
            len(connection_results) == 3 and
            all(r.success for r in connection_results.values()) and
            all(p.exitcode == 0 for p in self.workers.values())
        )

        result = MultiConnectionResult(
            connection_results=connection_results,
            network_scenario=self.network_scenario,
            network_config=self.network_config,
            shared_params={
                "initial_cw": self.config.shared_initial_cw,
                "max_ack_delay": self.config.shared_max_ack_delay,
                "max_data": self.config.shared_max_data,
                "max_stream_data": self.config.shared_max_stream_data,
            },
            duration_seconds=self.config.simulation_duration,
            start_timestamp=getattr(self, '_start_timestamp', ''),
        )
        result.finalize()
        return result

    async def cleanup(self):
        """Cleanup all resources."""
        # Terminate workers with force kill if needed to prevent zombies
        for process in self.workers.values():
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()  # Force kill if still alive
                    process.join(timeout=1)

        # Stop server with error protection
        if self.server:
            try:
                await self.server.stop()
            except Exception:
                pass  # Server may already be stopped

        # Close command pipes
        for pipe in self.command_pipes.values():
            try:
                pipe.close()
            except Exception:
                pass

        # Close metrics queue
        if self.metrics_queue:
            try:
                self.metrics_queue.close()
                self.metrics_queue.join_thread()
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════════════════════
    # UI SUPPORT METHODS (for Browser UI / WebSocket)
    # ═══════════════════════════════════════════════════════════════════════════

    def is_running(self) -> bool:
        """Check if simulation is currently running."""
        if not self.workers:
            return False
        return any(p.is_alive() for p in self.workers.values())

    def get_latest_metrics(self) -> Dict[int, dict]:
        """Get latest metrics for all connections."""
        # Return cached metrics (updated by _collect_metrics_loop)
        if self.ml_controller:
            return self.ml_controller.latest_metrics.copy()
        return self._latest_metrics.copy() if hasattr(self, '_latest_metrics') else {}

    def get_buffer_states(self) -> Dict[int, dict]:
        """Get buffer states for all connections."""
        return self._buffer_states.copy() if hasattr(self, '_buffer_states') else {}

    def get_current_params(self) -> Dict[int, dict]:
        """Get current parameter values for all connections."""
        params = {}
        for config in self.config.get_all_configs():
            params[config.connection_id] = {
                "loss_reduction_factor": config.loss_reduction_factor,
                "cubic_c": config.cubic_c,
                "minimum_window": config.minimum_window,
                "packet_threshold": config.packet_threshold,
                "time_threshold": config.time_threshold,
                "cubic_max_idle_time": config.cubic_max_idle_time,
            }
        return params

    def update_network_conditions(
        self,
        bandwidth_mbps: float,
        delay_ms: int,
        jitter_ms: int,
        loss_pct: float,
    ) -> bool:
        """
        Apply manual network conditions via the UI slider.
        Calls through to the live WirelessBottleneck instance (client-side egress)
        AND forwards the command to the server-side control endpoint (download egress)
        when SERVER_CONTROL_URL is set.
        Returns False if no local bottleneck is active (simulation not running).
        """
        if not self.bottleneck:
            return False
        try:
            self.bottleneck.apply_manual_override(
                bandwidth_mbps=bandwidth_mbps,
                delay_ms=int(delay_ms),
                jitter_ms=max(1, int(jitter_ms)),
                loss_pct=float(loss_pct),
            )
            # Keep network_config in sync so the UI display reflects changes
            self.network_config["capacity_bps"] = int(bandwidth_mbps * 1_000_000)
            self.network_config["propagation_delay"] = delay_ms / 1000.0
            self.network_config["loss_rate"] = loss_pct / 100.0

            # Forward to server-side (download) bottleneck in a daemon thread
            if _SERVER_CONTROL_URL:
                payload = json.dumps({
                    "bandwidth_mbps": bandwidth_mbps,
                    "delay_ms": int(delay_ms),
                    "jitter_ms": max(1, int(jitter_ms)),
                    "loss_pct": float(loss_pct),
                }).encode()
                threading.Thread(
                    target=_forward_to_server,
                    args=(_SERVER_CONTROL_URL + "/control", payload),
                    daemon=True,
                ).start()

            return True
        except Exception as e:
            print(f"[Orchestrator] update_network_conditions failed: {e}")
            return False

    def release_network_override(self) -> bool:
        """Resume automatic variation after manual slider override."""
        if not self.bottleneck:
            return False
        try:
            self.bottleneck.release_manual_override()

            # Forward release to server-side bottleneck
            if _SERVER_CONTROL_URL:
                payload = json.dumps({"release": True}).encode()
                threading.Thread(
                    target=_forward_to_server,
                    args=(_SERVER_CONTROL_URL + "/control", payload),
                    daemon=True,
                ).start()

            return True
        except Exception:
            return False

    def update_parameter(self, connection_id: int, param_name: str, value: float) -> bool:
        """
        Update a parameter on a specific connection.

        Args:
            connection_id: Target connection (1, 2, or 3)
            param_name: Name of parameter to update
            value: New parameter value

        Returns:
            True if update was sent successfully, False otherwise.
        """
        pipe = self.command_pipes.get(connection_id)
        if not pipe:
            return False

        # Validate parameter bounds
        # Validate before dispatch. Rejecting here keeps an invalid value from
        # reaching aioquic's globals, where it could destabilise congestion
        # control in a way that is hard to attribute after the fact.
        if param_name in self.PARAM_BOUNDS:
            min_val, max_val = self.PARAM_BOUNDS[param_name]
            if not (min_val <= value <= max_val):
                return False

        try:
            msg = IPCMessage(
                msg_type=MessageType.UPDATE_PARAM,
                connection_id=connection_id,
                timestamp=time.time(),
                payload={"param_name": param_name, "value": value},
            )
            pipe.send(msg.to_dict())

            # Mirror the change into the orchestrator's own config copy. The
            # worker holds the authoritative value; this copy is what the UI
            # and the exported results read, so the two must be kept in step.
            config = self.config.get_config(connection_id)
            if config and hasattr(config, param_name):
                setattr(config, param_name, value)

            return True
        except Exception:
            return False

    def stop(self):
        """Stop the orchestrator - terminate any running processes."""
        for conn_id, process in self.workers.items():
            try:
                if process and process.is_alive():
                    process.terminate()
                    process.join(timeout=2)
            except Exception:
                pass  # Process already terminated
        
        if self.server and hasattr(self.server, 'is_running'):
            self.server.is_running = False

    def _process_pending_messages(self):
        """Process any pending messages from the metrics queue."""
        if not hasattr(self, '_latest_metrics'):
            self._latest_metrics = {}
        if not hasattr(self, '_buffer_states'):
            self._buffer_states = {}

        while not self.metrics_queue.empty():
            try:
                msg = self.metrics_queue.get_nowait()
                if msg.msg_type == MessageType.METRICS:
                    self._latest_metrics[msg.connection_id] = msg.payload
                elif msg.msg_type == MessageType.BUFFER_STATE:
                    self._buffer_states[msg.connection_id] = msg.payload
                elif msg.msg_type == MessageType.FINISHED:
                    self.final_results[msg.connection_id] = msg.payload
                    if "epoch_history" in msg.payload:
                        self.epoch_histories[msg.connection_id] = msg.payload["epoch_history"]
            except Exception:
                break  # Queue empty or connection closed

    def get_qlearning_history(self) -> List[dict]:
        """Get Q-learning action history with settled metrics."""
        if self.ml_controller:
            return self.ml_controller.get_qlearning_history()
        return []

    def get_qlearning_summary(self) -> dict:
        """Get Q-learning agent summary if available."""
        # Try Andy's agent first (if it was used, it will have state)
        try:
            from ml_callbacks.q_learning_agent_andy import get_agent as get_andy_agent
            andy_agent = get_andy_agent()
            if andy_agent.step_count > 0:
                return andy_agent.summary()
        except Exception:
            pass

        # Fall back to default agent
        try:
            from ml_callbacks.q_learning_agent import get_agent
            agent = get_agent()
            return agent.summary()
        except Exception:
            return {}

    def get_total_throughput(self) -> dict:
        """
        Get total throughput across all 3 connections.

        Returns dict with:
        - total_throughput_mbps: Sum of all connections' throughput in Mbps
        - total_throughput_bps: Sum in bytes/sec
        - per_connection: Individual throughputs for breakdown
        """
        if self.ml_controller:
            return self.ml_controller.get_total_throughput()

        # Fallback if no ML controller
        metrics = self.get_latest_metrics()
        total_bps = 0.0
        per_connection = {}

        for conn_id in [1, 2, 3]:
            conn_metrics = metrics.get(conn_id, {})
            # Use cwnd-limited throughput (most accurate for bottleneck scenarios)
            tp_bps = (conn_metrics.get("throughput_cwnd", 0) or
                      conn_metrics.get("throughput_acked_delta", 0) or
                      conn_metrics.get("throughput_acked", 0))
            total_bps += tp_bps
            per_connection[conn_id] = {
                "throughput_bps": tp_bps,
                "throughput_mbps": tp_bps * 8 / 1_000_000,
            }

        return {
            "total_throughput_bps": total_bps,
            "total_throughput_mbps": total_bps * 8 / 1_000_000,
            "per_connection": per_connection,
        }

    def get_scenario_config(self) -> dict:
        """
        Get network scenario configuration for UI display.

        Returns dict with primary network parameters:
        - scenario_name: Name of the scenario (e.g., "congested_low")
        - capacity_mbps: Bandwidth in Mbps
        - rtt_ms: Round-trip time in ms (2 * propagation_delay)
        - loss_percent: Packet loss rate as percentage
        - queue_size: Queue size in packets
        - queue_discipline: Queue algorithm (FIFO, RED, CoDel, PIE)
        - time_varying: Whether bandwidth varies over time
        - variation_info: Variation details if time_varying is True
        """
        config = {
            "scenario_name": self.network_scenario or "none",
            "capacity_mbps": 0.0,
            "rtt_ms": 0.0,
            "loss_percent": 0.0,
            "queue_size": 0,
            "queue_discipline": "unknown",
            "time_varying": False,
            "variation_info": None,
        }

        # Extract from network_config (populated in run())
        if self.network_config:
            capacity_bps = self.network_config.get("capacity_bps", 0)
            config["capacity_mbps"] = capacity_bps / 1_000_000 if capacity_bps else 0.0

            prop_delay = self.network_config.get("propagation_delay", 0)
            config["rtt_ms"] = prop_delay * 2000 if prop_delay else 0.0  # 2x one-way delay, convert to ms

            loss_rate = self.network_config.get("loss_rate", 0)
            config["loss_percent"] = loss_rate * 100 if loss_rate else 0.0

            config["queue_size"] = self.network_config.get("queue_size_packets", 0)
            config["queue_discipline"] = self.network_config.get("queue_discipline", "unknown")
            config["time_varying"] = self.network_config.get("time_varying", False)

            # Add variation info if time-varying
            if config["time_varying"]:
                period = self.network_config.get("variation_period", 0)
                amplitude = self.network_config.get("variation_amplitude", 0)
                config["variation_info"] = {
                    "period_sec": period,
                    "amplitude_percent": amplitude * 100 if amplitude else 0,
                }

        return config
