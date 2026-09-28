"""
Hybrid Q-Learning Agent (10-Feature State Design)
=================================================

Combines the default agent's awareness of network conditions with the two most
useful signals from Andy's parameter-index design, aiming for a state space
rich enough to act on boundaries and imbalance yet small enough to generalise.
Selected with --ml-agent hybrid.

    From the default agent : condition bins, trends, loss and CWND awareness
    From Andy's agent      : boundary awareness and a fairness indicator,
                             each compressed to a single feature

How to run
----------
    uv run python -m main run --with-ml --ml-agent hybrid --duration 120
    uv run python -m main run --with-ml --ml-agent hybrid --scenario varying --duration 600

State space (10 features)
-------------------------
    state = (
        lat_bin,         latency condition            (0-3)
        tp_bin,          throughput condition         (0-3)
        jit_bin,         jitter condition             (0-3)
        lat_trend,       latency trend                (0-2)
        tp_trend,        throughput trend             (0-2)
        jit_trend,       jitter trend                 (0-2)
        loss_bin,        packet loss severity         (0-3)
        cwnd_bin,        congestion window state      (0-3)
        boundary_count,  parameters at a min/max bound (0-12)
        dominant_conn,   which connection dominates bandwidth (0-3)
    )

The final two features are the compression that defines this design. Rather
than tracking twelve individual parameter indices as Andy's agent does,
`boundary_count` reduces that to a single count of how many dials are pinned,
and `dominant_conn` summarises allocation imbalance in one value. Both signals
are retained while the state space stays roughly twelve times smaller.

Total state space: 4^5 * 3^3 * 13 * 4 = 995,328 states
    - 36x larger than the default agent  (27,648)
    - 12x smaller than Andy's agent      (~11.6M)

Action space: 25 actions, identical to the default and Andy agents
    - 24 parameter adjustments (4 parameters x 3 connections x 2 directions)
    - 1 no-op

Reward function: identical to the default and Andy agents
    - Video:      70% latency utility + 30% throughput utility
    - File:       100% throughput utility
    - Conference: 70% jitter utility + 30% throughput utility
    - Stability penalty  (mu = 0.05, applied when a parameter changed)
    - Starvation penalty (0.2 per connection below 500 KB/s)
    - Suffering penalty  (0.15 per connection with utility below 0.4)

    R = mean(U_video, U_file, U_conf) - churn - starvation - suffering

Fairness here is threshold-based rather than variance-based: a connection is
penalised only for falling below an absolute floor, not for being unequal. This
lets file transfer legitimately take a larger share while still preventing the
other two from being starved. Earlier descriptions of this agent cited a
variance-based fairness term (lambda = 0.25); that term is not present in the
implementation.

Throughput metric: throughput_acked_delta, as in the default agent.

Connections
-----------
Imports from : standard library only (ast, json, math, os, random,
               statistics, time, typing)
Imported by  : simulation.ml_controller and main.py (lazily, by agent type);
               selected with --ml-agent hybrid
Related      : q_learning_agent.py (8-feature default),
               q_learning_agent_andy.py (14-feature variant)
"""

import ast
import json
import math
import os
import random
import statistics
import time
from typing import Dict, List, Optional, Tuple

# Connection identities (match multi_connection_config.py)
CONN_VIDEO = 1  # video streaming (min latency)
CONN_FILE = 2   # file transfer (max throughput)
CONN_CONF = 3   # conference call (min jitter)
CONNECTIONS = [CONN_VIDEO, CONN_FILE, CONN_CONF]

# Metric bin thresholds (SI units: seconds, bytes/second)

# Latency (s) 0=excellent to 3=poor
LATENCY_BINS = [0.010, 0.025, 0.050]  # 10ms, 25ms, 50ms

# Throughput (bytes/s) 0=poor to 3=excellent
THROUGHPUT_BINS = [1_000_000, 2_000_000, 3_000_000]  # 1MB/s, 2MB/s, 3MB/s

# Jitter (s) 0=excellent to 3=poor
JITTER_BINS = [0.005, 0.015, 0.030]  # 5ms, 15ms, 30ms

# Packet loss rate (ratio 0-1) 0=excellent to 3=poor
LOSS_RATE_BINS = [0.01, 0.05, 0.10]  # 1%, 5%, 10%

# Congestion window (packets) 0=tight to 3=wide open
CWND_BINS = [10, 30, 60]  # 10 packets (tight), 30 (moderate), 60+ (open)

