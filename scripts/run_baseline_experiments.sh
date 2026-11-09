#!/usr/bin/env bash
# run_baseline_experiments.sh
# 示範如何以嚴格的 2 Core / 2GB DRAM 限制來啟動 ROS 2 節點
# chmod +x scripts/run_baseline_experiments.sh
set -euo pipefail

echo "=========================================================="
echo "啟動 Baseline 實驗 (OS 未微調 + 嚴格硬體限制)"
echo "CPU 限制: Cores 0, 1 (透過 taskset)"
echo "記憶體限制: 2GB (透過 systemd-run MemoryMax)"
echo "=========================================================="

export RESOURCE_PROFILE="normal"
MODELS="mobilevit_xxs mobilevit_s"
# 同一批次共用 RUN_TAG，每個 sweep 點仍有唯一 run_id 與獨立 CSV。
export RUN_TAG="${RUN_TAG:-$(date +%Y%m%dT%H%M%S)_$$}"

run_sweep() {
  local script_path="$1"

  if command -v taskset >/dev/null 2>&1 && command -v systemd-run >/dev/null 2>&1; then
    # Linux path: 子進程會繼承 CPU / memory restrictions.
    taskset -c 0,1 systemd-run --user --scope -p MemoryMax=2G bash "$script_path"
  else
    echo "警告：找不到 taskset/systemd-run，改以無 Linux 資源限制模式執行 $script_path"
    bash "$script_path"
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
