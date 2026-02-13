"""
ML Controller for dynamic parameter optimization.

Runs in the main process and coordinates parameter updates
based on ML callback decisions.
"""

import time
import asyncio
from typing import Dict, List, Callable, Optional
from multiprocessing import Queue
from multiprocessing.connection import Connection

from .ipc_messages import IPCMessage, MessageType


class MLController:
    """Central ML controller that runs in the main process."""

    def __init__(
        self,
        decision_interval: float = 0.1,
        ml_callback: Optional[Callable] = None,
    ):
        self.decision_interval = decision_interval
        self.ml_callback = ml_callback or self._default_decision
        self.latest_metrics: Dict[int, dict] = {}
        self.metrics_history: List[Dict] = []
        self.command_pipes: Dict[int, Connection] = {}
        self.metrics_queue: Optional[Queue] = None

    def set_ipc_channels(self, command_pipes: Dict[int, Connection], metrics_queue: Queue):
        """Set IPC channels after process creation."""
        self.command_pipes = command_pipes
        self.metrics_queue = metrics_queue

    async def run_control_loop(self, duration: float):
        """Main control loop."""
        start_time = time.time()

        while (time.time() - start_time) < duration:
            loop_start = time.time()

            self._collect_metrics()

            if len(self.latest_metrics) == 3:
                # Execute ML callback with error protection
                try:
                    decisions = self.ml_callback(self.latest_metrics.copy())
                except Exception as e:
                    # Log error and continue with no parameter changes
                    print(f"ML callback error: {e}")
                    decisions = {}

                for conn_id, params in decisions.items():
                    if params:
                        self._send_param_update(conn_id, params)

            self.metrics_history.append({
                "timestamp": time.time() - start_time,
                "metrics": self.latest_metrics.copy(),
            })

            elapsed = time.time() - loop_start
            if elapsed < self.decision_interval:
                await asyncio.sleep(self.decision_interval - elapsed)

    def _collect_metrics(self):
        """Collect all available metrics from queue."""
        while not self.metrics_queue.empty():
            try:
                msg = self.metrics_queue.get_nowait()
                if msg.msg_type == MessageType.METRICS:
                    self.latest_metrics[msg.connection_id] = msg.payload
            except Exception:
                break  # Queue empty or connection closed

    def _send_param_update(self, conn_id: int, params: dict):
        """Send parameter update to specific worker."""
        pipe = self.command_pipes.get(conn_id)
        if pipe:
            if len(params) == 1:
                param_name, value = list(params.items())[0]
                msg = IPCMessage(
                    msg_type=MessageType.UPDATE_PARAM,
                    connection_id=conn_id,
                    timestamp=time.time(),
                    payload={"param_name": param_name, "value": value},
                )
            else:
                msg = IPCMessage(
                    msg_type=MessageType.UPDATE_MULTIPLE_PARAMS,
                    connection_id=conn_id,
                    timestamp=time.time(),
                    payload={"params": params},
                )
            pipe.send(msg.to_dict())

    def _default_decision(self, metrics: Dict[int, dict]) -> Dict[int, dict]:
        """Default ML decision (no changes)."""
        return {}

    def compute_fairness_index(self) -> float:
        """Compute Jain's fairness index for throughput."""
        throughputs = [m.get("throughput", 0) for m in self.latest_metrics.values()]
        if not throughputs or sum(throughputs) == 0:
            return 1.0

        n = len(throughputs)
        sum_x = sum(throughputs)
        sum_x_sq = sum(x ** 2 for x in throughputs)
        return (sum_x ** 2) / (n * sum_x_sq) if sum_x_sq > 0 else 1.0
