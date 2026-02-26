import random
from typing import Dict

import numpy as np

from qlearn_funcs import choose_action, update_q
from reward import compute_reward
from state import make_binned_state, encode_state, num_states

# Actions: 0=latency, 1=balanced, 2=throughput
ACTION_NAMES = {0: "latency", 1: "balanced", 2: "throughput"}
NUM_ACTIONS = 3

# Q-learning hyperparameters (plain variables, no OOP)
alpha = 0.2
gamma = 0.9
eps = 0.15

def simulate_metrics(action: int, scenario: int) -> Dict:
    """Fake metrics generator to test the loop before real QUIC integration."""
    if scenario == 0:  # stable
        base_gp, base_rtt, base_qd, base_loss, base_jit = 10.0, 40.0, 8.0, 0.006, 6.0
    else:  # congested
        base_gp, base_rtt, base_qd, base_loss, base_jit = 4.5, 90.0, 35.0, 0.03, 12.0

    if action == 0:  # latency
        gp = base_gp * 0.85
        rtt = base_rtt * 0.75
        qd = base_qd * 0.75
        jit = base_jit * 0.8
        loss = base_loss * 0.9
    elif action == 2:  # throughput
        gp = base_gp * 1.15
        rtt = base_rtt * 1.25
        qd = base_qd * 1.35
        jit = base_jit * 1.2
        loss = base_loss * (1.3 if scenario == 1 else 1.05)
    else:  # balanced
        gp, rtt, qd, jit, loss = base_gp, base_rtt, base_qd, base_jit, base_loss

    fairness = 0.9 if scenario == 0 else (0.75 if action == 2 else 0.85)

    # noise
    gp += random.uniform(-0.5, 0.5)
    rtt += random.uniform(-6.0, 6.0)
    qd += random.uniform(-4.0, 4.0)
    jit += random.uniform(-2.0, 2.0)
    loss += random.uniform(-0.005, 0.005)

    return {
        "goodput_mbps": max(0.1, gp),
        "rtt_ms": max(1.0, rtt),
        "jitter_ms": max(0.1, jit),
        "loss_rate": max(0.0, min(0.2, loss)),
        "queue_delay_ms": max(0.0, qd),
        "fairness": max(0.0, min(1.0, fairness)),
    }

def main():
    # 5 binned features, 3 bins each -> 3^5 states
    NUM_STATES = num_states(num_features=5)

    # NumPy Q-table like the example you saw: Q[states, actions]
    Q = np.zeros((NUM_STATES, NUM_ACTIONS), dtype=np.float64)

    scenario = 0
    m0 = simulate_metrics(action=1, scenario=scenario)
    s0 = make_binned_state(m0)
    s_idx = encode_state(s0)

    cooldown = 0
    COOLDOWN_WINDOWS = 2
    last_action = 1

    for t in range(2000):
        if t == 1000:
            scenario = 1

        if cooldown > 0:
            a = last_action
            cooldown -= 1
        else:
            a = choose_action(Q, s_idx, eps)
            if a != last_action:
                cooldown = COOLDOWN_WINDOWS
            last_action = a

        m = simulate_metrics(action=a, scenario=scenario)
        r = compute_reward(m)

        s2 = make_binned_state(m)
        s2_idx = encode_state(s2)

        info = update_q(Q, s_idx, a, r, s2_idx, alpha, gamma)
        s_idx = s2_idx

        if t % 200 == 0:
            print(
                f"t={t} scenario={scenario} action={ACTION_NAMES[a]} "
                f"state={s2} r={r:.2f} td={info['td_error']:.2f} Qnew={info['new']:.2f}"
            )
'''
    test_m = simulate_metrics(action=1, scenario=1)
    test_s = make_binned_state(test_m)
    test_idx = encode_state(test_s)
    greedy = int(np.argmax(Q[test_idx]))
    print("Example congested state:", test_s, "greedy action:", ACTION_NAMES[greedy])
'''
if __name__ == "__main__":
    main()
