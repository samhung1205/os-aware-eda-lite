# AGENTS.md

## Current Project Context

This repository is for an Operating Systems final project inspired by:

`EDA: Energy-Efficient Inter-Layer Model Compilation for Edge DNN Inference Acceleration`

The project does **not** attempt to fully reproduce the original EDA compiler. Full reproduction would require tensor splitting, graph rewriting, memory planning, code generation, NPU scheduling, and hardware simulation, which is outside this project scope.

Current implemented project:

```text
OS-aware EDA-Lite for lightweight MobileViT + ROS2 runtime pressure analysis.
```

Preferred project description:

```text
An EDA-inspired lightweight simulator for OS-level edge AI performance analysis.
```

Current main workflow:

```text
MobileViT simplified profile simulation -> ROS2 runtime CSV analysis -> runtime-derived OS pressure profiles -> runtime-aware EDA-Lite comparison.
```

LLM material from `跨平台輕量化模型效能分析與模擬.pdf` is background motivation only for the current implementation. Do not add real LLM inference, long-context KV-cache simulation, or LLM report claims unless the user explicitly expands scope.

YOLO-related files exist from earlier iterations, but YOLO is paused and is **not** the main project path. Do not add new YOLO-specific implementation, commands, report claims, or experiment steps unless the user explicitly changes direction again.

## Current Implemented State

### 1. EDA-Lite Simulator

Implemented under:

```text
src/eda_lite/
```

Main modules:

- `model_loader.py`: loads simplified JSON model profiles.
- `cost_model.py`: estimates SRAM, DRAM traffic, energy, latency, and OS-aware total cost.
- `schedulers.py`: implements `layerwise`, `greedy`, `dp`, and `exhaustive` fusion schedulers. `dp` exactly minimises the reported whole-schedule `os_aware_total_cost` (Pareto-label DP); `exhaustive` is the 2^(n-1) oracle (n <= 20) used to verify it. Greedy only stops scanning at a non-fusible layer (SRAM feasibility is not monotone). No feasible schedule raises `InfeasibleScheduleError`.
- `plot_6lines.py`: pure vs one OS-aware profile six-line charts; profiles are CLI arguments (no hard-coded selection).
- `run_simulation.py`: runs one model profile against one experiment config.
- `run_profile_sweep.py`: runs multiple model profiles from one sweep config.
- `analyze_results.py`: summarizes simulation CSVs and generates SVG figures.

Supported model profile fields:

```text
model_name
layers[]
  name
  op_type
  input_kb
  output_kb
  weight_kb
  compute_macs
  fusible
```

Supported simulator outputs:

- selected subgraphs
- DRAM traffic estimate
- energy estimate
- latency estimate
- peak SRAM usage
- max fusion depth
- OS-aware total cost and its terms (`latency_cost`, `deadline_cost`, `memory_pressure_cost`, `communication_pressure_cost`, `effective_latency_ms`)
- `feasible` / `infeasible_reason` per row (an infeasible scheduler no longer aborts a sweep) and the row's `deadline_ms`

### 2. Main MobileViT Profiles

Current main profiles:

```text
data/model_profiles/mobilevit_xxs_simplified.json
data/model_profiles/mobilevit_s_simplified.json
```

These are simplified, coarse MobileViT block profiles for simulation and reporting. They are not ONNX-derived exact model structures.

Legacy optional profiles:

```text
data/model_profiles/edge_cnn_simplified.json
data/model_profiles/edge_cnn_large_simplified.json
data/model_profiles/yolo11n_simplified.json
data/model_profiles/yolo11s_simplified.json
```

Treat edge CNN as prior generic baseline work and YOLO as paused prior work, not the current default path.

### 3. EDA-Lite Experiment Configs

Main configs:

```text
experiments/eda_lite/mobilevit_sram_sweep.json
experiments/eda_lite/mobilevit_profile_sweep.json
experiments/eda_lite/mobilevit_runtime_aware_sweep.json
experiments/eda_lite/mobilevit_sensitivity_sweep.json
experiments/eda_lite/mobilevit_runtime_aware_sweep_legacy_unverified.json
experiments/eda_lite/runtime_os_profiles.example.json
experiments/eda_lite/runtime_os_profiles.legacy_unverified.json
```

Purpose:

