#!/bin/bash
# install_ros2_conda.sh
# 補齊 ROS 2 (RoboStack) 環境

echo "開始在 eda_lite 環境中透過 RoboStack 安裝 ROS 2 Humble..."

# 載入 conda 環境
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate eda_lite

# 設定 conda config 以支援 robostack (RoboStack 要求加入 conda-forge 與 robostack-staging)
conda config --env --add channels conda-forge
conda config --env --add channels robostack-staging
conda config --env --remove channels defaults 2>/dev/null || true

# 安裝 mamba 以加速套件解析 (強烈建議，因為 ROS 套件相依性極其複雜)
conda install -y mamba -c conda-forge

# 透過 mamba 安裝 ros-humble 相關套件
# 我們選擇安裝 ros-humble-desktop，並補上 sensor-msgs 與 cv-bridge 以供影像串流使用
mamba install -y ros-humble-desktop python=3.10
mamba install -y ros-humble-sensor-msgs ros-humble-cv-bridge

echo "======================================================="
echo "ROS 2 Humble 安裝完成！"
echo "為了確保所有 ROS 2 環境變數被正確載入，未來每次開啟終端機時，請先執行："
echo "conda deactivate"
echo "conda activate eda_lite"
echo "======================================================="
