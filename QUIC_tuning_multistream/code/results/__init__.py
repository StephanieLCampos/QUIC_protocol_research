"""
Results analysis package for the QUIC Multi-Stream Research Project.

Turns the raw CSV output of a completed sweep into findings:

    ResultsAnalyzer   loads every result CSV and identifies the optimal
                      parameter set for each application type
    ReportGenerator   renders those findings as human-readable reports

Connections:
    Imports from: .analyzer, .report_generator
    Imported by:  main.py
"""

from .analyzer import ResultsAnalyzer
from .report_generator import ReportGenerator

__all__ = [
    "ResultsAnalyzer",
    "ReportGenerator",
]
