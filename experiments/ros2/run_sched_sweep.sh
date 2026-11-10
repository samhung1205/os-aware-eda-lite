#!/usr/bin/env bash
# Phase 3 / Batch 1: scheduling-policy sweep for ONE model / FPS / delay point.
#
# Runs one launch per "arm", in the order given by SCHED_ARMS (the caller rotates the order
# between repeats so drift is spread over the arms). Arms:
#   legacy_qos:<depth>  Phase 2 behaviour: inference in the subscription callback, the DDS
#                       KEEP_LAST(<depth>) queue is the only queue (legacy baseline).
#   fifo | latest_frame | adaptive
#                       ingestion callback -> bounded application queue (QUEUE_CAPACITY)
#                       -> one inference worker; DDS KEEP_LAST depth = SCHED_DDS_DEPTH.
# Everything else (model, weights, preprocessing, dataset, FPS, deadline, warm-up, limits set
# by the caller's taskset/systemd-run/nice scope, DDS profile + probe gate) is identical.
set -euo pipefail
# shellcheck source=run_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/run_common.sh"

ROS2_SETUP="${ROS2_SETUP:-}"
ROS2_PACKAGE="${ROS2_PACKAGE:-mobilevit_uav_pipeline}"
ROS2_LAUNCH_FILE="${ROS2_LAUNCH_FILE:-mobilevit_uav_pipeline.launch.py}"
ROS2_LAUNCH_TARGET="${ROS2_LAUNCH_TARGET:-src/ros2_uav_pipeline/launch/mobilevit_uav_pipeline.launch.py}"
DATASET_PATH="${DATASET_PATH:-data/raw/images/coco128/images/train2017}"
RESULTS_DIR="${RESULTS_DIR:-results/raw/ros2_phase3_pilot}"
MODEL_NAME="${MODEL_NAME:-mobilevit_xxs}"
INPUT_FPS="${INPUT_FPS:-20}"
DEADLINE_MS="${DEADLINE_MS:-100}"
FAKE_DELAY_MS="${FAKE_DELAY_MS:-0}"
RESOURCE_PROFILE="${RESOURCE_PROFILE:-normal}"
RUN_SECONDS="${RUN_SECONDS:-60}"
WARMUP_FRAMES="${WARMUP_FRAMES:-10}"
SCHED_ARMS="${SCHED_ARMS:-legacy_qos:1 legacy_qos:5 fifo latest_frame adaptive}"
SCHED_DDS_DEPTH="${SCHED_DDS_DEPTH:-10}"
QUEUE_CAPACITY="${QUEUE_CAPACITY:-5}"
FIFO_OVERFLOW="${FIFO_OVERFLOW:-reject_newest}"
ADAPTIVE_WINDOW="${ADAPTIVE_WINDOW:-32}"
ADAPTIVE_QUANTILE="${ADAPTIVE_QUANTILE:-0.9}"
ADAPTIVE_MARGIN_MS="${ADAPTIVE_MARGIN_MS:-0.0}"
ADAPTIVE_OVERLOAD_THRESHOLD="${ADAPTIVE_OVERLOAD_THRESHOLD:-1.0}"
# torch + OpenCV intra-op threads for EVERY arm (legacy included). 1 = the effective
# parallelism the Phase 2 legacy callback had (main-thread OpenMP work ran on ~1 core); without
# it the worker thread of the application arms would compute ~35% faster than the legacy arms.
INTRA_OP_THREADS="${INTRA_OP_THREADS:-1}"
RUN_TAG="${RUN_TAG:-$(date +%Y%m%dT%H%M%S)_$$}"

# Usage: sched_arm <arm>  -> sets arm_policy arm_depth arm_label (exit 2 on unknown arm)
sched_arm() {
  local arm="$1"
  case "$arm" in
    legacy_qos:[0-9]*)
      arm_policy=legacy_qos; arm_depth="${arm#legacy_qos:}"; arm_label="legacy_q${arm_depth}" ;;
    fifo)
      arm_policy=fifo; arm_depth="$SCHED_DDS_DEPTH"; arm_label="fifo_c${QUEUE_CAPACITY}_q${arm_depth}" ;;
    latest_frame)
      arm_policy=latest_frame; arm_depth="$SCHED_DDS_DEPTH"; arm_label="latest_q${arm_depth}" ;;
    adaptive)
      arm_policy=adaptive; arm_depth="$SCHED_DDS_DEPTH"; arm_label="adaptive_c${QUEUE_CAPACITY}_q${arm_depth}" ;;
    *)
      echo "錯誤：未知的 SCHED_ARMS 項目 '${arm}'（允許 legacy_qos:<depth> fifo latest_frame adaptive）。" >&2
      return 2 ;;
  esac
}