# Normalize rewards
LATENCY_BEST = 0.020   # 20ms floor
LATENCY_WORST = 0.200  # 200ms
THROUGHPUT_MAX = 1_250_000.0  # 10 Mbps in bytes/s = fair share of 30 Mbps shared link
JITTER_WORST = 0.050   # 50ms

# Reward penalty weights
MU_STABILITY = 0.05  # penalise unnecessary parameter changes

# Starvation prevention (throughput-based)
MIN_VIABLE_THROUGHPUT = 500_000  # 500 KB/s minimum per connection
STARVATION_PENALTY = 0.2         # penalty per starving connection

# Suffering prevention (utility-based) - Option B fairness
# Only penalize when a connection's utility drops below threshold (not strict equality)
UTILITY_SUFFERING_THRESHOLD = 0.4  # Below this = connection is suffering
UTILITY_SUFFERING_PENALTY = 0.15   # Penalty per suffering connection

# Throughput metric selection
THROUGHPUT_METRIC = "delta"  # Uses throughput_acked_delta like Default

# Q-learning parameters
ALPHA = 0.10          # learning rate
GAMMA = 0.90          # discount factor
EPSILON_START = 0.30  # initial exploration probability
EPSILON_MIN = 0.05    # floor for exploration
EPSILON_DECAY = 0.995 # multiplicative decay per decision step

# Timing
CONTROL_INTERVAL = 2.0  # seconds between Q-learning decisions

# Parameter search space (same as Default and Andy)
PARAM_SPACE: Dict[str, dict] = {
    "loss_reduction_factor": {"step": 0.1, "min": 0.3, "max": 0.7, "integer": False},
    "cubic_c": {"step": 0.1, "min": 0.2, "max": 0.4, "integer": False},
    "minimum_window": {"step": 1, "min": 2, "max": 4, "integer": True},
    "packet_threshold": {"step": 1, "min": 3, "max": 4, "integer": True},
}
TUNABLE_PARAMS = list(PARAM_SPACE.keys())

# Action encoding
N_PARAMS = len(TUNABLE_PARAMS)  # 4
N_CONNS = len(CONNECTIONS)      # 3
N_ACTIONS = N_CONNS * N_PARAMS * 2 + 1  # 25
ACTION_NOOP = N_ACTIONS - 1     # 24


# Helper functions

def _bin(value: float, thresholds: List[float], lower_is_better: bool) -> int:
    """
    Map a continuous measurement onto a zero-based discrete bin index.

    Discretisation is what makes tabular Q-learning possible here: a continuous
    metric would give every observation a unique state and the Q-table would
    never revisit one.

    Args:
        value: The measurement to bin.
        thresholds: Ascending bin boundaries; N thresholds yield N+1 bins.
        lower_is_better: True for latency, jitter and loss; False for
            throughput and congestion window.

    Returns:
        For lower_is_better metrics, 0 means excellent and N means poor. For
        higher_is_better metrics the ordering is reversed, so a larger index
        always denotes a better condition for that metric.
    """
    if lower_is_better:
        for i, t in enumerate(thresholds):
            if value <= t:
                return i
        return len(thresholds)  # worst
    else:
        for i, t in enumerate(thresholds):
            if value < t:
                return i
        return len(thresholds)  # best


def _trend(current: float, previous: Optional[float], higher_is_better: bool) -> int:
    """
    Classify the direction of change in a metric.

    Trend is part of the state because the level alone is ambiguous: a
    connection performing poorly but recovering warrants a different action
    from one performing poorly and deteriorating.

    A 5% tolerance band around the previous value suppresses measurement noise;
    without it, ordinary sampling jitter would flip this feature constantly and
    fragment the Q-table across states differing only by noise.

    Returns:
        0 worsening, 1 stable, 2 improving. The first observation reports
        stable, there being no prior value to compare against.
    """
    if previous is None or previous == 0.0:
        return 1  # stable on first step

    tol = abs(previous) * 0.05
    delta = current - previous

    if higher_is_better:
        if delta > tol:
            return 2   # improved (went up)
        if delta < -tol:
            return 0   # worse (went down)
    else:
        if delta < -tol:
            return 2   # improved (went down)
        if delta > tol:
            return 0   # worse (went up)
    return 1  # stable


def _utility_latency(v: float) -> float:
    """
    Normalise latency to [0, 1], where 1 is best.

    Clamped at both ends so latency beyond the configured worst case cannot
    drive the reward negative, keeping the three connections' utilities
    commensurable when averaged.
    """
    u = (LATENCY_WORST - v) / (LATENCY_WORST - LATENCY_BEST)
    return max(0.0, min(1.0, u))


