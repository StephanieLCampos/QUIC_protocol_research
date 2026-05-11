"""
Standalone test for the upgraded q_learning_agent.

Feeds the agent synthetic metrics and verifies:
  1. State is the new 14-feature shape
  2. Parameters sync correctly from echoed metrics (all 4 params)
  3. _param_to_idx() produces correct step indices
  4. Action application updates internal _params and emits worker decisions
  5. Network condition bins (total throughput / mean RTT) are computed correctly
  6. Q-table grows as states are visited; rewards are recorded
  7. Checkpoint save/load round-trips correctly with ast.literal_eval

Run from this directory:
    python test_qlearn_agent.py
"""

import os
import sys
import time
import tempfile
import importlib

#make ml_callbacks importable when run from 3_conn_code/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ml_callbacks import q_learning_agent as qla


def banner(msg):
    print("\n" + "=" * 70)
    print(msg)
    print("=" * 70)


def make_metrics(
    tp_video=1.4e6, tp_file=3.5e6, tp_conf=0.13e6,
    rtt_video=0.096, rtt_file=0.098, rtt_conf=0.095,
    jitter_video=0.003, jitter_file=0.004, jitter_conf=0.002,
    params_video=None, params_file=None, params_conf=None,
):
    """Build a metrics dict matching what MLController would deliver."""
    def conn_payload(tp, rtt, jit, params):
        return {
            "throughput": tp,
            "rtt": rtt,
            "latency": rtt / 2,
            "jitter": jit,
            "packet_loss_rate": 0.0,
            "current_params": params or {
                "loss_reduction_factor": 0.5,
                "cubic_c": 0.3,
                "minimum_window": 3,
                "packet_threshold": 3,
            },
        }
    return {
        qla.CONN_VIDEO: conn_payload(tp_video, rtt_video, jitter_video, params_video),
        qla.CONN_FILE:  conn_payload(tp_file,  rtt_file,  jitter_file,  params_file),
        qla.CONN_CONF:  conn_payload(tp_conf,  rtt_conf,  jitter_conf,  params_conf),
    }


def test_param_to_idx():
    banner("TEST 1: _param_to_idx — exact step index conversion")
    cases = [
        ("loss_reduction_factor", 0.3, 0),
        ("loss_reduction_factor", 0.5, 2),
        ("loss_reduction_factor", 0.7, 4),
        ("cubic_c", 0.2, 0),
        ("cubic_c", 0.4, 2),
        ("minimum_window", 2, 0),
        ("minimum_window", 4, 2),
        ("packet_threshold", 3, 0),
        ("packet_threshold", 4, 1),
        #out-of-range values are clamped
        ("loss_reduction_factor", 0.1, 0),
        ("loss_reduction_factor", 0.9, 4),
        ("packet_threshold", 2,    0),  #below min: clamped to 0
    ]
    for param, value, expected in cases:
        got = qla._param_to_idx(param, value)
        ok = "OK " if got == expected else "FAIL"
        print(f"  [{ok}] _param_to_idx({param!r:25s}, {value:>5}) -> {got} (expected {expected})")
        assert got == expected, f"_param_to_idx mismatch for {param}={value}"


def test_state_shape():
    banner("TEST 2: _build_state — 14-feature tuple shape")
    agent = qla.QLearningAgent(checkpoint_path=None)
    metrics = make_metrics()
    #sync first so internal _params reflects echoed values
    agent._sync_from_metrics(metrics)
    state = agent._build_state(metrics)

    assert state is not None,                       "state should not be None"
    assert isinstance(state, tuple),                f"state should be tuple, got {type(state)}"
    assert len(state) == 14,                        f"state should have 14 elements, got {len(state)}"
    assert all(isinstance(x, int) for x in state),  "all state elements should be ints"

    print(f"  state = {state}")
    print(f"  length = {len(state)}    (expected 14)")
    print(f"  param indices [0:12] = {state[:12]}")
    print(f"  tp_bin  [12]         = {state[12]}")
    print(f"  rtt_bin [13]         = {state[13]}")
    print("  [OK] state shape is correct")


