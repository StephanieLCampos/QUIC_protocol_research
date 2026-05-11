# QUIC Q-Learning Project

A QUIC network simulator with a Q-learning agent that learns to tune QUIC's congestion-control parameters in real time, run inside Docker so the network bottleneck is realistically enforced.

The active code lives in **`QUIC_research-main/QUIC_3conn_implementation/`**. Everything else (`Old/`, `Q_mark1/`, `Q_new/`, the four `*.py` files at the root) is reference/legacy material that was studied but not modified.

---

## Quick start (TL;DR)

You need: Docker Desktop running, Windows 11 / macOS / Linux.

```powershell
cd "QUIC_research-main/QUIC_3conn_implementation"
docker build -t quic-wireless -f Dockerfile .
docker compose up
```

When it finishes (~90 seconds), all results land in `QUIC_research-main/QUIC_3conn_implementation/results/`.

To run longer (e.g. 30 minutes for real Q-learning convergence), edit `docker-compose.yml` and bump the three `--duration` values, then run again.

---

## What this project does

There are 3 simulated QUIC connections — each one mimics a different real-world app:

| Connection | App type | What it cares about |
|---|---|---|
| 1 | video streaming | high throughput |
| 2 | file transfer | high throughput, doesn't care about latency |
| 3 | conference call | low latency, low jitter |

All three share a bottlenecked link (5 Mbps cap, 30 ms RTT, 2% loss — enforced by Linux `tc`/netem inside Docker).

A Q-learning agent watches all three connections and every 2 seconds decides whether to nudge one of QUIC's tunable knobs up or down on one of the three connections — trying to maximize an overall reward that mixes per-connection performance and fairness.

---

## What we changed vs. the original code

### Changed: the agent's "state" (how it perceives the world)

**Before:** The agent saw 6 binned numbers — latency, throughput, jitter, and their trends.
**After:** The agent sees 14 numbers — its own 12 current parameter dial positions (4 parameters × 3 connections) plus 2 aggregated network indicators (total throughput, mean RTT).

Why: parameter values are already discrete dial positions, so we don't lose information by binning. And including the agent's own settings in its state makes it possible to learn "if I'm already at packet_threshold=4 on file_transfer, don't try to push it higher."

### Changed: small bug fixes and infrastructure plumbing

- **Multi-container mode now actually runs Q-learning.** Before, the agent existed but the multi-container `clients` command silently never attached it. We added the `--with-ml` flag plumbing in `3_conn_code/main.py` and turned it on in `docker-compose.yml`.
- **Worker echoes all 4 parameters.** The original worker process only reported 3 of the 4 tunable parameters back to the agent. Fixed in `simulation/worker_process.py`.
- **Ctrl-C / SIGTERM no longer crashes the server.** The original orchestrator tried to set a read-only `is_running` property on the QUIC server, causing an `AttributeError` on every interrupt. Added a setter in `simulation/server.py`.
- **Safer Q-table loading.** Replaced `eval()` with `ast.literal_eval()` when reading the Q-table checkpoint back from disk (security smell fix).

### Stays the same

| Component | Where | Untouched? |
|---|---|---|
| QUIC server / client implementation | `simulation/server.py`, `simulation/client.py` | ✅ |
| Worker process model | `simulation/worker_process.py` | ✅ (1-line addition only) |
| `MLController` decision loop | `simulation/ml_controller.py` | ✅ |
| `ProcessOrchestrator` | `simulation/process_orchestrator.py` | ✅ |
| IPC pipes/queues | `simulation/ipc_messages.py` | ✅ |
| Q-table data structure (sparse `Dict[Tuple, List[float]]`) | `ml_callbacks/q_learning_agent.py` | ✅ |
| 25 actions (24 ± steps + 1 no-op) | `ml_callbacks/q_learning_agent.py` | ✅ |
| Reward function | `ml_callbacks/q_learning_agent.py` | ✅ |
| Bellman update / TD-learning rule | `ml_callbacks/q_learning_agent.py` | ✅ |
| ε-greedy with decay (0.3 → 0.05) | `ml_callbacks/q_learning_agent.py` | ✅ |
| Network scenarios (congested_low, lossy, clean…) | `wireless_bottleneck/` | ✅ |
| `tc`/netem bottleneck enforcement | `wireless_bottleneck/`, `setup_veth.sh` | ✅ |
| Multi-container topology (server / clients / prober) | `docker-compose.yml` | ✅ (only durations + `--with-ml` flag) |
| Result file formats | `simulation/result.py` | ✅ |