- `mobilevit_sram_sweep.json`: single-profile SRAM/scheduler/OS-profile sweep.
- `mobilevit_profile_sweep.json`: MobileViT-XXS vs MobileViT-S simplified profile comparison.
- `mobilevit_runtime_aware_sweep.json`: EDA-Lite sweep using OS profiles from an external JSON file. Default: `runtime_os_profiles.example.json` (rows `os_profile_provenance=example`). Point it at `runtime_os_profiles.json` only after that file is `verified`.
- `mobilevit_runtime_aware_sweep_legacy_unverified.json`: runs the teammate-provided profiles with `allow_unverified_os_profiles: true`; rows are `unverified`, figures titled `[OS profile: UNVERIFIED]`.
- `runtime_os_profiles.legacy_unverified.json`: the 22 teammate-provided `measured_*` profiles (values unchanged, metadata added). No raw CSVs, summary or run metadata exist for them and they use the legacy cross-model calibration, so they are **UNVERIFIED**, never measured evidence.
- `mobilevit_sensitivity_sweep.json`: SRAM (128–2048 KB) x simulation deadline (top-level `deadline_ms` list) x built-in profiles, all four schedulers including `exhaustive`.
- `runtime_os_profiles.example.json`: example runtime-derived OS pressure profile file. It is not measured data.

Legacy configs:

```text
experiments/eda_lite/sram_sweep.json
experiments/eda_lite/edge_profile_sweep.json
experiments/eda_lite/edge_cnn_runtime_aware_sweep.json
experiments/eda_lite/yolo11_profile_sweep.json
```

### 4. ROS2 Runtime Analysis

Generic runtime tools are under:

```text
src/ros2_runtime/
```

Main modules:

- `analyze_runtime.py`: analyzes ROS2 runtime CSVs per configuration and `run_id`, rejects mixed runs, infers dropped frames from `frame_id` gaps when explicit dropped rows are absent, and generates runtime summary CSVs/SVG figures.
- `build_os_profiles.py`: converts ROS2 runtime summary CSVs into EDA-Lite OS profile JSON, including latency, deadline miss, memory pressure, and drop pressure. Latency is normalised per model against that model's idle run (same resource profile); memory against a verifiable limit (CLI, cgroup `memory.max`, or host RAM — never max RSS). Writes `metadata` (baselines, per-profile model/run, source hashes, `provenance_status`).
- `run_metadata.py`: writes `<run_id>.meta.json` per run (git commit, OS/kernel, CPU, Python/torch, ROS 2/RMW, QoS, `net.core.*`, requested vs effective limits, `measurement_class`, experiment parameters, parsed Fast DDS profile, `process.nice`). Never changes system settings.
- `runtime_probe.py` (Phase 2 / Batch 2): `<run_id>.probe.json` from the launch scope — UDP sockets and Fast DDS `/dev/shm` segment sizes of both nodes (runtime proof the SHM-only XML was applied), per-node CPU/RSS/affinity/nice, cgroup memory, host load, SMT-sibling busy time. The sweep scripts fail a run whose probe does not confirm an SHM-only profile.
- `aggregate_baseline.py` (Phase 2 / Batch 2): per-run table + per-condition mean/SD/min/max across runs (run = replicate), capacity / utilization / expected overload drop / `drop_cause`, SVG figures, SHA-256 manifest.
- `aggregate_scheduling.py` (Phase 3 / Batch 1): scheduling runs → per-run table (arm / block / position from meta.json, probe fields, `on_time_fps`), per-arm across-run stats, within-block paired differences vs a reference arm (default `legacy_q1`), SHA-256 manifest. Batch 2 flags: `--by-scenario` (dynamic runs never pair with fixed-rate ones), repeatable `--reference-arm`, `--paired-stats` (SD, 95 % t-interval, sign counts, exact sign-flip p), `effective_miss_excl_tail_pct`.
- `analyze_dynamic_phases.py` (Phase 3 / Batch 2): per-phase and step-transient outcomes of `fps_schedule` runs, across-run and paired tables. `plot_scheduling.py`: stdlib SVG figures of the formal benchmark. `host_load_gate.py`: waits until CPU_SET + SMT siblings and loadavg are quiet before a block (exit 4 if not).

