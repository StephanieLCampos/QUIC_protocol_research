# QUIC Protocol Research

Research testbed for studying how QUIC congestion-control parameters affect
application performance, and whether a reinforcement-learning agent can tune
those parameters better than any fixed configuration when several connections
with conflicting goals compete for one constrained link.

The repository contains two generations of the same research programme. Both
are kept because the second exists to answer a question the first could not.

| | `QUIC_tuning_multistream` | `QUIC_3conn_implementation` |
|---|---|---|
| **Generation** | 1 (Jan – Mar 2026) | 2 (Feb – May 2026) |
| **Question** | Which parameters suit which application? | Can an agent tune them live, under contention? |
| **Connections** | One at a time, in isolation | Three concurrently, competing |
| **Method** | Exhaustive grid search | Grid search + tabular Q-learning |
| **Tuning** | Fixed before each run | Changed mid-connection |
| **Network** | Linux `tc` bottleneck emulation | Same, extended with live control |

---

## The research question

Three application types want incompatible things from a transport protocol:

| Application | Traffic shape | Optimises for |
|---|---|---|
| Video streaming | Bursty: large keyframes, small delta frames | Low latency |
| File transfer | Continuous bulk, unpaced | High throughput |
| Conference call | Small packets at a strict 20ms cadence | Low jitter |

QUIC's CUBIC congestion control exposes tuning parameters that trade these
against one another. A configuration that maximises throughput tends to build
queues and hurt latency; one that protects latency leaves bandwidth unused.

Generation 1 measured that trade-off for each application in isolation.
Generation 2 asks the harder question: when all three share one bottleneck,
and each connection can be tuned independently and continuously, can a
Q-learning agent find an allocation that serves all three better than any
single fixed configuration?

---

## Team

This was a team project with three contributors:

- **Stephanie Campos**
- **Sean Lai**
- **Derek Chui**

An additional Q-learning agent variant in `3_conn_code/ml_callbacks/` carries an
in-source author credit to Andy Li.

Development ran from January to May 2026.

---

## Repository layout

```
QUIC_protocol_research/
├── generate_certs.sh               one-time TLS setup (run after cloning)
├── QUIC_tuning_multistream/        Generation 1 — offline parameter sweep
│   ├── code/
│   │   ├── main.py                 CLI: run / status / analyze / report / clear
│   │   ├── config/                 settings and parameter definitions
│   │   ├── synthesizers/           three application traffic models
│   │   ├── simulation/             QUIC client, server, single-run orchestration
│   │   ├── metrics/                collect → calculate → export
│   │   ├── grid_search/            parameter space, resumable scheduler, executor
│   │   ├── results/                analysis and report generation
│   │   ├── wireless_bottleneck/    Linux tc network emulation
│   │   └── examples/, test_*.py    demos and environment diagnostics
│   ├── docs/, reports/             requirements history and written findings
│   └── Dockerfile, run-*.sh        Linux container (tc is Linux-only)
│
└── QUIC_3conn_implementation/      Generation 2 — three competing connections
    ├── 3_conn_code/                the main application
    │   ├── main.py                 CLI: run / server / clients / probe
    │   ├── config/                 per-connection and multi-connection config
    │   ├── simulation/             orchestrator, worker processes, IPC, results
    │   ├── ml_callbacks/           three Q-learning agents
    │   ├── metrics/                collection, calculation, epoch management
    │   ├── synthesizers/           three application traffic models
    │   └── web/                    FastAPI dashboard + static front end
    ├── grid_search_code/           standalone sweep over the 6 dynamic parameters
    ├── research_code/              uniform-configuration comparison (27 values)
    ├── wireless_bottleneck/        evolved tc emulation (HTB, live control)
    ├── train_*.sh                  batch Q-learning training scripts
    └── Dockerfile, docker-compose.yml
```

---

## How the pieces fit together

The two generations form one pipeline. Each stage answers a question the next
stage depends on.

