"""
Metrics package for the QUIC Multi-Stream Research Project.

Provides the three-stage measurement pipeline used by every simulation run:

    MetricsCollector  ->  MetricsCalculator  ->  MetricsExporter
    (record events)       (derive metrics)       (write result CSV)

The collector accumulates raw events while a run is in flight, the calculator
reduces them to the six reported performance metrics, and the exporter writes
one CSV per parameter combination.

Connections:
    Imports from: .collector, .calculator, .exporter
    Imported by:  simulation.client, simulation.runner, grid_search.executor
"""

from .collector import MetricsCollector
from .calculator import MetricsCalculator
from .exporter import MetricsExporter

__all__ = [
    "MetricsCollector",
    "MetricsCalculator",
    "MetricsExporter",
]
