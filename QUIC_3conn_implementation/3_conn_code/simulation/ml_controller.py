"""
ML Controller for dynamic parameter optimization.

Runs in the main process and coordinates parameter updates
based on ML callback decisions.

Sits between the Q-learning agents and the worker processes: it gathers
telemetry from all three connections, invokes the agent's callback with a
consistent view of the system, dispatches the parameters the agent returns, and
records each action together with the outcome it produced.

Control loop
------------
Each iteration, at `decision_interval` (100ms by default):

    1. drain the metrics queue for the latest per-connection telemetry
    2. resolve any earlier action whose settling window has now elapsed
    3. if all three connections have reported, call the agent callback
    4. dispatch the returned parameter changes and record them as pending
    5. append to the history and sleep out the remainder of the interval

Two points of design worth noting
---------------------------------
All three connections must have reported before the agent is consulted. The
agents optimise a joint objective across the three competing flows, so acting
on a partial view would train against a system state that never existed.

Actions are recorded before their effect is known. A parameter change does not
take effect instantly: the congestion window needs time to react. Each action
is therefore held with its "before" metrics and only completed once
SETTLING_TIME has passed, at which point the "after" metrics are attached. That
pairing is what makes the exported history usable for attributing an outcome to
a decision.

Agent failures are contained: an exception raised inside a callback is logged
and treated as "no change this tick", so a faulty agent degrades to inaction
rather than aborting a long training run.

Connections
-----------
Imports from : .ipc_messages; ml_callbacks.q_learning_agent{,_andy,_hybrid}
               are imported lazily by agent type
Imported by  : simulation/__init__.py, .process_orchestrator
Writes       : Q-learning action history and summary (see
               export_qlearning_history)
"""

import time
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Optional
from multiprocessing import Queue
from multiprocessing.connection import Connection

from .ipc_messages import IPCMessage, MessageType


@dataclass
class QLearningAction:
    """Records a Q-learning action with metrics captured after settling."""
    timestamp: float
    connection_id: int
    param_name: str
    old_value: float
    new_value: float
    direction: str  # "increase" or "decrease"
    metrics_before: Dict[int, dict] = field(default_factory=dict)
    metrics_after: Dict[int, dict] = field(default_factory=dict)
    settled: bool = False