def test_network_condition_bins():
    banner("TEST 3: network condition bins respond to metric changes")
    agent = qla.QLearningAgent(checkpoint_path=None)

    #scenario A: low total tp, low rtt -> tp_bin=0, rtt_bin=0
    m_low = make_metrics(tp_video=0.1e6, tp_file=0.1e6, tp_conf=0.1e6,
                         rtt_video=0.020, rtt_file=0.020, rtt_conf=0.020)
    agent._sync_from_metrics(m_low)
    s = agent._build_state(m_low)
    print(f"  low load:    state[-2:]={s[-2:]} (expected (0, 0))")
    assert s[-2:] == (0, 0), f"expected (0, 0), got {s[-2:]}"

    #scenario B: saturated cap, very high rtt -> tp_bin=3, rtt_bin=3
    m_hi = make_metrics(tp_video=1.5e6, tp_file=2.5e6, tp_conf=0.5e6,
                        rtt_video=0.250, rtt_file=0.250, rtt_conf=0.250)
    agent._sync_from_metrics(m_hi)
    s = agent._build_state(m_hi)
    print(f"  saturated:   state[-2:]={s[-2:]} (expected (3, 3))")
    assert s[-2:] == (3, 3), f"expected (3, 3), got {s[-2:]}"

    #scenario C: mid (sample-run-like) -> tp_bin=3, rtt_bin=2
    #total = 1.4 + 3.5 + 0.13 = 5.03 MB/s -> > 3.5M -> bin 3
    #mean rtt = (0.096 + 0.098 + 0.095) / 3 = 0.0963 -> between 0.05 and 0.1 -> bin 1 (0.05<=v<=0.1)
    m_mid = make_metrics()
    agent._sync_from_metrics(m_mid)
    s = agent._build_state(m_mid)
    print(f"  sample run:  state[-2:]={s[-2:]} (expected (3, 1))")
    assert s[-2:] == (3, 1), f"expected (3, 1), got {s[-2:]}"

    print("  [OK] network condition bins work correctly")


def test_sync_all_four_params():
    banner("TEST 4: _sync_from_metrics syncs ALL 4 params (incl. packet_threshold)")
    agent = qla.QLearningAgent(checkpoint_path=None)
    new_params = {
        "loss_reduction_factor": 0.4,
        "cubic_c":               0.3,
        "minimum_window":        3,
        "packet_threshold":      4,
    }
    metrics = make_metrics(params_video=new_params, params_file=new_params, params_conf=new_params)
    agent._sync_from_metrics(metrics)

    for c in qla.CONNECTIONS:
        for p in qla.TUNABLE_PARAMS:
            got = agent._params[c][p]
            print(f"  conn={c} {p:25s} = {got} (expected {new_params[p]})")
            assert got == new_params[p], f"sync failed for conn={c} param={p}"
    print("  [OK] all 4 params sync correctly including packet_threshold")


def test_apply_action():
    banner("TEST 5: _apply_action updates internal params and emits decision")
    agent = qla.QLearningAgent(checkpoint_path=None)
    #set known starting state
    agent._params[qla.CONN_FILE]["cubic_c"] = 0.3

    #action 8 = conn_idx 1 (file), param_idx 0 (lrf), dir 0 (up)? Decode to verify.
    #Find an action that increases file's cubic_c:
    #conn=file means conn_idx=1, param=cubic_c is index 1 in TUNABLE_PARAMS, direction=0 (up)
    #action = 1 * 8 + 1 * 2 + 0 = 10
    target_action = 1 * 8 + 1 * 2 + 0
    decoded = qla._decode_action(target_action)
    print(f"  action {target_action} decodes to: {decoded}")
    assert decoded == (qla.CONN_FILE, "cubic_c", 0), f"decode mismatch: {decoded}"

    decisions = agent._apply_action(target_action)
    print(f"  decisions emitted: {decisions}")
    print(f"  file cubic_c after: {agent._params[qla.CONN_FILE]['cubic_c']}")
    assert decisions == {qla.CONN_FILE: {"cubic_c": 0.4}}, f"unexpected decisions: {decisions}"
    assert abs(agent._params[qla.CONN_FILE]["cubic_c"] - 0.4) < 1e-9
    print("  [OK] action correctly updated cubic_c from 0.3 -> 0.4")

    #pushing past max should be clamped to no-op
    decisions = agent._apply_action(target_action)
    print(f"  pushing past max: decisions={decisions} (expected empty)")
    assert decisions == {}, "expected no-op when pushing past max"
    print("  [OK] boundary clamp correctly produces no-op")


