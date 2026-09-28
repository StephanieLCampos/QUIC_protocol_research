"""
Wireless bottleneck emulation package.

Emulates a shared, constrained wireless link that QUIC traffic must traverse,
so that protocol behaviour can be studied under controlled and repeatable
network conditions rather than whatever the host network happens to provide.

    BottleneckConfig    what the link looks like (capacity, delay, loss, queue)
    WirelessScenario    named, reusable configurations for common conditions
    WirelessBottleneck  applies a configuration to a real interface via Linux tc
    BottleneckMonitor   records queue occupancy, drops and per-flow statistics

Platform requirement: enforcement is performed by Linux Traffic Control, so
this package only shapes traffic on Linux with iproute2 and elevated
privileges. On macOS or Windows it must be run inside a Linux container or VM.

Connections:
    Imports from: .bottleneck, .config, .scenarios, .monitor
    Imported by:  examples/, the test_* diagnostic scripts,
                  setup_namespace_bottleneck, .cli, .validate
"""

from .bottleneck import WirelessBottleneck
from .config import BottleneckConfig, LossModel, QueueDiscipline
from .scenarios import WirelessScenario, PREDEFINED_SCENARIOS, get_scenario, list_scenarios
from .monitor import BottleneckMonitor, BottleneckMetrics

__all__ = [
    "WirelessBottleneck",
    "BottleneckConfig",
    "LossModel",
    "QueueDiscipline",
    "WirelessScenario",
    "PREDEFINED_SCENARIOS",
    "get_scenario",
    "list_scenarios",
    "BottleneckMonitor",
    "BottleneckMetrics",
]
