"""
Research Code: uniform configuration experiments.

Runs the three-connection simulation with the *same* parameter set applied to
all three connections, then measures how each application type performs under
each configuration.

The question it answers
-----------------------
The grid search establishes an optimal configuration per application type in
isolation. This package asks what happens when one configuration is imposed on
all three at once: how much does a throughput-tuned setup cost the
latency-sensitive workload, and vice versa. That cost is the argument for
per-connection tuning, and therefore the motivation for the Q-learning work.

Each run of all three configurations yields 27 measurements:
3 configurations x 3 application types x 3 metrics (throughput, latency, jitter).

    config/uniform_presets.py  the three configurations, from grid search
    experiment_runner.py       runs one or all configurations
    results_extractor.py       collects the 27 values and their ranges

Connections
-----------
Depends on : ../3_conn_code (orchestrator, config), and on grid search output
             for the preset values
Run from   : the 3_conn_code directory, where the certificates live
"""

