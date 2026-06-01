#!/usr/bin/env bash
set -euo pipefail

ROS2_SETUP="${ROS2_SETUP:-}"
ROS2_PACKAGE="${ROS2_PACKAGE:-mobilevit_uav_pipeline}"
ROS2_LAUNCH_FILE="${ROS2_LAUNCH_FILE:-mobilevit_uav_pipeline.launch.py}"
ROS2_LAUNCH_TARGET="${ROS2_LAUNCH_TARGET:-src/ros2_uav_pipeline/launch/mobilevit_uav_pipeline.launch.py}"
DATASET_PATH="${DATASET_PATH:-data/raw/images/coco128/images/train2017}"
RESULTS_DIR="${RESULTS_DIR:-results/raw/ros2}"
MODEL_PATH="${MODEL_PATH:-mobilevit_xxs}"
MODEL_NAME="${MODEL_NAME:-mobilevit_xxs}"
QOS_DEPTH="${QOS_DEPTH:-5}"
DEADLINE_MS="${DEADLINE_MS:-100}"
FAKE_DELAY_MS="${FAKE_DELAY_MS:-0}"
RESOURCE_PROFILE="${RESOURCE_PROFILE:-normal}"
FPS_VALUES="${FPS_VALUES:-5 10 20 30}"
RUN_SECONDS="${RUN_SECONDS:-60}"

if [[ -n "$ROS2_SETUP" ]]; then
  # shellcheck source=/dev/null
  source "$ROS2_SETUP"
fi

if ! command -v ros2 >/dev/null 2>&1; then
  echo "錯誤：找不到 ros2 command。請先安裝/啟用 ROS2 環境，再執行本腳本。" >&2
  exit 127
fi

if command -v timeout >/dev/null 2>&1; then
  timeout_cmd=(timeout "${RUN_SECONDS}s")
elif command -v gtimeout >/dev/null 2>&1; then
  timeout_cmd=(gtimeout "${RUN_SECONDS}s")
else
  echo "錯誤：找不到 timeout/gtimeout。請安裝 GNU coreutils，或在 Linux 環境執行。" >&2
  exit 127
fi

if [[ -n "$ROS2_LAUNCH_TARGET" ]]; then
  launch_target=("$ROS2_LAUNCH_TARGET")
else
  launch_target=("$ROS2_PACKAGE" "$ROS2_LAUNCH_FILE")
fi

mkdir -p "$RESULTS_DIR"

for fps in $FPS_VALUES; do
  output_csv="$RESULTS_DIR/fps_sweep_${MODEL_NAME}_${fps}fps_qos${QOS_DEPTH}.csv"
  echo "Running FPS sweep: ${fps} FPS for ${RUN_SECONDS} seconds..."
  set +e
  "${timeout_cmd[@]}" ros2 launch "${launch_target[@]}" \
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
  status=$?
  set -e
  if [[ "$status" -ne 0 && "$status" -ne 124 ]]; then
    echo "錯誤：FPS sweep failed with status $status" >&2
    exit "$status"
  fi
done
