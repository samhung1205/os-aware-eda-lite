# OS-aware EDA-Lite

Lightweight MobileViT simulation for ROS2 OS-level edge AI performance analysis.

本專案是作業系統期末專題實作。目標不是完整重現 EDA compiler，而是建立一個可解釋、可重現的 EDA-inspired 輕量化 simulator，用來觀察 SRAM 限制、layer fusion 策略、ROS2 runtime pressure 與 DDS/掉幀壓力如何影響 edge AI 推論的估計成本。

目前主線是 **MobileViT simplified profile simulation + ROS2 runtime pressure analysis**。LLM 內容作為背景動機；本 repo 目前不執行真實 LLM inference。YOLO 相關路徑保留為早期 legacy work，不作為主流程。

## Status at a glance

| Data / result kind | Where | Status today |
|---|---|---|
| **Simulation estimates** (EDA-Lite energy, latency, DRAM traffic, SRAM, cost) | `results/csv/eda_lite_*`, `results/figures/eda_lite/` | reproducible from configs; cost-model units, **not** hardware measurements |
| **Example OS profiles** | `experiments/eda_lite/runtime_os_profiles.example.json` | illustrative values, rows labelled `example`; never report as measured |
| **Unverified legacy measurements** | `runtime_os_profiles.legacy_unverified.json`, `results/figures/ros2/*.svg`, anything derived from them | teammate-provided, no raw data → **UNVERIFIED**; refused unless a config opts in; figures tagged `[OS profile: UNVERIFIED]` |
| **Verified ROS 2 measurements** | `results/raw/ros2/` → `results/csv/ros2_runtime_summary.csv` → `runtime_os_profiles.json`; baseline tables `results/csv/ros2_baseline_{runs,conditions}.csv`, figures `results/figures/ros2_baseline/` | **Phase 2 / Batch 2 baseline**: 75 constrained runs (CPU 12,14 / 4G / swap 0, Fast DDS SHM profile verified at run time); `check_runtime_provenance.py` reports `VERIFIED` |

Phase 2 / Batch 2 ran the formal ROS 2 baseline (MobileViT-XXS / S × FPS 5–30, QoS depth 1/5/10, overload delay 0–150 ms, 3 runs each, plus an XXS 40/50/60 FPS capacity extension); see `report/PHASE2_BATCH2_RESULT.md`. The EDA-Lite runtime-aware sweep is **not** yet re-run with the measured profiles; OS profiles only re-weight the offline EDA-Lite cost model (on the MobileViT profiles they do not change the chosen partition).

Phase 3 / Batch 1 added **runtime frame scheduling in the ROS 2 detector** (`fifo`, `latest_frame`, `adaptive`; legacy QoS-depth behaviour kept as `legacy_qos`) and ran a short interleaved pilot (`results/raw/ros2_phase3_pilot/`, not part of the Phase 2 provenance chain); see `report/PHASE3_BATCH1_RESULT.md`. The pilot is preliminary evidence, not the formal A/B benchmark.

## Quickstart (simulator, analysis and tests — nothing to install)

Python 3.10 – 3.13, standard library only (`requirements-sim.txt` is intentionally empty):

```bash
python3 -m unittest discover -s tests                     # all tests (ROS 2 parts are mocked)
python3 -m src.eda_lite.run_profile_sweep \
  --config experiments/eda_lite/mobilevit_profile_sweep.json \
  --output /tmp/eda_lite_mobilevit_profile_sweep.csv      # simulation estimates + .provenance.json
python3 scripts/check_runtime_provenance.py               # exit 1 = BLOCKED (no real ROS 2 data yet)
bash scripts/ci_checks.sh all                             # exactly what GitHub Actions runs
```