def _utility_throughput(v: float) -> float:
    """
    Normalise throughput to [0, 1], where 1 is best.

    THROUGHPUT_MAX is one connection's fair share of the shared link rather
    than the link's full capacity, so a connection reaches utility 1.0 by
    taking its share rather than by monopolising the bottleneck.
    """
    return max(0.0, min(1.0, v / THROUGHPUT_MAX))


def _utility_jitter(v: float) -> float:
    """
    Normalise jitter to [0, 1], where 1 is best.

    Guards against a zero JITTER_WORST, which would otherwise divide by zero;
    in that degenerate configuration every jitter value scores perfectly.
    """
    if JITTER_WORST == 0:
        return 1.0
    return max(0.0, min(1.0, (JITTER_WORST - v) / JITTER_WORST))


def _get_throughput(metrics: Dict[int, dict], conn_id: int) -> float:
    """
    Read throughput for one connection using the configured source.

    The choice matters for learning quality:
      - "delta"   per-epoch ACK-verified rate. Responsive to recent change,
                  which is what a controller acting every 2s needs to see.
      - "acked"   cumulative ACK-verified average. Stable but increasingly
                  insensitive as a run lengthens.
      - "offered" application send rate. Ignores what the bottleneck actually
                  delivered, so it can report high throughput while nothing
                  arrives.

    "delta" is the default for those reasons, falling back to the cumulative
    figure during the first few ticks before a delta window has closed.

    Returns:
        Throughput in bytes per second.
    """
    conn_metrics = metrics.get(conn_id, {})

    if THROUGHPUT_METRIC == "delta":
        delta = conn_metrics.get("throughput_acked_delta", 0.0)
        if delta > 0:
            return delta
        return conn_metrics.get("throughput_acked", 0.0)
    elif THROUGHPUT_METRIC == "acked":
        return conn_metrics.get("throughput_acked", 0.0)
    else:  # "offered"
        return conn_metrics.get("throughput", 0.0)


def _clamp(name: str, value: float) -> float:
    """Clamp parameter value to defined range and round integers."""
    spec = PARAM_SPACE[name]
    v = max(spec["min"], min(spec["max"], value))
    return round(v) if spec["integer"] else round(v, 1)


def _decode_action(action: int) -> Optional[Tuple[int, str, int]]:
    """Decode action index to (connection_id, param_name, direction)."""
    if action == ACTION_NOOP:
        return None
    conn_idx = action // (N_PARAMS * 2)
    remainder = action % (N_PARAMS * 2)
    param_idx = remainder // 2
    direction = remainder % 2
    return CONNECTIONS[conn_idx], TUNABLE_PARAMS[param_idx], direction


