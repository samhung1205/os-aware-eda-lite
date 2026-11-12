#!/usr/bin/env bash
# run_os_tuned_experiments.sh
# 在「已手動」放大 UDP 接收緩衝區後，以相同限制啟動 ROS 2 節點。
# 本腳本不會執行 sudo 或修改系統設定；只檢查並記錄目前的 net.core.* 值。
# 注意：rmem_max 只是 socket 可要求的上限，DDS 不一定會要求更大的 buffer；同機的
# Fast DDS 可能走 shared memory transport，此時 UDP buffer 與結果無關。實際值與
# RMW_IMPLEMENTATION / transport 相關環境變數都記錄在每個 run 的 <run_id>.meta.json。
# chmod +x scripts/run_os_tuned_experiments.sh
set -euo pipefail

echo "=========================================================="
echo "啟動 OS 微調實驗 (已放大的 UDP Buffer + 嚴格硬體限制)"
echo "=========================================================="

TARGET_RMEM_MAX="${TARGET_RMEM_MAX:-4194304}"
echo "[1/2] 檢查 net.core.rmem_max >= ${TARGET_RMEM_MAX}（不自動修改）"
current_rmem_max="$(cat /proc/sys/net/core/rmem_max 2>/dev/null || true)"
current_rmem_default="$(cat /proc/sys/net/core/rmem_default 2>/dev/null || true)"
if [[ -z "$current_rmem_max" ]]; then
  echo "錯誤：讀不到 /proc/sys/net/core/rmem_max（非 Linux？），無法執行 tuned 實驗。" >&2
  exit 1
fi
echo "目前 net.core.rmem_max=${current_rmem_max} net.core.rmem_default=${current_rmem_default}"
if (( current_rmem_max < TARGET_RMEM_MAX )); then
  echo "錯誤：net.core.rmem_max=${current_rmem_max} < ${TARGET_RMEM_MAX}，tuned 條件不成立。" >&2
  echo "請自行確認後手動執行（本腳本不會執行 sudo）：" >&2
  echo "  sudo sysctl -w net.core.rmem_max=${TARGET_RMEM_MAX} net.core.rmem_default=${TARGET_RMEM_MAX}" >&2
  exit 1
fi

echo "[2/2] 以嚴格硬體限制啟動自動化 Sweep 測試..."
# 設定變數，讓 CSV 紀錄這個批次是 'tuned' 狀態
export RESOURCE_PROFILE="tuned"
UNCONSTRAINED_PROFILE="tuned_unconstrained"
CPU_SET="${CPU_SET:-0,1}"
MEMORY_MAX="${MEMORY_MAX:-2G}"
# MODELS / SWEEPS 可縮小範圍（例如 smoke test：MODELS=mobilevit_xxs SWEEPS=fps FPS_VALUES=5 RUN_SECONDS=20）。
MODELS="${MODELS:-mobilevit_xxs mobilevit_s}"
SWEEPS="${SWEEPS:-fps qos overload}"
# 主機有 swap 時，只設 MemoryMax 會讓超出限制的頁面被換出而不是 OOM；預設同時禁止 swap（0）。
# 設為空字串可回到只設 MemoryMax。實際值記錄在 meta.json effective.memory_swap_max_bytes。
MEMORY_SWAP_MAX="${MEMORY_SWAP_MAX-0}"
# 同一批次共用 RUN_TAG，每個 sweep 點仍有唯一 run_id 與獨立 CSV。
export RUN_TAG="${RUN_TAG:-$(date +%Y%m%dT%H%M%S)_$$}"

run_sweep() {
  local script_path="$1"

  if command -v taskset >/dev/null 2>&1 && command -v systemd-run >/dev/null 2>&1; then
    # Linux path: 子進程會繼承 CPU / memory restrictions。REQUESTED_* 只是「要求」；
    # 每個 run 的 <run_id>.meta.json 會在 scope 內讀回實際生效的限制，未生效則該 run 失敗。
    REQUESTED_CPUS="$CPU_SET" REQUESTED_MEMORY_MAX="$MEMORY_MAX" \
      taskset -c "$CPU_SET" systemd-run --user --scope -p MemoryMax="$MEMORY_MAX" \
        ${MEMORY_SWAP_MAX:+-p MemorySwapMax="$MEMORY_SWAP_MAX"} bash "$script_path"
  else
    # 沒有套用任何限制：label 改成 *_unconstrained，不可與受限 run 混為一談。
    echo "警告：找不到 taskset/systemd-run，以「無資源限制」執行 $script_path（resource_profile=${UNCONSTRAINED_PROFILE}）"
    RESOURCE_PROFILE="$UNCONSTRAINED_PROFILE" REQUESTED_CPUS="" REQUESTED_MEMORY_MAX="" bash "$script_path"
  fi
}

for model in $MODELS; do
  echo "=========================================================="
  echo ">>> 開始測試模型: $model <<<"
  echo "=========================================================="
  export MODEL_NAME="$model"
  
  for sweep in $SWEEPS; do
    case "$sweep" in
      fps) echo ">> 啟動 FPS 壓力測試..."; run_sweep experiments/ros2/run_fps_sweep.sh ;;
      qos) echo ">> 啟動 QoS 深度測試..."; run_sweep experiments/ros2/run_qos_sweep.sh ;;
      overload) echo ">> 啟動 CPU 過載延遲測試..."; run_sweep experiments/ros2/run_overload_sweep.sh ;;
      *) echo "錯誤：未知的 SWEEPS 項目 '$sweep'（允許 fps qos overload）。" >&2; exit 2 ;;
    esac
  done
done

echo "OS 微調所有測試完成！數據已儲存於 ${RESULTS_DIR:-results/raw/ros2}/"
