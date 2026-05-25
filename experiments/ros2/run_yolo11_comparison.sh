#!/usr/bin/env bash
set -euo pipefail

ROS2_SETUP="${ROS2_SETUP:-}"
ROS2_PACKAGE="${ROS2_PACKAGE:-edge_detection_pipeline}"
ROS2_LAUNCH_FILE="${ROS2_LAUNCH_FILE:-edge_detection.launch.py}"
DATASET_PATH="${DATASET_PATH:-data/raw/images}"
RESULTS_DIR="${RESULTS_DIR:-results/raw/ros2}"
INPUT_FPS="${INPUT_FPS:-20}"
QOS_DEPTH="${QOS_DEPTH:-5}"
DEADLINE_MS="${DEADLINE_MS:-100}"
FAKE_DELAY_MS="${FAKE_DELAY_MS:-0}"
RESOURCE_PROFILE="${RESOURCE_PROFILE:-normal}"

# Legacy script. YOLO execution is paused; set MODEL_SPECS explicitly to use it.
MODEL_SPECS="${MODEL_SPECS:-}"
if [[ -z "$MODEL_SPECS" ]]; then
  echo "run_yolo11_comparison.sh is legacy/paused. Set MODEL_SPECS explicitly to run it." >&2
  exit 2
fi

if [[ -n "$ROS2_SETUP" ]]; then
  # shellcheck source=/dev/null
  source "$ROS2_SETUP"
fi

mkdir -p "$RESULTS_DIR"

for spec in $MODEL_SPECS; do
  model_name="${spec%%:*}"
  model_path="${spec#*:}"
  output_csv="$RESULTS_DIR/yolo11_comparison_${model_name}_${INPUT_FPS}fps_qos${QOS_DEPTH}.csv"
  ros2 launch "$ROS2_PACKAGE" "$ROS2_LAUNCH_FILE" \
    dataset_path:="$DATASET_PATH" \
    input_fps:="$INPUT_FPS" \
    qos_depth:="$QOS_DEPTH" \
    model_path:="$model_path" \
    model_name:="$model_name" \
    fake_inference_delay_ms:="$FAKE_DELAY_MS" \
    deadline_ms:="$DEADLINE_MS" \
    resource_profile:="$RESOURCE_PROFILE" \
    scenario:="yolo11_comparison" \
    output_csv:="$output_csv"
done
