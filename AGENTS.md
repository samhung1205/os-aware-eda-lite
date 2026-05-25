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
- `schedulers.py`: implements `layerwise`, `greedy`, and `dp` fusion schedulers.
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
- OS-aware total cost

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
experiments/eda_lite/runtime_os_profiles.example.json
```

Purpose:

- `mobilevit_sram_sweep.json`: single-profile SRAM/scheduler/OS-profile sweep.
- `mobilevit_profile_sweep.json`: MobileViT-XXS vs MobileViT-S simplified profile comparison.
- `mobilevit_runtime_aware_sweep.json`: EDA-Lite sweep using OS profiles from an external JSON file.
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

- `analyze_runtime.py`: analyzes ROS2 runtime CSVs, infers dropped frames from `frame_id` gaps when explicit dropped rows are absent, and generates runtime summary CSVs/SVG figures.
- `build_os_profiles.py`: converts ROS2 runtime summary CSVs into EDA-Lite OS profile JSON, including latency, deadline miss, memory pressure, and drop pressure.

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

The scripts assume an external ROS2 MobileViT/UAV workspace and do not download, vendor, or verify that pipeline.

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

After real ROS2 data exists, update `experiments/eda_lite/mobilevit_runtime_aware_sweep.json` so `os_profile_file` points to the generated `runtime_os_profiles.json`.

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
```

## ROS2 Runtime CSV Contract

Recommended logger columns:

```text
scenario,model_name,input_fps,qos_depth,fake_delay_ms,resource_profile,
frame_id,published_at_ns,received_at_ns,completed_at_ns,
latency_ms,inference_ms,deadline_miss,dropped,cpu_percent,memory_mb
```

Notes:

- `latency_ms` may be provided directly.
- If `latency_ms` is absent, the analyzer can derive latency from `published_at_ns` and `completed_at_ns`.
- If explicit dropped rows are absent, the analyzer can infer dropped frames from gaps in monotonically increasing `frame_id`.
- `deadline_miss` may be provided directly.
- If `deadline_miss` is absent or false and `deadline_ms` exists, analyzer can infer deadline misses from latency.
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
os_aware_total_cost =
    estimated_energy
  + alpha * estimated_latency
  + beta  * deadline_miss_penalty
  + gamma * memory_pressure_penalty
  + delta * communication_drop_penalty
```

Built-in OS profiles:

- `normal`
- `high_latency`
- `high_memory_pressure`

Custom OS profiles can be provided through `os_profile_file`.

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
- Only call ROS2 data "measured" after it comes from actual ROS2 experiment CSVs.
- YOLO-related content is currently paused; do not frame the project as a YOLO project unless the user explicitly resumes that direction.

## Current Deliverables Present In Repo

Implemented:

- EDA-Lite simulator source code.
- MobileViT simplified profiles and profile sweep configs.
- Generic edge CNN and YOLO-related prior profiles, not current mainline.
- EDA-Lite CSV outputs and SVG figure generation.
- ROS2 experiment script templates with MobileViT defaults.
- ROS2 runtime CSV analyzer with frame-gap drop inference.
- ROS2 runtime summary to EDA-Lite OS profile converter.
- Unit tests.
- README.
- AI interaction log.

Still not implemented / not present:

- Actual ROS2 runtime measurements.
- Vendored ROS2 MobileViT/UAV pipeline source.
- Real model weights.
- ONNX parser.
- Real LLM inference or KV-cache simulation.
- Final report.
- Final presentation slides.

## Suggested Next Steps

Prioritize in this order unless the user redirects:

1. Draft report methodology and limitations based on MobileViT simplified simulation and ROS2 runtime-analysis pipeline.
2. Once an external ROS2 workspace is available, run FPS/QoS/overload experiments and save raw CSVs under `results/raw/ros2/`.
3. Convert real ROS2 summaries to `runtime_os_profiles.json`.
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
- Prefer Python standard library unless the user approves new dependencies.
- Keep all experiment parameters in JSON config or shell-script environment variables.
- Save generated tabular outputs as CSV.
- Generate plots from scripts as SVG.
- Update `README.md` whenever commands, file paths, or project scope changes.
- Update `report/ai_interaction_log.md` for major AI-assisted decisions or direction changes.
- Run `python3 -m unittest discover -s tests` after code changes.
- For ROS2 shell scripts, use `bash -n` for syntax checks when editing scripts.