def test_full_decision_cycle():
    banner("TEST 6: full agent.__call__ cycle - q-table grows, rewards accumulate")
    agent = qla.QLearningAgent(checkpoint_path=None, control_interval=0.0)  #fire every tick
    metrics = make_metrics()

    initial_q_size = len(agent._q)
    initial_step = agent.step_count

    #drive 30 ticks; vary metrics slightly to visit a few states
    import random
    random.seed(42)
    for i in range(30):
        m = make_metrics(
            tp_file=3.0e6 + random.uniform(-0.5e6, 0.5e6),
            rtt_video=0.080 + random.uniform(-0.04, 0.06),
            rtt_file=0.080 + random.uniform(-0.04, 0.06),
            rtt_conf=0.080 + random.uniform(-0.04, 0.06),
        )
        decisions = agent(m)

    print(f"  step_count: {initial_step} -> {agent.step_count}")
    print(f"  Q-table states visited: {initial_q_size} -> {len(agent._q)}")
    print(f"  rewards recorded: {len(agent._reward_log)}")
    print(f"  current epsilon: {agent.epsilon:.4f}")

    assert agent.step_count == 30,         f"expected 30 steps, got {agent.step_count}"
    assert len(agent._q) > 0,              "Q-table should have entries"
    assert len(agent._reward_log) > 0,     "rewards should be logged"
    assert agent.epsilon < qla.EPSILON_START, "epsilon should have decayed"

    #verify state shape consistency
    sample_state = next(iter(agent._q.keys()))
    assert len(sample_state) == 14, f"Q-table state should be 14-tuple, got {len(sample_state)}"
    print(f"  sample Q-state: {sample_state}")
    print(f"  sample Q-row [first 5 actions]: {agent._q[sample_state][:5]}")
    print("  [OK] decision cycle works end-to-end")


def test_checkpoint_roundtrip():
    banner("TEST 7: checkpoint save -> load round-trip with ast.literal_eval")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name

    try:
        #train a small Q-table
        agent1 = qla.QLearningAgent(checkpoint_path=path, control_interval=0.0)
        for _ in range(20):
            agent1(make_metrics())
        agent1._save(path)

        n_states_before = len(agent1._q)
        eps_before      = agent1.epsilon
        steps_before    = agent1.step_count
        sample_state    = next(iter(agent1._q.keys()))
        sample_q        = agent1._q[sample_state][:5]
        print(f"  saved: {n_states_before} states, eps={eps_before:.4f}, steps={steps_before}")

        #load fresh agent from checkpoint
        agent2 = qla.QLearningAgent(checkpoint_path=path)

        print(f"  loaded: {len(agent2._q)} states, eps={agent2.epsilon:.4f}, steps={agent2.step_count}")

        assert len(agent2._q)    == n_states_before, "state count mismatch after load"
        assert agent2.step_count == steps_before,    "step count mismatch after load"
        assert abs(agent2.epsilon - eps_before) < 1e-9, "epsilon mismatch after load"
        assert sample_state in agent2._q,            "specific state missing after load"
        assert agent2._q[sample_state][:5] == sample_q, "Q values mismatch after load"

        #confirm keys are real tuples of ints (not strings) — ast.literal_eval worked
        for k in agent2._q.keys():
            assert isinstance(k, tuple),               f"key not tuple: {type(k)}"
            assert len(k) == 14,                       f"key wrong length: {len(k)}"
            assert all(isinstance(x, int) for x in k), f"key elements not int: {k}"
        print("  [OK] checkpoint round-trip preserves Q-table, eps, steps, and key types")
    finally:
        if os.path.exists(path):
            os.unlink(path)


def main():
    print("Running upgraded q_learning_agent test suite\n")
    test_param_to_idx()
    test_state_shape()
    test_network_condition_bins()
    test_sync_all_four_params()
    test_apply_action()
    test_full_decision_cycle()
    test_checkpoint_roundtrip()
    banner("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
