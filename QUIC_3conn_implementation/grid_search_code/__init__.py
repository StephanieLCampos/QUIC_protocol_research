"""
QUIC Parameter Grid Search

Find optimal congestion control parameters for each application type.

Standalone sweep over the six dynamic CUBIC parameters, run separately from the
live three-connection simulation. Its purpose is to establish, for each
application type in isolation, which parameter values best serve that type's
objective. Those results become the tuning ranges the Q-learning agents in
3_conn_code search within.

    config/     the parameter space to be searched
    scheduler/  which combinations remain outstanding (resumable)
    runner/     executes one combination in an isolated process
    analysis/   identifies the optimal configuration per application type

Relationship to the rest of the project: this sweep measures one connection at
a time, with no competition. The three-connection system then asks the
different question of how such tuned connections behave when they contend for
one bottleneck.

Connections
-----------
Entry point : main.py
Depends on  : ../3_conn_code (its simulation and metrics modules are imported
              by the runner via an explicit sys.path insertion)
"""
