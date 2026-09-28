"""
Andy's Q-Learning Agent (14-Feature State Design)
=================================================

Author: Andy Li

Alternative Q-learning agent whose state is built from *parameter step indices*
plus aggregate network conditions, rather than from per-connection performance
bins as in the default agent. Selected with --ml-agent andy.

How to run
----------
    uv run python -m main run --with-ml --ml-agent andy --duration 120
    uv run python -m main run --with-ml --ml-agent andy --scenario congested_low --duration 120

Objectives, action space, reward function and learning rule are identical to
the default agent; only the state representation differs, which is what makes
the three agents directly comparable.

    Connection 1  video streaming   minimise latency
    Connection 2  file transfer     maximise throughput
    Connection 3  conference call   minimise jitter

Self-contained ml_callback with no dependencies beyond the standard library.
MLController calls it every `decision_interval` (0.1s); the agent throttles
itself to CONTROL_INTERVAL (2.0s) so CUBIC has time to respond before the
outcome is attributed to the change.

At each control step the agent reads all three connections' metrics, maps them
to a discrete state, selects an action epsilon-greedily, applies it, and
updates Q(s,a) once the result is observed.

State space (14 features)
-------------------------
    state = (
        lrf_v, lrf_f, lrf_c,   loss_reduction_factor step index (0-4) per conn
        cc_v,  cc_f,  cc_c,    cubic_c step index (0-2) per conn
        mw_v,  mw_f,  mw_c,    minimum_window step index (0-2) per conn
        pt_v,  pt_f,  pt_c,    packet_threshold step index (0-1) per conn
        tp_bin,                total throughput across all 3 conns (0-3)
        rtt_bin,               mean RTT across all 3 conns (0-3)
    )

The design rationale: parameter features are exact step indices, computed as
idx = round((value - min) / step), so the agent can tell when a dial has
already reached its boundary and that pushing further would be wasted. The
default agent, which sees only outcomes, cannot distinguish that case.

Network condition bins:
    TOTAL_TP_BINS = [500K, 2M, 3.5M] bytes/s   4 bins of total throughput
    RTT_BINS      = [50ms, 100ms, 200ms]       4 bins of mean RTT

Throughput metric: throughput_acked_delta, matching the default and hybrid
agents so the comparison is like for like.

State space size: 5^3 * 3^3 * 3^3 * 2^3 * 4 * 4 = approximately 11.6 million
theoretical states, of which only about 50-300 are visited in a typical run.
The Q-table is sparse and allocates only visited states, so this is tractable
in memory, but the sparsity is the central trade-off of this design: precise
parameter awareness comes at the cost of far less generalisation between
states than the default agent's 27,648-state representation affords.

Action space (25 actions)
-------------------------
Actions 0-23 adjust one parameter on one connection by one step (4 parameters
x 3 connections x 2 directions); action 24 is a no-op.

Tunable ranges, from the grid search results:

    loss_reduction_factor   step 0.1   range 0.3 - 0.7
    cubic_c                 step 0.1   range 0.2 - 0.4
    minimum_window          step 1     range 2 - 4
    packet_threshold        step 1     range 3 - 4

time_threshold and cubic_max_idle_time are held at their defaults.

Reward function
---------------
As implemented, the reward is:

    R = mean(U_video, U_file, U_conf)
        - mu * changed          stability penalty, discourages needless churn
        - starvation penalty    0.2 per connection below 500 KB/s
        - suffering penalty     0.15 per connection whose utility is below 0.4

Per-connection utilities are composite, each weighted toward its own objective
but retaining a throughput component so that no connection can be starved
outright:

    U_video = 0.7 * U_latency(lat)  + 0.3 * U_throughput(tp)
    U_file  = 1.0 * U_throughput(tp)
    U_conf  = 0.7 * U_jitter(jit)   + 0.3 * U_throughput(tp)

Each component utility is normalised to [0, 1]:

    U_latency    = (lat_worst - lat) / (lat_worst - lat_best)
    U_throughput = tp / tp_max
    U_jitter     = (jit_worst - jit) / jit_worst

Fairness is threshold-based rather than variance-based. Rather than penalising
any inequality between connections, the reward penalises a connection only once
it falls below an absolute floor. This is deliberate: file transfer is expected
to take a larger share, since throughput is its entire utility while the other
two weight it at only 30%, and penalising that imbalance directly would fight
the intended priority. What must be prevented is not inequality but starvation.

Note for readers comparing against earlier revisions: an older description of
this agent specified a variance-based fairness term (lambda * std of the three
utilities). That term is not present in the current implementation; the
threshold-based starvation and suffering penalties replaced it. LAMBDA_FAIRNESS
is likewise no longer defined.

Learning update
---------------
    Q(s,a) <- Q(s,a) + alpha [ r + gamma * max_a' Q(s',a') - Q(s,a) ]

    alpha = 0.10, gamma = 0.90, epsilon: 0.30 -> 0.05 (decay 0.995 per step)

Connections
-----------
Imports from : standard library only (ast, json, math, os, random,
               statistics, time, typing)
Imported by  : simulation.ml_controller and main.py (lazily, by agent type);
               selected with --ml-agent andy
Related      : q_learning_agent.py (8-feature default),
               q_learning_agent_hybrid.py (10-feature blend of the two)
"""

