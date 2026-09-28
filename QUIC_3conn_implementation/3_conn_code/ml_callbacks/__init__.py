"""
ml_callbacks package.

Q-learning agents that drive dynamic QUIC parameter tuning. Each module here is
a self-contained control policy exposing a `q_learning_callback` entry point
that MLController invokes with the latest metrics from all three connections.

Three agents are available, differing only in how they represent state:

    q_learning_agent.py         default, 8-feature   ~27,600 states
    q_learning_agent_hybrid.py  hybrid,  10-feature  ~995,000 states
    q_learning_agent_andy.py    Andy's,  14-feature  ~11.6M states

All three share the same 25-action space and the same reward function, so a
comparison between them isolates the effect of state representation alone. That
comparison is the central machine-learning question of this project: whether a
richer state description buys better tuning, or merely a Q-table too sparse to
generalise within a feasible training budget.

Selected at runtime with `--ml-agent {default,hybrid,andy}`.

Connections
-----------
Imported by : simulation.ml_controller, main.py (both import by agent type,
              lazily, so an error in one agent cannot prevent the others loading)
"""

# ml_callbacks package
