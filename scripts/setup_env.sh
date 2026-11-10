#!/bin/bash
# setup_env.sh - Setup Environment for OS-aware EDA-Lite Project
# chmod +x scripts/setup_env.sh

echo "Setting up OS-aware EDA-Lite Environment..."

# Since you don't have sudo access, we can install stress-ng, htop, sysstat via conda
# instead of the standard apt-get approach (sudo apt-get update && sudo apt-get install -y stress-ng htop sysstat)

if conda env list | awk '{print $1}' | grep -qx "eda_lite"; then
  echo "Conda environment 'eda_lite' already exists; reusing it."
else
  echo "Creating Conda environment 'eda_lite' with Python 3.10..."
  conda create -n eda_lite python=3.10 -y
fi

echo "Activating Conda environment..."
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate eda_lite

echo "Installing system-level tools (htop, sysstat, stress-ng) via Conda (Alternative to sudo apt)..."
conda install -c conda-forge htop sysstat stress-ng -y

echo "Installing pinned Python dependencies for the ROS 2 nodes (requirements-ros2.txt)..."
# CPU-only PyTorch wheels; pandas/matplotlib are not used by this project.
# The simulator/analysis/tests need nothing beyond the standard library (requirements-sim.txt).
# Preferred one-step alternative: conda env create -f environment.yml
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-ros2.txt

echo "Environment setup complete!"
echo "Please run 'conda activate eda_lite' to activate."
