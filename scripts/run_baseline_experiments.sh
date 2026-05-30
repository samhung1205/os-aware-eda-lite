#!/bin/bash
# run_baseline_experiments.sh
# 示範如何以嚴格的 2 Core / 2GB DRAM 限制來啟動 ROS 2 節點
# chmod +x scripts/run_baseline_experiments.sh

echo "=========================================================="
echo "啟動 Baseline 實驗 (OS 未微調 + 嚴格硬體限制)"
echo "CPU 限制: Cores 0, 1 (透過 taskset)"
echo "記憶體限制: 2GB (透過 systemd-run MemoryMax)"
echo "=========================================================="

# 啟動自動化 Sweep 腳本
# 我們將整個 Bash Sweep 腳本包在 taskset 與 systemd-run 內，
# 這樣它所產生的所有 ROS 2 子進程都會繼承這些嚴格的硬體限制。
export RESOURCE_PROFILE="normal"
MODELS="mobilevit_xxs mobilevit_s"

for model in $MODELS; do
  echo "=========================================================="
  echo ">>> 開始測試模型: $model <<<"
  echo "=========================================================="
  export MODEL_NAME="$model"
  
  echo ">> 啟動 FPS 壓力測試..."
  taskset -c 0,1 systemd-run --user --scope -p MemoryMax=2G bash experiments/ros2/run_fps_sweep.sh

  echo ">> 啟動 QoS 深度測試..."
  taskset -c 0,1 systemd-run --user --scope -p MemoryMax=2G bash experiments/ros2/run_qos_sweep.sh

  echo ">> 啟動 CPU 過載延遲測試..."
  taskset -c 0,1 systemd-run --user --scope -p MemoryMax=2G bash experiments/ros2/run_overload_sweep.sh
done

echo "Baseline 所有測試完成！數據已儲存於 results/raw/ros2/"
