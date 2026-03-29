"""
Process orchestrator for managing multiple QUIC connection processes.

Coordinates worker processes, handles IPC, and manages simulation lifecycle.
"""

import asyncio
import queue as _queue
import threading
import time
import os
import re
import statistics
from multiprocessing import Process, Pipe, Queue, Barrier
from typing import Dict, List, Optional, Callable

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

    # Parameter bounds for validation (dynamic parameters only)
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
    ):
        self.config = config
        self.ml_callback = ml_callback
        self.metrics_interval = metrics_interval
        self.network_scenario = network_scenario
        self.network_config = network_config or {}
        self.scenario = scenario  # Full scenario object for bottleneck setup
        self.server_only = server_only
        self.clients_only = clients_only

        self.workers: Dict[int, Process] = {}
        self.command_pipes: Dict[int, Pipe] = {}
        self.metrics_queue: Queue = Queue(maxsize=10000)  # Prevent unbounded memory growth
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
            self.start_barrier = Barrier(4)  # 3 workers + 1 main

            if self.ml_callback:
                self.ml_controller = MLController(
                    decision_interval=self.metrics_interval,
                    ml_callback=self.ml_callback,
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
        """Run a lightweight ICMP ping probe and return RTT summary stats."""
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
        """Extract transmitted bytes from tc qdisc stats output."""
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
        duration = duration or self.config.simulation_duration

        # Setup bottleneck if scenario is provided
        if HAS_WIRELESS_BOTTLENECK and self.scenario:
            # Persist core scenario parameters for downstream reporting
            scenario_cfg = getattr(self.scenario, "config", None)
            if scenario_cfg is not None:
                if hasattr(scenario_cfg, "capacity_bps"):
                    self.network_config["capacity_bps"] = getattr(scenario_cfg, "capacity_bps")
                if hasattr(scenario_cfg, "propagation_delay"):
                    self.network_config["propagation_delay"] = getattr(scenario_cfg, "propagation_delay")
                if hasattr(scenario_cfg, "loss_rate"):
                    self.network_config["loss_rate"] = getattr(scenario_cfg, "loss_rate")

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
            #start drain + joins in parallel then drain must run while workers are still writing FINISHED to the queue
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
                    break  # Queue empty or connection closed

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

    def _build_results(self) -> MultiConnectionResult:
        """Build final result object from collected data."""
        connection_results = {}

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

                connection_results[conn_id] = ConnectionResult(
                    connection_id=conn_id,
                    application_type=self.config.get_config(conn_id).application_type,
                    final_metrics=result_data.get("final_metrics", {}),
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
        if param_name in self.PARAM_BOUNDS:
            min_val, max_val = self.PARAM_BOUNDS[param_name]
            if not (min_val <= value <= max_val):
                return False  # Reject out-of-bounds value

        try:
            msg = IPCMessage(
                msg_type=MessageType.UPDATE_PARAM,
                connection_id=connection_id,
                timestamp=time.time(),
                payload={"param_name": param_name, "value": value},
            )
            pipe.send(msg.to_dict())

            # Update local config copy
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