# Validate every arm before the first launch.
for arm in $SCHED_ARMS; do sched_arm "$arm" || exit 2; done

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
else
  echo "錯誤：找不到 timeout。" >&2
  exit 127
fi
if [[ -n "$ROS2_LAUNCH_TARGET" ]]; then
  launch_target=("$ROS2_LAUNCH_TARGET")
else
  launch_target=("$ROS2_PACKAGE" "$ROS2_LAUNCH_FILE")
fi

mkdir -p "$RESULTS_DIR"
position=0
for arm in $SCHED_ARMS; do
  position=$((position + 1))
  sched_arm "$arm"
  run_id="sched_sweep_${MODEL_NAME}_${RESOURCE_PROFILE}_${INPUT_FPS}fps_${arm_label}_d${FAKE_DELAY_MS}_${RUN_TAG}"
  output_csv="$RESULTS_DIR/${run_id}.csv"
  run_prepare "$run_id" "$output_csv" || exit $?
  run_capture_metadata "$run_id" "$output_csv" "$RESOURCE_PROFILE" \
    scenario=sched_sweep model_name="$MODEL_NAME" model_weights=random_init \
    input_fps="$INPUT_FPS" qos_depth="$arm_depth" fake_delay_ms="$FAKE_DELAY_MS" \
    deadline_ms="$DEADLINE_MS" run_seconds="$RUN_SECONDS" warmup_frames="$WARMUP_FRAMES" \
    scheduler_policy="$arm_policy" scheduler_arm="$arm_label" arm_position="$position" \
    sched_arms="$SCHED_ARMS" run_tag="$RUN_TAG" \
    queue_capacity="$QUEUE_CAPACITY" fifo_overflow="$FIFO_OVERFLOW" \
    adaptive_window="$ADAPTIVE_WINDOW" adaptive_quantile="$ADAPTIVE_QUANTILE" \
    adaptive_margin_ms="$ADAPTIVE_MARGIN_MS" adaptive_overload_threshold="$ADAPTIVE_OVERLOAD_THRESHOLD" \
    intra_op_threads="$INTRA_OP_THREADS" \
    dataset_path="$DATASET_PATH" launch_target="${launch_target[*]}" || exit $?
  echo "Running scheduling sweep: ${arm_label} (${position}) for ${RUN_SECONDS} seconds..."
  run_start_probe "$run_id" "$output_csv"
  set +e
  "${timeout_cmd[@]}" ros2 launch "${launch_target[@]}" \
    dataset_path:="$DATASET_PATH" \
    input_fps:="$INPUT_FPS" \
    qos_depth:="$arm_depth" \
    model_name:="$MODEL_NAME" \
    fake_inference_delay_ms:="$FAKE_DELAY_MS" \
    deadline_ms:="$DEADLINE_MS" \
    resource_profile:="$RESOURCE_PROFILE" \
    scenario:="sched_sweep" \
    output_csv:="$output_csv" \
    run_id:="$run_id" \
    warmup_frames:="$WARMUP_FRAMES" \
    scheduler_policy:="$arm_policy" \
    queue_capacity:="$QUEUE_CAPACITY" \
    fifo_overflow:="$FIFO_OVERFLOW" \
    adaptive_window:="$ADAPTIVE_WINDOW" \
    adaptive_quantile:="$ADAPTIVE_QUANTILE" \
    adaptive_margin_ms:="$ADAPTIVE_MARGIN_MS" \
    adaptive_overload_threshold:="$ADAPTIVE_OVERLOAD_THRESHOLD" \
    intra_op_threads:="$INTRA_OP_THREADS"
  status=$?
  set -e
  run_stop_probe
  run_finish "$status" "$output_csv" "Scheduling sweep $run_id" || exit 1
done