```
  Generation 1                        Generation 2
  ────────────                        ────────────

  grid search                         grid_search_code
  192 combinations                    243 / 2,187 combinations
  1 connection, isolated              6 dynamic CUBIC parameters
        │                                    │
        │ best parameters                    │ tuning ranges + per-app defaults
        │ per application                    │
        ▼                                    ▼
  results/analyzer                    research_code
  optimal config per app              one uniform config on all 3 connections
                                      → 27 measurements: what does sharing cost?
                                             │
                                             │ motivates per-connection tuning
                                             ▼
                                      3_conn_code
                                      3 competing connections, tuned live
                                      by a Q-learning agent
```

### Generation 1 data flow — one measured run

```
ParameterSpace ──► ResumableScheduler ──► GridSearchExecutor
                   (what's left to run)    (runs each combination)
                                                 │
                                                 ▼
                                          SimulationRunner
                          patch aioquic globals → start server → connect client
                          → drive synthesizer → collect metrics → restore globals
                                                 │
                                                 ▼
                         MetricsCollector → MetricsCalculator → MetricsExporter
                                                 │
                                                 ▼
                                    output/measurements/<combination>.csv
                                                 │
                                                 ▼
                                   ResultsAnalyzer → ReportGenerator
```

### Generation 2 data flow — three connections at once

```
                        ProcessOrchestrator (main process)
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                            │
   QuicServer                  MLController                start barrier
   (shared endpoint)        (Q-learning control loop)    (synchronised start)
        │                            │
        │                 parameters │  ▲ metrics
        │                     (pipe) ▼  │ (shared queue)
        │          ┌─────────────────────────────────────┐
        │          │  worker 1  │  worker 2  │  worker 3 │   separate processes
        └──────────│   video    │    file    │ conference│   one aioquic each
                   └─────────────────────────────────────┘
                                     │
                          WirelessBottleneck (Linux tc)
                        shared, constrained link they compete over
                                     │
                                     ▼
                  MultiConnectionResult → JSON / CSV exports
                            + live dashboard on :8000
```

---

## The central design constraint

One implementation detail shaped the entire architecture, and is the most
useful thing to understand about this codebase.

**aioquic stores its congestion-control tuning in module-level globals.**
`K_CUBIC_C`, `K_CUBIC_LOSS_REDUCTION_FACTOR`, `K_PACKET_THRESHOLD` and the rest
are module attributes, not per-connection configuration. There is no supported
way to give two connections in one process different congestion-control
parameters.

Generation 1 worked within that constraint: it measured one connection at a
time, patching the globals before each run and restoring them afterwards
(`simulation/runner.py`). Because the globals are process-wide, its sweep also
had to run strictly sequentially.

Generation 2 could not. Its entire premise is three connections holding
*different* parameters simultaneously. The resolution was to give each
connection its own OS process, and therefore its own copy of the aioquic
modules — which is why the system is multi-process rather than simply async,
and why it needs pipes, a shared queue, a start barrier and a shared token
bucket to coordinate what would otherwise be ordinary in-process state.

Every awkward-looking piece of the Generation 2 architecture follows from that
one library constraint.

---

## Measurement approach

**Synthetic traffic.** The synthesizers emit zero-filled payloads. Packet
content has no effect on congestion control, so only size and timing are
modelled; this keeps runs cheap and perfectly reproducible.

**Real network emulation.** Bandwidth, delay, loss and queueing are enforced by
Linux `tc` at kernel level, not simulated in the application. Five named
scenarios (`stable_high`, `congested_low`, `varying`, `lossy`, `asymmetric`)
plus a series of fixed packet-error-rate scenarios cover the conditions of
interest. Because `tc` is Linux-only, every shaped experiment runs in a
container.

**Epoch-based metrics.** When parameters change mid-run, a congestion window
takes time to react. Metrics are therefore grouped into *epochs* — periods of
constant configuration — separated by a settling delay during which nothing is
sampled. Without this, averages would blend every configuration tried into one
meaningless number (`3_conn_code/metrics/epoch.py`).

**Robust statistics.** Summaries use trimmed medians rather than means, so a
single startup transient or scheduling spike cannot dominate a reported figure.

**Fairness.** Bandwidth sharing is scored with Jain's fairness index over
per-connection throughput, giving one comparable number for whether an agent
improved allocation or merely favoured one connection.

### Known measurement caveats

These are documented in the source and worth knowing before reading results:

- **Packet loss is estimated, not observed.** aioquic exposes no loss counter,
  so loss is inferred from ssthresh reductions, congestion-window drops and PTO
  counts using heuristic multipliers. Treat it as a relative indicator, not an
  exact count. The `tc` counters are authoritative where precision matters.
- **Latency is derived as RTT/2**, which assumes a symmetric path. That
  assumption does not hold under the `asymmetric` scenario.
- **Loopback does not shape properly.** Linux bypasses much of the queueing
  path on `lo`, so accurate results require the veth or multi-container setups.
  Local macOS runs are for development, not measurement.
- **Generation 1's `varying` scenario was fixed during the documentation
  pass.** Its rate-update path previously addressed qdisc handles from a
  superseded layout and never touched the root TBF, so the link ran at a fixed
  rate while reporting otherwise. It now edits the root TBF in place with
  `tc qdisc change`, and its variation period was aligned to Generation 2's
  6 seconds so the two are directly comparable. **Any `varying` results
  generated before this fix should be discarded and the runs repeated.**

---

## The Q-learning experiment

Three agents share an identical action space (25 actions: 4 parameters × 3
connections × 2 directions, plus a no-op) and an identical reward function.
They differ *only* in how they represent state, which makes the comparison
between them a clean experiment in state design:

| Agent | Features | State space | Design idea |
|---|---|---|---|
| `default` | 8 | ~27,600 | Performance bins plus trends |
| `hybrid` | 10 | ~995,000 | Default, plus compressed boundary and dominance signals |
| `andy` | 14 | ~11.6M | Exact parameter step indices, so boundaries are visible |

The trade-off under test is generalisation against precision. Andy's agent can
tell that a parameter is already pinned at its limit; the default agent cannot.
But with ~11.6M possible states and only a few hundred visited per run, its
Q-table is far sparser and generalises much less. The hybrid design keeps the
boundary signal while compressing it to a single feature.

The reward balances aggregate performance against starvation:

```
R = mean(U_video, U_file, U_conf)
    − stability penalty    (discourages needless parameter churn)
    − starvation penalty   (per connection below 500 KB/s)
    − suffering penalty    (per connection with utility below 0.4)
```

Fairness is enforced by absolute floors rather than by penalising inequality.
This is deliberate: file transfer is *expected* to take a larger share, since
throughput is its entire utility while the other two weight it at only 30%.
The goal is to prevent starvation, not to force equal shares.

---

## Running the project

### First-time setup

QUIC mandates TLS, so both projects need a certificate and key before a server
will start. These are disposable localhost credentials and are therefore
generated on demand rather than committed:

```bash
./generate_certs.sh
```

Run this once after cloning. The Generation 2 Docker image builds its own
certificates and does not need it; every other path does.

### Running

Both generations need Docker, because `tc` requires Linux.

```bash
# Generation 2 — three connections, Q-learning, live dashboard
cd QUIC_3conn_implementation
docker compose up
# dashboard at http://localhost:8000, results in ./results/

# Generation 1 — offline parameter sweep
cd QUIC_tuning_multistream
./run-bottleneck.sh
# then, inside the container:
python3 diagnose.py          # verify tc works here first
cd code && uv run main.py run
```

Each subdirectory's README covers its own setup, options and output in full.

---

## Where to look first

For a reader trying to understand the design quickly:

| To understand | Read |
|---|---|
| Why the architecture is multi-process | `3_conn_code/simulation/worker_process.py` |
| How the three connections are coordinated | `3_conn_code/simulation/process_orchestrator.py` |
| How parameter changes are attributed to outcomes | `3_conn_code/metrics/epoch.py` |
| The learning policy and reward design | `3_conn_code/ml_callbacks/q_learning_agent.py` |
| How the network constraint is actually applied | `wireless_bottleneck/bottleneck.py` |
| The simpler Generation 1 equivalent | `QUIC_tuning_multistream/code/simulation/runner.py` |

Every source file carries a header describing what it does and which modules it
connects to.

---

## Requirements

- Python 3.12+
- Docker and Docker Compose
- Linux kernel with `tc` support (provided by Docker on macOS and Windows)

Python dependencies: `aioquic >= 1.0.0`, `fastapi >= 0.109.0`,
`uvicorn >= 0.27.0`, `pandas >= 2.0.0` (Generation 1 analysis).
