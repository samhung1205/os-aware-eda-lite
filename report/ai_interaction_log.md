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