class QLearningAgentHybrid:
    """
    Hybrid Q-learning agent combining Default's network awareness with
    Andy's parameter boundary insights.

    10-feature state space (~1M states) balances convergence speed with
    boundary-aware and fairness-aware decision making.
    """

    def __init__(
        self,
        alpha: float = ALPHA,
        gamma: float = GAMMA,
        epsilon: float = EPSILON_START,
        epsilon_min: float = EPSILON_MIN,
        epsilon_decay: float = EPSILON_DECAY,
        control_interval: float = CONTROL_INTERVAL,
        checkpoint_path: Optional[str] = None,
    ):
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.control_interval = control_interval
        self.checkpoint_path = checkpoint_path

        # Q-table: sparse dict {state_tuple -> [Q value per action]}
        self._q: Dict[Tuple, List[float]] = {}

        # Timing
        self._last_decision_time: float = 0.0
        self._last_state: Optional[Tuple] = None
        self._last_action: Optional[int] = None
        self._last_action_changed: bool = False

        # Parameter tracker (synced from worker metrics each tick)
        self._params: Dict[int, Dict[str, float]] = {
            CONN_VIDEO: {"loss_reduction_factor": 0.5, "cubic_c": 0.3,
                         "minimum_window": 3, "packet_threshold": 3},
            CONN_FILE:  {"loss_reduction_factor": 0.7, "cubic_c": 0.4,
                         "minimum_window": 4, "packet_threshold": 3},
            CONN_CONF:  {"loss_reduction_factor": 0.5, "cubic_c": 0.2,
                         "minimum_window": 4, "packet_threshold": 3},
        }

        # Trend tracking
        self._prev_latency: Optional[float] = None
        self._prev_throughput: Optional[float] = None
        self._prev_jitter: Optional[float] = None

        # Stats
        self.step_count: int = 0
        self._reward_log: List[float] = []
        self._detailed_history: List[dict] = []
        self._checkpoint_loaded = False

        # Load checkpoint if exists
        if checkpoint_path:
            if os.path.exists(checkpoint_path):
                self._load(checkpoint_path)
                self._checkpoint_loaded = True
            else:
                print(f"[HybridAgent] No checkpoint found at {checkpoint_path} - starting fresh")

        print(
            f"[HybridAgent] Initialised - 10-feature state, {N_ACTIONS} actions, "
            f"control_interval={self.control_interval}s, "
            f"α={self.alpha} γ={self.gamma} ε={self.epsilon}→{self.epsilon_min}"
        )

    # Q-table helpers

    def _get_q(self, state: Tuple) -> List[float]:
        """Return Q-values for state, initialising to 0 on first visit."""
        if state not in self._q:
            self._q[state] = [0.0] * N_ACTIONS
        return self._q[state]

    def _best_action(self, state: Tuple) -> int:
        """Greedy action with random tie-breaking."""
        q_vals = self._get_q(state)
        max_q = max(q_vals)
        return random.choice([a for a, q in enumerate(q_vals) if q == max_q])

    def _update(self, s: Tuple, a: int, r: float, s_next: Tuple):
        """Bellman update: Q(s,a) <- Q(s,a) + α[r + γ·max Q(s',·) - Q(s,a)]"""
        q = self._get_q(s)
        q_max = max(self._get_q(s_next))
        q[a] += self.alpha * (r + self.gamma * q_max - q[a])

    # State building (10 features)

    def _compute_boundary_count(self) -> int:
        """
        Count how many parameters are at their min or max bounds.
        Range: 0-12 (4 params × 3 connections)

        This feature from Andy's insight helps the agent avoid wasting
        actions on parameters that can't be changed further.
        """
        count = 0
        for conn_id in CONNECTIONS:
            for param_name in TUNABLE_PARAMS:
                val = self._params[conn_id][param_name]
                spec = PARAM_SPACE[param_name]
                if val <= spec["min"] or val >= spec["max"]:
                    count += 1
        return count

    def _compute_dominant_conn(self, metrics: Dict[int, dict]) -> int:
        """
        Determine which connection is dominating bandwidth.
        Returns: 0=video, 1=file, 2=conference, 3=none/balanced

        A connection is "dominant" if it has >50% more throughput than others.
        This feature helps the agent make fairness-aware decisions.
        """
        throughputs = {c: _get_throughput(metrics, c) for c in CONNECTIONS}
        max_tp = max(throughputs.values())

        if max_tp == 0:
            return 3  # none

        # Check if any connection has >60% of max (dominant)
        for i, conn_id in enumerate(CONNECTIONS):
            tp = throughputs[conn_id]
            others = [throughputs[c] for c in CONNECTIONS if c != conn_id]
            if others and tp > 0:
                # Dominant if this connection has more than 1.5x the average of others
                avg_others = sum(others) / len(others)
                if avg_others > 0 and tp / avg_others > 1.5:
                    return i  # 0=video, 1=file, 2=conf

        return 3  # balanced/none

    def _build_state(self, metrics: Dict[int, dict]) -> Optional[Tuple]:
        """
        Build 10-feature discrete state tuple.

        Features 1-8: From Default (network awareness)
        - lat_bin, tp_bin, jit_bin: Current network conditions
        - lat_trend, tp_trend, jit_trend: Temporal trends
        - loss_bin: Packet loss severity
        - cwnd_bin: Congestion window state

        Features 9-10: From Andy's insight (compressed parameter awareness)
        - boundary_count: How many params at min/max (0-12)
        - dominant_conn: Which connection dominates bandwidth (0-3)

        Total state space: 4^5 × 3^3 × 13 × 4 = 995,328 states
        """
        if not all(c in metrics for c in CONNECTIONS):
            return None

        # Network metrics (from Default)
        lat = metrics[CONN_VIDEO].get("latency", 0.0)
        tp = _get_throughput(metrics, CONN_FILE)
        jit = metrics[CONN_CONF].get("jitter", 0.0)

        # Average loss across connections
        loss_rates = [metrics[c].get("packet_loss_rate", 0.0) for c in CONNECTIONS]
        avg_loss = sum(loss_rates) / len(loss_rates) if loss_rates else 0.0

        # Average CWND across connections
        cwnd_values = [metrics[c].get("cwnd", 20) for c in CONNECTIONS]
        avg_cwnd = sum(cwnd_values) / len(cwnd_values)

        # Bin the metrics
        lat_bin = _bin(lat, LATENCY_BINS, lower_is_better=True)
        tp_bin = _bin(tp, THROUGHPUT_BINS, lower_is_better=False)
        jit_bin = _bin(jit, JITTER_BINS, lower_is_better=True)
        loss_bin = _bin(avg_loss, LOSS_RATE_BINS, lower_is_better=True)
        cwnd_bin = _bin(avg_cwnd, CWND_BINS, lower_is_better=False)

        # Compute trends
        lat_trend = _trend(lat, self._prev_latency, higher_is_better=False)
        tp_trend = _trend(tp, self._prev_throughput, higher_is_better=True)
        jit_trend = _trend(jit, self._prev_jitter, higher_is_better=False)

        # Save for next step's trend calculation
        self._prev_latency = lat
        self._prev_throughput = tp
        self._prev_jitter = jit

        # NEW: Boundary count (from Andy's insight)
        boundary_count = self._compute_boundary_count()

        # NEW: Dominant connection (from Andy's insight)
        dominant_conn = self._compute_dominant_conn(metrics)

        return (lat_bin, tp_bin, jit_bin, lat_trend, tp_trend, jit_trend,
                loss_bin, cwnd_bin, boundary_count, dominant_conn)

    # Reward (same as Default)

    def _reward(self, metrics: Dict[int, dict], action_changed: bool) -> float:
        """
        Compute scalar reward from current metrics.

        Utility formula:
        - Video: 70% latency utility + 30% throughput utility
        - File: 100% throughput utility
        - Conference: 70% jitter utility + 30% throughput utility

        FAIRNESS (Option B): We use threshold-based fairness rather than strict equality.
        - Connections can have different utilities (file can excel)
        - Only penalize when a utility drops below UTILITY_SUFFERING_THRESHOLD (0.4)
        - This allows file to get more bandwidth as long as video/conference aren't suffering
        """
        if not all(c in metrics for c in CONNECTIONS):
            return 0.0

        # Get metrics for each connection
        video_lat = metrics[CONN_VIDEO].get("latency", 0.0)
        video_tp = _get_throughput(metrics, CONN_VIDEO)

        file_tp = _get_throughput(metrics, CONN_FILE)

        conf_jit = metrics[CONN_CONF].get("jitter", 0.0)
        conf_tp = _get_throughput(metrics, CONN_CONF)

        # Compute per-connection utilities
        u_video = 0.7 * _utility_latency(video_lat) + 0.3 * _utility_throughput(video_tp)
        u_file = _utility_throughput(file_tp)
        u_conf = 0.7 * _utility_jitter(conf_jit) + 0.3 * _utility_throughput(conf_tp)

        mean_u = (u_video + u_file + u_conf) / 3.0

        # Stability penalty: discourage unnecessary parameter changes
        churn = MU_STABILITY if action_changed else 0.0

        # Starvation penalty: heavy penalty if any connection falls below minimum viable throughput
        starvation = 0.0
        for conn_id, tp in [(CONN_VIDEO, video_tp), (CONN_FILE, file_tp), (CONN_CONF, conf_tp)]:
            if tp < MIN_VIABLE_THROUGHPUT:
                starvation += STARVATION_PENALTY

        # Suffering penalty : only penalize when a connection is struggling
        # This allows one connection to excel as long as others aren't suffering
        suffering = 0.0
        for u in [u_video, u_file, u_conf]:
            if u < UTILITY_SUFFERING_THRESHOLD:
                suffering += UTILITY_SUFFERING_PENALTY

        return mean_u - churn - starvation - suffering

    # Parameter management

    def _sync_from_metrics(self, metrics: Dict[int, dict]):
        """Sync internal parameter state from worker metrics."""
        for conn_id in CONNECTIONS:
            echoed = metrics.get(conn_id, {}).get("current_params", {})
            for p in TUNABLE_PARAMS:
                if p in echoed:
                    self._params[conn_id][p] = echoed[p]

    def _apply_action(self, action: int) -> Dict[int, Dict[str, float]]:
        """Apply action and return parameter changes."""
        decoded = _decode_action(action)
        if decoded is None:
            return {}  # no-op

        conn_id, param_name, direction = decoded
        step = PARAM_SPACE[param_name]["step"]
        current = self._params[conn_id][param_name]

        new_val = current + step if direction == 0 else current - step
        new_val = _clamp(param_name, new_val)

        if new_val == current:
            return {}  # already at boundary

        if new_val == self._params[conn_id].get(param_name):
            return {}

        self._params[conn_id][param_name] = new_val
        return {conn_id: {param_name: new_val}}

    def _is_action_at_boundary(self, action: int) -> bool:
        """Check if action would hit a parameter boundary."""
        decoded = _decode_action(action)
        if decoded is None:
            return False

        conn_id, param_name, direction = decoded
        spec = PARAM_SPACE[param_name]
        current = self._params[conn_id][param_name]

        if direction == 0:  # increase
            return current >= spec["max"]
        else:  # decrease
            return current <= spec["min"]

    # Main callback

    def __call__(self, metrics: Dict[int, dict]) -> Dict[int, dict]:
        """Called by MLController on every tick (~0.1s)."""
        now = time.time()

        # Always sync parameters from worker feedback
        self._sync_from_metrics(metrics)

        # Throttle to control interval
        if (now - self._last_decision_time) < self.control_interval:
            return {}

        # Build current state
        state = self._build_state(metrics)
        if state is None:
            return {}

        # Q-table update from last transition
        reward = None
        if self._last_state is not None and self._last_action is not None:
            changed = self._last_action_changed
            reward = self._reward(metrics, changed)
            self._update(self._last_state, self._last_action, reward, state)
            self._reward_log.append(reward)

            # Record detailed history
            decoded = _decode_action(self._last_action)
            if decoded is None:
                action_str = "no-op"
            else:
                conn_id, param, direction = decoded
                app = {CONN_VIDEO: "video", CONN_FILE: "file", CONN_CONF: "conf"}[conn_id]
                action_str = f"{app}.{param}.{'increase' if direction == 0 else 'decrease'}"

            self._detailed_history.append({
                "step": self.step_count,
                "timestamp": now,
                "state": self._last_state,
                "action": self._last_action,
                "action_decoded": action_str,
                "reward": reward,
                "epsilon": self.epsilon,
                "next_state": state,
            })

        # Epsilon-greedy action selection with boundary masking
        valid_actions = [a for a in range(N_ACTIONS) if not self._is_action_at_boundary(a)]
        if not valid_actions:
            valid_actions = [ACTION_NOOP]

        if random.random() < self.epsilon:
            action = random.choice(valid_actions)
        else:
            q_vals = self._get_q(state)
            valid_q = [(a, q_vals[a]) for a in valid_actions]
            max_q = max(q for _, q in valid_q)
            best_valid = [a for a, q in valid_q if q == max_q]
            action = random.choice(best_valid)

        # Decay exploration rate
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

        # Execute action
        decisions = self._apply_action(action)

        # Record transition
        self._last_state = state
        self._last_action = action
        self._last_action_changed = bool(decisions)
        self._last_decision_time = now
        self.step_count += 1

        # Periodic checkpoint
        if self.checkpoint_path and self.step_count % 50 == 0:
            if self._checkpoint_loaded or self.step_count >= 100:
                self._save(self.checkpoint_path)

        # Logging
        if self.step_count % 10 == 0:
            self._log(state, action, decisions, metrics)

        return decisions

    # Logging

    def _log(self, state, action, decisions, metrics):
        lat_ms = metrics.get(CONN_VIDEO, {}).get("latency", 0.0) * 1000
        jit_ms = metrics.get(CONN_CONF, {}).get("jitter", 0.0) * 1000
        tp_delta = metrics.get(CONN_FILE, {}).get("throughput_acked_delta", 0.0) * 8 / 1e6

        loss_rates = [metrics[c].get("packet_loss_rate", 0.0) for c in CONNECTIONS]
        avg_loss_pct = (sum(loss_rates) / len(loss_rates) * 100) if loss_rates else 0.0

        recent = self._reward_log[-10:] if self._reward_log else [0.0]
        avg_r = sum(recent) / len(recent)

        decoded = _decode_action(action)
        if decoded is None:
            act_str = "no-op"
        else:
            conn_id, param, direction = decoded
            app = {CONN_VIDEO: "video", CONN_FILE: "file", CONN_CONF: "conf"}[conn_id]
            act_str = f"{app}.{param} {'↑' if direction == 0 else '↓'}"

        # Extract hybrid-specific features
        boundary_count = state[8]
        dominant_conn = state[9]
        dominant_str = ["video", "file", "conf", "none"][dominant_conn]

        print(
            f"[HybridAgent step={self.step_count:4d}] "
            f"state={state[:8]} bounds={boundary_count} dom={dominant_str} "
            f"action={act_str} ε={self.epsilon:.3f} "
            f"lat={lat_ms:.1f}ms tp={tp_delta:.2f}Mbps jit={jit_ms:.1f}ms loss={avg_loss_pct:.1f}% "
            f"avg_R={avg_r:+.3f} Q-states={len(self._q)}"
        )

    # Checkpoint

    def _save(self, path: str):
        """Persist Q-table and training state to JSON."""
        try:
            data = {
                "q": {str(k): v for k, v in self._q.items()},
                "epsilon": self.epsilon,
                "step_count": self.step_count,
            }
            with open(path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"[HybridAgent] Checkpoint save failed: {e}")

    def _load(self, path: str):
        """Load Q-table and training state from JSON."""
        try:
            with open(path) as f:
                data = json.load(f)
            self._q = {ast.literal_eval(k): v for k, v in data["q"].items()}
            self.epsilon = data.get("epsilon", self.epsilon)
            self.step_count = data.get("step_count", 0)
            print(
                f"[HybridAgent] Checkpoint loaded: {len(self._q)} states, "
                f"step={self.step_count}, ε={self.epsilon:.3f}"
            )
        except Exception as e:
            print(f"[HybridAgent] Checkpoint load failed ({path}): {e}")

    # Analysis helpers

    def get_callback(self):
        """Return self as a callable ml_callback."""
        return self

    def summary(self) -> dict:
        """Return snapshot of agent's learned state."""
        if not self._q:
            return {"states_visited": 0, "avg_max_q": 0.0,
                    "epsilon": self.epsilon, "steps": self.step_count}
        max_qs = [max(v) for v in self._q.values()]
        return {
            "states_visited": len(self._q),
            "avg_max_q": sum(max_qs) / len(max_qs),
            "epsilon": self.epsilon,
            "steps": self.step_count,
            "avg_reward_last_100": (
                sum(self._reward_log[-100:]) / len(self._reward_log[-100:])
                if self._reward_log else 0.0
            ),
        }

    def get_q_table_export(self) -> dict:
        """Export Q-table data for saving to file."""
        bin_labels = {
            "lat": ["<10ms", "10-25ms", "25-50ms", ">50ms"],
            "tp": ["<1MB/s", "1-2MB/s", "2-3MB/s", ">3MB/s"],
            "jit": ["<5ms", "5-15ms", "15-30ms", ">30ms"],
            "loss": ["<1%", "1-5%", "5-10%", ">10%"],
            "cwnd": ["<10pkt", "10-30pkt", "30-60pkt", ">60pkt"],
            "trend": ["worsening", "stable", "improving"],
            "dominant": ["video", "file", "conf", "balanced"],
        }

        q_table_data = {}

        for state, q_values in self._q.items():
            state_str = str(state)
            lat_b, tp_b, jit_b, lat_t, tp_t, jit_t, loss_b, cwnd_b, bounds, dom = state

            state_readable = {
                "latency_bin": bin_labels["lat"][lat_b] if lat_b < 4 else f"bin_{lat_b}",
                "throughput_bin": bin_labels["tp"][tp_b] if tp_b < 4 else f"bin_{tp_b}",
                "jitter_bin": bin_labels["jit"][jit_b] if jit_b < 4 else f"bin_{jit_b}",
                "latency_trend": bin_labels["trend"][lat_t] if lat_t < 3 else f"trend_{lat_t}",
                "throughput_trend": bin_labels["trend"][tp_t] if tp_t < 3 else f"trend_{tp_t}",
                "jitter_trend": bin_labels["trend"][jit_t] if jit_t < 3 else f"trend_{jit_t}",
                "loss_bin": bin_labels["loss"][loss_b] if loss_b < 4 else f"bin_{loss_b}",
                "cwnd_bin": bin_labels["cwnd"][cwnd_b] if cwnd_b < 4 else f"bin_{cwnd_b}",
                "boundary_count": bounds,
                "dominant_conn": bin_labels["dominant"][dom] if dom < 4 else f"dom_{dom}",
            }

            best_action_idx = q_values.index(max(q_values))
            decoded = _decode_action(best_action_idx)
            if decoded is None:
                best_action_str = "no-op"
            else:
                conn_id, param, direction = decoded
                app = {CONN_VIDEO: "video", CONN_FILE: "file", CONN_CONF: "conf"}[conn_id]
                best_action_str = f"{app}.{param}.{'increase' if direction == 0 else 'decrease'}"

            q_table_data[state_str] = {
                "state_readable": state_readable,
                "q_values": q_values,
                "best_action": best_action_str,
                "best_q_value": max(q_values),
            }

        return {
            "total_states": len(self._q),
            "total_actions": N_ACTIONS,
            "hyperparameters": {
                "alpha": self.alpha,
                "gamma": self.gamma,
                "epsilon_start": EPSILON_START,
                "epsilon_min": self.epsilon_min,
                "epsilon_decay": self.epsilon_decay,
                "current_epsilon": self.epsilon,
            },
            "q_table": q_table_data,
        }

    def get_detailed_history(self) -> List[dict]:
        """Get detailed step-by-step history for rewards.csv export."""
        return self._detailed_history.copy()

    def get_hyperparameters(self) -> dict:
        """Get Q-learning hyperparameters for config export."""
        return {
            "alpha": self.alpha,
            "gamma": self.gamma,
            "epsilon_start": EPSILON_START,
            "epsilon_min": self.epsilon_min,
            "epsilon_decay": self.epsilon_decay,
            "control_interval": self.control_interval,
            "throughput_metric": THROUGHPUT_METRIC,
            "reward_weights": {
                "mu_stability": MU_STABILITY,
                "utility_suffering_threshold": UTILITY_SUFFERING_THRESHOLD,
                "utility_suffering_penalty": UTILITY_SUFFERING_PENALTY,
            },
            "metric_bounds": {
                "latency_best_s": LATENCY_BEST,
                "latency_worst_s": LATENCY_WORST,
                "throughput_max_bps": THROUGHPUT_MAX,
                "jitter_worst_s": JITTER_WORST,
            },
        }

    def best_actions_table(self) -> List[dict]:
        """Return best action for every visited state."""
        rows = []
        app_map = {
            CONN_VIDEO: "video_streaming",
            CONN_FILE: "file_transfer",
            CONN_CONF: "conference_call",
        }
        bin_labels = {
            "lat": ["<10ms", "10-25ms", "25-50ms", ">50ms"],
            "tp": ["<1MB/s", "1-2MB/s", "2-3MB/s", ">3MB/s"],
            "jit": ["<5ms", "5-15ms", "15-30ms", ">30ms"],
            "loss": ["<1%", "1-5%", "5-10%", ">10%"],
            "cwnd": ["<10pkt", "10-30pkt", "30-60pkt", ">60pkt"],
            "trend": ["worsening", "stable", "improving"],
            "dominant": ["video", "file", "conf", "balanced"],
        }

        for state, q_vals in self._q.items():
            lat_b, tp_b, jit_b, lat_t, tp_t, jit_t, loss_b, cwnd_b, bounds, dom = state

            best = q_vals.index(max(q_vals))
            decoded = _decode_action(best)
            if decoded is None:
                action_str = "no-op"
            else:
                conn_id, param, direction = decoded
                action_str = f"{app_map[conn_id]}.{param} {'increase' if direction == 0 else 'decrease'}"

            rows.append({
                "state": state,
                "lat_state": bin_labels["lat"][lat_b] if lat_b < 4 else f"bin_{lat_b}",
                "tp_state": bin_labels["tp"][tp_b] if tp_b < 4 else f"bin_{tp_b}",
                "jit_state": bin_labels["jit"][jit_b] if jit_b < 4 else f"bin_{jit_b}",
                "loss_state": bin_labels["loss"][loss_b] if loss_b < 4 else f"bin_{loss_b}",
                "cwnd_state": bin_labels["cwnd"][cwnd_b] if cwnd_b < 4 else f"bin_{cwnd_b}",
                "lat_trend": bin_labels["trend"][lat_t] if lat_t < 3 else f"trend_{lat_t}",
                "tp_trend": bin_labels["trend"][tp_t] if tp_t < 3 else f"trend_{tp_t}",
                "jit_trend": bin_labels["trend"][jit_t] if jit_t < 3 else f"trend_{jit_t}",
                "boundary_count": bounds,
                "dominant_conn": bin_labels["dominant"][dom] if dom < 4 else f"dom_{dom}",
                "best_action": action_str,
                "best_q": max(q_vals),
            })

        return sorted(rows, key=lambda r: r["best_q"], reverse=True)


# Module-level singleton

_agent: Optional[QLearningAgentHybrid] = None


def get_agent(checkpoint_path: Optional[str] = "output/q_learning_checkpoint_hybrid.json") -> QLearningAgentHybrid:
    """
    Return/create module-level hybrid agent singleton.

    Environment Variables:
        CLEAR_QTABLE: Set to "1" to delete existing checkpoint and start fresh
    """
    global _agent
    if _agent is None:
        if os.environ.get("CLEAR_QTABLE") == "1" and checkpoint_path:
            if os.path.exists(checkpoint_path):
                os.remove(checkpoint_path)
                print(f"[HybridAgent] CLEAR_QTABLE=1: Deleted checkpoint {checkpoint_path}")
        _agent = QLearningAgentHybrid(checkpoint_path=checkpoint_path)
    return _agent


def q_learning_callback(metrics: Dict[int, dict]) -> Dict[int, dict]:
    """Module-level callback for --with-ml flag."""
    return get_agent()(metrics)
