#!/usr/bin/env bash
# Shared run checks for the ROS2 sweep scripts. Source this file; do not execute it.
#
# One sweep point = one launch = one run:
#   $RESULTS_DIR/<run_id>.csv            detector rows
#   $RESULTS_DIR/<run_id>.publisher.csv  published frames
#   $RESULTS_DIR/<run_id>.meta.json      run conditions (src/ros2_runtime/run_metadata.py):
#                                        git commit, OS/kernel, CPU, Python/Torch, ROS 2/RMW,
#                                        QoS, net.core.* buffers, requested vs effective limits
#
# Resource limits: wrappers export REQUESTED_CPUS / REQUESTED_MEMORY_MAX for what they
# asked taskset / systemd-run for. run_capture_metadata runs inside the same scope as
# the launch, reads the limits actually in effect, and fails the run when a requested
# limit is not verified (set ALLOW_UNVERIFIED_LIMITS=1 to keep going; the run is then
# recorded as constraint_unverified / constraint_failed, never as constrained).
# A run is successful only if it was still running when `timeout` stopped it
# (exit 124) and the detector CSV contains at least one data row. Any other exit
# means the launch ended early (start-up or runtime failure); its CSVs are renamed
# to *.failed so the analyzer never ingests them.

# Usage: run_prepare <run_id> <output_csv>
run_prepare() {
  local run_id="$1" output_csv="$2"
  if [[ ! "$run_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "錯誤：run_id '${run_id}' 含不允許的字元（只允許英數字、. _ -）。" >&2
    return 2
  fi
  local path
  for path in "$output_csv" "${output_csv%.csv}.publisher.csv" "${output_csv%.csv}.meta.json" "${output_csv%.csv}.probe.json"; do
    if [[ -e "$path" ]]; then
      echo "錯誤：${path} 已存在，拒絕 append 或覆寫。請改用新的 RUN_TAG。" >&2
      return 1
    fi
  done
}

# Usage: run_capture_metadata <run_id> <output_csv> <resource_profile> [key=value ...]
run_capture_metadata() {
  local run_id="$1" output_csv="$2" resource_profile="$3"
  shift 3
  local meta="${output_csv%.csv}.meta.json"
  local args=(--output "$meta" --run-id "$run_id" --resource-profile "$resource_profile"
              --requested-cpus "${REQUESTED_CPUS:-}" --requested-memory-max "${REQUESTED_MEMORY_MAX:-}")
  local kv
  for kv in "$@"; do
    args+=(--param "$kv")
  done
  if [[ "${ALLOW_UNVERIFIED_LIMITS:-0}" != "1" ]]; then
    args+=(--require-applied)
  fi
  local status=0
  "${PYTHON_BIN:-python3}" -m src.ros2_runtime.run_metadata "${args[@]}" || status=$?
  if [[ "$status" -ne 0 ]]; then
    [[ -e "$meta" ]] && mv "$meta" "$meta.failed"
    echo "錯誤：${run_id} 的 run metadata 檢查失敗（exit ${status}），未啟動 launch。" >&2
    return "$status"
  fi
}

# Runtime probe (Phase 2 / Batch 2, src/ros2_runtime/runtime_probe.py): runs in the same
# scope as the launch and writes <run_id>.probe.json with the DDS transport actually used
# (UDP sockets, Fast DDS /dev/shm segment sizes), per-node CPU / RSS / affinity / nice,
# cgroup memory and host load. RUNTIME_PROBE=0 disables it. With an SHM-only
# FASTRTPS_DEFAULT_PROFILES_FILE and REQUIRE_DDS_VERIFIED=1 (default when a profile is set)
# a run whose probe does not confirm the profile is failed.
# Usage: run_start_probe <run_id> <output_csv>
run_start_probe() {
  PROBE_PID=""
  [[ "${RUNTIME_PROBE:-1}" == "1" ]] || return 0
  local run_id="$1" output_csv="$2"
  "${PYTHON_BIN:-python3}" -m src.ros2_runtime.runtime_probe \
    --output "${output_csv%.csv}.probe.json" --run-id "$run_id" \
    --max-seconds "$(( ${RUN_SECONDS:-60} + 60 ))" \
    --dds-profile "${FASTRTPS_DEFAULT_PROFILES_FILE:-${FASTDDS_DEFAULT_PROFILES_FILE:-}}" &
  PROBE_PID=$!
}

# Wait (max NODE_EXIT_TIMEOUT s, default 15) until the publisher / detector of the launch that
# just ended have exited, so the next run never starts while they are still shutting down.
_wait_nodes_exit() {
  local cg="" deadline=$(( SECONDS + ${NODE_EXIT_TIMEOUT:-15} )) pid left
  cg="/sys/fs/cgroup$(sed -n 's/^0:://p' /proc/self/cgroup 2>/dev/null)"
  [[ -r "$cg/cgroup.procs" ]] || return 0
  while (( SECONDS < deadline )); do
    left=0
    while read -r pid; do
      grep -qaE 'mobilevit_detector_node|image_stream_node' "/proc/$pid/cmdline" 2>/dev/null && left=1
    done < "$cg/cgroup.procs"
    (( left )) || return 0
    sleep 0.2
  done
  echo "警告：launch 結束 ${NODE_EXIT_TIMEOUT:-15}s 後仍有 node process 未退出。" >&2
}

# Usage: run_stop_probe
run_stop_probe() {
  _wait_nodes_exit
  [[ -n "${PROBE_PID:-}" ]] || return 0
  kill -TERM "$PROBE_PID" 2>/dev/null || true
  wait "$PROBE_PID" 2>/dev/null || true
  PROBE_PID=""
}

# Prints a failure reason when the probe does not confirm the requested DDS profile.
_probe_check() {
  local output_csv="$1" probe="${1%.csv}.probe.json"
  local profile="${FASTRTPS_DEFAULT_PROFILES_FILE:-${FASTDDS_DEFAULT_PROFILES_FILE:-}}"
  [[ "${RUNTIME_PROBE:-1}" == "1" && -n "$profile" && "${REQUIRE_DDS_VERIFIED:-1}" == "1" ]] || return 0
  if [[ ! -f "$probe" ]]; then
    echo "缺少 runtime probe 輸出 ${probe}，無法確認 DDS profile 已載入"
    return 0
  fi
  "${PYTHON_BIN:-python3}" - "$probe" <<'PY'
import json, sys
dds = json.load(open(sys.argv[1]))["dds"]
if not dds.get("expect_shm_only"):
    # Only SHM-only profiles can be confirmed from sockets / segments. Anything else
    # (unparseable XML, UDP profile) cannot be verified: refuse instead of passing silently.
    print("DDS profile 不是可解析的 SHM-only profile，無法於執行期驗證（設 REQUIRE_DDS_VERIFIED=0 才可執行）")
elif not dds.get("verified"):
    print("DDS profile 未在執行期確認：" + "; ".join(dds.get("reasons") or ["unknown"]))
PY
}

# Usage: run_finish <launch_exit_status> <output_csv> <label>
run_finish() {
  local status="$1" output_csv="$2" label="$3"
  local reason=""
  if [[ "$status" -ne 124 ]]; then
    reason="launch 在 RUN_SECONDS 之前結束（exit ${status}），視為啟動或執行失敗"
  elif [[ ! -f "$output_csv" ]] || [[ "$(wc -l < "$output_csv")" -lt 2 ]]; then
    reason="到時結束但 detector 沒有處理任何 frame（${output_csv} 無資料列）"
  else
    reason="$(_probe_check "$output_csv")"
  fi
  if [[ -z "$reason" ]]; then
    echo "完成：${label}（到時正常結束）"
    return 0
  fi
  local path
  for path in "$output_csv" "${output_csv%.csv}.publisher.csv" "${output_csv%.csv}.meta.json" "${output_csv%.csv}.probe.json"; do
    if [[ -e "$path" ]]; then
      mv "$path" "$path.failed"
    fi
  done
  echo "錯誤：${label} 失敗：${reason}。部分輸出已改名為 *.failed，不會被 analyzer 讀取。" >&2
  return 1
}

# MODEL_PATH used to be forwarded as a launch argument that no node read. The detector
# only creates the timm model named MODEL_NAME with random weights (pretrained=False),
# so a weights path would be silently ignored. Refuse it instead.
if [[ -n "${MODEL_PATH:-}" ]]; then
  echo "錯誤：不支援 MODEL_PATH='${MODEL_PATH}'：detector 只依 MODEL_NAME 建立隨機初始化權重的 timm 模型（pretrained=False），不載入權重檔。請 unset MODEL_PATH。" >&2
  return 2
fi
