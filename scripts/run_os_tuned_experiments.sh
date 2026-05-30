#!/bin/bash
# run_os_tuned_experiments.sh
# 示範在微調 OS 網路緩衝區後，啟動相同的 ROS 2 節點
# chmod +x scripts/run_os_tuned_experiments.sh

echo "=========================================================="
echo "啟動 OS 微調實驗 (放大 UDP Buffer + 嚴格硬體限制)"
echo "=========================================================="

echo "[1/2] 微調 Linux Kernel 參數: 放寬 UDP Receive Buffer (rmem_max) 到 4MB"
echo "注意：此步驟需要 sudo 權限。它能暫時緩解網路堆疊丟包，但無法解決 CPU 計算瓶頸。"
sudo sysctl -w net.core.rmem_max=4194304

echo "[2/2] 以嚴格硬體限制啟動自動化 Sweep 測試..."
# 設定變數，讓 CSV 紀錄這個批次是 'tuned' 狀態
export RESOURCE_PROFILE="tuned"
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

echo "OS 微調所有測試完成！數據已儲存於 results/raw/ros2/"