Provenance helpers: `src/provenance.py` (SHA-256 records, summary manifest, OS profile status, simulation `.provenance.json` sidecars). `scripts/check_runtime_provenance.py` verifies raw → summary → profiles → simulation: exit 0 VERIFIED (current state, Phase 2 / Batch 2), 1 BLOCKED (link missing), 2 BROKEN (hash mismatch / stale). `scripts/check_phase3_provenance.py` (Phase 3 / Batch 2) is the independent gate for `results/raw/ros2_phase3_formal/`: `git.dirty=false`, one commit with runtime code unchanged to HEAD, 25 identical controls, DDS probe, complete blocks, summary + aggregate manifests (VERIFIED for the 102 formal runs; the Batch 1 pilot is BROKEN by design: dirty tree). Both gates run in `ci_checks.sh provenance`.

Legacy compatibility path:

```text
src/ros2_yolo11/
```

This path exists from earlier work and should only re-export generic runtime analysis behavior.

### 5. ROS2 Experiment Script Templates

Implemented under:

```text
experiments/ros2/
```

Current main scripts:

- `run_fps_sweep.sh`
- `run_qos_sweep.sh`
- `run_overload_sweep.sh`

Paused / optional older script:

- `run_yolo11_comparison.sh`

The scripts launch the checked-in pipeline `src/ros2_uav_pipeline/` by default (or an installed package with `ROS2_LAUNCH_TARGET=""`). Phase 2 / Batch 1 ran a smoke test (data outside `results/`); Phase 2 / Batch 2 ran the formal constrained baseline (75 runs under `results/raw/ros2/`, provenance `VERIFIED`); see `report/PHASE2_BATCH2_RESULT.md`. Baseline settings: `CPU_SET=12,14 MEMORY_MAX=4G MEMORY_SWAP_MAX=0 NICE_LEVEL=10 ROS_DOMAIN_ID=87 RMW_IMPLEMENTATION=rmw_fastrtps_cpp FASTRTPS_DEFAULT_PROFILES_FILE=experiments/ros2/fastdds_shm_large.xml`, 60 s runs, warm-up 10, deadline 100 ms.

Pipeline semantics (Phase 1 / Batch 4, audit P2-6):

- The detector builds `timm.create_model(model_name, pretrained=False)` via `run_log.create_model_strict`: random weights, latency only, no accuracy. A failed model load ends the run; it never falls back to another model.
- There is no `model_path`: the launch file raises if it is passed, and the sweep scripts exit 2 if `MODEL_PATH` is set.
- QoS: publisher RELIABLE depth 10 (fixed), detector BEST_EFFORT KEEP_LAST `qos_depth`; QoS sweeps vary only the subscriber depth.
- `jitter_ms` = population std dev of per-frame end-to-end latency (not inter-arrival jitter); P95/P99 are nearest-rank.
- Start-up (Phase 2 / Batch 1): the detector subscribes after the model and CSV are ready; the publisher starts frame 0 (and its log) only once a subscriber is matched. Float parameters (`input_fps`, `deadline_ms`) use `dynamic_typing` so `input_fps:=5` works.
- DDS transport: on the Phase 2 server the RMW default transports lose 50–85% of the ~1 MB best-effort frames (rmem_max 212992). `experiments/ros2/fastdds_shm_large.xml` (Fast DDS SHM-only, 16 MB segment) delivers all frames (verified lossless up to 50 FPS in Batch 2); set `FASTRTPS_DEFAULT_PROFILES_FILE` to it. `<run_id>.meta.json` records it under `dds_profile` (path + SHA-256 + parsed); `<run_id>.probe.json` verifies at run time that it was applied. Do not mix transport settings within one comparison.
- Overload queue semantics (Batch 2 finding): under overload the single-threaded detector always serves the oldest of the `qos_depth` frames kept by KEEP_LAST, so queue wait ≈ `qos_depth / input_fps` and drop rate ≈ `1 - 1/ρ` (ρ = input_fps × service time) independent of depth.
- Scheduling (Phase 3 / Batch 1, `src/ros2_uav_pipeline/mobilevit_uav_pipeline/scheduling.py`, stdlib, unit-tested without ROS): detector `scheduler_policy` = `legacy_qos` (default; unchanged Phase 2 path, inference in the subscription callback, DDS KEEP_LAST is the only queue) or `fifo` / `latest_frame` / `adaptive` / `deadline_guard` (Batch 2 ablation: adaptive without the utilisation switch, always the newest feasible frame) (ingestion callback → bounded application queue → exactly one inference worker thread; main thread only spins the executor). Exact semantics in the module docstring. Every frame that reaches the app queue gets exactly one CSV row (processed / `drop_reason` / `shutdown_pending` / `shutdown_inflight`); a worker exception ends the run (exit 1 → `*.failed`). DDS queue ≠ application queue: legacy drops are `dds_unreceived_frames`, app drops are `app_policy_dropped_frames`.
- `intra_op_threads` (torch + OpenCV, default 0 = library defaults): with the node's imports, OpenMP work on the main thread runs on ~1 core while a worker thread gets 2 (torch ~35 % faster) and a busy-spinning OpenCV helper. Comparisons across arms must use one value (the sched sweep uses 1 for every arm, matching the effective Batch 2 behaviour). Phase 2 runs used the default.
- Dynamic input (Phase 3 / Batch 2): publisher parameter `fps_schedule` = `"<fps>@<s>,..."` from frame 0 (`@`, not `:` — ROS 2 YAML-parses `10:20` as 620); empty = fixed `input_fps`. `run_sched_sweep.sh` `FPS_SCHEDULE` → `scenario=sched_dynamic`. Formal driver `experiments/ros2/run_sched_formal.sh` (clean tree + load gate before every block). Formal data was measured from a detached worktree at the measurement commit so that editing the checkout cannot make runs dirty.
- Wrappers: `MODELS` / `SWEEPS` narrow a batch (`SWEEPS=sched` runs `experiments/ros2/run_sched_sweep.sh`; `experiments/ros2/run_sched_pilot.sh` is the interleaved pilot driver); `MEMORY_SWAP_MAX` (default 0) adds `MemorySwapMax` because the host has swap; `memory.swap.max` is recorded (informational). Choose `CPU_SET` from the allowed, idle CPUs (Phase 2 server: i7-13700, P-cores 0–15, E-cores 16–23; smoke test used 12,14), never assume `0,1`.