---

## Where the code lives

```
QUIC Q-LEARNING/                                    ← workspace root (you're here)
│
├── README.md                                        ← this file
│
├── QUIC_research-main/                              ← ACTIVE PROJECT
│   └── QUIC_3conn_implementation/
│       ├── Dockerfile                               ← Docker image build
│       ├── docker-compose.yml                       ← 3-container setup
│       ├── setup_veth.sh                            ← network plumbing (in-container)
│       ├── results/                                 ← run outputs land here
│       │
│       ├── wireless_bottleneck/                     ← tc/netem bottleneck enforcement
│       │
│       └── 3_conn_code/                             ← all simulation + agent code
│           ├── main.py                              ← CLI entry point
│           │
│           ├── ml_callbacks/
│           │   └── q_learning_agent.py              ← THE Q-LEARNING AGENT
│           │                                          (state design, actions, reward,
│           │                                          Bellman update — everything)
│           │
│           ├── simulation/                          ← the simulator
│           │   ├── server.py                        ← QUIC server (the "is_running" fix)
│           │   ├── client.py                        ← QUIC client logic
│           │   ├── worker_process.py                ← per-connection worker process
│           │   ├── ml_controller.py                 ← orchestrates agent calls (~0.1s tick)
│           │   ├── process_orchestrator.py          ← spawns/supervises workers
│           │   ├── ipc_messages.py                  ← pipe/queue message types
│           │   ├── multi_connection_config.py       ← per-connection defaults
│           │   └── result.py                        ← result aggregation & export
│           │
│           ├── metrics/
│           │   └── collector.py                     ← per-connection throughput/RTT/jitter
│           │
│           └── test_qlearn_agent.py                 ← unit tests for the agent
│
├── Old/                                             ← reference: previous code revisions
├── Q_mark1/                                         ← reference: earlier branch
├── Q_new/                                           ← reference: another branch
├── qlearn_funcs.py / reward.py / state.py /         ← reference: standalone Q-learning
│   run_stub.py                                          code that was studied
└── qlearning notes (1).md                           ← project notes
```

**The two files that matter the most:**

- `3_conn_code/ml_callbacks/q_learning_agent.py` — the whole Q-learning brain
- `3_conn_code/simulation/worker_process.py` — what runs inside each per-connection process

---

## How to run it (full instructions)

### 1. Prerequisites

- Docker Desktop running.
- ~3 GB free disk space for the Docker image.

### 2. Build the image (one time, or after code changes)

```powershell
cd "QUIC_research-main/QUIC_3conn_implementation"
docker build -t quic-wireless -f Dockerfile .
```

Takes 1–5 minutes the first time, ~10 seconds for incremental rebuilds (cached layers).

### 3. Run the simulation

```powershell
docker compose up
```

This starts **three containers** on a private Docker network:

| Container | Role |
|---|---|
| `quic-server` | Runs the QUIC server, applies the bottleneck via `tc` on its `eth0` |
| `quic-clients` | Runs 3 worker processes (video / file / conference), each opening a QUIC connection to the server. **The Q-learning agent lives here.** |
| `quic-prober` | A separate ICMP-ping sidecar that measures path RTT independently (sanity check) |

By default the run lasts ~80 seconds. You'll see the agent's log lines stream by:

```
[QLAgent] Initialised - 25 actions, control_interval=2.0s, alpha=0.1 gamma=0.9 eps=0.3->0.05
[QLAgent step=  10] params=(2, 3, 2, 1, 2, 1, 2, 0, 2, 0, 0, 0) tp_bin=3 rtt_bin=0 action=conf.packet_threshold v eps=0.285 total_tp=182.74Mbps mean_rtt=39.9ms avg_R=+0.869 Q-states=5
```

Each `[QLAgent step]` line shows: the current 14-feature state, what action was taken (e.g. `conf.packet_threshold v` = "decrease packet_threshold on conference connection one notch"), epsilon, network conditions, average recent reward, and how many states the Q-table has seen so far.