class MLController:
    """Central ML controller that runs in the main process."""

    # How long to wait after a parameter change before the resulting metrics
    # are considered attributable to it. A congestion window does not respond
    # instantly, so sampling immediately would credit the new parameters with
    # the old configuration's behaviour and corrupt the learning signal.
    SETTLING_TIME = 1.5

    def __init__(
        self,
        decision_interval: float = 0.1,
        ml_callback: Optional[Callable] = None,
        ml_agent_type: str = "default",  # "default", "andy", or "hybrid"
    ):
        self.decision_interval = decision_interval
        self.ml_callback = ml_callback or self._default_decision
        self.ml_agent_type = ml_agent_type  # Track which agent is being used
        self.latest_metrics: Dict[int, dict] = {}
        self.metrics_history: List[Dict] = []
        self.command_pipes: Dict[int, Connection] = {}
        self.metrics_queue: Optional[Queue] = None
        self.final_results: Dict[int, dict] = {}  #FINISHED messages captured during control loop

        # Q-learning action tracking
        self.qlearning_history: List[QLearningAction] = []
        self._pending_actions: List[QLearningAction] = []  # Actions awaiting settling
        self._current_params: Dict[int, Dict[str, float]] = {}  # Track current param values

    def set_ipc_channels(self, command_pipes: Dict[int, Connection], metrics_queue: Queue):
        """Set IPC channels after process creation."""
        self.command_pipes = command_pipes
        self.metrics_queue = metrics_queue

    async def run_control_loop(self, duration: float):
        """Main control loop."""
        start_time = time.time()

        while (time.time() - start_time) < duration:
            loop_start = time.time()
            now = time.time()

            self._collect_metrics()

            # Check for pending actions that have settled
            self._check_settled_actions(now)

            # Require telemetry from all three connections before consulting
            # the agent. The agents optimise a joint objective across the
            # competing flows, so a partial view would train the policy against
            # a system state that never actually occurred.
            if len(self.latest_metrics) == 3:
                try:
                    decisions = self.ml_callback(self.latest_metrics.copy())
                except Exception as e:
                    # Contain agent failures. Treating an exception as "no
                    # change this tick" lets a long training run survive a bug
                    # in an experimental agent rather than losing the run.
                    print(f"ML callback error: {e}")
                    decisions = {}

                for conn_id, params in decisions.items():
                    if params:
                        # Track the action before sending
                        self._record_action(conn_id, params, now)
                        self._send_param_update(conn_id, params)

            self.metrics_history.append({
                "timestamp": time.time() - start_time,
                "metrics": self.latest_metrics.copy(),
            })

            # Sleep only the remainder of the interval, so the loop holds a
            # steady cadence rather than drifting by however long the agent
            # took to decide.
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
                elif msg.msg_type == MessageType.FINISHED:
                    self.final_results[msg.connection_id] = msg.payload
            except Exception:
                break  # Queue empty or connection closed

    def get_total_throughput(self) -> dict:
        """
        Calculate total throughput across all 3 connections.

        Returns dict with:
        - total_throughput_mbps: Sum of all connections' throughput in Mbps
        - total_throughput_bps: Sum in bytes/sec
        - per_connection: Individual throughputs for breakdown
        """
        total_bps = 0.0
        per_connection = {}

        for conn_id in [1, 2, 3]:
            metrics = self.latest_metrics.get(conn_id, {})
            # Use cwnd-limited throughput (most accurate for bottleneck), then fall back
            tp_bps = (metrics.get("throughput_cwnd", 0) or
                      metrics.get("throughput_acked_delta", 0) or
                      metrics.get("throughput_acked", 0))
            total_bps += tp_bps
            per_connection[conn_id] = {
                "throughput_bps": tp_bps,
                "throughput_mbps": tp_bps * 8 / 1_000_000,  # Convert to Mbps
            }

        return {
            "total_throughput_bps": total_bps,
            "total_throughput_mbps": total_bps * 8 / 1_000_000,  # Convert to Mbps
            "per_connection": per_connection,
        }

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

    def _record_action(self, conn_id: int, params: dict, timestamp: float):
        """Record a Q-learning action for later metrics capture."""
        # Initialize current params tracking if needed
        if conn_id not in self._current_params:
            self._current_params[conn_id] = {}

        # Sync current params from worker metrics if available (more accurate than our tracking)
        worker_params = self.latest_metrics.get(conn_id, {}).get("current_params", {})
        if worker_params:
            self._current_params[conn_id].update(worker_params)

        for param_name, new_value in params.items():
            # Get old value from our tracking, fall back to worker metrics, then to new_value
            old_value = self._current_params.get(conn_id, {}).get(param_name)
            if old_value is None:
                old_value = worker_params.get(param_name, new_value)

            # Skip recording if no actual change (can happen due to sync timing)
            if old_value == new_value:
                continue

            direction = "increase" if new_value > old_value else "decrease"

            action = QLearningAction(
                timestamp=timestamp,
                connection_id=conn_id,
                param_name=param_name,
                old_value=old_value,
                new_value=new_value,
                direction=direction,
                metrics_before=self._copy_metrics(),
                metrics_after={},
                settled=False,
            )
            self._pending_actions.append(action)

            # Update tracked params
            if conn_id not in self._current_params:
                self._current_params[conn_id] = {}
            self._current_params[conn_id][param_name] = new_value

    def _check_settled_actions(self, now: float):
        """Check pending actions and capture metrics for those that have settled."""
        still_pending = []
        for action in self._pending_actions:
            if (now - action.timestamp) >= self.SETTLING_TIME:
                # Settling time has passed, capture current metrics
                action.metrics_after = self._copy_metrics()
                action.settled = True
                self.qlearning_history.append(action)
            else:
                still_pending.append(action)
        self._pending_actions = still_pending

    def _copy_metrics(self) -> Dict[int, dict]:
        """Create a deep copy of current metrics."""
        return {k: v.copy() for k, v in self.latest_metrics.items()}

    def get_qlearning_history(self) -> List[dict]:
        """Get Q-learning action history as serializable dicts."""
        history = []
        for action in self.qlearning_history:
            history.append({
                "timestamp": action.timestamp,
                "connection_id": action.connection_id,
                "param_name": action.param_name,
                "old_value": action.old_value,
                "new_value": action.new_value,
                "direction": action.direction,
                "metrics_before": action.metrics_before,
                "metrics_after": action.metrics_after,
                "settled": action.settled,
            })
        return history

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

    def export_qlearning_history(self, output_dir: str, scenario: str = "") -> str:
        """
        Export Q-learning history to organized folder structure.

        Creates:
        results/
        └── {scenario}/
            └── run_{timestamp}/
                ├── README.md
                ├── qlearning_actions.json
                ├── qlearning_actions.csv
                └── metrics.json
        """
        import csv
        import json
        import os
        from datetime import datetime, timezone, timedelta

        # Convert to Pacific Time (PST/PDT)
        # PST is UTC-8, PDT is UTC-7 (we'll use the TZ env var if set, otherwise default to Pacific)
        utc_now = datetime.now(timezone.utc)
        try:
            import zoneinfo
            pacific_tz = zoneinfo.ZoneInfo("America/Los_Angeles")
            pacific_now = utc_now.astimezone(pacific_tz)
        except (ImportError, Exception):
            # Fallback: assume PST (UTC-8) if zoneinfo not available
            pacific_now = utc_now.astimezone(timezone(timedelta(hours=-8)))

        # Format: Apr06_2026_1234PM (12-hour format with AM/PM)
        timestamp = pacific_now.strftime('%b%d_%Y_%I%M%p')
        timestamp_readable = pacific_now.strftime('%B %d, %Y at %I:%M %p %Z')
        scenario_name = scenario or "default"

        # Create hierarchical folder structure: output_dir/scenario/run_timestamp/
        run_dir = os.path.join(output_dir, scenario_name, f"run_{timestamp}")
        os.makedirs(run_dir, exist_ok=True)

        # Get agent based on tracked agent type (set during controller initialization)
        agent = None
        summary = {}
        try:
            if self.ml_agent_type == "andy":
                from ml_callbacks.q_learning_agent_andy import get_agent as get_andy_agent
                agent = get_andy_agent()
            elif self.ml_agent_type == "hybrid":
                from ml_callbacks.q_learning_agent_hybrid import get_agent as get_hybrid_agent
                agent = get_hybrid_agent()
            else:
                from ml_callbacks.q_learning_agent import get_agent
                agent = get_agent()
            summary = agent.summary()
        except Exception as e:
            print(f"[MLController] Warning: Could not get agent summary: {e}")
            summary = {}

        # Connection names for readability
        conn_names = {
            1: "Video Streaming",
            2: "File Transfer",
            3: "Conference Call"
        }
        conn_names_short = {
            1: "video_streaming",
            2: "file_transfer",
            3: "conference_call"
        }

        # Format history for export
        formatted_history = []
        for action in self.qlearning_history:
            conn_id = action.connection_id
            metrics_before = action.metrics_before.get(conn_id, {})
            metrics_after = action.metrics_after.get(conn_id, {})

            formatted_history.append({
                "action_number": len(formatted_history) + 1,
                "timestamp": action.timestamp,
                "connection_id": conn_id,
                "connection_name": conn_names_short.get(conn_id, f"connection_{conn_id}"),
                "parameter": action.param_name,
                "old_value": action.old_value,
                "new_value": action.new_value,
                "direction": action.direction,
                "metrics_before": {
                    "throughput_mbps": (metrics_before.get("throughput_cwnd", 0) or
                                       metrics_before.get("throughput_acked_delta", 0) or
                                       metrics_before.get("throughput_acked", 0)) / 1_000_000,
                    "rtt_ms": metrics_before.get("rtt", 0) * 1000,
                    "jitter_ms": metrics_before.get("jitter", 0) * 1000,
                    "loss_percent": metrics_before.get("packet_loss_rate", 0) * 100,
                },
                "metrics_after": {
                    "throughput_mbps": (metrics_after.get("throughput_cwnd", 0) or
                                       metrics_after.get("throughput_acked_delta", 0) or
                                       metrics_after.get("throughput_acked", 0)) / 1_000_000,
                    "rtt_ms": metrics_after.get("rtt", 0) * 1000,
                    "jitter_ms": metrics_after.get("jitter", 0) * 1000,
                    "loss_percent": metrics_after.get("packet_loss_rate", 0) * 100,
                },
            })

        # 1. Write qlearning_actions.json
        json_data = {
            "export_timestamp": datetime.now().isoformat(),
            "scenario": scenario_name,
            "summary": {
                "total_actions": len(self.qlearning_history),
                "total_steps": summary.get("steps", 0),
                "final_epsilon": summary.get("epsilon", 0),
                "q_states_visited": summary.get("states_visited", 0),
                "avg_reward_last_100": summary.get("avg_reward_last_100", 0),
            },
            "actions": formatted_history,
        }
        json_path = os.path.join(run_dir, "qlearning_actions.json")
        with open(json_path, "w") as f:
            json.dump(json_data, f, indent=2)

        # 2. Write qlearning_actions.csv
        csv_path = os.path.join(run_dir, "qlearning_actions.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Action #", "Connection", "Parameter", "Old Value", "New Value", "Direction",
                "Before: Throughput (MB/s)", "Before: RTT (ms)", "Before: Jitter (ms)", "Before: Loss (%)",
                "After: Throughput (MB/s)", "After: RTT (ms)", "After: Jitter (ms)", "After: Loss (%)"
            ])
            for action in formatted_history:
                mb = action["metrics_before"]
                ma = action["metrics_after"]
                writer.writerow([
                    action["action_number"],
                    action["connection_name"],
                    action["parameter"],
                    action["old_value"],
                    action["new_value"],
                    action["direction"],
                    f"{mb['throughput_mbps']:.3f}",
                    f"{mb['rtt_ms']:.2f}",
                    f"{mb['jitter_ms']:.2f}",
                    f"{mb['loss_percent']:.2f}",
                    f"{ma['throughput_mbps']:.3f}",
                    f"{ma['rtt_ms']:.2f}",
                    f"{ma['jitter_ms']:.2f}",
                    f"{ma['loss_percent']:.2f}",
                ])

        # 3. Write metrics.json (final metrics for each connection)
        metrics_data = {
            "export_timestamp": datetime.now().isoformat(),
            "scenario": scenario_name,
            "connections": {}
        }
        total_throughput_bps = 0.0
        total_bytes_sent = 0
        for conn_id, metrics in self.latest_metrics.items():
            # Use cwnd-limited throughput (most accurate for bottleneck scenarios)
            tp_bps = (metrics.get("throughput_cwnd", 0) or
                      metrics.get("throughput_acked_delta", 0) or
                      metrics.get("throughput_acked", 0))
            total_throughput_bps += tp_bps
            total_bytes_sent += metrics.get("bytes_sent", 0)
            metrics_data["connections"][conn_names_short.get(conn_id, f"conn_{conn_id}")] = {
                "throughput_mbps": tp_bps * 8 / 1_000_000,  # Convert to Mbps
                "rtt_ms": metrics.get("rtt", 0) * 1000,
                "jitter_ms": metrics.get("jitter", 0) * 1000,
                "loss_percent": metrics.get("packet_loss_rate", 0) * 100,
                "bytes_sent": metrics.get("bytes_sent", 0),
            }
        # Add total throughput across all connections
        metrics_data["total"] = {
            "throughput_mbps": total_throughput_bps * 8 / 1_000_000,
            "throughput_bps": total_throughput_bps,
            "bytes_sent": total_bytes_sent,
        }
        metrics_path = os.path.join(run_dir, "metrics.json")
        with open(metrics_path, "w") as f:
            json.dump(metrics_data, f, indent=2)

        # 4. Write q_table.json (the learned Q-values)
        try:
            q_table_data = agent.get_q_table_export()
            q_table_data["export_timestamp"] = datetime.now().isoformat()
            q_table_data["scenario"] = scenario_name
            q_table_path = os.path.join(run_dir, "q_table.json")
            with open(q_table_path, "w") as f:
                json.dump(q_table_data, f, indent=2)
        except Exception as e:
            print(f"[MLController] Warning: Could not export q_table.json: {e}")

        # 5. Write metrics_timeseries.csv (continuous metrics over time)
        timeseries_path = os.path.join(run_dir, "metrics_timeseries.csv")
        with open(timeseries_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp",
                "conn1_throughput_mbps", "conn1_rtt_ms", "conn1_jitter_ms", "conn1_loss_pct",
                "conn2_throughput_mbps", "conn2_rtt_ms", "conn2_jitter_ms", "conn2_loss_pct",
                "conn3_throughput_mbps", "conn3_rtt_ms", "conn3_jitter_ms", "conn3_loss_pct",
                "total_throughput_mbps",
            ])
            for entry in self.metrics_history:
                ts = entry.get("timestamp", 0)
                row = [f"{ts:.2f}"]
                total_tp = 0.0
                for conn_id in [1, 2, 3]:
                    m = entry.get("metrics", {}).get(conn_id, {})
                    # Use cwnd-limited throughput (most accurate for bottleneck scenarios)
                    tp_bps = (m.get("throughput_cwnd", 0) or
                              m.get("throughput_acked_delta", 0) or
                              m.get("throughput_acked", 0))
                    tp_mbps = tp_bps * 8 / 1_000_000  # Convert to Mbps
                    total_tp += tp_mbps
                    rtt = m.get("rtt", 0) * 1000
                    jitter = m.get("jitter", 0) * 1000
                    loss = m.get("packet_loss_rate", 0) * 100
                    row.extend([f"{tp_mbps:.4f}", f"{rtt:.2f}", f"{jitter:.2f}", f"{loss:.3f}"])
                row.append(f"{total_tp:.4f}")
                writer.writerow(row)

        # 6. Write config.json (run configuration for reproducibility)
        try:
            qlearning_params = agent.get_hyperparameters()
        except Exception:
            qlearning_params = {}

        config_data = {
            "export_timestamp": datetime.now().isoformat(),
            "scenario": scenario_name,
            "qlearning": qlearning_params,
            "connections": {
                "video_streaming": self._current_params.get(1, {}),
                "file_transfer": self._current_params.get(2, {}),
                "conference_call": self._current_params.get(3, {}),
            },
            "controller": {
                "decision_interval": self.decision_interval,
                "settling_time": self.SETTLING_TIME,
            },
        }
        config_path = os.path.join(run_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(config_data, f, indent=2)

        # 7. Write rewards.csv (reward at each Q-learning step)
        try:
            detailed_history = agent.get_detailed_history()
            rewards_path = os.path.join(run_dir, "rewards.csv")
            with open(rewards_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["step", "timestamp", "reward", "epsilon", "action", "state", "next_state"])
                for entry in detailed_history:
                    writer.writerow([
                        entry.get("step", 0),
                        f"{entry.get('timestamp', 0):.2f}",
                        f"{entry.get('reward', 0):.4f}",
                        f"{entry.get('epsilon', 0):.4f}",
                        entry.get("action_decoded", ""),
                        str(entry.get("state", "")),
                        str(entry.get("next_state", "")),
                    ])
        except Exception as e:
            print(f"[MLController] Warning: Could not export rewards.csv: {e}")

        # 8. Write README.md
        readme_path = os.path.join(run_dir, "README.md")
        self._write_readme(readme_path, scenario_name, timestamp_readable, summary,
                          formatted_history, conn_names, self.latest_metrics,
                          len(self.metrics_history), len(detailed_history) if 'detailed_history' in dir() else 0)

        print(f"[MLController] Q-learning results exported to {run_dir}/")
        return run_dir

    def _write_readme(self, filepath: str, scenario: str, timestamp: str,
                      summary: dict, actions: list, conn_names: dict, final_metrics: dict,
                      timeseries_count: int = 0, rewards_count: int = 0):
        """Generate a human-readable README.md summary."""
        lines = [
            f"# Q-Learning Run Report",
            f"",
            f"**Scenario:** {scenario}  ",
            f"**Timestamp:** {timestamp}  ",
            f"**Total Q-Learning Steps:** {summary.get('steps', 0)}  ",
            f"**Parameter Changes:** {len(actions)}  ",
            f"**Final Exploration Rate (ε):** {summary.get('epsilon', 0):.1%}  ",
            f"**Q-States Visited:** {summary.get('states_visited', 0)}  ",
            f"**Avg Reward (last 100):** {summary.get('avg_reward_last_100', 0):.4f}  ",
            f"",
            f"---",
            f"",
            f"## Final Metrics by Connection",
            f"",
            f"| Connection | Throughput (MB/s) | RTT (ms) | Jitter (ms) | Loss (%) |",
            f"|------------|-------------------|----------|-------------|----------|",
        ]

        conn_names_short = {1: "video_streaming", 2: "file_transfer", 3: "conference_call"}
        total_tp = 0.0
        for conn_id in [1, 2, 3]:
            metrics = final_metrics.get(conn_id, {})
            # Use cwnd-limited throughput (most accurate for bottleneck scenarios)
            tp_bps = (metrics.get("throughput_cwnd", 0) or
                      metrics.get("throughput_acked_delta", 0) or
                      metrics.get("throughput_acked", 0))
            tp = tp_bps * 8 / 1_000_000  # Convert to Mbps
            total_tp += tp
            rtt = metrics.get("rtt", 0) * 1000
            jitter = metrics.get("jitter", 0) * 1000
            loss = metrics.get("packet_loss_rate", 0) * 100
            lines.append(f"| {conn_names.get(conn_id, f'Conn {conn_id}')} | {tp:.3f} | {rtt:.2f} | {jitter:.2f} | {loss:.2f} |")

        # Add total throughput row
        lines.append(f"| **Total** | **{total_tp:.3f}** | - | - | - |")

        lines.extend([
            f"",
            f"---",
            f"",
            f"## Q-Learning Actions (Parameter Changes)",
            f"",
        ])

        if not actions:
            lines.append("*No parameter changes were made during this run (all no-op actions).*")
        else:
            lines.extend([
                f"| # | Connection | Parameter | Change | Before → After (Throughput) | RTT Change |",
                f"|---|------------|-----------|--------|------------------------------|------------|",
            ])
            for action in actions:
                conn = action["connection_name"].replace("_", " ").title()
                param = action["parameter"]
                change = f"{action['old_value']} → {action['new_value']}"
                mb = action["metrics_before"]
                ma = action["metrics_after"]
                tp_change = f"{mb['throughput_mbps']:.2f} → {ma['throughput_mbps']:.2f} MB/s"
                rtt_change = f"{mb['rtt_ms']:.1f} → {ma['rtt_ms']:.1f} ms"
                lines.append(f"| {action['action_number']} | {conn} | {param} | {change} | {tp_change} | {rtt_change} |")

        lines.extend([
            f"",
            f"---",
            f"",
            f"## Files in this Directory",
            f"",
            f"| File | Description | Rows/Entries |",
            f"|------|-------------|--------------|",
            f"| `README.md` | This summary file | - |",
            f"| `qlearning_actions.json` | Parameter changes with before/after metrics | {len(actions)} actions |",
            f"| `qlearning_actions.csv` | Same as above, for spreadsheets | {len(actions)} rows |",
            f"| `metrics.json` | Final metrics for each connection | 3 connections |",
            f"| `q_table.json` | Learned Q-values (the trained policy) | {summary.get('states_visited', 0)} states |",
            f"| `metrics_timeseries.csv` | Metrics at every time step (includes total throughput) | {timeseries_count} rows |",
            f"| `config.json` | Run configuration & hyperparameters | - |",
            f"| `rewards.csv` | Reward at each Q-learning step | {rewards_count} rows |",
            f"",
            f"---",
            f"",
            f"## How to Use These Files",
            f"",
            f"### For Analysis",
            f"- **Quick overview**: Read this `README.md`",
            f"- **Plot metrics over time**: Import `metrics_timeseries.csv` into Excel/Python",
            f"- **Analyze learning**: Check `rewards.csv` for reward progression",
            f"",
            f"### For Research",
            f"- **Reproduce this run**: Use settings from `config.json`",
            f"- **Study learned policy**: Examine `q_table.json`",
            f"- **Compare runs**: Diff the `metrics.json` files across runs",
            f"",
        ])

        with open(filepath, "w") as f:
            f.write("\n".join(lines))
