# ROS2 Experiment Scripts

These scripts drive the ROS2 MobileViT/UAV pipeline checked in under `src/ros2_uav_pipeline/` (default `ROS2_LAUNCH_TARGET`), or an installed equivalent package (`ROS2_LAUNCH_TARGET=""` + `ROS2_PACKAGE` / `ROS2_LAUNCH_FILE`). They are parameterized through environment variables and have not yet been run on the Phase 2 Linux machine. Environment: `conda env create -f environment.yml` (ROS 2 Humble, Python 3.10, pinned `requirements-ros2.txt`).

The main ROS2 experiment path is FPS, QoS depth, and artificial overload sweeps. YOLO-specific execution is legacy/paused.

Common environment variables:

```bash
export ROS2_WORKSPACE="$HOME/ros2-mobilevit-uav-pipeline"
export ROS2_SETUP="$ROS2_WORKSPACE/install/setup.bash"
export ROS2_PACKAGE="mobilevit_uav_pipeline"
export ROS2_LAUNCH_FILE="mobilevit_uav_pipeline.launch.py"
export DATASET_PATH="$PWD/data/raw/images/coco128/images/train2017"
export RESULTS_DIR="$PWD/results/raw/ros2"
export MODEL_NAME="mobilevit_xxs"   # timm model name, random-init weights (pretrained=False)
# MODEL_PATH is not supported (no weight file is loaded) and makes the scripts exit with status 2.
# Optional batch tag; must be new for every batch (default: <timestamp>_<pid>).
# export RUN_TAG="20261110T120000_batch1"
```

Run scripts from the project root:

```bash
bash experiments/ros2/run_fps_sweep.sh
bash experiments/ros2/run_qos_sweep.sh
bash experiments/ros2/run_overload_sweep.sh
```

Optional COCO128 image-folder input can be prepared with:

```bash
bash experiments/ros2/prepare_coco128.sh
```

COCO128 is used only as a compact image stream source for ROS2 runtime pressure tests. It is not a YOLO training or evaluation experiment in this project.

The scripts build command lines using `ros2 launch`. The launch file accepts `dataset_path`, `input_fps`, `qos_depth`, `model_name`, `fake_inference_delay_ms`, `deadline_ms`, `resource_profile`, `scenario`, `output_csv`, `run_id`, and `warmup_frames` (`model_path` was removed: it was never read, and passing it is now an error). The detector creates `timm.create_model(model_name, pretrained=False)` (random weights: latency only, no accuracy) and exits instead of falling back to another model if that fails. QoS sweeps vary only the subscriber depth (BEST_EFFORT, KEEP_LAST `qos_depth`); the publisher stays RELIABLE depth 10. If your adapted launch file uses different argument names, update the variables or launch argument names in the scripts instead of changing the analyzer.

Each sweep point is one run: the scripts pass a unique `run_id` and write `$RESULTS_DIR/<run_id>.csv`, where `run_id = <scenario>_<model>_<resource_profile>_<fps>fps_qos<depth>_d<delay>_<RUN_TAG>`. A sweep point stops with an error if its CSV already exists, so re-running never appends to or overwrites earlier data. Each run also writes `$RESULTS_DIR/<run_id>.publisher.csv` (published frames, used for complete drop accounting).

A sweep point succeeds only if it was still running when `timeout` stopped it (exit 124) and the detector CSV has data rows. If the launch ends earlier (for example the detector fails at start-up; the launch file shuts down as soon as either node exits), the script stops with an error and renames that run's CSVs to `*.failed`. `WARMUP_FRAMES` (default 10) marks the first processed frames of every run as warm-up.

Before each launch the scripts write `$RESULTS_DIR/<run_id>.meta.json` (`python3 -m src.ros2_runtime.run_metadata`, run from the repository root): git commit, OS/kernel, CPU, Python/torch versions, `ROS_DISTRO` / `RMW_IMPLEMENTATION` / DDS transport variables, node QoS, `net.core.*` buffers as read, the experiment parameters, and requested (`REQUESTED_CPUS`, `REQUESTED_MEMORY_MAX`) vs effective limits with a `measurement_class`. A run whose requested limits cannot be verified fails before launch unless `ALLOW_UNVERIFIED_LIMITS=1`.

The scripts never run `sudo` or change sysctls, cgroups or conda/RoboStack setup. Do not report generated CSVs as measured runtime data unless they came from a real ROS2 run and `python3 scripts/check_runtime_provenance.py` reports `VERIFIED`.
