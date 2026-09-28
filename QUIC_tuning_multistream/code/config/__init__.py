"""
Configuration package for the QUIC Multi-Stream Research Project (Generation 1).

Re-exports the two configuration surfaces used across the project: global
runtime settings (paths, host/port, traffic-shape defaults) and the QUIC
parameter definitions that drive the grid search.

Connections:
    Imports from: .settings, .parameters
    Imported by:  main.py, grid_search.executor, simulation.runner,
                  examples.run_app_with_real_bottleneck, examples.wireless_experiment
"""

from .settings import Settings
from .parameters import ParameterPresets, GRID_SEARCH_PARAMS

__all__ = ["Settings", "ParameterPresets", "GRID_SEARCH_PARAMS"]
