# Runtime Result Provenance

This note tracks which ROS2 runtime artifacts exist, how they are verified, and how they may be used in the report.

## Verification

```bash
python3 scripts/check_runtime_provenance.py
```

| Exit | Status | Meaning |
|---|---|---|
| 0 | `VERIFIED` | raw CSVs + publisher logs + run metadata → `ros2_runtime_summary.csv` (+ `.manifest.json`) → `runtime_os_profiles.json` all hash-match; no simulation sidecar is stale |
| 1 | `BLOCKED` | a link is missing — needs a real ROS2 run, never synthetic data |
| 2 | `BROKEN` | files exist but no longer match their recorded hashes, a run's limits were not verified, or a sidecar is stale |

**Current status: `BLOCKED`.** The repository contains no raw ROS2 CSVs, publisher logs, run metadata or runtime summary.

## The chain

| Link | File | Records |
|---|---|---|
| raw run | `results/raw/ros2/<run_id>.csv`, `.publisher.csv`, `.meta.json` | measurements; run conditions (git commit, OS/kernel, CPU, Python/torch, ROS 2/RMW, QoS, `net.core.*`, requested vs effective limits, `measurement_class`, parameters) |
| summary | `results/csv/ros2_runtime_summary.csv` + `ros2_runtime_summary.manifest.json` | SHA-256 of the summary and every raw input; per-run metadata file and measurement class |
| OS profiles | `experiments/eda_lite/runtime_os_profiles.json` → `metadata` | SHA-256 of summary + manifest; calibration baselines; per-profile model/run; `provenance_status` |
| simulation | `results/csv/<name>.csv` + `<name>.provenance.json` | SHA-256 of output CSV, config, model profile(s), OS profile file; its status |

A profile file is `verified` only if its summary and manifest still hash-match, the manifest verifies down to every raw file, and every run has metadata with `measurement_class` `constrained` or `unconstrained`. The simulator refuses `unverified` files unless the config sets `allow_unverified_os_profiles: true`, and labels every row with `os_profile_provenance`.

## Present Artifacts

| Artifact | Status | Notes |
|---|---|---|
| `experiments/eda_lite/runtime_os_profiles.legacy_unverified.json` | **UNVERIFIED** | 22 teammate-provided `measured_*` profiles (from commit `3340326`, values unchanged). No raw data; legacy cross-model calibration (P1-7); resource limits never verified (P1-8). Cannot be recalibrated without `avg_latency_ms` / `avg_memory_mb` per run and the memory limit. |
| `experiments/eda_lite/runtime_os_profiles.example.json` | example | Illustrative values, default source of `mobilevit_runtime_aware_sweep.json`. |
| `results/figures/ros2/*.svg` | **UNVERIFIED** | Teammate-provided ROS2 figures; no source data in the repository. |
| `results/figures/eda_lite/{s,xxs}/*.svg` | UNVERIFIED OS profile | Regenerated with `[OS profile: UNVERIFIED]` in the title (data values unchanged; the four tracked metrics depend only on the partition). |
| `results/csv/eda_lite_mobilevit_runtime_aware_sweep.csv` (+ sidecar) | example | Regenerated from the default config; matches it exactly. |

## Reporting Rule

Nothing derived from the legacy profiles or the ROS2 figures may be called a measured result. Label it UNVERIFIED (teammate-provided, raw data not available). Only call runtime data measured after a real run makes the check report `VERIFIED`.

## Regeneration Path

1. Prepare image input: `bash experiments/ros2/prepare_coco128.sh`.
2. Run ROS2 experiments on Linux with ROS 2 (`taskset`, `systemd-run` with cgroup v2 memory delegation): `bash scripts/run_baseline_experiments.sh`. Runs whose requested limits are not in effect fail before launch.
3. Rebuild runtime summary (+ manifest) and verified OS profiles:

```bash
python3 -m src.ros2_runtime.analyze_runtime \
  --input results/raw/ros2 \
  --summary-output results/csv/ros2_runtime_summary.csv \
  --figures-dir results/figures/ros2

python3 -m src.ros2_runtime.build_os_profiles \
  --input results/csv/ros2_runtime_summary.csv \
  --output experiments/eda_lite/runtime_os_profiles.json \
  --profile-prefix measured --require-verified
```

4. `python3 scripts/check_runtime_provenance.py` must report `VERIFIED`. Then point `experiments/eda_lite/mobilevit_runtime_aware_sweep.json` at `runtime_os_profiles.json` and rebuild figures with `RUNTIME_SWEEP_CONFIG=experiments/eda_lite/mobilevit_runtime_aware_sweep.json OS_PROFILE_S=... OS_PROFILE_XXS=... bash scripts/rebuild_eda_lite_figures.sh`.
