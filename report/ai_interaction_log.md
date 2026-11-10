# AI Interaction Log

## 2026-05-23

Prompt summary:

- Read `AGENTS.md` and start the OS-aware EDA-Lite final project from an empty folder.
- Plan first, avoid unnecessary work, and implement the first phase only after the plan was approved.

Implementation decision:

- Start with the standalone Python EDA-Lite simulator.
- Avoid ROS2 setup, YOLO weight downloads, ONNX parsing, plotting, and external dependencies in v1.
- Use a documented simplified YOLO11n-style layer profile for simulation estimates.

Important limitation:

- EDA-Lite energy and latency values are estimates from a lightweight cost model, not real hardware measurements.

## 2026-05-25

Prompt summary:

- Continue the next implementation stage after the initial EDA-Lite simulator and README were checked.

Implementation decision:

- Add a second simplified profile, `yolo11s_simplified.json`, to compare a larger YOLO11-style workload against `yolo11n_simplified.json`.
- Add a multi-profile sweep CLI so model comparison can be reproduced from one config file.
- Update the analysis CLI to require `--plot-model` when plotting multi-model CSVs, preventing misleading figures that mix different model profiles.

Important limitation:

- YOLO11n and YOLO11s profiles are coarse estimates for simulation only. They are not extracted from full YOLO11 ONNX graphs and should not be reported as exact architecture measurements.

## 2026-05-25 ROS2 Runtime Stage

Prompt summary:

- Continue to the next stage after multi-profile EDA-Lite simulation was checked.

Implementation decision:

- Add ROS2 experiment shell scripts for FPS sweep, QoS depth sweep, artificial overload sweep, and YOLO11 model comparison.
- Keep ROS2 integration external and parameterized instead of downloading or vendoring the TA sample repository.
- Define a CSV logging contract for runtime measurements.
- Add a standard-library runtime analyzer that summarizes latency, P95/P99 latency, jitter, deadline misses, frame drops, CPU usage, and memory usage.

Important limitation:

- The repository now contains ROS2 experiment wrappers and analyzers, but it still does not contain real ROS2 measurements. Any runtime CSV must come from an actual ROS2 experiment run before being reported as measured data.

## 2026-05-25 Direction Change: Pause YOLO

Prompt summary:

- Continue to the next stage, but pause YOLO-related execution because the project plan changed and YOLO is no longer expected to be used.

Implementation decision:

- Add generic `edge_cnn_simplified` and `edge_cnn_large_simplified` profiles as the main non-YOLO model simulation path.
- Add runtime-derived OS profile support so EDA-Lite can use ROS2 runtime summary data through `os_profile_file`.
- Add a converter from ROS2 runtime summary CSV to EDA-Lite OS pressure profile JSON.
- Keep existing YOLO files as optional prior work, but remove them from the main README workflow.

Important limitation:

- `runtime_os_profiles.example.json` is an example pressure profile file, not measured data. Real runtime-aware simulation should regenerate the OS profile file from actual ROS2 summary CSV.

## 2026-05-25 Direction Change: MobileViT + ROS2 Mainline

Prompt summary:

- Integrate the teammate-provided MobileViT/UAV ROS2 direction with the current working EDA-Lite repository.
- Keep this repository as the main base, avoid vendoring unverified ROS2 nodes, and pivot the main project narrative to lightweight MobileViT plus ROS2 OS-level performance simulation.

Implementation decision:

- Add coarse MobileViT-XXS and MobileViT-S simplified model profiles for EDA-Lite simulation.
- Add MobileViT SRAM/profile/runtime-aware sweep configs.
- Move the generic ROS2 runtime analyzer implementation into `src/ros2_runtime/` and leave `src/ros2_yolo11/` as a legacy compatibility wrapper.
- Extend runtime analysis to infer dropped frames from `frame_id` gaps when explicit dropped rows are absent.
- Extend runtime-derived OS profiles and the OS-aware cost model with optional `drop_rate` communication pressure.
- Update ROS2 script defaults and documentation to use external MobileViT/UAV pipeline names instead of YOLO defaults.

