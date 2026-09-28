"""
Grid search runner module.

Executes parameter combinations, individually and in parallel.

Connections
-----------
Contains    : single_connection_runner (one combination, isolated process),
              executor (the parallel sweep over all pending combinations)
Imported by : main.py
"""
