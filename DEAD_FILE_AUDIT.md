# Dead File Audit

Files identified during the documentation pass as unused, unreferenced,
redundant, or otherwise unnecessary to the project.

**Nothing has been deleted.** This is a report for review. Items are grouped by
confidence, with the highest-confidence removals first.

Counts are as of the audit. `git ls-files | git check-ignore --no-index --stdin`
reported **337 tracked files that the repository's own `.gitignore` says should
not be tracked** (333 after the TLS keys were untracked) — they were committed before those rules were added, and
`.gitignore` does not retroactively untrack anything.

---

## Priority 0 — Committed TLS private keys  *(RESOLVED — see note)*

```
QUIC_3conn_implementation/3_conn_code/certs/cert.pem
QUIC_3conn_implementation/3_conn_code/certs/key.pem
QUIC_tuning_multistream/code/certs/cert.pem
QUIC_tuning_multistream/code/certs/key.pem
```

`.gitignore` lines 53-56 already excluded `**/certs/*.pem`, but these four files
were committed before those rules existed and remained tracked. `.gitignore`
does not retroactively untrack anything.

**Assessed exposure (low).** Both are self-signed `CN=localhost` RSA-2048 pairs
generated for the test harness — Jan 2026 for Generation 1, Feb 2026 for
Generation 2. The GitHub repository is **private with zero forks**, so the keys
were never publicly exposed. They authenticate nothing beyond a loopback QUIC
server in this testbed.

**What was done.**

1. Both key pairs were **regenerated**, so the previously committed material is
   now worthless even where it survives in history.
2. All four files were untracked with `git rm --cached`; the working copies
   remain on disk and are now correctly ignored.
3. `generate_certs.sh` was added at the repository root to produce them on
   demand, and the setup step is documented in all three READMEs.
4. Key files are written with `chmod 600`.

**Remaining.** The superseded keys still exist in git history — 9 commits for
Generation 2, 11 for Generation 1 — and on three remote branches (`main`,
`add-q-learn`, `copilot/quic-research-docker-setup`). Because they have been
rotated and the repository has never been public, this is cosmetic rather than a
live risk. Purging them entirely requires a history rewrite and a force-push,
which is a separate decision (it invalidates existing clones).

---

## Priority 1 — Certainly unnecessary

### 1. Compiled Python bytecode (98 tracked files)

All `__pycache__/*.pyc` files across 20 directories. Build artifacts, already
covered by `.gitignore` lines 21–23, machine- and version-specific, and
regenerated automatically.

### 2. Orphaned `code/` directory — 23 files, no source

```
QUIC_3conn_implementation/code/
├── config/__pycache__/*.pyc
├── grid_search/__pycache__/*.pyc
├── metrics/__pycache__/*.pyc
├── results/__pycache__/*.pyc
├── simulation/__pycache__/*.pyc
└── synthesizers/__pycache__/*.pyc
```

This directory contains **only** compiled bytecode — 23 `.pyc` files and not a
single `.py`. The module names match Generation 1's package layout, so it
appears to be the residue of an early copy of `QUIC_tuning_multistream/code`
whose sources were later removed while the bytecode was committed.

Nothing imports it and it cannot be imported meaningfully. Safe to delete
entirely.

### 3. macOS metadata (2 files)

```
.DS_Store
QUIC_3conn_implementation/.DS_Store
```

Already covered by `.gitignore` lines 46–47.

### 4. Editor configuration (1 file)

```
QUIC_3conn_implementation/3_conn_code/.vscode/settings.json
```

Personal editor state, already covered by `.gitignore` line 49.

---

## Priority 2 — Committed run outputs (223 tracked files)

Experimental output committed to version control, all matching `.gitignore`
lines 2–14.

| Location | Files | Contents |
|---|---|---|
| `QUIC_tuning_multistream/code/output/measurements/` | 193 | Grid search result CSVs |
| `QUIC_tuning_multistream/code/output/` | 1 | `summary_report.txt` |
| `QUIC_3conn_implementation/3_conn_code/output/` | 30 | `epoch_history_*`, `metrics_history_*`, `results_*` JSON from Feb 2026 runs |