Important limitation:

- MobileViT profiles are coarse simulation profiles, not ONNX-derived exact architectures.
- `runtime_os_profiles.example.json` remains example data only.
- No teammate ROS2 numbers should be reported as measured in this repo until real ROS2 CSVs are present under `results/raw/ros2/`.

## 2026-05-26 Final Report Planning Stage

Prompt summary:

- Complete the project step by step with the main topic confirmed as Vision Transformer / MobileViT.
- Avoid YOLO experiments in the mainline.
- Use a small image-folder dataset such as COCO128 only as ROS2 runtime input.

Implementation decision:

- Add `report/final_report.md` as the Markdown final report draft.
- Add `report/ros2_pipeline_integration.md` to define the teammate ROS2 pipeline files, launch arguments, and CSV contract needed before reporting measured runtime results.
- Add `experiments/ros2/prepare_coco128.sh` to prepare COCO128 under `data/raw/images/`.
- Update ROS2 script defaults to use `data/raw/images/coco128/images/train2017` as the image-folder dataset path.
- Ignore raw image data and downloaded COCO128 zip in git.

Important limitation:

- The local machine currently has no `ros2` command and this repo still has no measured ROS2 CSVs.
- COCO128 is an image stream input source only, not a YOLO experiment.

## 2026-05-31 ROS2 Pipeline Sync Review

Prompt summary:

- Review teammate-pushed ROS2 updates and continue the next stage.

Implementation decision:

- Update tests so `mobilevit_runtime_aware_sweep.json` can use the checked-in 22-profile `runtime_os_profiles.json`.
- Harden ROS2 node parameter handling by reading typed parameter `.value` fields instead of integer-only values for float launch arguments.
- Add Python dependency metadata for the ROS2 MobileViT pipeline.
- Allow ROS2 scripts to use either a direct checked-in launch file path through `ROS2_LAUNCH_TARGET` or an installed package launch through `ROS2_PACKAGE`/`ROS2_LAUNCH_FILE`.
- Add `report/runtime_result_provenance.md` to separate checked-in runtime-derived artifacts from missing raw ROS2 CSVs.

Important limitation:

- `runtime_os_profiles.json` contains `measured_*` profiles, but raw ROS2 CSVs and `ros2_runtime_summary.csv` are not currently checked in, so final reporting must mention that provenance gap.

## 2026-06-01 Local Reproduction Step

Prompt summary:

- Continue the next stage step by step, including dataset preparation, ROS2 runtime execution, runtime profile regeneration, and EDA-Lite figure rebuild.

Implementation decision:

- Download and extract COCO128 locally through `experiments/ros2/prepare_coco128.sh`; the dataset remains ignored by git.
- Add preflight checks to ROS2 sweep scripts so missing `ros2` or missing `timeout`/`gtimeout` fails explicitly instead of being hidden by `|| true`.
- Make baseline and OS-tuned wrapper scripts fall back when Linux-only `taskset` and `systemd-run` are unavailable.
- Keep OS-tuned UDP buffer adjustment Linux/sudo-only and skip it in unsupported environments.
- Rebuild MobileViT pure and runtime-aware EDA-Lite CSVs and figures through `scripts/rebuild_eda_lite_figures.sh`.

Important limitation:

- The local machine is macOS and does not currently provide `ros2`, `taskset`, or `systemd-run`. ROS2 raw CSV generation remains blocked until running in a ROS2-capable Linux/RoboStack environment or after installing and activating a working ROS2 stack.
- `results/raw/ros2/` still has no raw CSVs, and `results/csv/ros2_runtime_summary.csv` is still absent.

## 2026-11-09 Correctness / Reproducibility Audit

Prompt summary:

- Start moving the MobileViT + ROS2 project toward a reproducible Edge AI Runtime & Scheduling Benchmark. This stage is audit-only: no architecture rewrite, no UI.

Implementation decision:

- Add `report/audit_p0_p1_p2.md` with P0/P1/P2 findings, affected files, reproduction steps, and minimal fix suggestions.
- Add read-only `scripts/audit_repro.py` that reproduces each auto-checkable finding and prints `REPRODUCED` or `FIXED`.
- No existing source, config, or result file was modified.

Key findings:

- DP minimises a per-subgraph surrogate, not the reported `os_aware_total_cost` (memory term uses max vs sum; deadline hinge is per-subgraph vs total). Latent on current configs, reproducible on a toy case.
- Detector CSV is opened in append mode and `frame_id` restarts per run; re-runs merge and hide drops.
- `measured_*` OS profiles used by the main runtime-aware sweep cannot be rebuilt from the repo; the tracked runtime-aware CSV is stale.
- On current configs the deadline term is always zero and no OS profile changes any schedule; DP and greedy produce identical partitions.

## 2026-11-10 Phase 1 / PR-A1: ROS2 Experiment Data Integrity

Prompt summary:

- Fix audit item P0-2 so different ROS2 runs can never contaminate each other, with minimal changes on a separate branch and regression tests.

Implementation decision:

- One detector launch = one run = one CSV. Add a `run_id` (launch/node argument, default `auto`) as the first CSV column, and create the CSV exclusively so an existing file is never appended to or overwritten. The helpers live in a stdlib-only `run_log.py` so they can be unit-tested without ROS2.
- Sweep scripts build a unique `run_id` from the sweep parameters, `RESOURCE_PROFILE`, and `RUN_TAG` (default `<timestamp>_<pid>`), use it as the CSV file name, and refuse to start if the file already exists.
- The runtime analyzer groups by configuration plus `run_id`, adds a `run_id` summary column, and raises instead of silently de-duplicating when runs cannot be separated. Legacy CSVs without `run_id` remain supported as one run per file and are rejected if they contain appended runs.

Important limitation:

- Not exercised against a real ROS2 runtime in this environment; the detector change is covered by helper tests, and the scripts are covered with fake `ros2`/`timeout` executables.

## 2026-11-10 Phase 1 / Batch 1: ROS2 Measurement Correctness

Prompt summary:

- Fix audit items P1-4 (deadline), P1-5 (frame-drop accounting and grouping keys), P1-6 (timing and warm-up), plus launch reliability, on top of PR-A1, with minimal changes and no fabricated measurements.

Implementation decision:

- Checkpoint-commit PR-A1 (`a40816d`) before this batch, leaving the user's `plot_6lines.py` change uncommitted.
- Detector logs `deadline_ms`, `warmup`, `transport_ms`, `preprocess_ms`, `artificial_delay_ms` and a model-only `inference_ms`. Cross-process stamps use the host wall clock; stage durations use `perf_counter`. Unparseable frame ids stay empty and failed image conversions are logged as explicit drops instead of running inference on random input.
- Publisher writes `<run_id>.publisher.csv` (one row per published frame); the launch file resolves `run_id` once for both nodes and shuts down when either node exits.
- Sweep scripts treat only a timed end (exit 124) with data rows as success; failed runs stop the sweep and are renamed to `*.failed`.
- Analyzer: one deadline definition (`latency_ms > deadline_ms`, processed frames only), set-union drop accounting over the publisher-log window, `frame_accounting` completeness flag with empty values instead of 0% when unknown, normalised numeric grouping keys, warm-up exclusion, and appended summary columns for stage timings.
- `build_os_profiles` refuses a present-but-empty `drop_rate_pct` instead of assuming 0%.

Important limitation:

- Still not exercised on a real ROS2 runtime; node and launch behaviour is covered by stdlib helper tests, stubbed launch modules, and fake `ros2`/`timeout` executables. The EDA-Lite deadline/cost model is unchanged (next batch).

## 2026-11-10 Phase 1 / Batch 2: Scheduling & Cost Model Correctness

Prompt summary:

- Fix audit P0-1 (DP objective), P1-1/P1-2 (greedy pruning, sweep robustness), P1-3 (pure profile, ties, hard-coded profile selection, sensitivity), and the EDA-Lite side of P1-4 (deadline semantics), keeping the architecture and without fabricating improvements.

