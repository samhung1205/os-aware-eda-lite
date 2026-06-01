#!/usr/bin/env bash
set -euo pipefail

echo "Rebuilding MobileViT pure and OS-aware EDA-Lite CSVs..."

python3 -m src.eda_lite.run_simulation \
  --profile data/model_profiles/mobilevit_s_simplified.json \
  --config experiments/eda_lite/mobilevit_sram_sweep.json \
  --output results/csv/eda_lite_mobilevit_s_pure.csv

python3 -m src.eda_lite.run_simulation \
  --profile data/model_profiles/mobilevit_xxs_simplified.json \
  --config experiments/eda_lite/mobilevit_sram_sweep.json \
  --output results/csv/eda_lite_mobilevit_xxs_pure.csv

python3 -m src.eda_lite.run_simulation \
  --profile data/model_profiles/mobilevit_s_simplified.json \
  --config experiments/eda_lite/mobilevit_runtime_aware_sweep.json \
  --output results/csv/eda_lite_mobilevit_s_runtime_aware_sweep.csv

python3 -m src.eda_lite.run_simulation \
  --profile data/model_profiles/mobilevit_xxs_simplified.json \
  --config experiments/eda_lite/mobilevit_runtime_aware_sweep.json \
  --output results/csv/eda_lite_mobilevit_xxs_runtime_aware_sweep.csv

echo "Rebuilding six-line comparison figures..."
python3 -m src.eda_lite.plot_6lines

echo "EDA-Lite comparison figures written under results/figures/eda_lite/"
