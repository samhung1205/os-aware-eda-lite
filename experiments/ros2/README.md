# ROS2 Experiment Scripts

These scripts are wrappers for an external ROS2 MobileViT/UAV or equivalent edge inference pipeline. They are intentionally parameterized through environment variables so this repository does not need to vendor or download that pipeline.

The main ROS2 experiment path is FPS, QoS depth, and artificial overload sweeps. YOLO-specific execution is legacy/paused.

Common environment variables:

```bash
export ROS2_WORKSPACE="$HOME/ros2-mobilevit-uav-pipeline"
export ROS2_SETUP="$ROS2_WORKSPACE/install/setup.bash"
export ROS2_PACKAGE="mobilevit_uav_pipeline"
export ROS2_LAUNCH_FILE="mobilevit_uav_pipeline.launch.py"
export DATASET_PATH="$PWD/data/raw/images/coco128/images/train2017"
export RESULTS_DIR="$PWD/results/raw/ros2"
export MODEL_NAME="mobilevit_xxs"
export MODEL_PATH="mobilevit_xxs"
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

The scripts build command lines using `ros2 launch`. The launch file is expected to accept arguments such as `dataset_path`, `input_fps`, `qos_depth`, `model_path`, `model_name`, `fake_inference_delay_ms`, `deadline_ms`, `resource_profile`, `scenario`, `output_csv`, and `run_id`. If your adapted launch file uses different argument names, update the variables or launch argument names in the scripts instead of changing the analyzer.

Each sweep point is one run: the scripts pass a unique `run_id` and write `$RESULTS_DIR/<run_id>.csv`, where `run_id = <scenario>_<model>_<resource_profile>_<fps>fps_qos<depth>_d<delay>_<RUN_TAG>`. A sweep point stops with an error if its CSV already exists, so re-running never appends to or overwrites earlier data.

Optional OS tuning such as `sysctl` changes, `taskset`, cgroups, or conda/RoboStack setup belongs to the external ROS2 environment until it is verified. Do not report generated CSVs as measured runtime data unless they came from a real ROS2 run.