Implementation decision:

- Checkpoint-commit Batch 1 (`54667ab`) first, excluding the user's `plot_6lines.py`, SVGs, `.DS_Store`, and Office lock file.
- `dp` now minimises the reported whole-schedule cost exactly with a Pareto-label prefix DP over (additive cost, total latency, max peak), dropping coordinates whose weight is zero; the tie-break preference is part of dominance so `dp` returns the same partition as the new `exhaustive` oracle. Chosen over always delegating to exhaustive search because it stays exact without an n <= 20 limit; chosen over changing the reported cost to a per-subgraph sum because a per-subgraph memory penalty is semantically wrong.
- Deadline penalty uses `latency_multiplier * L`. The ROS2 wall-clock deadline is not copied into the simulation (units differ); the link stays the dimensionless miss rate and multiplier.
- Greedy stops scanning only at non-fusible layers. Infeasible schedulers produce `feasible=false` rows; configuration errors still abort.
- Summary reports ties (`greedy=dp`) and baseline status. Built-in `pure` profile. Six-line plot profiles moved to CLI/env vars (edited on top of the user's uncommitted `SIX_LINE_METRICS` change, which is preserved).

Important limitation:

- On the MobileViT coarse profiles no OS profile or deadline changes a schedule; only SRAM feasibility does. This is reported as-is. Runtime-aware costs with measured `latency_multiplier` up to 30.2 are dominated by the deadline term, which inherits P1-7 (cross-model normalisation) and P0-3 (unverifiable measured profiles).

## 2026-11-10 Phase 1 / Batch 3: Experiment Provenance & OS Profile Calibration

Prompt summary:

- Fix audit P0-3 (provenance), P1-7 (OS profile calibration) and P1-8 (run reproducibility) with minimal changes, without fabricating measurements or forcing the provenance check to pass.

Implementation decision:

- Checkpoint-commit Batch 2 (`9eb6341`) first. `plot_6lines.py` was staged as a Batch-2-only blob (the user's `SIX_LINE_METRICS` hunk removed in the index) so the user's change stays uncommitted in the working tree; the staged snapshot passed the tests on its own.
- Hash chain instead of a single `MANIFEST.sha256`: the analyzer writes `<summary>.manifest.json` (raw CSV / publisher log / run metadata hashes), `build_os_profiles` records the summary + manifest hashes and a `provenance_status`, every simulation CSV gets a `.provenance.json` sidecar. `check_runtime_provenance.py` distinguishes VERIFIED / BLOCKED / BROKEN.
- The 22 teammate-provided profiles are kept value-for-value but moved to `runtime_os_profiles.legacy_unverified.json` and marked `unverified`; `runtime_os_profiles.json` is reserved for verified pipeline output. The default runtime-aware config points back to the example profiles; a separate legacy config opts in to unverified data and every row/figure says so.
- Calibration per model and resource profile against the comparable idle run (not the global minimum); memory pressure against a verifiable limit (CLI, cgroup `memory.max`, host RAM) instead of max RSS. Model-specific profiles only apply to the matching `runtime_model_name`.
- Run metadata is captured by a stdlib module inside the same taskset/systemd-run scope as the launch; requested and effective limits are recorded separately and a run is `constrained` only if every requested limit is read back. Scripts never call `sudo`; the tuned wrapper only checks `rmem_max`.

Important limitation:

- No raw ROS2 data exists, so P0-3 is BLOCKED (mechanism verified only with synthetic temp data in tests) and the legacy profiles cannot be recalibrated. P1-8's cgroup/affinity read-back is unit-tested with a fake `/proc` and cgroup tree but has not run on Linux with ROS 2.

## 2026-11-10 Phase 1 / Batch 4: Engineering Quality & Reproducibility

Prompt summary:

- Close audit P2-1 … P2-6 (CI, dependencies, repo hygiene, documentation, test gaps, remaining pipeline details) as the last Phase 1 batch, without dashboards, adaptive scheduling, new models, heavy frameworks, or changes to the verified DP / greedy logic.

Implementation decision:

- Checkpoint-commit Batch 3 (`64a844f`) first, again staging a Batch-3-only `plot_6lines.py` blob so the user's `SIX_LINE_METRICS` hunk stays uncommitted; `.DS_Store` and the user's SVGs were not committed.
- CI is a thin GitHub Actions wrapper around `scripts/ci_checks.sh`, so the exact CI steps run locally. No ROS 2 and no pip install in CI: the suite is stdlib-only (enforced by a test). The provenance gate keeps `BLOCKED` as a warning and fails a `VERIFIED` status that has no raw data behind it. A repeat job runs the suite 5× without retries.
- The Batch 3 intermittent error appeared once more during this batch (124 tests, 1 error, output not captured) and could not be reproduced in ~145 further runs (sequential, concurrent clones, working tree + clone). Instead of guessing, every subprocess-based test now fails with the child's full stdout/stderr (`tests/cli_support.run_cli`), CI keeps verbose logs, and the repeat job surfaces recurrences.
- Dependencies split into an empty stdlib `requirements-sim.txt`, pinned `requirements-ros2.txt`, and a RoboStack `environment.yml` (ros-base instead of desktop; conda `opencv` instead of pip `opencv-python`, so `cv_bridge` and `cv2` match).
- Pipeline (P2-6): `create_model_strict` replaces the silent `mobilevit_xxs` fallback; the unused `model_path` is removed and rejected (launch and scripts) rather than wired to a checkpoint loader, because random-init weights are sufficient for latency and loading weights would be new functionality. Model profiles validate the `output_kb → input_kb` chain, unique names and finite numbers. QoS / jitter / percentile / random-weight semantics are documented, not changed.
- Hygiene: 18 tracked caches / `.DS_Store` untracked (`git rm --cached`, files kept on disk); `.gitignore` encodes one results policy (raw and derived CSVs tracked with their sidecars; failed runs, caches, lock files ignored), documented in `results/README.md`.

Important limitation:

- Pinned ROS 2 versions and `environment.yml` were not solved or run (no Linux / ROS 2 here). GitHub Actions has not run yet (nothing pushed); the workflow was validated by YAML parsing and by running `scripts/ci_checks.sh all` locally on macOS / Python 3.11 and the test suite on a bare Python 3.13 venv. Real measurements remain BLOCKED.

## 2026-11-10 Phase 2 / Batch 1: Linux ROS 2 Environment & Smoke Validation

Prompt summary:

- On the shared lab Linux server: build the RoboStack / PyTorch environment in an isolated conda env, verify CPU / memory constraints without sudo, run a short real ROS 2 + MobileViT-XXS smoke test (unconstrained, then constrained), keep smoke data out of `results/`, no full sweep, no push / merge.

Implementation decision:

- `environment.yml` solved unchanged; froze it in `environment.lock.yml` (prefix removed, channel order and the PyTorch CPU index restored so it is recreatable).
- Constraints: taskset (CPUs 12,14 = two idle P-cores; the CPU is hybrid) + `systemd-run --user --scope` MemoryMax (memory controller delegated; `cpu`/`cpuset` are not). Added `MemorySwapMax` (default 0) because the host has swap, and record `memory.swap.max`.
- The real run exposed a startup crash (`input_fps:=5` is INTEGER, declared DOUBLE) → `dynamic_typing` on float parameters.
- Diagnosed a 50–85% frame loss as DDS transport (RMW defaults with 212992-byte socket buffers and ~1 MB best-effort images; CycloneDDS/UDP showed kernel RcvbufErrors) by A/B runs instead of changing sysctls; added an opt-in Fast DDS SHM profile (recorded with SHA-256 in run metadata) rather than silently changing the default transport — the choice for formal baselines is left to the user.
- Publisher now starts after a subscriber is matched and the detector subscribes after loading the model (clean publisher log; analyzer already excluded pre-warm-up frames).

Important limitation:

- Smoke data only (5 FPS, 20 s, XXS); not measured evidence, not committed under `results/`. Provenance stays BLOCKED. MobileViT-S and higher FPS untested.

