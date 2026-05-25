#!/usr/bin/env bash
set -euo pipefail

ROS2_SETUP="${ROS2_SETUP:-}"
ROS2_PACKAGE="${ROS2_PACKAGE:-mobilevit_uav_pipeline}"
ROS2_LAUNCH_FILE="${ROS2_LAUNCH_FILE:-mobilevit_uav_pipeline.launch.py}"
DATASET_PATH="${DATASET_PATH:-data/raw/images/coco128/images/train2017}"
RESULTS_DIR="${RESULTS_DIR:-results/raw/ros2}"
MODEL_PATH="${MODEL_PATH:-mobilevit_xxs}"
MODEL_NAME="${MODEL_NAME:-mobilevit_xxs}"
QOS_DEPTH="${QOS_DEPTH:-5}"
DEADLINE_MS="${DEADLINE_MS:-100}"
FAKE_DELAY_MS="${FAKE_DELAY_MS:-0}"
RESOURCE_PROFILE="${RESOURCE_PROFILE:-normal}"
FPS_VALUES="${FPS_VALUES:-5 10 20 30}"

if [[ -n "$ROS2_SETUP" ]]; then
  # shellcheck source=/dev/null
  source "$ROS2_SETUP"
fi

mkdir -p "$RESULTS_DIR"

for fps in $FPS_VALUES; do
  output_csv="$RESULTS_DIR/fps_sweep_${MODEL_NAME}_${fps}fps_qos${QOS_DEPTH}.csv"
  ros2 launch "$ROS2_PACKAGE" "$ROS2_LAUNCH_FILE" \
    dataset_path:="$DATASET_PATH" \
    input_fps:="$fps" \
    qos_depth:="$QOS_DEPTH" \
    model_path:="$MODEL_PATH" \
    model_name:="$MODEL_NAME" \
    fake_inference_delay_ms:="$FAKE_DELAY_MS" \
    deadline_ms:="$DEADLINE_MS" \
    resource_profile:="$RESOURCE_PROFILE" \
    scenario:="fps_sweep" \
    output_csv:="$output_csv"
done
