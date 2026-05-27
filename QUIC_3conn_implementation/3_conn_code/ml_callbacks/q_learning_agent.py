"""
ql agent for quic param optimization

Basically implements tabular ql to dynamically tune quic cubic params over the three connections
but they all have different performance goals

Connection 1 is video streaming = min latency
Connection 2 is file transfer = max throughput
Connection 3 is onference call = min jitter


This file is a standalone ml_callback and plugs into MLController via --with-ml flag in main.py
No external dependencies beyond python standard library.

how to run

#default after updating main.py import
uv run python -m main run --with-ml --duration 120

#explicit module path
uv run python -m main run --ml-callback ml_callbacks.q_learning_agent:q_learning_callback

#with network scenario
uv run python -m main run --with-ml --scenario congested_low --duration 120

The MLController calls ml_callback(metrics) every `decision_interval` seconds
(default 0.1s). The agent throttles itself to act every CONTROL_INTERVAL
seconds (2.0s) to give CUBIC congestion control time to respond to changes.

Every 2s the agent acts, and at each control step the agent
- Reads metrics from all 3 connections
- Maps them to discrete state
- Pick action and epsilon greedy over q table
- Apply param change to the right connection
- At next steps it gets resulting metrics and updates q(s,a)


State space (8 features)
state = (lat bin, tp bin, jit bin, lat trend, tp trend, jit trend, loss bin, cwnd bin)
Metric bins (0 best 3 worst for lat/jit/loss, 0 worst for tp/cwnd)

Lat 0 = <10ms, 1 = 10-25ms, 2 = 25-50ms, 3 = 50ms+
Tp 0 = <1MB/s, 1 = 1-2MB/s, 2 = 2-3MB/s, 3 = 3MB/s+
Jitter 0 = <5ms, 1 = 5-15ms, 2 = 15-30ms, 3 = 30ms+
Loss 0 = <1%, 1 = 1-5%, 2 = 5-10%, 3 = 10%+
CWND 0 = <10pkt, 1 = 10-30pkt, 2 = 30-60pkt, 3 = 60pkt+ (congestion window)

Trend bins has 3 levels: 0 worse 1 stable 2 improving

So total state spaces will be 4^5*3^3 = 27648

Action space is 25 tot
Actions 0-23 change one param on one connection by one step
4 params, 3 connections, 2 directions increase or decrease = 24
24th action nothing happens

Params tunable from grid search results

Loss reduction factors, step 0.1 and range 0.3, 0.7
Cubic c step 0.1 range 0.2 0.4
Min window step 1 range 2 4
Packet threshold step 1 range 3 4
Time and cubic max idle constants at defaults

Reward func
R = mean(U stream U file U conf)
Lambda * std(u stream u file u conf) = fairness pen
Mu * changed = stability pen

Each utility 0, 1
U stream = (lat worst - lat) / (lat worst - lat best)
U file = tp / tp max
U conf = (jit worst - jit) / jit worst

ql update via bellman

Q(s,a) <- Q(s,a) + α [r + γ * max_{a'} Q(s',a') - Q(s,a)]
α = 0.1, γ = 0.9, ε: 0.30 -> 0.05 (decay 0.995 / step)
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

#m etric bin thresholds
# All metrics are in SI units (seconds, bytes/second) as used by MetricsResult.

#latency (s) 0=excellent = 3=poor
LATENCY_BINS = [0.010, 0.025, 0.050]  #10ms 25ms 50ms

#throughput (bytes/s) 0=poor to 3=excellent
#scaled to 30 Mbps cap at 1MB/s=8Mbps 2MB/s=16Mbps 3MB/s=24Mbps
THROUGHPUT_BINS = [1_000_000, 2_000_000, 3_000_000]

#jitter (s) 0=excellent to 3=poor
JITTER_BINS = [0.005, 0.015, 0.030] #5ms 15ms 30ms

#packet loss rate (ratio 0-1) 0=excellent to 3=poor
#Used as network condition context in state
LOSS_RATE_BINS = [0.01, 0.05, 0.10]  #1% 5% 10%

#congestion window (packets) 0=tight to 3=wide open
#CWND is the primary output of CUBIC - knowing it helps agent understand action effects
CWND_BINS = [10, 30, 60]  #10 packets (tight), 30 (moderate), 60+ (open)

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

# Throughput metric selection for Q-learning
# "delta" = per-epoch (responsive to changes, good for varying conditions)
# "acked" = cumulative average (stable, good for steady-state conditions)
# "offered" = application send rate (not bottleneck-aware)
THROUGHPUT_METRIC = "delta"  # Options: "offered", "acked", "delta"

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
# Ranges for tunable parameters (same as Andy's agent):
#   Video (1): loss_reduction_factor=0.6, cubic_c=0.4, minimum_window=4, packet_threshold=4
#   File (2): loss_reduction_factor=0.7, cubic_c=0.4, minimum_window=2, packet_threshold=3
#   Conference (3): loss_reduction_factor=0.5, cubic_c=0.3, minimum_window=4, packet_threshold=3
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
    map cont value to 0 based bin index
    For lower_is_better metrics like latency, jitter
    bin 0=excellent (below first threshold) and bin N=bad (above last threshold)
    For higher_is_better metrics like throughput
    bin 0=bad (below first threshold) and bin N=excellent (above last threshold)
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


def _trend(current: float, previous: Optional[float], higher_is_better: bool) -> int:
    """
    return trend code 0=worsening, 1=stable, 2=improving
    use 5% tolerance band around prev value to avoid noise
    """
    if previous is None or previous == 0.0:
        return 1 #stable on first step

    tol = abs(previous) * 0.05
    delta = current - previous

    if higher_is_better:
        if delta > tol: return 2   #improved (went up)
        if delta < -tol: return 0   #worse (went down)
    else:
        if delta < -tol: return 2   #improved (went down)
        if delta > tol: return 0   #worse (went up)
    return 1   #stable


def _utility_latency(v: float) -> float:
    """Normalise latency to 0,1 where 1 is best (lowest)"""
    u = (LATENCY_WORST - v) / (LATENCY_WORST - LATENCY_BEST)
    return max(0.0, min(1.0, u))


def _utility_throughput(v: float) -> float:
    """Normalise throughput to 0,1 where 1 = best (highest)"""
    return max(0.0, min(1.0, v / THROUGHPUT_MAX))


def _utility_jitter(v: float) -> float:
    """Normalise jitter to [0,1] where 1 is best (lowest)"""
    if JITTER_WORST == 0:
        return 1.0
    return max(0.0, min(1.0, (JITTER_WORST - v) / JITTER_WORST))


def _get_throughput(metrics: Dict[int, dict], conn_id: int) -> float:
    """
    Get throughput based on configured metric type.

    Returns throughput in bytes/second from the selected source:
    - "delta": Per-epoch delta (responsive to changes)
    - "acked": Cumulative ACK-verified (stable average)
    - "offered": Application send rate (not bottleneck-aware)
    """
    conn_metrics = metrics.get(conn_id, {})

    if THROUGHPUT_METRIC == "delta":
        delta = conn_metrics.get("throughput_acked_delta", 0.0)
        # Fall back to cumulative if delta not available yet (first few ticks)
        if delta > 0:
            return delta
        return conn_metrics.get("throughput_acked", 0.0)
    elif THROUGHPUT_METRIC == "acked":
        return conn_metrics.get("throughput_acked", 0.0)
    else:  # "offered"
        return conn_metrics.get("throughput", 0.0)


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
        #All 4 tunable params are synced from worker metrics each call
        #Initial values match defaults from multi_connection_config.py
        self._params: Dict[int, Dict[str, float]] = {
            CONN_VIDEO: {"loss_reduction_factor": 0.5, "cubic_c": 0.3,
                         "minimum_window": 3, "packet_threshold": 3},
            CONN_FILE:  {"loss_reduction_factor": 0.7, "cubic_c": 0.4,
                         "minimum_window": 4, "packet_threshold": 3},
            CONN_CONF:  {"loss_reduction_factor": 0.5, "cubic_c": 0.2,
                         "minimum_window": 4, "packet_threshold": 3},
        }

        #Track trends
        self._prev_latency: Optional[float] = None
        self._prev_throughput: Optional[float] = None
        self._prev_jitter: Optional[float] = None

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
            f"α={self.alpha} γ={self.gamma} ε={self.epsilon}→{self.epsilon_min}"
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
        convert live metrics to a discrete state tuple then returns None if any connections metrics arent available yet

        State tuple (8 components):
        - lat_bin: latency bin from Connection 1 (0-3)
        - tp_bin: throughput bin from Connection 2 (0-3)
        - jit_bin: jitter bin from Connection 3 (0-3)
        - lat_trend: latency trend (0=worsening, 1=stable, 2=improving)
        - tp_trend: throughput trend (0=worsening, 1=stable, 2=improving)
        - jit_trend: jitter trend (0=worsening, 1=stable, 2=improving)
        - loss_bin: packet loss rate bin (0-3) - network condition context
        - cwnd_bin: congestion window bin (0-3) - CUBIC output state

        Total state space: 4^5 * 3^3 = 27648 states
        """
        if not all(c in metrics for c in CONNECTIONS):
            return None

        lat = metrics[CONN_VIDEO].get("latency",    0.0)
        tp  = _get_throughput(metrics, CONN_FILE)  # Uses configured metric type
        jit = metrics[CONN_CONF ].get("jitter",     0.0)

        # Get average packet loss across all connections as network condition indicator
        loss_rates = [metrics[c].get("packet_loss_rate", 0.0) for c in CONNECTIONS]
        avg_loss = sum(loss_rates) / len(loss_rates) if loss_rates else 0.0

        # Get average CWND across all connections - direct indicator of congestion control state
        cwnd_values = [metrics[c].get("cwnd", 20) for c in CONNECTIONS]
        avg_cwnd = sum(cwnd_values) / len(cwnd_values)

        lat_bin = _bin(lat, LATENCY_BINS,    lower_is_better=True)
        tp_bin  = _bin(tp,  THROUGHPUT_BINS, lower_is_better=False)
        jit_bin = _bin(jit, JITTER_BINS,     lower_is_better=True)
        loss_bin = _bin(avg_loss, LOSS_RATE_BINS, lower_is_better=True)
        cwnd_bin = _bin(avg_cwnd, CWND_BINS, lower_is_better=False)

        lat_trend = _trend(lat, self._prev_latency,    higher_is_better=False)
        tp_trend  = _trend(tp,  self._prev_throughput, higher_is_better=True)
        jit_trend = _trend(jit, self._prev_jitter,     higher_is_better=False)

        #save for next steps trend
        self._prev_latency    = lat
        self._prev_throughput = tp
        self._prev_jitter     = jit

        return (lat_bin, tp_bin, jit_bin, lat_trend, tp_trend, jit_trend, loss_bin, cwnd_bin)

    #reward

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
        video_tp  = _get_throughput(metrics, CONN_VIDEO)

        file_tp   = _get_throughput(metrics, CONN_FILE)

        conf_jit  = metrics[CONN_CONF].get("jitter", 0.0)
        conf_tp   = _get_throughput(metrics, CONN_CONF)

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
        Update internally tracked parameters from echoed current_params in each worker's metrics payload.
        All 4 tunable params are synced to keep agent in sync with actual worker state.
        """
        for conn_id in CONNECTIONS:
            echoed = metrics.get(conn_id, {}).get("current_params", {})
            for p in ("loss_reduction_factor", "cubic_c", "minimum_window", "packet_threshold"):
                if p in echoed:
                    self._params[conn_id][p] = echoed[p]

    def _apply_action(self, action: int) -> Dict[int, Dict[str, float]]:
        """
        Compute param change for action, update internal state then returns {conn_id: {param_name: new_value}} or {} for no change.

        Only returns a change if the new value differs from the current tracked value.
        This prevents sending "changes" that are actually no-ops due to boundary clamping.
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

        # Double-check: if new_val equals what we already have tracked, skip
        # This can happen if _params was recently synced to a value different from
        # what we thought, making our "change" actually match reality
        if new_val == self._params[conn_id].get(param_name):
            return {}

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
        reward = None
        if self._last_state is not None and self._last_action is not None:
            # Use tracked flag to check if action actually changed params (not just attempted)
            changed = self._last_action_changed
            reward = self._reward(metrics, changed)
            self._update(self._last_state, self._last_action, reward, state)
            self._reward_log.append(reward)

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
                "reward": reward,
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
        lat_ms = metrics.get(CONN_VIDEO, {}).get("latency",    0.0) * 1000
        jit_ms = metrics.get(CONN_CONF,  {}).get("jitter",     0.0) * 1000

        # Log both cumulative and delta throughput for comparison
        tp_cumulative = metrics.get(CONN_FILE, {}).get("throughput_acked", 0.0) * 8 / 1e6
        tp_delta = metrics.get(CONN_FILE, {}).get("throughput_acked_delta", 0.0) * 8 / 1e6
        tp_active = _get_throughput(metrics, CONN_FILE) * 8 / 1e6  # Currently used metric

        # Get average packet loss rate across all connections
        loss_rates = [metrics[c].get("packet_loss_rate", 0.0) for c in CONNECTIONS]
        avg_loss_pct = (sum(loss_rates) / len(loss_rates) * 100) if loss_rates else 0.0

        recent  = self._reward_log[-10:] if self._reward_log else [0.0]
        avg_r   = sum(recent) / len(recent)

        decoded = _decode_action(action)
        if decoded is None:
            act_str = "no-op"
        else:
            conn_id, param, direction = decoded
            app = {CONN_VIDEO: "video", CONN_FILE: "file", CONN_CONF: "conf"}[conn_id]
            act_str = f"{app}.{param} {'↑' if direction == 0 else '↓'}"

        # Show active metric with delta in parentheses for comparison
        print(
            f"[QLAgent step={self.step_count:4d}] "
            f"state={state} action={act_str} "
            f"ε={self.epsilon:.3f} "
            f"lat={lat_ms:.1f}ms tp={tp_active:.2f}Mbps(Δ={tp_delta:.2f}) jit={jit_ms:.1f}ms loss={avg_loss_pct:.1f}% "
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
                f"step={self.step_count}, ε={self.epsilon:.3f}"
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

    def get_q_table_export(self) -> dict:
        """Export Q-table data for saving to file."""
        # State labels for human readability
        bin_labels = {
            "lat": ["<10ms", "10-25ms", "25-50ms", ">50ms"],
            "tp": ["<1MB/s", "1-2MB/s", "2-3MB/s", ">3MB/s"],
            "jit": ["<5ms", "5-15ms", "15-30ms", ">30ms"],
            "loss": ["<1%", "1-5%", "5-10%", ">10%"],
            "cwnd": ["<10pkt", "10-30pkt", "30-60pkt", ">60pkt"],
            "trend": ["worsening", "stable", "improving"],
        }

        q_table_data = {}
        state_visit_counts = {}

        for state, q_values in self._q.items():
            state_str = str(state)
            # Handle old 6-tuple, 7-tuple, and new 8-tuple states for backward compatibility
            if len(state) == 8:
                lat_b, tp_b, jit_b, lat_t, tp_t, jit_t, loss_b, cwnd_b = state
            elif len(state) == 7:
                lat_b, tp_b, jit_b, lat_t, tp_t, jit_t, loss_b = state
                cwnd_b = 0  # Default for old states
            else:
                lat_b, tp_b, jit_b, lat_t, tp_t, jit_t = state
                loss_b = 0  # Default for old states
                cwnd_b = 0

            # Human-readable state description
            state_readable = {
                "latency_bin": bin_labels["lat"][lat_b] if lat_b < 4 else f"bin_{lat_b}",
                "throughput_bin": bin_labels["tp"][tp_b] if tp_b < 4 else f"bin_{tp_b}",
                "jitter_bin": bin_labels["jit"][jit_b] if jit_b < 4 else f"bin_{jit_b}",
                "latency_trend": bin_labels["trend"][lat_t] if lat_t < 3 else f"trend_{lat_t}",
                "throughput_trend": bin_labels["trend"][tp_t] if tp_t < 3 else f"trend_{tp_t}",
                "jitter_trend": bin_labels["trend"][jit_t] if jit_t < 3 else f"trend_{jit_t}",
                "loss_bin": bin_labels["loss"][loss_b] if loss_b < 4 else f"bin_{loss_b}",
                "cwnd_bin": bin_labels["cwnd"][cwnd_b] if cwnd_b < 4 else f"bin_{cwnd_b}",
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
        """
        for every visited state return currently greedy action useful for post run analysis/reporting
        """
        rows = []
        app_map = {
            CONN_VIDEO: "video_streaming",
            CONN_FILE:  "file_transfer",
            CONN_CONF:  "conference_call",
        }
        bin_labels = {
            "lat":  ["<10ms", "10-25ms", "25-50ms", ">50ms"],
            "tp":   ["<100KB/s", "100-500KB/s", "500KB/s-1.25MB/s", ">1.25MB/s"],
            "jit":  ["<5ms", "5-15ms", "15-30ms", ">30ms"],
            "loss": ["<1%", "1-5%", "5-10%", ">10%"],
            "cwnd": ["<10pkt", "10-30pkt", "30-60pkt", ">60pkt"],
            "trend": ["worsening", "stable", "improving"],
        }
        for state, q_vals in self._q.items():
            # Handle old 6-tuple, 7-tuple, and new 8-tuple states for backward compatibility
            if len(state) == 8:
                lat_b, tp_b, jit_b, lat_t, tp_t, jit_t, loss_b, cwnd_b = state
            elif len(state) == 7:
                lat_b, tp_b, jit_b, lat_t, tp_t, jit_t, loss_b = state
                cwnd_b = 0  # Default for old states
            else:
                lat_b, tp_b, jit_b, lat_t, tp_t, jit_t = state
                loss_b = 0  # Default for old states
                cwnd_b = 0
            best = int.__index__(q_vals.index(max(q_vals)))
            decoded = _decode_action(best)
            if decoded is None:
                action_str = "no-op"
            else:
                conn_id, param, direction = decoded
                action_str = (
                    f"{app_map[conn_id]}.{param} "
                    f"{'increase' if direction == 0 else 'decrease'}"
                )
            rows.append({
                "state": state,
                "lat_state":  bin_labels["lat"][lat_b],
                "tp_state":   bin_labels["tp"][tp_b],
                "jit_state":  bin_labels["jit"][jit_b],
                "loss_state": bin_labels["loss"][loss_b],
                "cwnd_state": bin_labels["cwnd"][cwnd_b],
                "lat_trend":  bin_labels["trend"][lat_t],
                "tp_trend":   bin_labels["trend"][tp_t],
                "jit_trend":  bin_labels["trend"][jit_t],
                "best_action": action_str,
                "best_q":      max(q_vals),
            })
        return sorted(rows, key=lambda r: r["best_q"], reverse=True)


#module level singleton for main.py --with-ml default import whatever that means

_agent: Optional[QLearningAgent] = None


def get_agent(checkpoint_path: Optional[str] = "output/q_learning_checkpoint.json") -> QLearningAgent:
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