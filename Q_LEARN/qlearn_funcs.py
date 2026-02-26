
import random
from typing import Dict

import numpy as np

def choose_action(Q: np.ndarray, s_idx: int, eps: float) -> int:
    """Epsilon-greedy action choice."""
    num_actions = Q.shape[1]
    if random.random() < eps:
        return random.randrange(num_actions)
    return int(np.argmax(Q[s_idx]))

def bellman_target(Q: np.ndarray, r: float, s2_idx: int, gamma: float) -> float:
    """Off-policy Q-learning target: r + gamma * max_a' Q[s',a']"""
    return float(r + gamma * np.max(Q[s2_idx]))

def update_q(Q: np.ndarray, s_idx: int, a: int, r: float, s2_idx: int, alpha: float, gamma: float) -> Dict[str, float]:
    """One Q-learning update using TD error."""
    current = float(Q[s_idx, a])
    target = bellman_target(Q, r, s2_idx, gamma)
    td_error = target - current
    Q[s_idx, a] = current + alpha * td_error
    return {"current": current, "target": target, "td_error": float(td_error), "new": float(Q[s_idx, a])}
