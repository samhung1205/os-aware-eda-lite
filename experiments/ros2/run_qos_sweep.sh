#!/usr/bin/env bash
set -euo pipefail

ROS2_SETUP="${ROS2_SETUP:-}"
ROS2_PACKAGE="${ROS2_PACKAGE:-mobilevit_uav_pipeline}"
ROS2_LAUNCH_FILE="${ROS2_LAUNCH_FILE:-mobilevit_uav_pipeline.launch.py}"
DATASET_PATH="${DATASET_PATH:-data/raw/images/coco128/images/train2017}"
RESULTS_DIR="${RESULTS_DIR:-results/raw/ros2}"
MODEL_PATH="${MODEL_PATH:-mobilevit_xxs}"
MODEL_NAME="${MODEL_NAME:-mobilevit_xxs}"
INPUT_FPS="${INPUT_FPS:-20}"
DEADLINE_MS="${DEADLINE_MS:-100}"
FAKE_DELAY_MS="${FAKE_DELAY_MS:-0}"
RESOURCE_PROFILE="${RESOURCE_PROFILE:-normal}"
QOS_VALUES="${QOS_VALUES:-1 5 10}"

if [[ -n "$ROS2_SETUP" ]]; then
  # shellcheck source=/dev/null
  source "$ROS2_SETUP"
fi

mkdir -p "$RESULTS_DIR"

for qos in $QOS_VALUES; do
  output_csv="$RESULTS_DIR/qos_sweep_${MODEL_NAME}_${INPUT_FPS}fps_qos${qos}.csv"
  echo "Running QoS sweep: QoS depth ${qos} for 60 seconds..."
  timeout 60s ros2 launch src/ros2_uav_pipeline/launch/mobilevit_uav_pipeline.launch.py \
    dataset_path:="$DATASET_PATH" \
    input_fps:="$INPUT_FPS" \
    qos_depth:="$qos" \
    model_path:="$MODEL_PATH" \
    model_name:="$MODEL_NAME" \
    fake_inference_delay_ms:="$FAKE_DELAY_MS" \
    deadline_ms:="$DEADLINE_MS" \
    resource_profile:="$RESOURCE_PROFILE" \
    scenario:="qos_sweep" \
    output_csv:="$output_csv" || true
done
