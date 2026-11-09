#!/usr/bin/env bash
# Shared run checks for the ROS2 sweep scripts. Source this file; do not execute it.
#
# One sweep point = one launch = one run:
#   $RESULTS_DIR/<run_id>.csv            detector rows
#   $RESULTS_DIR/<run_id>.publisher.csv  published frames
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
  for path in "$output_csv" "${output_csv%.csv}.publisher.csv"; do
    if [[ -e "$path" ]]; then
      echo "錯誤：${path} 已存在，拒絕 append 或覆寫。請改用新的 RUN_TAG。" >&2
      return 1
    fi
  done
}

# Usage: run_finish <launch_exit_status> <output_csv> <label>
run_finish() {
  local status="$1" output_csv="$2" label="$3"
  local reason=""
  if [[ "$status" -ne 124 ]]; then
    reason="launch 在 RUN_SECONDS 之前結束（exit ${status}），視為啟動或執行失敗"
  elif [[ ! -f "$output_csv" ]] || [[ "$(wc -l < "$output_csv")" -lt 2 ]]; then
    reason="到時結束但 detector 沒有處理任何 frame（${output_csv} 無資料列）"
  fi
  if [[ -z "$reason" ]]; then
    echo "完成：${label}（到時正常結束）"
    return 0
  fi
  local path
  for path in "$output_csv" "${output_csv%.csv}.publisher.csv"; do
    if [[ -e "$path" ]]; then
      mv "$path" "$path.failed"
    fi
  done
  echo "錯誤：${label} 失敗：${reason}。部分輸出已改名為 *.failed，不會被 analyzer 讀取。" >&2
  return 1
}
