from typing import Dict, Tuple

BINS_PER_FEATURE = 3  # 0=low, 1=med, 2=high

def bin_low_med_high(x: float, low_th: float, high_th: float) -> int:
    if x < low_th:
        return 0
    if x < high_th:
        return 1
    return 2

def make_binned_state(metrics: Dict) -> Tuple[int, int, int, int, int]:
    """Convert raw metrics into low/med/high bins.
    Expected keys:
      rtt_ms, jitter_ms, loss_rate, queue_delay_ms, goodput_mbps
    """
    rtt_bin = bin_low_med_high(metrics["rtt_ms"], low_th=50.0, high_th=100.0)
    jitter_bin = bin_low_med_high(metrics["jitter_ms"], low_th=5.0, high_th=15.0)
    loss_bin = bin_low_med_high(metrics["loss_rate"], low_th=0.01, high_th=0.03)
    qdelay_bin = bin_low_med_high(metrics["queue_delay_ms"], low_th=10.0, high_th=30.0)
    tput_bin = bin_low_med_high(metrics["goodput_mbps"], low_th=3.0, high_th=8.0)
    return (rtt_bin, jitter_bin, loss_bin, qdelay_bin, tput_bin)

def num_states(num_features: int) -> int:
    return (BINS_PER_FEATURE ** num_features)

def encode_state(state_tuple: Tuple[int, ...]) -> int:
    """Base-3 encoding of a tuple of digits in {0,1,2}."""
    idx = 0
    base = 1
    for v in state_tuple:
        idx += int(v) * base
        base *= BINS_PER_FEATURE
    return idx