### 6. CI, Environment And Repository Hygiene (Phase 1 / Batch 4)

- `.github/workflows/ci.yml`: tests on Python 3.10–3.13 (nothing installed), `bash -n`, `scripts/audit_repro.py --strict`, provenance gate, 5× repeated test runs. Every step is `bash scripts/ci_checks.sh <step>`; `bash scripts/ci_checks.sh all` reproduces CI locally. CI installs no ROS 2; the gate reports `BLOCKED` as a warning and must never turn it into `VERIFIED`.
- Dependencies: `requirements-sim.txt` (stdlib only, empty), `requirements-ros2.txt` (pinned torch/torchvision/timm/numpy/psutil for the ROS 2 nodes), `environment.yml` (RoboStack Humble, Python 3.10, conda `opencv`), `requirements.txt` → `-r requirements-ros2.txt`. Solved and imported on the Phase 2 server; frozen in `environment.lock.yml` (pip shows `torch 2.5.1+cpu`).
- Results policy (`results/README.md`, `.gitignore`): raw `results/raw/ros2/*.{csv,publisher.csv,meta.json}` tracked; derived `results/csv/*.csv` tracked with their `.provenance.json` / `.manifest.json`; figures tracked; `*.failed`, caches, `.DS_Store`, `~$*`, `ci-logs/` ignored.
- `load_model_profile` validates finite numbers, unique layer names and `output_kb[i] == input_kb[i+1]`.
- Tests that run CLIs use `tests/cli_support.run_cli` (full stdout/stderr on failure).

## Main Commands

Use `python3`, not `python`, unless the environment clearly provides `python`.

### Run Single-Profile MobileViT EDA-Lite Sweep

```bash
python3 -m src.eda_lite.run_simulation \
  --profile data/model_profiles/mobilevit_xxs_simplified.json \
  --config experiments/eda_lite/mobilevit_sram_sweep.json \
  --output results/csv/eda_lite_mobilevit_xxs_sram_sweep.csv
```

### Run MobileViT Profile Sweep

```bash
python3 -m src.eda_lite.run_profile_sweep \
  --config experiments/eda_lite/mobilevit_profile_sweep.json \
  --output results/csv/eda_lite_mobilevit_profile_sweep.csv
```

### Analyze MobileViT EDA-Lite Results

```bash
python3 -m src.eda_lite.analyze_results \
  --input results/csv/eda_lite_mobilevit_profile_sweep.csv \
  --summary-output results/csv/eda_lite_mobilevit_profile_summary.csv \
  --figures-dir results/figures/mobilevit_s \
  --plot-os-profile normal \
  --plot-model mobilevit_s_simplified_profile_estimate
```

