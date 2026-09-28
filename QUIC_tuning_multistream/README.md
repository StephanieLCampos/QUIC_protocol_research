# QUIC Multi-Stream Research (Generation 1)

Systematic grid search over QUIC congestion-control parameters, measuring how
each of three application types responds to each configuration.

This is the first of the two generations in this repository. It measures **one
connection at a time, in isolation**, with parameters fixed before each run.
The successor project, [`QUIC_3conn_implementation`](../QUIC_3conn_implementation),
extends the work to three concurrent connections tuned live by a Q-learning
agent.

Part of a team project with three contributors: Stephanie Campos, Sean Lai and
Derek Chui.

---

## What this project answers

Three application types want different things from a transport protocol, and
QUIC's CUBIC parameters trade those wants against one another:

| Application | Traffic pattern | Optimisation target |
|---|---|---|
| Video streaming | I-frames every 60 frames (~50KB), P-frames between (~5KB), 30fps | Minimise RTT |
| File transfer | 64KB chunks, unpaced | Maximise throughput |
| Conference call | ~320-byte packets every 20ms (128kbps) | Minimise jitter |

The sweep measures every combination of three parameters against all three
application types, then identifies the best configuration for each.

### Parameter space

| Parameter | Values | Meaning |
|---|---|---|
| `initial_cw` | 12000, 36000, 72000, 120000 bytes | Initial congestion window (10, 30, 60, 100 packets) |
| `max_ack_delay` | 0.002, 0.010, 0.025, 0.050 s | How long a receiver defers an ACK |
| `loss_reduction_factor` | 0.4, 0.5, 0.6, 0.7 | cwnd multiplier on loss (CUBIC beta) |

4 × 4 × 4 = 64 combinations per application type, **192 simulations in total**.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           main.py                                   │
│                    (CLI Entry Point)                                │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   grid_search   │  │   simulation    │  │     results     │
│                 │  │                 │  │                 │
│ - executor      │  │ - runner        │  │ - analyzer      │
│ - scheduler     │  │ - client        │  │ - report_gen    │
│ - param_space   │  │ - server        │  │                 │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         │           ┌────────┴────────┐           │
         │           │                 │           │
         │           ▼                 ▼           │
         │  ┌─────────────────┐ ┌─────────────┐   │
         │  │  synthesizers   │ │   metrics   │   │
         │  │                 │ │             │   │
         │  │ - video         │ │ - collector │   │
         │  │ - file          │ │ - calculator│   │
         │  │ - conference    │ │ - exporter  │◄──┘
         │  └─────────────────┘ └─────────────┘
         │                              │
         │                              ▼
         │                      ┌─────────────┐
         └─────────────────────►│   config    │
                                │             │
                                │ - settings  │
                                │ - parameters│
                                └─────────────┘
