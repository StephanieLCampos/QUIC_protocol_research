"""
Process orchestrator for managing multiple QUIC connection processes.

Coordinates worker processes, handles IPC, and manages simulation lifecycle.
"""

import asyncio
import threading
import time
from multiprocessing import Process, Pipe, Queue, Barrier
from typing import Dict, List, Optional, Callable

from config.multi_connection_config import MultiConnectionConfig
from .worker_process import worker_process_entry
from .server import QuicServer
from .ml_controller import MLController
from .result import MultiConnectionResult, ConnectionResult
from .ipc_messages import IPCMessage, MessageType


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
    ):
        self.config = config
        self.ml_callback = ml_callback
        self.metrics_interval = metrics_interval
        self.network_scenario = network_scenario
        self.network_config = network_config or {}

        self.workers: Dict[int, Process] = {}
        self.command_pipes: Dict[int, Pipe] = {}
        self.metrics_queue: Queue = Queue(maxsize=10000)  # Prevent unbounded memory growth
        self.start_barrier: Optional[Barrier] = None
        self.server: Optional[QuicServer] = None
        self.ml_controller: Optional[MLController] = None
        self.metrics_history: List[Dict] = []
        self.final_results: Dict[int, dict] = {}
        self.epoch_histories: Dict[int, List[Dict]] = {}  # Per-connection epoch data

        # Initialize for UI access
        self._latest_metrics: Dict[int, dict] = {}
        self._buffer_states: Dict[int, dict] = {}

    async def setup(self):
        """Setup server and prepare for workers."""
        self.server = QuicServer(host=self.config.server_host, port=self.config.server_port)
        await self.server.start()
        self.start_barrier = Barrier(4)  # 3 workers + 1 main

        if self.ml_callback:
            self.ml_controller = MLController(
                decision_interval=self.metrics_interval,
                ml_callback=self.ml_callback,
            )

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
                ),
                name=f"QUIC-{conn_config.application_type}",
            )
            self.workers[conn_config.connection_id] = process

    async def run(self, duration: Optional[float] = None) -> MultiConnectionResult:
        """Run all connections concurrently."""
        duration = duration or self.config.simulation_duration

        try:
            await self.setup()
            self._spawn_workers(duration)

            for process in self.workers.values():
                process.start()

            if self.ml_controller:
                self.ml_controller.set_ipc_channels(self.command_pipes, self.metrics_queue)

            # Wait for all workers to be ready (run in thread to not block event loop)
            try:
                await asyncio.to_thread(self.start_barrier.wait, 10.0)
            except threading.BrokenBarrierError:
                raise RuntimeError("Workers failed to start - barrier timeout after 10s")

            if self.ml_controller:
                await self.ml_controller.run_control_loop(duration)
                self.metrics_history = self.ml_controller.metrics_history
            else:
                await self._collect_metrics_loop(duration)

            for conn_id, process in self.workers.items():
                process.join(timeout=duration + 5)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=2)

            self._collect_final_results()
            return self._build_results()

        finally:
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
        """Collect any remaining messages from queue."""
        while not self.metrics_queue.empty():
            try:
                msg = self.metrics_queue.get_nowait()
                if msg.msg_type == MessageType.FINISHED:
                    self.final_results[msg.connection_id] = msg.payload
                    # Extract epoch_history from finished payload
                    if "epoch_history" in msg.payload:
                        self.epoch_histories[msg.connection_id] = msg.payload["epoch_history"]
            except Exception:
                break  # Queue empty or connection closed

    def _build_results(self) -> MultiConnectionResult:
        """Build final result object from collected data."""
        connection_results = {}

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
                    metrics_history=result_data.get("metrics_history", []),
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
