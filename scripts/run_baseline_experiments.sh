#!/usr/bin/env bash
# run_baseline_experiments.sh
# 示範如何以嚴格的 2 Core / 2GB DRAM 限制來啟動 ROS 2 節點
# 限制是否真的生效由每個 run 的 <run_id>.meta.json 驗證（measurement_class）。
# chmod +x scripts/run_baseline_experiments.sh
set -euo pipefail

echo "=========================================================="
echo "啟動 Baseline 實驗 (OS 未微調 + 嚴格硬體限制)"
CPU_SET="${CPU_SET:-0,1}"
MEMORY_MAX="${MEMORY_MAX:-2G}"
echo "要求的 CPU 限制: ${CPU_SET} (透過 taskset)"
echo "要求的記憶體限制: ${MEMORY_MAX} (透過 systemd-run MemoryMax；需要 cgroup v2 memory delegation)"
echo "=========================================================="

export RESOURCE_PROFILE="normal"
UNCONSTRAINED_PROFILE="unconstrained"
MODELS="mobilevit_xxs mobilevit_s"
# 同一批次共用 RUN_TAG，每個 sweep 點仍有唯一 run_id 與獨立 CSV。
export RUN_TAG="${RUN_TAG:-$(date +%Y%m%dT%H%M%S)_$$}"

run_sweep() {
  local script_path="$1"

  if command -v taskset >/dev/null 2>&1 && command -v systemd-run >/dev/null 2>&1; then
    # Linux path: 子進程會繼承 CPU / memory restrictions。REQUESTED_* 只是「要求」；
    # 每個 run 的 <run_id>.meta.json 會在 scope 內讀回實際生效的限制，未生效則該 run 失敗。
    REQUESTED_CPUS="$CPU_SET" REQUESTED_MEMORY_MAX="$MEMORY_MAX" \
      taskset -c "$CPU_SET" systemd-run --user --scope -p MemoryMax="$MEMORY_MAX" bash "$script_path"
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
  
  echo ">> 啟動 FPS 壓力測試..."
  run_sweep experiments/ros2/run_fps_sweep.sh

  echo ">> 啟動 QoS 深度測試..."
  run_sweep experiments/ros2/run_qos_sweep.sh

  echo ">> 啟動 CPU 過載延遲測試..."
  run_sweep experiments/ros2/run_overload_sweep.sh
done

echo "Baseline 所有測試完成！數據已儲存於 results/raw/ros2/"