```

### Module reference

| Module | Purpose |
|---|---|
| `config/settings.py` | Global settings: paths, host/port, durations, traffic defaults |
| `config/parameters.py` | Parameter presets and the searched value grid |
| `synthesizers/base.py` | Abstract synthesizer and factory |
| `synthesizers/video_streaming.py` | I/P-frame pattern at 30fps |
| `synthesizers/file_transfer.py` | Bulk 64KB chunks, unpaced |
| `synthesizers/conference_call.py` | Constant-bitrate audio at 20ms intervals |
| `simulation/server.py` | QUIC server receiving synthetic data |
| `simulation/client.py` | QUIC client sending synthesizer output |
| `simulation/runner.py` | Orchestrates a single measured run |
| `metrics/collector.py` | Records events during a run |
| `metrics/calculator.py` | Derives the six reported metrics |
| `metrics/exporter.py` | Writes the result CSV |
| `grid_search/parameter_space.py` | Enumerates every combination |
| `grid_search/scheduler.py` | Determines what remains to run (resumability) |
| `grid_search/executor.py` | Runs each pending combination |
| `results/analyzer.py` | Loads results, finds optimal configurations |
| `results/report_generator.py` | Renders text reports |
| `wireless_bottleneck/` | Linux `tc` network emulation |

---

## Data flow

```
ParameterSpace ──► ResumableScheduler ──► GridSearchExecutor
  (all 192)         (what's still pending)  (runs each one)
                                                  │
                                                  ▼
                                          SimulationRunner
                     1. patch aioquic congestion-control globals
                     2. start QUIC server
                     3. connect client, open 3 streams
                     4. drive the application's synthesizer
                     5. collect metrics
                     6. restore the original globals
                                                  │
                                                  ▼
                MetricsCollector ──► MetricsCalculator ──► MetricsExporter
                 (raw events)         (six metrics)        (one CSV)
                                                  │
                                                  ▼
                              output/measurements/<combination>.csv
                                                  │
                                                  ▼
                              ResultsAnalyzer ──► ReportGenerator
```

### Two design points worth knowing

**Parameters are applied by patching aioquic's module globals.** aioquic exposes
`K_INITIAL_WINDOW` and `K_CUBIC_LOSS_REDUCTION_FACTOR` as module-level
constants, not as per-connection configuration. `SimulationRunner` captures the
originals at import, patches them before each run, and restores them in a
`finally` block.

Because those globals are process-wide, **the sweep must run sequentially** —
two concurrent runs in one process would overwrite each other's parameters and
silently corrupt both measurements. This constraint is precisely what motivated
Generation 2's multi-process design.

**Resumability has no state file.** Each result CSV is named after the exact
combination that produced it, so the presence of a file *is* the record that
the combination has been measured. An interrupted sweep resumes simply by being
re-run; no recovery step is needed.

---

## Metrics

Six metrics are recorded per run:

| Metric | Unit | Notes |
|---|---|---|
| Throughput | bytes/sec | Total bytes ÷ duration |
| RTT | seconds | Mean of aioquic's smoothed RTT samples |
| Latency | seconds | Estimated as RTT / 2 |
| Jitter | seconds | Standard deviation of inter-packet delays |
| Packet loss rate | 0.0–1.0 | Derived from aioquic's recovery state |
| Connection establishment time | seconds | Handshake duration |

**Caveats.** Latency is derived rather than measured, so it assumes a symmetric
path — an assumption that fails under the `asymmetric` scenario. Jitter is the
spread of inter-arrival gaps, so a stream that is uniformly late but perfectly
regular scores near zero. RTT and loss statistics are read from aioquic's
private recovery object, as no public API exposes them; every such access is
guarded so an aioquic change degrades a metric rather than failing a run.

---

## Wireless bottleneck emulation

Network conditions are enforced by Linux Traffic Control (`tc`), giving real
kernel-level shaping rather than an in-application simulation.

| Scenario | Capacity | RTT | Loss | Represents |
|---|---|---|---|---|
| `stable_high` | 100 Mbps | 10 ms | 0.1% | Good WiFi or wired |
| `congested_low` | 5 Mbps | 30 ms | 2% | Contended WiFi (RED queue) |
| `varying` | 20 Mbps ±40% | 20 ms | 1% | Mobility and fading (CoDel) |
| `lossy` | 10 Mbps | 40 ms | 5% burst | Poor radio (Gilbert-Elliott) |
| `asymmetric` | 50↓ / 10↑ Mbps | 25 ms | 0.5% | Mobile network shape |

**Why loopback is not enough.** The Linux kernel bypasses much of the queueing
path on `lo`, so `tc` rules applied there are largely ignored. Accurate shaping
requires a veth pair, which is what `setup_network_namespace.sh` creates. This
is why several scripts exist in both a loopback and a veth variant.

**The `varying` scenario was repaired during the documentation pass.**
Previously its rate updates addressed qdisc handles from a superseded layout
(`parent 10:`, `handle 20:`) and never referenced the root TBF at `1:`, so the
link held a fixed 20 Mbps for the whole run while reporting ±40% oscillation.
The failure was swallowed by exception handlers, so runs completed and produced
plausible-looking results.

Two changes fixed it:

- `_update_rate_limit` now edits the root TBF in place with
  `tc qdisc change dev <iface> root handle 1: tbf …`. In-place editing is
  required, not merely tidier: deleting a root qdisc would remove the netem
  child (delay and loss) along with it on every tick.
- The variation period was changed from 2s to **6s**, matching the Generation 2
  scenario of the same name so results from the two are directly comparable.

The link now sweeps 12 – 28 Mbps over a 6-second cycle, with a rate change every
500ms (12 steps per cycle). Confirm on a live run with:

```bash
watch -n1 'tc -s qdisc show dev veth0'
```

**Any `varying` results produced before this fix should be discarded and the
runs repeated.** No other Generation 1 scenario sets `time_varying`, so nothing
else is affected.

---

## Setup

### TLS certificates (required, one-time)

The QUIC server will not start without a certificate and key. They are
disposable localhost credentials, generated on demand rather than committed:

```bash
cd ..            # repository root
./generate_certs.sh
```

This writes `code/certs/cert.pem` and `code/certs/key.pem`. Both are ignored by
git. The container mounts the host's `code/` directory, so the certificates
generated here serve Docker runs as well as local ones.

### Container

`tc` exists only on Linux, so on macOS or Windows everything runs in a
container.

### Docker (required for real shaping)

```bash
cd QUIC_tuning_multistream

# Interactive shell with the code mounted and NET_ADMIN available
./run-bottleneck.sh

# Or pass a command straight through to the bottleneck module
./run-bottleneck.sh list
./run-bottleneck.sh validate
./run-bottleneck.sh test --scenario lossy
```

`run-container-only.sh` is a fallback for environments where the helper script
cannot install packages (restrictive proxy, VPN, offline); it drops into a bare
container and leaves setup to you.

### Verify the environment first

Run these in order inside the container. Each isolates a different layer, so a
failure tells you where the problem is:

```bash
python3 diagnose.py               # Python, tc, privileges, imports
python3 test_bottleneck_only.py   # tc setup/teardown, no QUIC involved
python3 -m wireless_bottleneck list
python3 examples/quickstart.py    # full QUIC run through a bottleneck
```

If `test_simple_bandwidth.py` shows no rate limit, the environment itself
cannot shape traffic and no amount of QUIC-level debugging will help.

### Local install (analysis only)

```bash
cd code
uv sync          # or: pip install -e .
```

---

## Running the grid search

```bash
cd code

# Check what will run
uv run main.py status
uv run main.py run --dry-run

# Execute the sweep (hours; safe to interrupt and re-run)
uv run main.py run

# Analyse
uv run main.py analyze

# Generate the report — NOT automatic after `run`
uv run main.py report -o output/summary_report.txt

# Deep dive on one application type
uv run main.py report --app-type file_transfer -o output/file_transfer.txt

# Start over (destructive)
uv run main.py clear -f
```

The report step must be run explicitly; finishing the sweep does not update
`output/summary_report.txt` on its own.

### Resumability

If the process crashes or is interrupted, just run `uv run main.py run` again.
Completed simulations are detected by their existing CSV files, and only the
remainder execute.

### CLI reference

| Command | Purpose |
|---|---|
| `run` | Execute the sweep (`--dry-run` to preview) |
| `status` | Show progress and the parameter space |
| `analyze` | Print the optimal configuration per application type |
| `report` | Render a text report (`--app-type`, `-o`) |
| `clear` | Delete all result CSVs (`-f` skips confirmation) |

Global: `--output-dir` (default `output/measurements`).

---

## Output

```
code/output/
├── measurements/
│   └── <app_type>_<initial_cw>_<max_ack_delay>_<loss_factor>.csv
└── summary_report.txt
```

Example: `video_streaming_12000_0.025_0.5.csv`

The filename encodes the full parameter combination. That is load-bearing
rather than cosmetic — it is what makes the sweep resumable and what
`results/analyzer.py` parses to recover each run's parameters.

---

## Directory contents

```
QUIC_tuning_multistream/
├── code/
│   ├── main.py                      CLI entry point
│   ├── config/                      settings and parameter definitions
│   ├── synthesizers/                three application traffic models
│   ├── simulation/                  QUIC client, server, run orchestration
│   ├── metrics/                     collect → calculate → export
│   ├── grid_search/                 parameter space, scheduler, executor
│   ├── results/                     analysis and reporting
│   ├── wireless_bottleneck/         Linux tc emulation (module README inside)
│   ├── examples/                    four runnable demonstrations
│   ├── diagnose.py                  environment diagnostic
│   ├── test_*.py                    standalone diagnostics (not a pytest suite)
│   ├── setup_network_namespace.sh   creates the veth pair for real shaping
│   ├── setup_namespace_bottleneck.py
│   ├── certs/                       self-signed TLS certificates
│   └── output/                      measurements and reports
├── docs/                            requirements history (v0 → v3), prompts
├── reports/                         written findings
├── QUICKSTART_GUIDE.md              step-by-step macOS walkthrough
├── Dockerfile                       Linux image with tc and aioquic
├── run-bottleneck.sh                container launcher (preferred)
└── run-container-only.sh            bare-container fallback
```

Note that the `test_*.py` files are standalone diagnostic scripts despite their
prefix; this project has no automated test suite.

---

## Requirements

- Python 3.10+ (3.12 in the container image)
- [uv](https://github.com/astral-sh/uv) package manager
- Docker Desktop, for any run that needs real network shaping
- Linux with `iproute2`, provided by the container

Python dependencies: `aioquic >= 1.0.0`, `cryptography >= 41.0.0`,
`pandas >= 2.0.0`.

---

## Further reading

- [`QUICKSTART_GUIDE.md`](QUICKSTART_GUIDE.md) — step-by-step macOS walkthrough
- [`code/quick_start.md`](code/quick_start.md) — grid search workflow
- [`code/high_level_view.md`](code/high_level_view.md) — architecture notes
- [`code/wireless_bottleneck/README.md`](code/wireless_bottleneck/README.md) — network emulation module
- [`reports/`](reports/) — parameter, RTT/latency and synthetic-data findings
- [`docs/`](docs/) — how the requirements evolved across four revisions