When a CSV contains multiple models, always pass `--plot-model`.

### Analyze ROS2 Runtime CSVs

```bash
python3 -m src.ros2_runtime.analyze_runtime \
  --input results/raw/ros2 \
  --summary-output results/csv/ros2_runtime_summary.csv \
  --figures-dir results/figures/ros2
```

### Convert Runtime Summary To EDA-Lite OS Profiles

```bash
python3 -m src.ros2_runtime.build_os_profiles \
  --input results/csv/ros2_runtime_summary.csv \
  --output experiments/eda_lite/runtime_os_profiles.json \
  --profile-prefix measured
```

Add `--require-verified` to refuse writing anything that does not verify back to raw CSVs + run metadata. After real ROS2 data exists and `python3 scripts/check_runtime_provenance.py` reports `VERIFIED`, update `experiments/eda_lite/mobilevit_runtime_aware_sweep.json` so `os_profile_file` points to the generated `runtime_os_profiles.json`.

### Run Runtime-Aware MobileViT EDA-Lite Sweep

```bash
python3 -m src.eda_lite.run_simulation \
  --profile data/model_profiles/mobilevit_xxs_simplified.json \
  --config experiments/eda_lite/mobilevit_runtime_aware_sweep.json \
  --output results/csv/eda_lite_mobilevit_runtime_aware_sweep.csv
```

### Run Tests

```bash
python3 -m unittest discover -s tests
bash scripts/ci_checks.sh all        # same checks as GitHub Actions
python3 scripts/audit_repro.py --strict
```

## ROS2 Runtime CSV Contract

Recommended logger columns:

```text
run_id,scenario,model_name,input_fps,qos_depth,fake_delay_ms,resource_profile,
deadline_ms,frame_id,warmup,published_at_ns,received_at_ns,completed_at_ns,
latency_ms,transport_ms,preprocess_ms,artificial_delay_ms,inference_ms,
deadline_miss,dropped,cpu_percent,memory_mb
```

Publisher log (`<run_id>.publisher.csv`, one row per published frame):

```text
run_id,frame_id,published_at_ns
```

Notes:

- `latency_ms` may be provided directly.
- If `latency_ms` is absent, the analyzer can derive latency from `published_at_ns` and `completed_at_ns`.
- If explicit dropped rows are absent, the analyzer can infer dropped frames from gaps in monotonically increasing `frame_id`.
- `deadline_miss` may be provided directly.
- If `deadline_miss` is absent or false and `deadline_ms` exists, analyzer can infer deadline misses from latency.
- `run_id` identifies one detector launch. Each run writes its own CSV (`$RESULTS_DIR/<run_id>.csv`); the detector and sweep scripts never append to or overwrite an existing CSV.
- The analyzer summarises each `(configuration, run_id)` separately and raises an error instead of de-duplicating when a `frame_id` repeats within a run, a `run_id` spans several configurations, or a legacy CSV (no `run_id`) contains appended runs. Legacy CSVs are one run per file (`run_id = legacy:<csv path>`).
- Deadline: a processed frame misses iff `latency_ms > deadline_ms`; dropped frames are never misses; `deadline_miss_rate_pct` = misses / processed frames; `effective_miss_rate_pct` = (misses + dropped) / total frames.
- Drops: frames in the window never processed; the window is the publisher log when present (`frame_accounting=publisher_log`), else the observed `frame_id` range (lower bound). Unknown drops stay empty, never 0%.
- Timing: cross-process stamps use the host wall clock; stage durations (`preprocess_ms`, `artificial_delay_ms`, `inference_ms`) use `perf_counter`. `inference_ms` excludes the injected delay in current CSVs (`timing_schema=v2`).
- Warm-up rows (`warmup=1`, detector `warmup_frames`, analyzer `--warmup-frames`) are excluded from statistics.
- The launch file shuts down when either node exits; scripts treat any non-timeout end as failure and rename its CSVs to `*.failed`.
- Run conditions: `<run_id>.meta.json` next to each CSV; the summary carries `measurement_class` (`constrained` / `unconstrained` / `constraint_unverified` / `constraint_failed` / `unknown`), `memory_limit_mb`, `host_memory_mb`. Requested limits that are not read back make the run fail (unless `ALLOW_UNVERIFIED_LIMITS=1`); wrappers without `taskset`/`systemd-run` label runs `unconstrained`, never `normal`. Scripts never run `sudo`; the tuned wrapper only checks `net.core.rmem_max`.
- The analyzer writes `<summary stem>.manifest.json` with SHA-256 of the summary and every raw input.
- ROS2 CSVs are runtime measurements only if they were generated by an actual ROS2 run.
- Test, example, or synthetic CSVs must not be reported as measured results.