### 4. Read the results

When the run completes, look in `QUIC_research-main/QUIC_3conn_implementation/results/`. You'll have 7 JSON files:

| File | What's in it |
|---|---|
| `median_metrics_summary_*.json` | **Start here** — clean per-connection summary (throughput, RTT, jitter) |
| `bottleneck_summary_*.json` | Was the link bottlenecked? Configured vs. observed throughput |
| `epoch_history_*.json` | One entry per parameter change — what changed, when, and the metrics around it |
| `metrics_history_*.json` | Raw per-100ms samples for every connection (large file) |
| `results_*.json` | Combined dump of everything |
| `network_probe_*.json` | Independent ICMP RTT measurements from the prober sidecar |

### 5. Run a longer simulation (for actual Q-learning convergence)

70-second runs only give the agent ~35 decisions — fine to verify the code works, not enough to actually learn a good policy. For real training, bump the three `--duration` flags in `docker-compose.yml`:

```yaml
# server
command: python -m main server --duration 1800 ...

# clients
command: python -m main clients ... --duration 1790 ... --with-ml

# prober
command: python -m main probe ... --duration 1780 ...
```

That's a 30-minute run = ~900 decisions, plenty to see clear convergence. To watch the agent live without keeping a terminal in the foreground:

```powershell
docker compose up -d
docker compose logs -f quic-clients
```

### 6. Clean shutdown

```powershell
docker compose down
```

Or just Ctrl-C — the `is_running` fix means SIGINT/SIGTERM now exits cleanly and still writes results.

### 7. Run a different scenario

Available network scenarios live in `wireless_bottleneck/scenarios/`. Common ones: `clean`, `congested_low`, `degraded`, `lossy`. Switch with:

```powershell
$env:SCENARIO = "lossy"; docker compose up
```

---

## How to know it worked

A healthy run shows:

1. **All 3 containers exit cleanly** (`Exit code: 0`). The prober may exit early — that's fine.
2. **All 7 result JSON files appear in `results/`.**
3. **Multiple epochs per connection** (`epoch_count > 1` in `epoch_history_*.json`). Multiple epochs means the agent actually took actions. If you see `epoch_count: 1` everywhere, the agent didn't run.
4. **`[QLAgent step= N]` lines in the clients log** with Q-states growing over time.
5. **Bottleneck enforced** — in `bottleneck_summary_*.json`, `observed_link_throughput_mbps` should be near 5.0 (the cap) and well below `total_offered_throughput_mbps`.

If you see `[Clients] ML controller enabled: q_learning_callback` in the logs, the agent is attached. If you don't, the `--with-ml` flag isn't being passed.

---

## Known limitations (not bugs, just things we didn't do)

These don't break anything; just things you may eventually want.

| Limitation | Effect | Fix complexity |
|---|---|---|
| Q-table not persisted across `docker compose up` runs | Every run starts from zero learning | 1-line cadence change + 1 volume mount |
| First epoch in each run has 1 sample, marked invalid | First decision is noise | ~5 lines in `ml_controller.py` |
| Old reports in `3_conn_code/reports/` describe the 6-feature state | Documentation drift only | Edit a couple `.md` files |
| No A/B harness comparing `--with-ml` vs no-ML | Manual JSON diffing if you want to compare | ~30-line script |
| `asyncio.get_event_loop()` deprecation warning at startup | Cosmetic only, fine on Python ≤ 3.13 | 2-line swap to `asyncio.new_event_loop()` |

---

## The big idea, in one paragraph

The base project is a real QUIC simulator with three competing connections sharing a `tc`-enforced wireless-style bottleneck. On top, a tabular Q-learning agent observes both its own current settings (12 dial positions across 4 parameters × 3 connections) and 2 aggregated network indicators (total throughput, mean RTT) — 14 features total. Every 2 seconds it picks one of 25 actions: nudge one parameter on one connection up or down by exactly one notch, or do nothing. It receives a reward based on per-connection utility minus fairness and stability penalties, updates its sparse Q-table with the Bellman rule, decays epsilon, and over many control steps it learns a policy mapping "this combination of settings + this network state" → "best next nudge."
