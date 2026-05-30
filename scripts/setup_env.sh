#!/bin/bash
# setup_env.sh - Setup Environment for OS-aware EDA-Lite Project
# chmod +x scripts/setup_env.sh

echo "Setting up OS-aware EDA-Lite Environment..."

# Since you don't have sudo access, we can install stress-ng, htop, sysstat via conda
# instead of the standard apt-get approach (sudo apt-get update && sudo apt-get install -y stress-ng htop sysstat)

echo "Creating Conda environment 'eda_lite' with Python 3.10..."
conda create -n eda_lite python=3.10 -y

echo "Activating Conda environment..."
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate eda_lite

echo "Installing system-level tools (htop, sysstat, stress-ng) via Conda (Alternative to sudo apt)..."
conda install -c conda-forge htop sysstat stress-ng -y

echo "Installing Python dependencies..."
pip install torch torchvision pandas "numpy<2.0.0" matplotlib timm psutil

echo "Environment setup complete!"
echo "Please run 'conda activate eda_lite' to activate."