Runtime summary metrics include:

- total rows / inferred total frames
- processed frames
- dropped frames
- drop rate
- deadline misses
- deadline miss rate
- average latency
- P95/P99 latency
- jitter
- average inference time
- average CPU usage
- average memory usage

## OS-Aware Cost Model

EDA-Lite uses a lightweight cost model:

```text
L_eff = latency_multiplier * L
os_aware_total_cost =
    E
  + alpha * L_eff
  + beta  * deadline_miss_rate * max(0, L_eff - deadline_ms)
  + gamma * memory_pressure * max_subgraph_peak_sram / sram_kb
  + delta * drop_rate * L
```

`E` and `L` are sums over subgraphs; the deadline hinge and peak SRAM are whole-schedule terms. The `dp`/`exhaustive` objective is this exact function. Cost-model weights must be non-negative.

Deadline semantics: EDA-Lite `deadline_ms` is a budget for **simulated** latency (cost-model units); the ROS2 `deadline_ms` is a wall-clock end-to-end budget. They are linked only through the dimensionless `deadline_miss_rate` and `latency_multiplier`; do not copy the runtime deadline value into the simulation.

Built-in OS profiles:

- `pure` (latency multiplier 1.0, no deadline/memory/drop pressure; the compiler-only baseline — never call `normal` "pure")
- `normal`
- `high_latency`
- `high_memory_pressure`

Summaries report scheduler ties as `greedy=dp` (never as a greedy win), and leave reductions empty when the `layerwise` baseline is missing or infeasible (`baseline_status`). On the MobileViT coarse profiles OS profiles change the reported cost but not the chosen partition; do not claim otherwise without new evidence.

Custom OS profiles can be provided through `os_profile_file`. Each simulation row records `os_profile_provenance` (`builtin` / `inline` / `example` / `verified` / `unverified`). Unverified files are refused unless the config sets `"allow_unverified_os_profiles": true`. Model-specific runtime profiles only apply to the model profile with the matching `runtime_model_name` (MobileViT profiles declare `mobilevit_xxs` / `mobilevit_s`); mixing models is an error.

Expected OS profile JSON shape:

```json
{
  "os_profiles": ["measured_example"],
  "os_profile_definitions": {
    "measured_example": {
      "latency_multiplier": 1.0,
      "deadline_miss_rate": 0.02,
      "memory_pressure": 0.45,
      "drop_rate": 0.03
    }
  }
}
```

`drop_rate` is optional for backward compatibility and defaults to `0.0`.

## Reporting Rules

When writing reports, slides, captions, or experiment discussion:

- Frame the current implementation as MobileViT + ROS2 OS-level simulation and analysis.
- Use LLM material only as background motivation unless real LLM tooling is added later.
- Clearly separate measured ROS2 runtime results from EDA-Lite simulation estimates.
- Label EDA-Lite energy and latency as estimates or simulation outputs.
- Do not present estimated energy as real hardware energy.
- Do not claim this project fully reproduces the original EDA compiler.
- Explain the simplified memory, energy, MobileViT block, and communication-drop assumptions.
- Explain that MobileViT profiles are coarse simulation profiles, not exact ONNX model structures.
- If using `runtime_os_profiles.example.json`, state that it is an example profile, not measured data.
- Only call ROS2 data "measured" after it comes from actual ROS2 experiment CSVs and `scripts/check_runtime_provenance.py` reports `VERIFIED`.
- `runtime_os_profiles.legacy_unverified.json`, `results/figures/ros2/*.svg` and anything derived from them are UNVERIFIED teammate-provided artifacts; label them so.
- Only call a run "constrained" when its metadata says `measurement_class=constrained`.
- YOLO-related content is currently paused; do not frame the project as a YOLO project unless the user explicitly resumes that direction.

## Current Deliverables Present In Repo

Implemented:

- EDA-Lite simulator source code.
- MobileViT simplified profiles and profile sweep configs.
- Generic edge CNN and YOLO-related prior profiles, not current mainline.
- EDA-Lite CSV outputs and SVG figure generation.
- ROS2 experiment script templates with MobileViT defaults.
- ROS2 runtime CSV analyzer with frame-gap drop inference.
- ROS2 runtime summary to EDA-Lite OS profile converter (per-model calibration, provenance metadata).
- Run metadata capture, provenance manifests/sidecars and `scripts/check_runtime_provenance.py`.
- Unit tests (stdlib only) and GitHub Actions CI (`.github/workflows/ci.yml`, `scripts/ci_checks.sh`).
- Split dependency files (`requirements-sim.txt`, `requirements-ros2.txt`, `environment.yml`).
- `results/README.md` tracking policy and provenance status.
- README.
- AI interaction log.
- Phase 4 dashboard (`dashboard/`, static, offline) built by `src/dashboard/build_data.py` from the Phase 2 baseline and Phase 3 formal tables only; `--check` in CI; `scripts/check_table_regeneration.py` rebuilds the tables from raw runs; preview via `bash scripts/serve_dashboard.sh` (127.0.0.1 only). `report/PHASE4_RESULT.md`.

Still not implemented / not present:

- EDA-Lite runtime-aware sweep re-run with the verified `runtime_os_profiles.json` (Batch 2 generated the file; `mobilevit_runtime_aware_sweep.json` still points at the example file).
- Real model weights (the detector uses random-init timm weights; latency only).
- Runtime-aware EDA-Lite scheduling (EDA-Lite schedules offline; OS profiles only re-weight the cost; the ROS 2 frame scheduler is separate and does not feed EDA-Lite).
- ONNX parser.
- Real LLM inference or KV-cache simulation.
- Final presentation slides.

(`src/ros2_uav_pipeline/` and a draft `report/final_report.md` are present.)

## Suggested Next Steps

Prioritize in this order unless the user redirects:

1. Draft report methodology and limitations based on MobileViT simplified simulation and ROS2 runtime-analysis pipeline.
2. (Done in Phase 2 / Batch 2) formal FPS/QoS/overload baseline under `results/raw/ros2/`, verified `runtime_os_profiles.json`, provenance `VERIFIED`.
3. Phase 3: Batch 1 (policies + pilot) and Batch 2 (formal A/B, 102 runs, `report/PHASE3_BATCH2_RESULT.md`) done. Finding: deadline feasibility dropping beats Latest-Frame only when inter-arrival + service > deadline; Deadline-Guard = Adaptive (the utilisation switch adds nothing measurable). Phase 4 dashboard done (`report/PHASE4_RESULT.md`); it reports the guard as the effective mechanism.
4. Re-run `mobilevit_runtime_aware_sweep.json` with real runtime-derived OS profiles.
5. Generate final figures and write results discussion.

Avoid these unless explicitly requested:

- Adding new YOLO implementation.
- Downloading YOLO weights.
- Claiming ONNX/operator-accurate modeling.
- Claiming measured ROS2 runtime without real CSVs.
- Claiming hardware-accurate energy measurement.
- Adding real LLM serving or Android/ONNXim execution paths.

## Coding And Maintenance Rules

- Keep implementation deterministic and easy to explain.
- Prefer Python standard library unless the user approves new dependencies. The simulator, analysis, provenance tools and tests must stay stdlib-only (a test enforces it); ROS 2 node dependencies go in the pinned `requirements-ros2.txt`.
- Keep all experiment parameters in JSON config or shell-script environment variables.
- Save generated tabular outputs as CSV.
- Generate plots from scripts as SVG.
- Update `README.md` whenever commands, file paths, or project scope changes (detailed manual: `docs/REFERENCE.md`).
- After changing any formal table or the dashboard builder, run `python3 -m src.dashboard.build_data` and commit `dashboard/data/` (CI fails on a STALE bundle). Never add pilot / legacy-unverified / example inputs to the builder; it rejects them.
- Update `report/ai_interaction_log.md` for major AI-assisted decisions or direction changes.
- Run `python3 -m unittest discover -s tests` (or `bash scripts/ci_checks.sh all`) after code changes.
- Never commit `__pycache__`, `.pyc`, `.DS_Store` or Office lock files; follow `results/README.md` for what results to commit.
- For ROS2 shell scripts, use `bash -n` for syntax checks when editing scripts.