These are dated artifacts of specific runs, not inputs to anything. The
Generation 1 CSVs are the most defensible to keep, since the resumable
scheduler treats their presence as "already measured" and they are the input to
`results/analyzer.py` — but for a portfolio repository, a small representative
sample plus the generated report would demonstrate the same thing at a fraction
of the noise.

**Note:** deleting the Generation 1 CSVs resets grid search progress, since
completion is tracked purely by file existence. That is intended behaviour, not
a side effect to be surprised by.

---

## Priority 3 — Unused source modules

Reachable by import but never actually used. Each has been documented in place
with a "Status: not used on the active code path" note rather than removed.

| File | Why it is unused |
|---|---|
| `QUIC_3conn_implementation/3_conn_code/simulation/client.py` | `QuicClient` / `ClientProtocol` are exported by `simulation/__init__.py` but never constructed. Worker processes call `aioquic.asyncio.connect()` directly, because each must apply its own congestion-control globals before connecting. |
| `QUIC_3conn_implementation/3_conn_code/simulation/buffer_manager.py` | `SendBuffer` / `BufferManager` are referenced only within the file itself. Workers write straight to aioquic, and the dashboard's buffer display is fed by `BUFFER_STATE` IPC messages instead. |
| `QUIC_3conn_implementation/3_conn_code/metrics/exporter.py` | `MetricsExporter` is exported by `metrics/__init__.py` but has no caller. All files a run produces are written by `simulation/result.py`. |

`client.py` retains some value as a simpler standalone client example; the other
two are genuinely superseded.

### Dead code inside live files (not for deletion, but worth knowing)

- `wireless_bottleneck/bottleneck.py` (**both** copies) — `_setup_qdisc`,
  `_setup_netem` and `_setup_rate_limit` are an earlier qdisc arrangement no
  longer called by `setup()`. `_setup_qdisc` is marked `DEPRECATED` in its own
  docstring. They are the only readers of the RED/CoDel/PIE tuning fields on
  `BottleneckConfig`, so those settings currently have no effect.
- `QUIC_tuning_multistream/code/wireless_bottleneck/bottleneck.py` —
  **(FIXED)** `_update_rate_limit` addressed qdisc handles (`parent 10:`,
  `handle 20:`) from the superseded layout rather than the root TBF at `1:`,
  so the qdisc enforcing the scenario's stated capacity was never modified and
  the `varying` scenario ran at a fixed rate while reporting oscillation. The
  failure was swallowed by exception handlers. It now uses
  `tc qdisc change … root handle 1: tbf …` to edit the root TBF in place, and
  the variation period was aligned to Generation 2's 6 seconds. **Any
  `varying` results generated before this fix should be discarded.** Only this
  one scenario sets `time_varying=True`, so nothing else was affected.
- `simulation/process_orchestrator.py` line ~793 — `client_to_server_map` is
  computed and never read; the two comments beside it record that it was
  already recognised as unnecessary.

---

## Priority 4 — Redundant and superseded documentation

### Exact duplicates

```
QUIC_tuning_multistream/docs/olds/requirements_v0.md
QUIC_tuning_multistream/docs/olds/requirements_v1.md
```

These two files are byte-identical. One can go.

### Near-duplicates across locations

```
QUIC_3conn_implementation/final_reports_old/WIRELESS_BOTTLENECK_GUIDE.md
QUIC_3conn_implementation/3_conn_code/old_reports/WIRELESS_BOTTLENECK_GUIDE.md
```

Two versions of the same guide in different directories (they differ, so one is
an older revision). Both are additionally superseded by
`wireless_bottleneck/README.md`.

### Explicitly superseded directories

