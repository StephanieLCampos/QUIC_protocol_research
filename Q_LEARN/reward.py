'''
from typing import Dict

def compute_reward(metrics: Dict) -> float:
    """Reward scalar. Includes fairness ONLY in reward.
    Expected keys:
      goodput_mbps, rtt_ms, jitter_ms, loss_rate, fairness (0..1)
    """
    gp = metrics["goodput_mbps"]
    rtt = metrics["rtt_ms"]
    jit = metrics["jitter_ms"]
    loss = metrics["loss_rate"]
    fair = metrics["fairness"]

    return (
        1.0 * gp
        - 0.02 * rtt
        - 0.05 * jit
        - 20.0 * loss
        + 2.0 * fair
    )
'''
from typing import Dict

def compute_reward(metrics: Dict) -> float:
    """
    Reward scalar. Includes fairness ONLY in reward.
    Expected keys:
      goodput_mbps, rtt_ms, jitter_ms, loss_rate, queue_delay_ms, fairness (0..1)
    """
    gp = metrics["goodput_mbps"]
    rtt = metrics["rtt_ms"]
    jit = metrics["jitter_ms"]
    loss = metrics["loss_rate"]
    qd = metrics["queue_delay_ms"]
    fair = metrics["fairness"]
# should not use same parameters (measurements) for states and reward, creates bias 
    reward = (
        1.0 * gp
        - 0.02 * rtt
        - 0.05 * jit
        - 0.02 * qd      # penalize queue delay explicitly
        - 20.0 * loss
        + 2.0 * fair
    )
    return reward
