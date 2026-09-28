"""
Wireless bottleneck emulation package (Generation 2).

Emulates a shared, constrained wireless link that all three QUIC connections
must traverse, so that they genuinely compete for a limited resource under
controlled and repeatable conditions.

    BottleneckConfig    what the link looks like (capacity, delay, loss, queue)
    WirelessScenario    named, reusable configurations for common conditions
    WirelessBottleneck  applies a configuration to a real interface via Linux tc
    BottleneckMonitor   records queue occupancy, drops and per-flow statistics

Differences from the Generation 1 copy in QUIC_tuning_multistream
-----------------------------------------------------------------
This is an evolved copy, not a duplicate. The substantive changes:

    - HTB replaces TBF as the rate-limiting qdisc, allowing the rate to be
      changed in place with `tc class change` rather than by deleting and
      re-adding the qdisc. This is what makes live slider control workable.
    - Ingress policing is available as an alternative to egress shaping, for
      constraining the download direction.
    - Manual override, so the dashboard can drive link conditions directly.
    - Channel-quality variation: an Ornstein-Uhlenbeck random walk that varies
      bandwidth, delay, jitter and loss together (see bottleneck.py).
    - SCENARIOS is exported as an alias of PREDEFINED_SCENARIOS.
    - The `varying` scenario's period was lengthened from 2s to 6s so that a
      Q-learning agent acting every 2s can make several decisions within one
      network state.

monitor.py, validate.py, cli.py and __main__.py are unchanged from Generation 1.

Platform requirement: enforcement is performed by Linux Traffic Control, so
this package only shapes traffic on Linux with iproute2 and elevated
privileges.

Connections
-----------
Imports from : .bottleneck, .config, .scenarios, .monitor
Imported by  : 3_conn_code/main.py, simulation.process_orchestrator (both
               optional imports), examples/run_3conn_through_bottleneck.py
"""

from .bottleneck import WirelessBottleneck
from .config import BottleneckConfig, LossModel, QueueDiscipline
from .scenarios import WirelessScenario, PREDEFINED_SCENARIOS, get_scenario, list_scenarios
from .monitor import BottleneckMonitor, BottleneckMetrics

# Expose SCENARIOS for convenience
SCENARIOS = PREDEFINED_SCENARIOS

__all__ = [
    "WirelessBottleneck",
    "BottleneckConfig",
    "LossModel",
    "QueueDiscipline",
    "WirelessScenario",
    "PREDEFINED_SCENARIOS",
    "SCENARIOS",
    "get_scenario",
    "list_scenarios",
    "BottleneckMonitor",
    "BottleneckMetrics",
]