import ast
import json
import math
import os
import random
import statistics
import time
from typing import Dict, List, Optional, Tuple

#consts (can adjust to match setup)

#connection identity match multi_connection_config.py
CONN_VIDEO = 1 #video streaming (min latency)
CONN_FILE = 2 #file transfer (max throughput)
CONN_CONF = 3 #conference call (min jitter)
CONNECTIONS = [CONN_VIDEO, CONN_FILE, CONN_CONF]

#metric bin thresholds
# All metrics are in SI units (seconds, bytes/second) as used by MetricsResult.

#per-connection bins (kept for utility/reward functions only; not used in state)
#latency (s) 0=excellent to 3=poor
LATENCY_BINS = [0.010, 0.025, 0.050]  #10ms 25ms 50ms
#throughput (bytes/s) 0=poor to 3=excellent
THROUGHPUT_BINS = [1_000_000, 2_000_000, 3_000_000]
#jitter (s) 0=excellent to 3=poor
JITTER_BINS = [0.005, 0.015, 0.030] #5ms 15ms 30ms

#network condition bins used in state (aggregated across all 3 connections)
#total throughput (bytes/s) 0=very low to 3=near 30 Mbps cap
TOTAL_TP_BINS = [500_000, 2_000_000, 3_500_000]   #~4 Mbps, 16 Mbps, 28 Mbps
#mean RTT (s) 0=low/healthy to 3=very high/severe congestion
RTT_BINS = [0.050, 0.100, 0.200]                  #50ms, 100ms, 200ms

#normalize rewards
LATENCY_BEST = 0.020  #20ms floor when 25ms propagation delay is in use
LATENCY_WORST = 0.200 #200ms
THROUGHPUT_MAX = 1_250_000.0  #10 Mbps in bytes/s = fair share of 30 Mbps shared link
JITTER_WORST = 0.050 #50ms

#reward penalty weights
MU_STABILITY = 0.05 #penalise unnecessary parameter changes

#starvation prevention (throughput-based)
MIN_VIABLE_THROUGHPUT = 500_000  # 500 KB/s = 4 Mbps minimum per connection
STARVATION_PENALTY = 0.2  # Heavy penalty per starving connection

#suffering prevention (utility-based) - Option B fairness
#Only penalize when a connection's utility drops below threshold (not strict equality)
UTILITY_SUFFERING_THRESHOLD = 0.4  # Below this = connection is suffering
UTILITY_SUFFERING_PENALTY = 0.15   # Penalty per suffering connection

# Throughput metric selection for Q-learning (aligned with Default/Hybrid)
# "delta" = per-epoch ACK-verified bytes (responsive to changes)
# "acked" = cumulative average (stable)
# "cwnd" = CWND-limited estimate (theoretical max) - NOT RECOMMENDED
THROUGHPUT_METRIC = "delta"

#ql params
ALPHA = 0.10 #learning rate
GAMMA = 0.90 #discount factor
EPSILON_START = 0.30 #initial exploration probability
EPSILON_MIN = 0.05 #floor for exploration
EPSILON_DECAY = 0.995 #multiplicative decay per decision step

#timing
#MLController calls callback every ~0.1s only act every CONTROL_INTERVAL to give CUBIC time to settle after a parameter change.
CONTROL_INTERVAL = 2.0   #secs between actual Q-learning decisions

