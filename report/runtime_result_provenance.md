# Runtime Result Provenance

This note tracks which ROS2 runtime artifacts are currently present and how they can be used in the report.

## Present Artifacts

- `experiments/eda_lite/runtime_os_profiles.json`
  - Contains 22 `measured_*` OS pressure profiles.
  - Covers `mobilevit_xxs` and `mobilevit_s` across FPS, QoS, and overload scenarios.
- `results/figures/ros2/*.svg`
  - Contains ROS2 runtime summary figures for average latency, P95 latency, deadline miss rate, and drop rate.
- `results/figures/eda_lite/s/*.svg`
- `results/figures/eda_lite/xxs/*.svg`

## Missing Artifacts

The repository currently does not include:

- Raw ROS2 runtime CSVs under `results/raw/ros2/`.
- The analyzed runtime summary CSV, normally expected at `results/csv/ros2_runtime_summary.csv`.
- The pure and OS-aware per-model EDA-Lite CSVs may be regenerated locally by `scripts/rebuild_eda_lite_figures.sh`. They are ignored by git because generated CSVs are not tracked by default.

## Reporting Rule

The checked-in `runtime_os_profiles.json` and ROS2 figures may be discussed as teammate-provided runtime-derived artifacts. For stricter reproducibility, the final report should not call them fully auditable measured results until raw ROS2 CSVs or `ros2_runtime_summary.csv` are restored or regenerated.

Check the current provenance state with:

```bash
python3 scripts/check_runtime_provenance.py
```

## Regeneration Path

1. Prepare image input:

```bash
bash experiments/ros2/prepare_coco128.sh
```

This creates `data/raw/images/coco128/images/train2017` with 128 image files. The downloaded zip and extracted images are intentionally ignored by git.

2. Run ROS2 experiments in a Linux/RoboStack environment:

```bash
bash scripts/run_baseline_experiments.sh
```

The baseline wrapper uses Linux `taskset` and `systemd-run` when available. On macOS or other environments without those tools, it falls back to the raw sweep scripts, but `ros2` and `timeout`/`gtimeout` are still required.

3. Rebuild runtime summary and OS profiles:

```bash
python3 -m src.ros2_runtime.analyze_runtime \
  --input results/raw/ros2 \
  --summary-output results/csv/ros2_runtime_summary.csv \
  --figures-dir results/figures/ros2

python3 -m src.ros2_runtime.build_os_profiles \
  --input results/csv/ros2_runtime_summary.csv \
  --output experiments/eda_lite/runtime_os_profiles.json \
  --profile-prefix measured
```

4. Rebuild EDA-Lite comparison inputs and six-line figures:

```bash
bash scripts/rebuild_eda_lite_figures.sh
```
