"""
Grid search package for QUIC parameter optimization.

Drives the systematic parameter sweep that forms the Generation 1 experiment:

    ParameterSpace      enumerates every parameter combination to be tested
    ResumableScheduler  filters that list down to the combinations not yet run
    GridSearchExecutor  runs each pending combination and exports its result

Connections:
    Imports from: .parameter_space, .scheduler, .executor
    Imported by:  main.py
"""

from .parameter_space import ParameterSpace, ParameterCombination
from .scheduler import ResumableScheduler
from .executor import GridSearchExecutor

__all__ = [
    "ParameterSpace",
    "ParameterCombination",
    "ResumableScheduler",
    "GridSearchExecutor",
]
