#!/usr/bin/env bash
set -euo pipefail

ROS2_SETUP="${ROS2_SETUP:-}"
ROS2_PACKAGE="${ROS2_PACKAGE:-mobilevit_uav_pipeline}"
ROS2_LAUNCH_FILE="${ROS2_LAUNCH_FILE:-mobilevit_uav_pipeline.launch.py}"
DATASET_PATH="${DATASET_PATH:-data/rosbags/uav_flight_video.db3}"
RESULTS_DIR="${RESULTS_DIR:-results/raw/ros2}"
MODEL_PATH="${MODEL_PATH:-mobilevit_xxs}"
MODEL_NAME="${MODEL_NAME:-mobilevit_xxs}"
INPUT_FPS="${INPUT_FPS:-20}"
QOS_DEPTH="${QOS_DEPTH:-5}"
DEADLINE_MS="${DEADLINE_MS:-100}"
RESOURCE_PROFILE="${RESOURCE_PROFILE:-normal}"
DELAY_VALUES_MS="${DELAY_VALUES_MS:-0 30 80 150}"

if [[ -n "$ROS2_SETUP" ]]; then
  # shellcheck source=/dev/null
  source "$ROS2_SETUP"
fi

mkdir -p "$RESULTS_DIR"

for delay_ms in $DELAY_VALUES_MS; do
  output_csv="$RESULTS_DIR/overload_sweep_${MODEL_NAME}_${INPUT_FPS}fps_delay${delay_ms}ms.csv"
  ros2 launch "$ROS2_PACKAGE" "$ROS2_LAUNCH_FILE" \
    dataset_path:="$DATASET_PATH" \
    input_fps:="$INPUT_FPS" \
    qos_depth:="$QOS_DEPTH" \
    model_path:="$MODEL_PATH" \
    model_name:="$MODEL_NAME" \
    fake_inference_delay_ms:="$delay_ms" \
    deadline_ms:="$DEADLINE_MS" \
    resource_profile:="$RESOURCE_PROFILE" \
    scenario:="overload_sweep" \
    output_csv:="$output_csv"
done
