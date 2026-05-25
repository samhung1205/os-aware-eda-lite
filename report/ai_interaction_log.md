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
