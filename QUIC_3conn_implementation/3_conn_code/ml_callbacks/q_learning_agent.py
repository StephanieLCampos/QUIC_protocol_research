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


State space (14 features)
state = (
    lrf_v, lrf_f, lrf_c,    # loss_reduction_factor step idx (0-4) per connection
    cc_v,  cc_f,  cc_c,     # cubic_c step idx (0-2) per connection
    mw_v,  mw_f,  mw_c,     # minimum_window step idx (0-2) per connection
    pt_v,  pt_f,  pt_c,     # packet_threshold step idx (0-1) per connection
    tp_bin,                  # total throughput across all 3 conns: 0-3 (4 bins)
    rtt_bin,                 # mean RTT across all 3 conns: 0-3 (4 bins)
)

Param features are exact step indices (idx = round((value - min) / step)) so the
agent can detect when a dial is already at its boundary.

Network condition bins (latency = RTT/2 under symmetric path assumption):
  TOTAL_TP_BINS = [500K, 2M, 3.5M] bytes/s   -> 4 bins of total throughput
  RTT_BINS      = [50ms, 100ms, 200ms]       -> 4 bins of mean RTT

Theoretical max: 5^3 * 3^3 * 3^3 * 2^3 * 4 * 4 = ~11.6M states
Practical visited: ~50-300 states (sparse Q-table only allocates what is visited)

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
THROUGHPUT_MAX = 3_750_000.0  #30 Mbps in bytes/s = bandwidth cap so utility varies below cap
JITTER_WORST = 0.050 #50ms

#reward penalty weights
LAMBDA_FAIRNESS = 0.10 #penalise imbalance between connections
MU_STABILITY = 0.05 #penalise unnecessary parameter changes

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

        #param tracker
        #All 4 tunable params are now echoed back from worker_process and synced each tick.
        #Initial defaults match multi_connection_config.py and are kept within PARAM_SPACE bounds
        #so _param_to_idx() always produces a valid step index.
        self._params: Dict[int, Dict[str, float]] = {
            CONN_VIDEO: {"loss_reduction_factor": 0.6, "cubic_c": 0.4,
                         "minimum_window": 4, "packet_threshold": 4},
            CONN_FILE:  {"loss_reduction_factor": 0.7, "cubic_c": 0.4,
                         "minimum_window": 2, "packet_threshold": 3},
            CONN_CONF:  {"loss_reduction_factor": 0.5, "cubic_c": 0.3,
                         "minimum_window": 4, "packet_threshold": 3},
        }

        #stats
        self.step_count: int = 0
        self._reward_log: List[float] = []

        #load checkpoint if its there
        if checkpoint_path and os.path.exists(checkpoint_path):
            self._load(checkpoint_path)

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
        total_tp = sum(metrics[c].get("throughput", 0.0) for c in CONNECTIONS)
        mean_rtt = sum(metrics[c].get("rtt", 0.0) for c in CONNECTIONS) / len(CONNECTIONS)

        tp_bin  = _bin(total_tp, TOTAL_TP_BINS, lower_is_better=False)
        rtt_bin = _bin(mean_rtt, RTT_BINS,      lower_is_better=True)

        return tuple(param_features) + (tp_bin, rtt_bin)

    #reward

    def _reward(self, metrics: Dict[int, dict], action_changed: bool) -> float:
        """
        Compute scalar reward from curr metrics
        R = mean(U_stream, U_file, U_conf)
        lamba*std(utilities) as fairness to penalise large spread
        mu*changed as stability to discourage thrashing
        """
        if not all(c in metrics for c in CONNECTIONS):
            return 0.0

        lat = metrics[CONN_VIDEO].get("latency",    0.0)
        tp  = metrics[CONN_FILE ].get("throughput", 0.0)
        jit = metrics[CONN_CONF ].get("jitter",     0.0)

        u_stream = _utility_latency(lat)
        u_file   = _utility_throughput(tp)
        u_conf   = _utility_jitter(jit)

        mean_u = (u_stream + u_file + u_conf) / 3.0

        try:
            std_u = statistics.stdev([u_stream, u_file, u_conf])
        except statistics.StatisticsError:
            std_u = 0.0

        churn = MU_STABILITY if action_changed else 0.0

        return mean_u - LAMBDA_FAIRNESS * std_u - churn

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
            changed = (self._last_action != ACTION_NOOP)
            r = self._reward(metrics, changed)
            self._update(self._last_state, self._last_action, r, state)
            self._reward_log.append(r)

        #epsilon greedy action selection
        if random.random() < self.epsilon:
            action = random.randrange(N_ACTIONS) #explore
        else:
            action = self._best_action(state) #exploit

        #decay explore rate
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

        #execute action
        decisions = self._apply_action(action)

        #record transition
        self._last_state = state
        self._last_action = action
        self._last_decision_time = now
        self.step_count += 1

        #periodic checkpoint
        if self.checkpoint_path and self.step_count % 50 == 0:
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

        total_tp_mbps = sum(metrics[c].get("throughput", 0.0) for c in CONNECTIONS) * 8 / 1e6
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


def get_agent(checkpoint_path: Optional[str] = "output/q_learning_checkpoint.json") -> QLearningAgent:
    """
    Return/create module level ql agent singleton
    Passing checkpoint_path enables automatic save/restore of q table across runs, so agent collects experience over mult episodes
    set checkpoint_path=None to start fresh everytime
    """
    global _agent
    if _agent is None:
        _agent = QLearningAgent(checkpoint_path=checkpoint_path)
    return _agent


def q_learning_callback(metrics: Dict[int, dict]) -> Dict[int, dict]:
    """
    Module level callback that main.py imports when --with-ml is used
    Delegates to singleton QLearningAgent so state is preserved for full duration of simulation run
    """
    return get_agent()(metrics)