#param search space from grid search results
PARAM_SPACE: Dict[str, dict] = {
    "loss_reduction_factor": {"step": 0.1, "min": 0.3, "max": 0.7, "integer": False},
    "cubic_c": {"step": 0.1, "min": 0.2, "max": 0.4, "integer": False},
    "minimum_window": {"step": 1,   "min": 2,   "max": 4,   "integer": True},
    "packet_threshold": {"step": 1,   "min": 3,   "max": 4,   "integer": True},
}
TUNABLE_PARAMS = list(PARAM_SPACE.keys())   #ordered by index <-> param name

#encoding actions
#action = conn_index * (N_PARAMS*2) + param_index * 2 + direction
#direction 0 is increase and direction 1 is decrease
#last action is no op
N_PARAMS = len(TUNABLE_PARAMS) #4
N_CONNS = len(CONNECTIONS) #3
N_ACTIONS = N_CONNS * N_PARAMS * 2 + 1 #25
ACTION_NOOP = N_ACTIONS - 1 #24


#helpers

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
        For lower_is_better metrics, 0 means excellent (below the first
        threshold) and N means poor. For higher_is_better metrics the ordering
        is reversed, so that a larger index always denotes a better condition
        for that metric.
    """
    if lower_is_better:
        for i, t in enumerate(thresholds):
            if value <= t:
                return i
        return len(thresholds) #worst
    else:
        for i, t in enumerate(thresholds):
            if value < t:
                return i
        return len(thresholds) #best


def _param_to_idx(name: str, value: float) -> int:
    """
    Convert a parameter's current value to its step index within PARAM_SPACE range.

    Each tunable param has a small fixed set of legal values (e.g. cubic_c is
    {0.2, 0.3, 0.4} -> indices {0, 1, 2}). This is what the state stores so the
    agent can see exact dial positions and detect boundaries.
    """
    spec = PARAM_SPACE[name]
    raw_idx = round((float(value) - spec["min"]) / spec["step"])
    max_idx = round((spec["max"] - spec["min"]) / spec["step"])
    return max(0, min(int(raw_idx), int(max_idx)))


def _utility_latency(v: float) -> float:
    """
    Normalise latency to [0, 1], where 1 is best.

    Clamped at both ends so that latency beyond the configured worst case
    cannot drive the reward negative, and better-than-best cannot exceed 1.
    A bounded utility keeps the three connections' contributions commensurable
    when they are averaged.
    """
    u = (LATENCY_WORST - v) / (LATENCY_WORST - LATENCY_BEST)
    return max(0.0, min(1.0, u))


def _utility_throughput(v: float) -> float:
    """
    Normalise throughput to [0, 1], where 1 is best.

    THROUGHPUT_MAX is set to one connection's fair share of the shared link
    rather than the link's full capacity, so a connection reaches utility 1.0
    by taking its share rather than by monopolising the bottleneck.
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


def _clamp(name: str, value: float) -> float:
    """clamp param value to defined range and round integers"""
    spec = PARAM_SPACE[name]
    v = max(spec["min"], min(spec["max"], value))
    return round(v) if spec["integer"] else round(v, 1)


def _decode_action(action: int) -> Optional[Tuple[int, str, int]]:
    """
    decode action index to (connection_id, param_name, direction), returns None for no op action.
    direction 0=increase 1=decrease
    """
    if action == ACTION_NOOP:
        return None
    conn_idx  = action // (N_PARAMS * 2)
    remainder = action  % (N_PARAMS * 2)
    param_idx = remainder // 2
    direction = remainder  % 2
    return CONNECTIONS[conn_idx], TUNABLE_PARAMS[param_idx], direction


#ql agent

