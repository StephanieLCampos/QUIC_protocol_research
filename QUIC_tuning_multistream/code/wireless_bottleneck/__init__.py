"""
Wireless bottleneck simulation module.

This module provides network emulation capabilities to simulate
shared wireless bottlenecks where multiple QUIC connections compete
under controlled wireless conditions.
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