The ROS 2 benchmark (Linux + ROS 2 Humble) is a separate workflow; see [ROS2 Runtime Experiments](#ros2-runtime-experiments) and `report/PHASE1_BATCH4_RESULT.md` (Phase 2 preflight checklist).

## Project Scope

目前已完成：

- 讀取簡化模型 profile JSON。
- 支援 MobileViT-XXS 與 MobileViT-S 的 coarse block simulation profiles。
- 支援單一模型與多模型 profile sweep。
- 支援四種排程策略：
  - `layerwise`：每層獨立執行。
  - `greedy`：由左到右，每次取「可行的最長」融合區段（SRAM 可行性非單調，只有遇到 non-fusible layer 才停止掃描）。
  - `dp`：精確最小化 reported `os_aware_total_cost`（整個 schedule 的成本，含 max peak SRAM 與總 latency 的 deadline hinge）的 contiguous partition；以 Pareto label DP 實作，並以 exhaustive oracle 驗證。
  - `exhaustive`：窮舉全部 `2^(n-1)` 個 partition 的 oracle（最多 20 層），用於驗證 `dp`。
- 某個 scheduler 在給定 SRAM 下沒有可行解時，sweep 不會中止，而是輸出 `feasible=false` 的列（數值欄位留空，`infeasible_reason` 說明原因）。
- 支援 SRAM sweep：主 config 為 256KB、512KB、1024KB、2048KB；sensitivity config 另含 128/192/384KB。
- 支援 OS-aware cost profile：`pure`（compiler-only baseline：latency multiplier 1.0，無 deadline/memory/drop 懲罰）、`normal`、`high_latency`、`high_memory_pressure`，以及 runtime-derived custom profiles。
- 輸出 CSV 結果，包含 DRAM traffic、estimated energy、estimated latency、peak SRAM usage、fusion depth 與 OS-aware total cost。
- 從 simulation CSV 產生 summary CSV 與 SVG 圖表。
- 提供 ROS2 FPS/QoS/overload 實驗腳本，預設啟動 repo 內的 MobileViT UAV pipeline（`src/ros2_uav_pipeline/`，尚未在實機上執行過）。
- 分析 ROS2 runtime CSV，輸出 latency、jitter、drop rate、deadline miss rate 與 SVG 圖表。
- 在 explicit dropped rows 缺席時，可由 `frame_id` 缺口推估 dropped frames。
- 將 ROS2 runtime summary 轉成 EDA-Lite 自訂 OS pressure profiles，包含 drop pressure。

目前仍不包含或尚未完整追溯：

- raw ROS2 runtime CSVs under `results/raw/ros2/`.
- `results/csv/ros2_runtime_summary.csv`.
- 真實 MobileViT 權重：ROS 2 detector 以 timm `pretrained=False`（隨機初始化）建立模型，只量測延遲，不量測準確率。
- Adaptive / runtime scheduling：EDA-Lite 是離線模擬，OS profile 只改變成本權重。
- ONNX parser。
- 真實 LLM inference 或 KV-cache simulation。
- 真實硬體 energy measurement。
- 完整 EDA paper compiler reproduction。

Current checked-in ROS2 runtime-derived artifacts are documented in:

```text
report/runtime_result_provenance.md
```

Check whether runtime artifacts are complete enough for measured-result reporting:

```bash
python3 scripts/check_runtime_provenance.py
```

It verifies the hash chain raw CSVs + run metadata → `ros2_runtime_summary.csv` (+ `.manifest.json`) → `runtime_os_profiles.json` → simulation CSVs (`*.provenance.json` sidecars). Exit 0 = `VERIFIED`, 1 = `BLOCKED` (a link is missing — currently there is **no raw ROS2 data in the repository**), 2 = `BROKEN` (a file no longer matches its recorded hash, or a sidecar is stale).

Provenance status of OS profile sources (written per simulation row as `os_profile_provenance`):

| Status | Meaning | Usable by the simulator |
|---|---|---|
| `builtin` / `inline` | `pure`, `normal`, … or profiles defined in the config | yes |
| `example` | `runtime_os_profiles.example.json`, illustrative values | yes, never report as measured |
| `verified` | built by `build_os_profiles` from a summary whose manifest verifies down to raw CSVs and run metadata | yes |
| `unverified` | anything else, e.g. `runtime_os_profiles.legacy_unverified.json` (22 teammate-provided `measured_*` profiles without raw data, legacy cross-model calibration) | only with `"allow_unverified_os_profiles": true`; figures are titled `[OS profile: UNVERIFIED]` |

## 🚀 完整端到端執行流程 (End-to-End Pipeline)

步驟 1–3 需要 Linux + ROS 2 Humble 實機（Phase 2，尚未執行）；在沒有真實 raw 資料前，步驟 4 只能使用 example 或 UNVERIFIED legacy profiles，`check_runtime_provenance.py` 會維持 `BLOCKED`。只有模擬部分（步驟 4 的 pure 曲線、Quickstart）目前可以完整重現。

### 步驟 0：環境建置 (Environment Setup)
只有 ROS 2 實機量測需要這一步（不需要 `sudo`）。建議一步建立：
```bash
conda env create -f environment.yml   # RoboStack ROS 2 Humble + Python 3.10 + requirements-ros2.txt
conda activate eda_lite
```
或沿用分步腳本（內容與 `environment.yml` 一致）：`bash scripts/setup_env.sh` 建立/重用 `eda_lite` 環境並安裝 `requirements-ros2.txt`，再執行 `bash scripts/install_ros2_conda.sh` 安裝 `ros-humble-ros-base`、`ros-humble-cv-bridge`、conda `opencv`。詳見 [Requirements](#requirements)。

### 步驟 1：執行 ROS 2 硬體壓力測試 (實機量測)
確保已設定好上述環境與 ROS 2 變數後，執行自動化總管腳本，它會要求 CPU/RAM 資源限制並連續跑完 FPS、QoS、Overload 三大測試（每個 run 產生 `<run_id>.csv`、`<run_id>.publisher.csv`、`<run_id>.meta.json`）。限制是否真的生效由每個 run 的 metadata 讀回確認，未生效的 run 會直接失敗：
```bash
bash scripts/run_baseline_experiments.sh
```

### 步驟 2：分析 ROS 2 數據與產生長條圖
將原始 CSV 進行彙整，推估系統 Jitter 與真實掉幀率，並產出視覺化長條圖：
```bash
python3 -m src.ros2_runtime.analyze_runtime \
  --input results/raw/ros2 \
  --summary-output results/csv/ros2_runtime_summary.csv \
  --figures-dir results/figures/ros2
```

### 步驟 3：轉換為 OS-Aware 懲罰特徵
將上一步的 ROS 2 掉幀與延遲數據，轉換為 EDA 模擬器看得懂的 JSON OS 懲罰設定檔：
```bash
python3 -m src.ros2_runtime.build_os_profiles \
  --input results/csv/ros2_runtime_summary.csv \
  --output experiments/eda_lite/runtime_os_profiles.json \
  --profile-prefix measured
```
*(註：輸出的 `metadata.provenance_status` 必須是 `verified`（可加 `--require-verified` 強制）；之後再把 `experiments/eda_lite/mobilevit_runtime_aware_sweep.json` 的 `os_profile_file` 改指向 `runtime_os_profiles.json`。預設仍指向 example profiles。)*

### 步驟 4：執行 EDA-Lite 模擬與產出最終 6 條線比較圖
依序執行 Pure（`pure` profile：只有 energy + 正常 latency cost，無 OS 懲罰）與 OS-Aware（一個 runtime-derived profile）的模擬，最後將它們疊加成對比圖：
```bash
bash scripts/rebuild_eda_lite_figures.sh
```
The script first runs `check_runtime_provenance.py` (stops on `BROKEN`), then rebuilds MobileViT-S and MobileViT-XXS pure simulation CSVs, runtime-aware simulation CSVs (each with a `.provenance.json` sidecar), and the final six-line comparison figures. Each model only receives OS profiles measured on that model. By default the OS profiles come from `mobilevit_runtime_aware_sweep_legacy_unverified.json` (the teammate-provided profiles, **UNVERIFIED**), so the figure titles carry `[OS profile: UNVERIFIED]`. The compared profiles and source are not hard-coded in Python; override them with environment variables:

```bash
RUNTIME_SWEEP_CONFIG=experiments/eda_lite/mobilevit_runtime_aware_sweep_legacy_unverified.json \
OS_PROFILE_S=measured_overload_sweep_mobilevit_s_20_0fps_q5_d150_normal \
OS_PROFILE_XXS=measured_overload_sweep_mobilevit_xxs_20_0fps_q5_d150_normal \
PURE_PROFILE=pure FIGURES_ROOT=results/figures/eda_lite \
bash scripts/rebuild_eda_lite_figures.sh
```

`plot_6lines` can also be run directly: `python3 -m src.eda_lite.plot_6lines --model <model_name> --pure-csv <csv> --os-csv <csv> --os-profile <name> [--pure-profile pure] --out-dir <dir>`. Infeasible rows are left out of the lines.

完成後，最終報告圖表將全部安穩地躺在 `results/figures/eda_lite/` 底下！

## Repository Layout
```text
.
  AGENTS.md  README.md
  requirements-sim.txt         # simulator / analysis / tests: stdlib only (empty on purpose)
  requirements-ros2.txt        # ROS 2 nodes: pinned torch / torchvision / timm / numpy / psutil
  requirements.txt             # -> requirements-ros2.txt (backward compatibility)
  environment.yml              # RoboStack ROS 2 Humble + Python 3.10
  .github/workflows/ci.yml     # tests (3.10-3.13), bash -n, audit --strict, provenance gate, repeat runs
  src/
    provenance.py              # hash chain / manifest / provenance status helpers
    eda_lite/                  # model_loader, cost_model, schedulers, run_simulation,
                               # run_profile_sweep, analyze_results, plot_6lines
    ros2_runtime/              # analyze_runtime, build_os_profiles, run_metadata
    ros2_uav_pipeline/         # ROS 2 package: image_stream_node, mobilevit_detector_node,
                               # run_log (stdlib helpers), launch/mobilevit_uav_pipeline.launch.py
    ros2_yolo11/               # legacy re-export (YOLO paused)
  data/model_profiles/         # mobilevit_{xxs,s}_simplified.json (main); edge_cnn*, yolo11* (legacy)
  experiments/
    eda_lite/                  # sweep configs; runtime_os_profiles.{example,legacy_unverified}.json
    ros2/                      # run_common.sh, run_{fps,qos,overload}_sweep.sh, prepare_coco128.sh,
                               # run_yolo11_comparison.sh (paused)
  scripts/
    ci_checks.sh               # CI steps, runnable locally
    audit_repro.py             # audit regression cases (--strict for CI)
    check_runtime_provenance.py
    rebuild_eda_lite_figures.sh
    run_baseline_experiments.sh  run_os_tuned_experiments.sh   # ROS 2 wrappers (Linux)
    setup_env.sh  install_ros2_conda.sh
  results/
    README.md                  # tracking policy + provenance status of every result
    raw/ros2/  csv/  figures/
  report/                      # final_report.md, audit_p0_p1_p2.md, PHASE1_*_RESULT.md,
                               # runtime_result_provenance.md, ros2_pipeline_integration.md,
                               # ai_interaction_log.md
  tests/                       # unittest; cli_support.py = subprocess helper with full diagnostics
```

## Requirements

| Part | Python | Dependencies | Install |
|---|---|---|---|
| EDA-Lite simulator, ROS 2 runtime **analysis** (`analyze_runtime`, `build_os_profiles`, `run_metadata`), provenance tools, tests | 3.10 – 3.13 (CI tests all four) | standard library only | nothing (`requirements-sim.txt`) |
| ROS 2 nodes (`src/ros2_uav_pipeline/`) and sweep scripts | 3.10 (RoboStack Humble) | ROS 2 Humble (`rclpy`, `launch`, `sensor_msgs`, `cv_bridge`), conda `opencv`, pinned `torch==2.5.1`, `torchvision==0.20.1`, `timm==1.0.11`, `numpy==1.26.4`, `psutil==7.0.0` | `conda env create -f environment.yml` |

- `cv2` comes from conda-forge `opencv` (the build `cv_bridge` links against); do not `pip install opencv-python` into the ROS environment. `numpy` stays `< 2` for Humble's `cv_bridge`.
- The pins solved and imported on the Phase 2 server (Ubuntu 22.04.4 x86_64, 2026-11-10; pip reports `torch 2.5.1+cpu` / `torchvision 0.20.1+cpu`, the CPU-wheel local version). The solved environment is frozen in `environment.lock.yml` (`conda env create -f environment.lock.yml`). Every run records the versions actually imported in `<run_id>.meta.json`.
- Bash and GNU `timeout` (or `gtimeout`) are needed for the sweep scripts; `taskset` + `systemd-run` (cgroup v2) for constrained runs.

## Run MobileViT Simulation

Single-profile SRAM sweep:

```bash
python3 -m src.eda_lite.run_simulation \
  --profile data/model_profiles/mobilevit_xxs_simplified.json \
  --config experiments/eda_lite/mobilevit_sram_sweep.json \
  --output results/csv/eda_lite_mobilevit_xxs_sram_sweep.csv
```

MobileViT-XXS vs MobileViT-S profile sweep:

```bash
python3 -m src.eda_lite.run_profile_sweep \
  --config experiments/eda_lite/mobilevit_profile_sweep.json \
  --output results/csv/eda_lite_mobilevit_profile_sweep.csv
```

Analyze MobileViT profile sweep:

```bash
python3 -m src.eda_lite.analyze_results \
  --input results/csv/eda_lite_mobilevit_profile_sweep.csv \
  --summary-output results/csv/eda_lite_mobilevit_profile_summary.csv \
  --figures-dir results/figures/mobilevit_s \
  --plot-os-profile normal \
  --plot-model mobilevit_s_simplified_profile_estimate
```

When a CSV contains multiple models, always pass `--plot-model`.

## ROS2 Runtime Experiments

ROS2 scripts are stored in:

```text
experiments/ros2/
```

This repository now includes a lightweight ROS2 MobileViT/UAV pipeline under `src/ros2_uav_pipeline/`. The scripts can launch the checked-in launch file directly, or use an installed ROS2 package if you set `ROS2_LAUNCH_TARGET=""`.

Common environment variables:

```bash
export ROS2_WORKSPACE="$HOME/ros2-mobilevit-uav-pipeline"
export ROS2_SETUP="$ROS2_WORKSPACE/install/setup.bash"
export ROS2_PACKAGE="mobilevit_uav_pipeline"
export ROS2_LAUNCH_FILE="mobilevit_uav_pipeline.launch.py"
export ROS2_LAUNCH_TARGET="src/ros2_uav_pipeline/launch/mobilevit_uav_pipeline.launch.py"
export DATASET_PATH="$PWD/data/raw/images/coco128/images/train2017"
export RESULTS_DIR="$PWD/results/raw/ros2"
export MODEL_NAME="mobilevit_xxs"   # timm model name; weights are random-init (no weight file)
# Optional batch tag; must be new for every batch (default: <timestamp>_<pid>).
# export RUN_TAG="20261110T120000_batch1"
```

Prepare optional COCO128 image-folder input:

```bash
bash experiments/ros2/prepare_coco128.sh
```

COCO128 is used only as a compact image stream source for ROS2 runtime pressure tests. It is not a YOLO training or evaluation experiment. Dataset documentation: https://docs.ultralytics.com/datasets/detect/coco128/

Run the main sweeps:

```bash
bash experiments/ros2/run_fps_sweep.sh
bash experiments/ros2/run_qos_sweep.sh
bash experiments/ros2/run_overload_sweep.sh
```

By default, the scripts launch the checked-in launch file through `ROS2_LAUNCH_TARGET`. To launch an installed ROS2 package instead, set `ROS2_LAUNCH_TARGET=""` and use `ROS2_PACKAGE` plus `ROS2_LAUNCH_FILE`. The sweep scripts fail early if `ros2` is not available, and require either GNU `timeout` or `gtimeout` so each scenario stops after `RUN_SECONDS` seconds.

Same-host DDS transport (Phase 2 / Batch 1 finding): the publisher sends ~0.4–1.2 MB `bgr8` frames to a BEST_EFFORT subscription. With the RMW default transports and `net.core.rmem_max = 212992`, 50–85% of frames were lost even at 5 FPS (CycloneDDS over UDP: ~99%, with kernel UDP `RcvbufErrors`). The checked-in Fast DDS profile switches to shared memory with a 16 MB segment (process-local, no sudo) and delivered 100% of frames in the smoke test:

```bash
export FASTRTPS_DEFAULT_PROFILES_FILE="$PWD/experiments/ros2/fastdds_shm_large.xml"
export ROS_DOMAIN_ID=87              # any domain no one else uses on a shared host
```

Its path, SHA-256 and parsed content (`shm_only`, segment size) are recorded in `<run_id>.meta.json` → `dds_profile`. The Phase 2 / Batch 2 baseline uses this profile; never mix it with RMW-default runs in one comparison. Setting the variable does not prove the profile was applied (Fast DDS falls back to its defaults on an XML error), so each run also writes `<run_id>.probe.json` (`src/ros2_runtime/runtime_probe.py`, read-only, same scope): UDP sockets and Fast DDS `/dev/shm` segment sizes of both nodes, per-node CPU / RSS / affinity / nice, cgroup memory, host load and SMT-sibling busy time. With an SHM-only profile a run with any UDP socket or no 16 MB segment is failed (`*.failed`); `REQUIRE_DDS_VERIFIED=0` / `RUNTIME_PROBE=0` disable this. The wrapper pins `RMW_IMPLEMENTATION=rmw_fastrtps_cpp` when a Fast DDS profile is set, runs the sweeps under `nice -n $NICE_LEVEL` (default 10, shared host), and between runs waits for the previous launch's nodes to exit.

Aggregate a baseline across independent runs (run = replicate, frames are never pooled):

```bash
python3 -m src.ros2_runtime.analyze_runtime --input results/raw/ros2 \
  --summary-output results/csv/ros2_runtime_summary.csv --warmup-frames 10
python3 -m src.ros2_runtime.aggregate_baseline --summary results/csv/ros2_runtime_summary.csv \
  --raw-dir results/raw/ros2 --runs-output results/csv/ros2_baseline_runs.csv \
  --conditions-output results/csv/ros2_baseline_conditions.csv --figures-dir results/figures/ros2_baseline
```

The summary now also carries `p50_latency_ms`, `p50/p95_transport_ms`, `p50_inference_ms`, `avg_service_ms` (preprocess + artificial delay + inference), `offered_fps` (publisher log) and `processed_fps` (completion stamps), `max_memory_mb`. The aggregate adds `capacity_fps = 1000 / avg_service_ms`, `utilization = offered_fps × avg_service_ms / 1000`, the drop rate a lossless transport would show under that utilization, and `drop_cause` (`none` / `overload` / `below_capacity`).

Run the two-model baseline wrapper:

```bash
bash scripts/run_baseline_experiments.sh
# narrower (e.g. a smoke test on the Phase 2 server, idle P-cores 12 and 14):
CPU_SET=12,14 MEMORY_MAX=4G MODELS=mobilevit_xxs SWEEPS=fps FPS_VALUES=5 RUN_SECONDS=20 \
  RESULTS_DIR=/tmp/smoke bash scripts/run_baseline_experiments.sh
```

`MODELS` (default `mobilevit_xxs mobilevit_s`) and `SWEEPS` (default `fps qos overload`) narrow a batch. Pick `CPU_SET` from the CPUs your account may use (`grep Cpus_allowed_list /proc/self/status`) and from idle cores; do not assume `0,1`. On Linux, the wrapper requests 2-core / 2GB limits with `taskset -c $CPU_SET` and `systemd-run --user --scope -p MemoryMax=$MEMORY_MAX -p MemorySwapMax=$MEMORY_SWAP_MAX` (defaults `0,1` / `2G` / `0`; swap is disabled so a host with swap cannot page the run out instead of enforcing the limit; `MEMORY_SWAP_MAX=` drops the property) and exports them as `REQUESTED_CPUS` / `REQUESTED_MEMORY_MAX`. Requesting is not the same as applying: `systemd-run --user` silently ignores `MemoryMax` without cgroup v2 memory-controller delegation. Before every launch, `run_capture_metadata` (in `experiments/ros2/run_common.sh`) runs `python3 -m src.ros2_runtime.run_metadata` inside the same scope and writes `$RESULTS_DIR/<run_id>.meta.json` with:

- run_id, git commit (+ dirty flag), OS/kernel, CPU model, logical CPUs, host RAM, Python, torch/timm/numpy/opencv/psutil versions;
- `ROS_DISTRO`, `RMW_IMPLEMENTATION` (unset = distro default), DDS transport variables (`FASTDDS_BUILTIN_TRANSPORTS`, `FASTRTPS_DEFAULT_PROFILES_FILE`, `CYCLONEDDS_URI`, `ROS_LOCALHOST_ONLY`, …), the node QoS (reliable publisher depth 10 → best-effort subscription depth `qos_depth`), and `net.core.{r,w}mem_{max,default}` as read;
- the Fast DDS XML profile in use (`dds_profile`: path + SHA-256, or none);
- requested limits, effective limits (CPU affinity, cgroup `memory.max` / `cpu.max`, informational `memory.swap.max`) and `measurement_class`: `constrained` (every requested limit read back and matching), `unconstrained` (none requested), `constraint_unverified` (could not read back, e.g. macOS / cgroup v1) or `constraint_failed` (read back and not in effect);
- the experiment parameters (scenario, model, fps, QoS depth, delay, deadline, run seconds, warm-up, dataset, launch target).

If a requested limit is not verified, the run fails before launch (`*.meta.json.failed`); `ALLOW_UNVERIFIED_LIMITS=1` lets it continue, recorded as `constraint_unverified`/`constraint_failed`, and OS profiles built from it stay `unverified`. Without `taskset`/`systemd-run` the wrappers request nothing and label the runs `resource_profile=unconstrained` (`tuned_unconstrained`), never `normal`.

`scripts/run_os_tuned_experiments.sh` never runs `sudo` or changes sysctls. It requires `net.core.rmem_max >= TARGET_RMEM_MAX` (default 4194304) to be set by you beforehand and otherwise exits with the command to run manually. A larger `rmem_max` is only a cap: DDS may not request bigger buffers, and same-host Fast DDS may use shared memory, so the buffer may not matter. The actual values and RMW/transport settings are in each run's metadata; do not assume the tuning improved DDS.

The launch file accepts `dataset_path`, `input_fps`, `qos_depth`, `model_name`, `fake_inference_delay_ms`, `deadline_ms`, `resource_profile`, `scenario`, `output_csv`, `run_id`, and `warmup_frames`. If the adapted ROS2 project uses different launch argument names, update the shell scripts.

Model semantics (audit P2-6):

- `model_name` is passed to `timm.create_model(model_name, pretrained=False)`: **random initial weights**, no checkpoint file, no download. Forward-pass latency does not depend on the weight values, but no detection accuracy is measured, and results must say so.
- If the model cannot be created, the detector exits (no CSV is written), the launch shuts down and the sweep marks the run failed. It never falls back to another model, so a CSV labelled `mobilevit_s` always contains `mobilevit_s` measurements.
- There is no `model_path`: the old argument was declared and forwarded but never read. Passing `model_path:=...` to the launch file, or setting `MODEL_PATH` for the sweep scripts, is now an error instead of being silently ignored.

Run identity (P0-2 fix):

- Every detector launch is one run with a unique `run_id` (launch argument `run_id`, default `auto`).
- The sweep scripts build `run_id = <scenario>_<model>_<resource_profile>_<fps>fps_qos<depth>_d<delay>_<RUN_TAG>` and write `$RESULTS_DIR/<run_id>.csv`. `RUN_TAG` defaults to `<timestamp>_<pid>`; the baseline and OS-tuned wrappers export one `RUN_TAG` per batch. Only letters, digits, `.`, `_` and `-` are allowed.
- The detector creates its CSV exclusively and fails if the file already exists, and the scripts refuse to start a sweep point whose CSV already exists. Runtime CSVs are never appended to or overwritten.
- The analyzer summarises each `(configuration, run_id)` separately and writes a `run_id` summary column. Instead of de-duplicating, it raises an error when a `frame_id` repeats within one run, when one `run_id` is used by several configurations, or when a legacy CSV contains appended runs (repeated or decreasing `frame_id`).
- Legacy CSVs without `run_id` are still accepted: each file is treated as one run with `run_id = legacy:<csv path>`.
- Each run also writes `$RESULTS_DIR/<run_id>.publisher.csv` (published frames), and failed runs are renamed to `*.failed`; see “Measurement definitions” below.

### Scheduling policies (Phase 3 / Batch 1)

The detector parameter `scheduler_policy` selects the execution path (`src/ros2_uav_pipeline/mobilevit_uav_pipeline/scheduling.py` documents the exact semantics):

| Policy | Queue | Discard rule |
|---|---|---|
| `legacy_qos` (default) | DDS KEEP_LAST(`qos_depth`) only; inference runs in the subscription callback | DDS overwrites the oldest sample (not observable by the app) |
| `fifo` | bounded app queue (`queue_capacity`, default 5), arrival order | full → `fifo_overflow=reject_newest` (tail drop, default) or `evict_oldest` |
| `latest_frame` | at most 1 pending frame | a newer frame supersedes the pending one |
| `adaptive` | bounded app queue, evict oldest when full | deadline feasibility from past service times (`adaptive_window`, `adaptive_quantile`, `adaptive_margin_ms`), EDF when ρ̂ < `adaptive_overload_threshold`, newest feasible frame otherwise; waits for a fresh frame when none is feasible |

The application policies share one architecture: ingestion callback (timestamps + enqueue only) → bounded queue → exactly one inference worker thread. Every frame that reaches the queue gets exactly one CSV row (processed, `drop_reason`, or `shutdown_pending` / `shutdown_inflight` on shutdown). `intra_op_threads` (torch + OpenCV) must be equal across compared arms (the sweep uses 1; see the report for why).

```bash
# one model / FPS point, all arms (inside the same constrained scope as the baseline):
MODELS=mobilevit_s SWEEPS=sched INPUT_FPS=20 SCHED_ARMS="legacy_qos:1 legacy_qos:5 fifo latest_frame adaptive" \
  RESULTS_DIR=results/raw/ros2_phase3_pilot bash scripts/run_baseline_experiments.sh
# interleaved pilot (rotated arm order per repeat; DRY_RUN=1 prints the plan):
REPEATS=3 RUN_SECONDS=40 bash experiments/ros2/run_sched_pilot.sh
python3 -m src.ros2_runtime.analyze_runtime --input results/raw/ros2_phase3_pilot \
  --summary-output results/csv/ros2_phase3_pilot_summary.csv --warmup-frames 10
python3 -m src.ros2_runtime.aggregate_scheduling --summary results/csv/ros2_phase3_pilot_summary.csv \
  --raw-dir results/raw/ros2_phase3_pilot --runs-output results/csv/ros2_phase3_pilot_runs.csv \
  --conditions-output results/csv/ros2_phase3_pilot_arms.csv --paired-output results/csv/ros2_phase3_pilot_paired.csv
```

Summary columns added for scheduling (appended; older columns unchanged): `scheduler_policy`, `queue_capacity`, `scheduler_params`, the disjoint split of `dropped_frames` into `app_policy_dropped_frames` / `shutdown_unfinished_frames` / `dds_unreceived_frames` / `tail_unobserved_frames` / `other_dropped_frames`, `policy_drop_reasons`, `app_policy_drop_rate_pct`, queue wait and frame-age percentiles, `max_queue_len`, `scheduler_decisions`, `intra_op_threads`.

Do not report runtime data as fully auditable measured results unless CSVs were generated by a real ROS2 run and the raw CSVs or runtime summary CSV are available.

The teammate pipeline integration checklist is documented in:

```text
report/ros2_pipeline_integration.md
```

## Analyze ROS2 Runtime CSV

After ROS2 experiments produce CSV files in `results/raw/ros2`, generate a runtime summary and figures:

```bash
python3 -m src.ros2_runtime.analyze_runtime \
  --input results/raw/ros2 \
  --summary-output results/csv/ros2_runtime_summary.csv \
  --figures-dir results/figures/ros2
```

Recommended ROS2 logger columns:

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
- Dropped frames combine explicit `dropped` rows, `frame_id` gaps and, when present, the publisher log (see below).
- `run_id` identifies one detector launch. Rows are summarised per configuration and run; see “Run identity” above for the rejection rules and legacy CSV handling.
- Older CSVs (without the newer columns) remain readable; their timing is reported with `timing_schema=legacy` (their `inference_ms` may include the artificial delay).

Measurement definitions (Phase 1 / Batch 1):

- **Clocks.** Cross-process timestamps (`published_at_ns`, `received_at_ns`, `completed_at_ns`) use the host wall clock (`time.time_ns()`, same as ROS `SYSTEM_TIME`, unaffected by `use_sim_time`); publisher and detector must run on the same host. Stage durations use the monotonic `time.perf_counter_ns()`.
- **Timing fields.** `transport_ms` = published → detector callback start (DDS transport + executor queue). `preprocess_ms` = cv_bridge + resize + tensor. `artificial_delay_ms` = injected `fake_inference_delay_ms` sleep. `inference_ms` = model forward pass only. `latency_ms` = end-to-end, published → inference completed.
- **Deadline.** A processed frame misses its deadline iff `latency_ms > deadline_ms` (the run's `deadline_ms`, logged per row; one run must use one value). Dropped frames are never deadline misses. `deadline_miss_rate_pct` = misses / processed frames (≤ 100%). `effective_miss_rate_pct` = (misses + dropped) / total frames. The logged `deadline_miss` flag is used only when `deadline_ms` is unknown (legacy CSVs). This is the runtime deadline; the EDA-Lite `cost_model.deadline_ms` (33.3) is a separate simulation parameter.
- **Warm-up.** The detector flags its first `warmup_frames` processed frames (default 10; scripts: `WARMUP_FRAMES`) with `warmup=1`. The analyzer excludes them, plus the first `--warmup-frames N` received frames per run (default 0, also works for legacy CSVs), and starts the measurement window after the last warm-up `frame_id`.
- **Dropped frames.** dropped = frames in the window that were never processed. With a publisher log the window is every published frame (`frame_accounting=publisher_log`, includes leading/trailing drops); otherwise it is the observed `frame_id` range (`frame_id_range`, a lower bound) or explicit drop rows only (`explicit_only`). Explicit `dropped` rows and `frame_id` gaps are merged as a set, so each frame is counted once. If drops cannot be determined (`unavailable`), `dropped_frames`, `drop_rate_pct`, `total_rows` and `effective_miss_rate_pct` are left empty, never 0, and `build_os_profiles` refuses such rows.
- **Grouping keys.** `input_fps` is normalised to float text (`20` → `20.0`), `qos_depth` and `fake_delay_ms` to integers when integral, so equal values form one group; non-numeric values sort after numeric ones.
- **QoS.** The publisher is RELIABLE / KEEP_LAST depth 10 (fixed); the detector subscribes BEST_EFFORT / KEEP_LAST depth `qos_depth`. The QoS sweep therefore varies **only the subscriber queue depth**; publisher history and reliability are constant, and a best-effort subscription to a reliable publisher is delivered best-effort. The QoS actually used is recorded in each run's `meta.json` (`qos`).
- **Latency statistics.** `avg_latency_ms` = mean end-to-end latency of processed, non-warm-up frames; `p95_latency_ms` / `p99_latency_ms` = nearest-rank percentiles (no interpolation; with few frames P99 is the maximum); `jitter_ms` = **population standard deviation of per-frame end-to-end latency**, not RFC 3550 / inter-arrival jitter.
- **CPU / memory.** `avg_cpu_percent` averages `psutil.Process.cpu_percent()` of the detector process (per-process; can exceed 100 with several cores; psutil reports 0.0 on its first call). `avg_memory_mb` averages the detector's RSS.
- **Start-up (Phase 2 / Batch 1).** The detector subscribes only after its model and CSV are ready, and the publisher starts numbering, publishing and logging frames only once it sees a subscriber, so frames are not published into a detector that is still importing torch. (With warm-up > 0 the analyzer already excluded those frames; the gate also keeps `WARMUP_FRAMES=0` runs and the raw publisher log clean.) Float launch arguments (`input_fps`, `deadline_ms`) accept integer literals such as `input_fps:=5`.
- **Launch reliability.** The launch file shuts down when either node exits. A sweep point succeeds only if `timeout` stopped it (exit 124) and the detector CSV has data rows; otherwise the script stops with an error and renames that run's CSVs to `*.failed`, which the analyzer ignores.

Optional: `--warmup-frames N` excludes the first N received frames of every run in addition to detector-flagged warm-up rows.

Runtime summary columns:

- `scenario`
- `model_name`
- `input_fps`
- `qos_depth`
- `fake_delay_ms`
- `resource_profile`
- `run_id`
- `total_rows`
- `processed_frames`
- `dropped_frames`
- `drop_rate_pct`
- `deadline_misses`
- `deadline_miss_rate_pct`
- `avg_latency_ms`
- `p95_latency_ms`
- `p99_latency_ms`
- `jitter_ms`
- `avg_inference_ms`
- `avg_cpu_percent`
- `avg_memory_mb`
- `deadline_ms`
- `effective_miss_rate_pct`
- `published_frames`
- `frame_accounting`
- `warmup_frames_excluded`
- `avg_transport_ms`
- `avg_preprocess_ms`
- `avg_artificial_delay_ms`
- `p95_inference_ms`
- `timing_schema`
- `measurement_class`, `memory_limit_mb` (effective cgroup limit), `host_memory_mb`, `run_metadata` (from `<run_id>.meta.json`; `unknown`/empty when absent)

The newer columns are appended after the original ones, so existing column order is unchanged. The analyzer also writes `<summary stem>.manifest.json` (`--manifest-output` to override) with the SHA-256 of the summary and of every detector CSV, publisher log and run metadata file it read.

## Build Runtime OS Profiles

Convert a ROS2 runtime summary into EDA-Lite OS pressure profiles:

```bash
python3 -m src.ros2_runtime.build_os_profiles \
  --input results/csv/ros2_runtime_summary.csv \
  --output experiments/eda_lite/runtime_os_profiles.json \
  --profile-prefix measured
```

Calibration (audit P1-7):

- `latency_multiplier = avg_latency_ms / baseline`, where the baseline is the **same model's** idle run under the same `resource_profile`: `fake_delay_ms = 0`, `fps_sweep` preferred, lowest `input_fps`, then lowest `qos_depth`; repeated runs averaged. Models are never normalised against each other. `--baseline-resource-profile normal` makes e.g. `tuned` runs use the `normal` idle run; `--baseline-latency-ms 40` or `--baseline-latency-ms mobilevit_xxs=40 mobilevit_s=120` overrides it. A model without an idle run is an error.
- `memory_pressure = avg_memory_mb / reference`, reference = `--memory-reference-mb`, else the run's effective cgroup limit (`memory_limit_mb`), else host RAM (`host_memory_mb`). No reference → error (the old max-RSS normalisation is gone).
- `metadata` records every baseline (value, condition, run_ids), each profile's model/run/measurement class/memory reference, the source summary + manifest SHA-256, and `provenance_status` (`verified` only if the manifest verifies to raw CSVs and every run has metadata with `measurement_class` `constrained` or `unconstrained`). `--require-verified` writes nothing otherwise.

Then update `experiments/eda_lite/mobilevit_runtime_aware_sweep.json` so `os_profile_file` points to `runtime_os_profiles.json`, and run:

```bash
python3 -m src.eda_lite.run_simulation \
  --profile data/model_profiles/mobilevit_xxs_simplified.json \
  --config experiments/eda_lite/mobilevit_runtime_aware_sweep.json \
  --output results/csv/eda_lite_mobilevit_runtime_aware_sweep.csv
```

`mobilevit_runtime_aware_sweep.json` uses `runtime_os_profiles.example.json` by default (rows labelled `example`; not measured data). The teammate-provided `measured_*` profiles were moved to `runtime_os_profiles.legacy_unverified.json`; `mobilevit_runtime_aware_sweep_legacy_unverified.json` runs them with `allow_unverified_os_profiles: true` (rows labelled `unverified`). See `report/runtime_result_provenance.md` before using any runtime-derived number.

Model matching: runtime-derived profiles carry the ROS2 model they were measured on (`metadata.profiles[name].model_name`), and model profiles declare `runtime_model_name` (`mobilevit_xxs` / `mobilevit_s`). Profiles listed by the file are filtered to the simulated model; an explicitly configured profile from another model is an error.

Every `run_simulation` / `run_profile_sweep` output gets `<output stem>.provenance.json` with the SHA-256 of the output CSV, config, model profile(s) and OS profile file plus its provenance status, so `check_runtime_provenance.py` can flag stale CSVs.

## Model Profile Format

模型 profile 使用簡化 JSON，不代表完整 ONNX graph。

`load_model_profile` validates: non-empty `model_name` and `layers`; all fields present; numbers finite and non-negative; `fusible` boolean; unique layer names; and the sequential chain `layers[i].output_kb == layers[i+1].input_kb` (relative tolerance 1e-6). Optional `runtime_model_name` (`mobilevit_xxs` / `mobilevit_s`) ties the profile to runtime OS profiles of the same ROS 2 model.

必要欄位：

```json
{
  "model_name": "example_model",
  "layers": [
    {
      "name": "conv1",
      "op_type": "Conv",
      "input_kb": 64,
      "output_kb": 48,
      "weight_kb": 48,
      "compute_macs": 120000000,
      "fusible": true
    }
  ]
}
```

Main profiles:

```text
data/model_profiles/mobilevit_xxs_simplified.json
data/model_profiles/mobilevit_s_simplified.json
```

Legacy optional profiles:

```text
data/model_profiles/edge_cnn_simplified.json
data/model_profiles/edge_cnn_large_simplified.json
data/model_profiles/yolo11n_simplified.json
data/model_profiles/yolo11s_simplified.json
```

## Experiment Config Format

範例 config：

```json
{
  "sram_kb": [256, 512, 1024, 2048],
  "schedulers": ["layerwise", "greedy", "dp"],
  "os_profiles": ["normal", "high_latency", "high_memory_pressure"],
  "cost_model": {
    "dram_energy_per_kb": 1.0,
    "compute_energy_per_mmac": 0.05,
    "dram_latency_per_kb_ms": 0.001,
    "compute_latency_per_mmac_ms": 0.01,
    "subgraph_overhead_ms": 0.02,
    "weight_tile_kb": 64.0,
    "alpha": 1.0,
    "beta": 100.0,
    "gamma": 50.0,
    "delta": 75.0,
    "deadline_ms": 33.3
  }
}
```

Main configs:

```text
experiments/eda_lite/mobilevit_sram_sweep.json
experiments/eda_lite/mobilevit_profile_sweep.json
experiments/eda_lite/mobilevit_runtime_aware_sweep.json
experiments/eda_lite/mobilevit_sensitivity_sweep.json
experiments/eda_lite/runtime_os_profiles.example.json
```

`schedulers` accepts `layerwise`, `greedy`, `dp`, and `exhaustive`. An optional top-level `"deadline_ms": [..]` list sweeps the simulation deadline (overriding `cost_model.deadline_ms`); every output row records its `deadline_ms`. `mobilevit_sensitivity_sweep.json` uses it:

```bash
python3 -m src.eda_lite.run_profile_sweep \
  --config experiments/eda_lite/mobilevit_sensitivity_sweep.json \
  --output results/csv/eda_lite_mobilevit_sensitivity_sweep.csv
python3 -m src.eda_lite.analyze_results \
  --input results/csv/eda_lite_mobilevit_sensitivity_sweep.csv \
  --summary-output results/csv/eda_lite_mobilevit_sensitivity_summary.csv \
  --figures-dir results/figures/mobilevit_sensitivity \
  --plot-model mobilevit_s_simplified_profile_estimate \
  --plot-os-profile normal --plot-deadline-ms 33.3
```

Simulation CSV columns (new ones appended at the end): `feasible`, `infeasible_reason`, `deadline_ms`, `effective_latency_ms`, and the cost terms `latency_cost`, `deadline_cost`, `memory_pressure_cost`, `communication_pressure_cost` (`os_aware_total_cost` = `estimated_energy` + these four).

Summary CSV: `best_scheduler` lists **all** schedulers tied at the minimum cost joined with `=` (e.g. `greedy=dp`); a tie is not a greedy win. Appended columns: `deadline_ms`, `num_tied_schedulers`, `tied_same_partition`, `feasible_schedulers`, `infeasible_schedulers`, and `baseline_status` (`ok` / `missing` / `infeasible`; reduction-vs-layerwise columns stay empty unless `ok`). Groups with no feasible scheduler have an empty `best_scheduler`.

## Cost Model Notes

EDA-Lite v1 使用簡化成本模型：

```text
L_eff = m * L                                   # L = sum of subgraph latencies
os_aware_total_cost =
    E                                           # sum of subgraph energies
  + alpha * L_eff
  + beta  * r * max(0, L_eff - deadline_ms)     # whole-schedule hinge
  + gamma * p * P / SRAM                        # P = max subgraph peak SRAM
  + delta * d * L
```

`m, r, p, d` = OS profile `latency_multiplier`, `deadline_miss_rate`, `memory_pressure`, `drop_rate`. The same function is the `dp`/`exhaustive` objective and the reported cost. All cost-model weights must be non-negative (validated), which the exact DP relies on.

**Deadline semantics.**
- *EDA-Lite* `deadline_ms` is a per-inference budget for the **simulated** latency (cost-model units, not wall clock). The penalty uses the effective latency `m * L`, the same OS-inflated latency the latency term charges for (before Phase 1 / Batch 2 it used the raw `L`, so `latency_multiplier` never produced deadline excess).
- *ROS 2* `deadline_ms` is an end-to-end **wall-clock** budget (publish → inference done) per frame; the runtime analyzer reports `deadline_miss_rate_pct` against it.
- The two are linked only through dimensionless profile values: `deadline_miss_rate` (measured miss fraction) and `latency_multiplier` (measured latency ratio). The runtime deadline value is not copied into the simulation, because simulated latency is not calibrated to wall-clock time.
- The communication term keeps the raw `L` (unchanged).

**What changes a schedule (MobileViT coarse profiles).** Fusion lowers energy, latency, and therefore the deadline term together, so only the SRAM limit (feasibility) and memory pressure can push toward less fusion. With the shipped weights the memory term is too small to change any MobileViT schedule (`gamma` would have to be roughly 50–130× larger), so `greedy` and `dp` tie everywhere and every OS profile picks the same partition as `pure`; OS profiles change the reported cost, not the decision. See `report/PHASE1_BATCH2_RESULT.md`.

其中：

- DRAM traffic 會計入 subgraph 的第一個 input、最後一個 output 與所有 weights。
- 融合後的中間 activation read/write 會被省略，用來模擬 layer fusion 減少 DRAM traffic。
- SRAM usage 以 input、output、最大中間 activation 與 weight tile 估計。
- `drop_rate` 由 ROS2 runtime summary 的 `drop_rate_pct` 轉換而來，用來表示 DDS/UDP/接收端壓力造成的 communication pressure。
- OS profile 可使用內建 coarse pressure profile，也可由 ROS2 runtime summary 轉成自訂 profile。

OS profile JSON shape:

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

## Run Tests

在專案根目錄執行（不需要安裝任何套件，也不需要 ROS 2）：

```bash
python3 -m unittest discover -s tests
bash scripts/ci_checks.sh all          # tests + bash -n + audit --strict + provenance gate
bash scripts/ci_checks.sh repeat 5     # repeat the suite; every run's verbose log in ci-logs/
```

**CI** (`.github/workflows/ci.yml`, GitHub Actions, Ubuntu): the test suite on Python 3.10 / 3.11 / 3.12 / 3.13 with nothing installed; `bash -n` on every tracked shell script; `audit_repro.py --strict` (fails on any `REPRODUCED` case); the provenance gate; and a job that repeats the suite 5 times without retries (flake detection; logs uploaded as artifacts). ROS 2 is not installed in CI: the nodes, launch file and sweep scripts are covered by stdlib helpers, stubbed launch modules and fake `ros2` / `timeout` binaries.

Provenance gate: `BLOCKED` (exit 1, no real data) is reported as a warning and does not fail CI; `BROKEN` fails; `VERIFIED` is accepted only if real raw CSVs and run metadata are committed under `results/raw/ros2/`. CI can never turn `BLOCKED` into `VERIFIED`.

Tests that run a CLI or script use `tests/cli_support.run_cli`, which fails with the command, exit code and the child's full stdout/stderr (instead of a bare `CalledProcessError`).

目前測試會檢查：

- simulator 可以讀取 JSON model profile。
- MobileViT profiles and profile sweep configs can run.
- `layerwise`、`greedy`、`dp` scheduling behavior.
- `dp` equals the exhaustive oracle (random small models and MobileViT profiles); greedy on non-monotone SRAM; infeasible sweep rows; ties / missing baselines in the summary; `pure` profile; effective-latency deadline; per-term sensitivity (`tests/test_eda_lite_scheduling.py`).
- analysis summary and SVG generation.
- multi-model analysis requires `--plot-model`.
- ROS2 runtime analyzer can derive latency from timestamps.
- ROS2 runtime analyzer can infer dropped frames from `frame_id` gaps.
- ROS2 runtime summary can convert deadline, memory, and drop pressure into OS profiles.
- old OS profile JSON without `drop_rate` remains compatible.
- Batch 4 (`tests/test_engineering_quality.py`): strict model loading (no fallback), `model_path` removed from launch/scripts, model-profile validation, dependency split, stdlib-only imports, repo hygiene / `.gitignore` results policy, CI workflow and provenance gate behaviour.
- provenance chain end to end on synthetic temp data (verified / tampered / missing metadata / unapplied limits / stale sidecar), legacy profiles refused without opt-in and never mixed across models, per-model calibration and memory references, run metadata limits classification and scripts (`tests/test_provenance_calibration.py`).

## Correctness / Reproducibility Audit

Known correctness and reproducibility issues (P0/P1/P2) are tracked in `report/audit_p0_p1_p2.md`. Re-check which ones are still present with:

```bash
python3 scripts/audit_repro.py            # report
python3 scripts/audit_repro.py --strict   # exit 1 if any case is REPRODUCED (used by CI)
```

Cases cover P0-1 … P1-8, LAUNCH, and the automatable P2 items (P2-1 CI, P2-2 dependencies, P2-3 hygiene, P2-6 pipeline contracts). Each case prints `REPRODUCED` (still present), `FIXED`, or `BLOCKED` (code fixed, but confirming it needs data from a real ROS2 run, e.g. P0-3 raw CSVs, P1-8 cgroup read-back on Linux). The script is read-only and uses only the standard library.

## Reporting Rules

- Clearly separate measured ROS2 runtime results from EDA-Lite simulation estimates.
- Label EDA-Lite energy and latency as estimates or simulation outputs.
- Do not present estimated energy as real hardware energy.
- Do not claim this project fully reproduces the original EDA compiler.
- Explain the simplified memory, energy, MobileViT block, and communication-drop assumptions.
- Explain that MobileViT profiles are coarse simulation profiles, not exact ONNX model structures.
- If using `runtime_os_profiles.example.json`, state that it is an example profile, not measured data.
- Only call ROS2 data "measured" after it comes from actual ROS2 experiment CSVs and `scripts/check_runtime_provenance.py` reports `VERIFIED`.
- Label anything derived from `runtime_os_profiles.legacy_unverified.json` or `results/figures/ros2/*.svg` as UNVERIFIED.
- Say that ROS 2 inference uses random-initialised weights (latency only, no accuracy), and define jitter as the latency standard deviation.
- Do not claim adaptive / runtime scheduling: EDA-Lite schedules offline.
- YOLO-related content is paused; do not frame the project as a YOLO project unless the direction explicitly changes.

## Development Notes

- 每新增一個可執行功能，同步更新本 README。
- 保持 EDA-Lite simulator deterministic，方便報告解釋與測試。
- 清楚區分 runtime measurement 與 simulation estimate。
- 不宣稱完整重現 EDA paper，只稱為 EDA-inspired lightweight simulator。
- ROS2 CSV 只有實際跑過 pipeline 後才能標示為 runtime measurement；synthetic 或測試資料不得當作實測結果。

下一階段建議（Phase 2；preflight checklist 見 `report/PHASE1_BATCH4_RESULT.md`）：

1. 撰寫 report methodology 與 limitations。
2. 在 Linux + ROS 2 Humble 上建立 `environment.yml` 環境、通過 preflight，執行 FPS/QoS/overload experiments 並提交 raw CSV + publisher log + meta.json（見 `results/README.md`）。
3. 用真實 ROS2 summary 產生 `runtime_os_profiles.json`（`--require-verified`），把 `mobilevit_runtime_aware_sweep.json` 改指向它，再重跑。
4. 產生 final figures 並寫 results discussion。