class QLearningAgent:
    """
    tabular ql agent for quic param optimization
    `ml_callback` for ProcessOrchestrator/MLController, pass `agent` (or `agent.get_callback()`) as callback agent= QLearningAgent()
    orchestrator = ProcessOrchestrator(config, ml_callback=agent) Agent also allable directly so `agent(metrics)` works
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
        self.checkpoint_path  = checkpoint_path

        #q table sparse dict {state_tuple -> [Q value per action] }
        self._q: Dict[Tuple, List[float]] = {}

        #timing
        self._last_decision_time: float = 0.0
        self._last_state: Optional[Tuple] = None
        self._last_action: Optional[int] = None
        self._last_action_changed: bool = False  # Track if action actually changed params

        #param tracker
        #All 4 tunable params are now echoed back from worker_process and synced each tick.
        #Initial defaults match multi_connection_config.py and are kept within PARAM_SPACE bounds
        #so _param_to_idx() always produces a valid step index.
        self._params: Dict[int, Dict[str, float]] = {
            CONN_VIDEO: {"loss_reduction_factor": 0.5, "cubic_c": 0.3,
                         "minimum_window": 3, "packet_threshold": 3},
            CONN_FILE:  {"loss_reduction_factor": 0.7, "cubic_c": 0.4,
                         "minimum_window": 4, "packet_threshold": 3},
            CONN_CONF:  {"loss_reduction_factor": 0.5, "cubic_c": 0.2,
                         "minimum_window": 4, "packet_threshold": 3},
        }

        #stats
        self.step_count: int = 0
        self._reward_log: List[float] = []

        # Detailed history for export (step, timestamp, state, action, reward, epsilon)
        self._detailed_history: List[dict] = []

        # Track if we successfully loaded a checkpoint (to avoid overwriting good data)
        self._checkpoint_loaded = False

        #load checkpoint if its there
        if checkpoint_path:
            if os.path.exists(checkpoint_path):
                self._load(checkpoint_path)
                self._checkpoint_loaded = True
            else:
                print(f"[QLAgent] No checkpoint found at {checkpoint_path} - starting fresh")

        print(
            f"[QLAgent] Initialised - {N_ACTIONS} actions, "
            f"control_interval={self.control_interval}s, "
            f"alpha={self.alpha} gamma={self.gamma} eps={self.epsilon}->{self.epsilon_min}"
        )

    #q table helpers

    def _get_q(self, state: Tuple) -> List[float]:
        """return q vals for state init to 0 on first visit"""
        if state not in self._q:
            self._q[state] = [0.0] * N_ACTIONS
        return self._q[state]

    def _best_action(self, state: Tuple) -> int:
        """greedy action with random tie breaking."""
        q_vals = self._get_q(state)
        max_q  = max(q_vals)
        return random.choice([a for a, q in enumerate(q_vals) if q == max_q])

    def _update(self, s: Tuple, a: int, r: float, s_next: Tuple):
        """Bellman update Q(s,a) <- Q(s,a) + α[r + γ·max Q(s',·) - Q(s,a)]"""
        q     = self._get_q(s)
        q_max = max(self._get_q(s_next))
        q[a] += self.alpha * (r + self.gamma * q_max - q[a])

    #Extract state

    def _build_state(self, metrics: Dict[int, dict]) -> Optional[Tuple]:
        """
        Build 14-feature discrete state tuple:
          - 12 features: exact step index of each tunable param on each connection
          - 2 features: aggregated network condition bins (total throughput, mean RTT)
        Returns None if any connection's metrics are not yet available.
        """
        if not all(c in metrics for c in CONNECTIONS):
            return None

        #12 parameter step-index features (read from internally tracked self._params)
        param_features: List[int] = []
        for param_name in TUNABLE_PARAMS:
            for conn_id in CONNECTIONS:
                param_features.append(_param_to_idx(param_name, self._params[conn_id][param_name]))

        #2 aggregated network condition features: bottleneck conditions seen by all 3 conns
        #Use configured throughput metric (aligned with Default/Hybrid)
        total_tp = sum(self._get_throughput(metrics, c) for c in CONNECTIONS)
        mean_rtt = sum(metrics[c].get("rtt", 0.0) for c in CONNECTIONS) / len(CONNECTIONS)

        tp_bin  = _bin(total_tp, TOTAL_TP_BINS, lower_is_better=False)
        rtt_bin = _bin(mean_rtt, RTT_BINS,      lower_is_better=True)

        return tuple(param_features) + (tp_bin, rtt_bin)

    #reward

    def _get_throughput(self, metrics: Dict[int, dict], conn_id: int) -> float:
        """
        Read throughput for one connection using the configured source.

        Unlike the default and hybrid agents, where this is a module-level
        helper, it is a method here; behaviour for the shared "delta" and
        "acked" modes is equivalent.

        Sources:
          - "delta"  per-epoch ACK-verified rate. Responsive to recent change,
                     which is what a controller acting every 2s needs to see.
          - "acked"  cumulative ACK-verified average. Stable, but increasingly
                     insensitive to a late action as a run lengthens.
          - "cwnd"   cwnd/RTT ceiling. This mode is specific to this agent and
                     falls back through the delta and cumulative figures when
                     no cwnd estimate is available.

        "delta" is the configured default, matching the other two agents so
        that comparisons between them remain like for like.

        Returns:
            Throughput in bytes per second.
        """
        m = metrics.get(conn_id, {})

        if THROUGHPUT_METRIC == "delta":
            delta = m.get("throughput_acked_delta", 0.0)
            if delta > 0:
                return delta
            return m.get("throughput_acked", 0.0)
        elif THROUGHPUT_METRIC == "acked":
            return m.get("throughput_acked", 0.0)
        else:  # "cwnd"
            return (m.get("throughput_cwnd", 0.0) or
                    m.get("throughput_acked_delta", 0.0) or
                    m.get("throughput_acked", 0.0))

    def _reward(self, metrics: Dict[int, dict], action_changed: bool) -> float:
        """
        Compute scalar reward from curr metrics.

        DESIGN: Each connection's utility reflects its PRIMARY goal while including
        a throughput component to prevent starvation.

        - Video: PRIMARY = low latency (70%), SECONDARY = throughput (30%)
        - File:  PRIMARY = high throughput (100%) - this is THE priority connection
        - Conf:  PRIMARY = low jitter (70%), SECONDARY = throughput (30%)

        FAIRNESS (Option B): We use threshold-based fairness rather than strict equality.
        - Connections can have different utilities (file can excel)
        - Only penalize when a utility drops below UTILITY_SUFFERING_THRESHOLD (0.4)
        - This allows file to get more bandwidth as long as video/conference aren't suffering

        File transfer naturally gets priority because:
        1. Its utility is 100% throughput (most sensitive to bandwidth)
        2. Video/conference only have 30% throughput weight (less sensitive)
        """
        if not all(c in metrics for c in CONNECTIONS):
            return 0.0

        # Get metrics for each connection
        video_lat = metrics[CONN_VIDEO].get("latency", 0.0)
        video_tp  = self._get_throughput(metrics, CONN_VIDEO)

        file_tp   = self._get_throughput(metrics, CONN_FILE)

        conf_jit  = metrics[CONN_CONF].get("jitter", 0.0)
        conf_tp   = self._get_throughput(metrics, CONN_CONF)

        # Compute per-connection composite utilities
        # Video: PRIMARY is latency (70%), with throughput floor to prevent starvation (30%)
        u_video = 0.7 * _utility_latency(video_lat) + 0.3 * _utility_throughput(video_tp)

        # File: throughput is the ONLY goal - this connection should get bandwidth priority
        u_file = _utility_throughput(file_tp)

        # Conference: PRIMARY is jitter (70%), with throughput floor to prevent starvation (30%)
        u_conf = 0.7 * _utility_jitter(conf_jit) + 0.3 * _utility_throughput(conf_tp)

        mean_u = (u_video + u_file + u_conf) / 3.0

        # Stability penalty: discourage unnecessary parameter changes
        churn = MU_STABILITY if action_changed else 0.0

        # Starvation penalty: heavy penalty if any connection falls below minimum viable throughput
        starvation = 0.0
        for conn_id, tp in [(CONN_VIDEO, video_tp), (CONN_FILE, file_tp), (CONN_CONF, conf_tp)]:
            if tp < MIN_VIABLE_THROUGHPUT:
                starvation += STARVATION_PENALTY

        # Suffering penalty (Option B fairness): only penalize when a connection is struggling
        # This allows one connection to excel as long as others aren't suffering
        suffering = 0.0
        for u in [u_video, u_file, u_conf]:
            if u < UTILITY_SUFFERING_THRESHOLD:
                suffering += UTILITY_SUFFERING_PENALTY

        return mean_u - churn - starvation - suffering

    #manage params

    def _sync_from_metrics(self, metrics: Dict[int, dict]):
        """
        Update internally tracked parameters from echoed current_params in each worker's
        metrics payload. All 4 tunable params are echoed back by worker_process._send_metrics().
        """
        for conn_id in CONNECTIONS:
            echoed = metrics.get(conn_id, {}).get("current_params", {})
            for p in TUNABLE_PARAMS:
                if p in echoed:
                    self._params[conn_id][p] = echoed[p]

    def _apply_action(self, action: int) -> Dict[int, Dict[str, float]]:
        """
        Compute param change for action, update internal state then returns {conn_id: {param_name: new_value}} or {} for no change
        """
        decoded = _decode_action(action)
        if decoded is None:
            return {}   #no op

        conn_id, param_name, direction = decoded
        step    = PARAM_SPACE[param_name]["step"]
        current = self._params[conn_id][param_name]

        new_val = current + step if direction == 0 else current - step
        new_val = _clamp(param_name, new_val)

        if new_val == current:
            return {}   #already at boundary so treat as no op

        self._params[conn_id][param_name] = new_val
        return {conn_id: {param_name: new_val}}

    def _is_action_at_boundary(self, action: int) -> bool:
        """
        Check if an action would hit a parameter boundary (no change possible).
        Used to mask out ineffective actions from selection.
        """
        decoded = _decode_action(action)
        if decoded is None:
            return False  # no-op is never at boundary

        conn_id, param_name, direction = decoded
        spec = PARAM_SPACE[param_name]
        current = self._params[conn_id][param_name]

        if direction == 0:  # increase
            return current >= spec["max"]
        else:  # decrease
            return current <= spec["min"]

    #main callback

    def __call__(self, metrics: Dict[int, dict]) -> Dict[int, dict]:
        """
        Called by MLController on every tick (~0.1 s).

        Returns a parameter-update dict {conn_id: {param: value}} to be sent
        to the corresponding worker, or {} to make no change this tick.
        """
        now = time.time()

        #always sync echoed params from worker feedback
        self._sync_from_metrics(metrics)

        #throttle to only make ql decision every control interval s
        if (now - self._last_decision_time) < self.control_interval:
            return {}

        #build curr state
        state = self._build_state(metrics)
        if state is None:
            return {} #some connections not yet reporting

        #q table update via last transition
        if self._last_state is not None and self._last_action is not None:
            # Use tracked flag to check if action actually changed params (not just attempted)
            changed = self._last_action_changed
            r = self._reward(metrics, changed)
            self._update(self._last_state, self._last_action, r, state)
            self._reward_log.append(r)

            # Record detailed history for the previous step (now that we have the reward)
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
                "reward": r,
                "epsilon": self.epsilon,
                "next_state": state,
            })

        #epsilon greedy action selection with boundary masking
        #get valid actions (exclude those that would hit boundaries)
        valid_actions = [a for a in range(N_ACTIONS) if not self._is_action_at_boundary(a)]
        if not valid_actions:
            valid_actions = [ACTION_NOOP]  #fallback to no-op if all params at boundaries

        if random.random() < self.epsilon:
            action = random.choice(valid_actions) #explore only valid actions
        else:
            #exploit: find best action among valid actions only
            q_vals = self._get_q(state)
            valid_q = [(a, q_vals[a]) for a in valid_actions]
            max_q = max(q for _, q in valid_q)
            best_valid = [a for a, q in valid_q if q == max_q]
            action = random.choice(best_valid)

        #decay explore rate
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

        #execute action
        decisions = self._apply_action(action)

        #record transition
        self._last_state = state
        self._last_action = action
        self._last_action_changed = bool(decisions)  # Track if action actually changed params
        self._last_decision_time = now
        self.step_count += 1

        #periodic checkpoint - only save if we loaded successfully or have done significant training
        #This prevents short evaluation runs from overwriting well-trained checkpoints
        if self.checkpoint_path and self.step_count % 50 == 0:
            if self._checkpoint_loaded or self.step_count >= 100:
                self._save(self.checkpoint_path)

        #logging
        if self.step_count % 10 == 0:
            self._log(state, action, decisions, metrics)

        return decisions

    #more logging

    def _log(self, state, action, decisions, metrics):
        #last 2 elements of state are the network condition bins
        tp_bin  = state[-2]
        rtt_bin = state[-1]

        #Use configured throughput metric (aligned with Default/Hybrid)
        total_tp_bps = sum(self._get_throughput(metrics, c) for c in CONNECTIONS)
        total_tp_mbps = total_tp_bps * 8 / 1e6
        mean_rtt_ms   = sum(metrics[c].get("rtt", 0.0) for c in CONNECTIONS) / len(CONNECTIONS) * 1000

        recent = self._reward_log[-10:] if self._reward_log else [0.0]
        avg_r  = sum(recent) / len(recent)

        decoded = _decode_action(action)
        if decoded is None:
            act_str = "no-op"
        else:
            conn_id, param, direction = decoded
            app = {CONN_VIDEO: "video", CONN_FILE: "file", CONN_CONF: "conf"}[conn_id]
            act_str = f"{app}.{param} {'^' if direction == 0 else 'v'}"

        print(
            f"[QLAgent step={self.step_count:4d}] "
            f"params={state[:12]} tp_bin={tp_bin} rtt_bin={rtt_bin} "
            f"action={act_str} eps={self.epsilon:.3f} "
            f"total_tp={total_tp_mbps:.2f}Mbps mean_rtt={mean_rtt_ms:.1f}ms "
            f"avg_R={avg_r:+.3f} Q-states={len(self._q)}"
        )

    #checkpoint

    def _save(self, path: str):
        """persist q table and training state to json"""
        try:
            data = {
                "q": {str(k): v for k, v in self._q.items()},
                "epsilon": self.epsilon,
                "step_count": self.step_count,
            }
            with open(path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"[QLAgent] Checkpoint save failed: {e}")

    def _load(self, path: str):
        """Load Q-table and training state from a JSON file."""
        try:
            with open(path) as f:
                data = json.load(f)
            #keys are saved as str(tuple); ast.literal_eval safely restores them
            #(safer than eval since checkpoint files can be tampered with on disk)
            self._q = {ast.literal_eval(k): v for k, v in data["q"].items()}
            self.epsilon = data.get("epsilon",    self.epsilon)
            self.step_count = data.get("step_count", 0)
            print(
                f"[QLAgent] Checkpoint loaded: {len(self._q)} states, "
                f"step={self.step_count}, eps={self.epsilon:.3f}"
            )
        except Exception as e:
            print(f"[QLAgent] Checkpoint load failed ({path}): {e}")

    #analysis helpers

    def get_callback(self):
        """Return self as a callable ml_callback (convenience alias)."""
        return self

    def summary(self) -> dict:
        """Return a snapshot of the agent's learned state for analysis."""
        if not self._q:
            return {"states_visited": 0, "avg_max_q": 0.0,
                    "epsilon": self.epsilon, "steps": self.step_count}
        max_qs = [max(v) for v in self._q.values()]
        return {
            "states_visited": len(self._q),
            "avg_max_q":      sum(max_qs) / len(max_qs),
            "epsilon":        self.epsilon,
            "steps":          self.step_count,
            "avg_reward_last_100": (
                sum(self._reward_log[-100:]) / len(self._reward_log[-100:])
                if self._reward_log else 0.0
            ),
        }

    def get_detailed_history(self) -> List[dict]:
        """Get detailed step-by-step history for rewards.csv export."""
        return self._detailed_history.copy()

    def get_q_table_export(self) -> dict:
        """Export Q-table data for saving to file."""
        # State labels for human readability (14-feature state)
        tp_labels = ["<500KB/s", "500KB/s-2MB/s", "2-3.5MB/s", ">3.5MB/s"]
        rtt_labels = ["<50ms", "50-100ms", "100-200ms", ">200ms"]

        q_table_data = {}

        for state, q_values in self._q.items():
            state_str = str(state)

            # Unpack 14-feature state: 12 param indices + 2 network bins
            params_idx = state[:12]
            tp_b, rtt_b = state[12], state[13]

            # Human-readable state description for 14-feature state
            state_readable = {
                "loss_reduction_factor": {
                    "video": params_idx[0], "file": params_idx[1], "conf": params_idx[2]
                },
                "cubic_c": {
                    "video": params_idx[3], "file": params_idx[4], "conf": params_idx[5]
                },
                "minimum_window": {
                    "video": params_idx[6], "file": params_idx[7], "conf": params_idx[8]
                },
                "packet_threshold": {
                    "video": params_idx[9], "file": params_idx[10], "conf": params_idx[11]
                },
                "tp_bin": tp_labels[tp_b] if 0 <= tp_b < len(tp_labels) else str(tp_b),
                "rtt_bin": rtt_labels[rtt_b] if 0 <= rtt_b < len(rtt_labels) else str(rtt_b),
            }

            # Find best action for this state
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

    def get_hyperparameters(self) -> dict:
        """Get Q-learning hyperparameters for config export."""
        return {
            "alpha": self.alpha,
            "gamma": self.gamma,
            "epsilon_start": EPSILON_START,
            "epsilon_min": self.epsilon_min,
            "epsilon_decay": self.epsilon_decay,
            "control_interval": self.control_interval,
            "throughput_metric": THROUGHPUT_METRIC,  # Now aligned with Default/Hybrid
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
        """
        For every visited state, return the currently greedy action.
        Useful for post-run analysis/reporting.

        State layout (14 features):
          [0:3]   loss_reduction_factor step idx for video/file/conf
          [3:6]   cubic_c step idx
          [6:9]   minimum_window step idx
          [9:12]  packet_threshold step idx
          [12]    total throughput bin (0-3)
          [13]    mean RTT bin (0-3)
        """
        rows = []
        app_map = {
            CONN_VIDEO: "video_streaming",
            CONN_FILE:  "file_transfer",
            CONN_CONF:  "conference_call",
        }
        tp_labels  = ["<500KB/s", "500KB/s-2MB/s", "2-3.5MB/s", ">3.5MB/s"]
        rtt_labels = ["<50ms", "50-100ms", "100-200ms", ">200ms"]

        for state, q_vals in self._q.items():
            best = q_vals.index(max(q_vals))
            decoded = _decode_action(best)
            if decoded is None:
                action_str = "no-op"
            else:
                conn_id, param, direction = decoded
                action_str = (
                    f"{app_map[conn_id]}.{param} "
                    f"{'increase' if direction == 0 else 'decrease'}"
                )

            #unpack 12 param indices + 2 bin indices
            params_idx = state[:12]
            tp_b, rtt_b = state[12], state[13]

            rows.append({
                "state": state,
                "param_indices": {
                    "loss_reduction_factor": dict(zip(["video", "file", "conf"], params_idx[0:3])),
                    "cubic_c":               dict(zip(["video", "file", "conf"], params_idx[3:6])),
                    "minimum_window":        dict(zip(["video", "file", "conf"], params_idx[6:9])),
                    "packet_threshold":      dict(zip(["video", "file", "conf"], params_idx[9:12])),
                },
                "tp_state":  tp_labels[tp_b]   if 0 <= tp_b  < len(tp_labels)  else str(tp_b),
                "rtt_state": rtt_labels[rtt_b] if 0 <= rtt_b < len(rtt_labels) else str(rtt_b),
                "best_action": action_str,
                "best_q":      max(q_vals),
            })
        return sorted(rows, key=lambda r: r["best_q"], reverse=True)


#module level singleton for main.py --with-ml default import whatever that means

_agent: Optional[QLearningAgent] = None


def get_agent(checkpoint_path: Optional[str] = "output/q_learning_checkpoint_andy.json") -> QLearningAgent:
    """
    Return/create module level ql agent singleton
    Passing checkpoint_path enables automatic save/restore of q table across runs, so agent collects experience over mult episodes
    set checkpoint_path=None to start fresh everytime

    Environment Variables:
        CLEAR_QTABLE: Set to "1" to delete existing checkpoint and start fresh
    """
    global _agent
    if _agent is None:
        # Check for CLEAR_QTABLE environment variable
        if os.environ.get("CLEAR_QTABLE") == "1" and checkpoint_path:
            if os.path.exists(checkpoint_path):
                os.remove(checkpoint_path)
                print(f"[QLAgent] CLEAR_QTABLE=1: Deleted checkpoint {checkpoint_path}")
        _agent = QLearningAgent(checkpoint_path=checkpoint_path)
    return _agent


def q_learning_callback(metrics: Dict[int, dict]) -> Dict[int, dict]:
    """
    Module level callback that main.py imports when --with-ml is used
    Delegates to singleton QLearningAgent so state is preserved for full duration of simulation run
    """
    return get_agent()(metrics)