| Directory | Files | Assessment |
|---|---|---|
| `QUIC_3conn_implementation/final_reports_old/` | 18 | Named "old" by the authors. Contains eight overlapping documents on the same throughput-measurement question (`FINAL_THROUGHPUT_CALCULATION.md`, `new_throughput_info2.md`, `new_throughput_implementation_plan.md`, `Alternative_throughput_measurements.md`, `per_conn_network_throughput.md`, `Receiver-side_throughput_measurement.md`, `RS_measurement_implementation_plan.md`, `throughput_measurements_REPORT.md`) — an iterative working record rather than a finished result. |
| `QUIC_3conn_implementation/3_conn_code/old_reports/` | 4 | Named "old". Two are implementation *plans* for work now complete. |
| `QUIC_tuning_multistream/docs/olds/` | 11 | Named "olds". Four superseded requirements revisions (v0, v1, v2, plus an unversioned `requirements.md`) and five raw prompt files (`prompt.txt`, `prompt2.txt`, `prompt3.txt`, `prompt3.md`, `prompt3_0.md`). |

The prompt files in particular are development scaffolding rather than project
documentation, and read oddly in a portfolio context.

### Work-in-progress notes at top level

```
QUIC_3conn_implementation/fairness_function_changes.md   (329 lines)
```

A change log for one function, sitting at the top level of the project where it
is the first thing a browser sees after the README. Its content is now largely
reflected in the reward-function documentation in
`ml_callbacks/q_learning_agent.py`. Belongs in a reports directory if kept.

### Stray binary

```
QUIC_3conn_implementation/final_reports_old/Screenshot 2026-03-31 at 8.35.37 PM.png
```

An undated-in-name screenshot referenced by nothing, in a directory already
marked old.

### Documentation worth keeping

For balance — these are referenced from the READMEs and contain findings rather
than working notes:

- `QUIC_3conn_implementation/final_reports_may/` (6 files) — most recent analysis
- `QUIC_3conn_implementation/3_conn_code/final_reports_3conn/` (7 files)
- `QUIC_3conn_implementation/grid_search_code/final_reports_grid/` (6 files) — the optimal-parameter analysis that feeds the agents' tuning ranges
- `QUIC_tuning_multistream/reports/` (7 files) — Generation 1 findings
- `QUIC_tuning_multistream/docs/requirements_v3.md` — the current requirements

---

## Priority 5 — `.gitignore` defects

Two rules are broader than intended and will cause problems for future
contributors, independently of the tracked-file situation above.

| Line | Rule | Unintended match |
|---|---|---|
| 4 | `**/results/` | Matches the **source package** `QUIC_tuning_multistream/code/results/` (`analyzer.py`, `report_generator.py`, `__init__.py`). Those files are already tracked so they survive, but any *new* file added to that package would be silently ignored. |
| 18 | `**/reports/` | Matches `QUIC_tuning_multistream/reports/`, which holds hand-written findings, not generated output. |
| 14 | `**/*.csv` | Blanket rule. Fine for run outputs, but would also ignore any CSV added deliberately as fixture or reference data. |

**Recommendation:** anchor the output rules to their actual locations
(`code/output/`, `3_conn_code/output/`, `/results/`) rather than using `**/`
wildcards that collide with source and documentation directories.

---

## Summary

| Category | Files | Confidence |
|---|---|---|
| TLS private keys | 4 | **Resolved** — rotated and untracked |
| Compiled bytecode (`__pycache__`) | 98 | Certain |
| Orphaned `QUIC_3conn_implementation/code/` | 23 | Certain |
| macOS / editor metadata | 3 | Certain |
| Committed run outputs | 223 | High — consider keeping a sample |
| Unused source modules | 3 | High — documented in place |
| Duplicate / superseded docs | ~35 | Medium — judgement call |

Removing the certain and high-confidence items would take the repository from
roughly 480 tracked files to under 150, without touching anything the project
actually runs on.

The three unused source modules have been annotated in place rather than
removed, so the information survives regardless of what is deleted.
