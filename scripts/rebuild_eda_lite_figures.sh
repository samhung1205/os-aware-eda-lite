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

# Six-line charts: "pure" (compiler-only baseline) vs one OS-aware profile per model.
# Override the compared profile or output root with environment variables.
PURE_PROFILE="${PURE_PROFILE:-pure}"
OS_PROFILE_S="${OS_PROFILE_S:-measured_overload_sweep_mobilevit_s_20_0fps_q5_d150_normal}"
OS_PROFILE_XXS="${OS_PROFILE_XXS:-measured_overload_sweep_mobilevit_xxs_20_0fps_q5_d150_normal}"
FIGURES_ROOT="${FIGURES_ROOT:-results/figures/eda_lite}"

echo "Rebuilding six-line comparison figures (${PURE_PROFILE} vs OS-aware)..."
python3 -m src.eda_lite.plot_6lines \
  --model mobilevit_s_simplified_profile_estimate \
  --pure-csv results/csv/eda_lite_mobilevit_s_pure.csv \
  --os-csv results/csv/eda_lite_mobilevit_s_runtime_aware_sweep.csv \
  --pure-profile "${PURE_PROFILE}" \
  --os-profile "${OS_PROFILE_S}" \
  --out-dir "${FIGURES_ROOT}/s"

python3 -m src.eda_lite.plot_6lines \
  --model mobilevit_xxs_simplified_profile_estimate \
  --pure-csv results/csv/eda_lite_mobilevit_xxs_pure.csv \
  --os-csv results/csv/eda_lite_mobilevit_xxs_runtime_aware_sweep.csv \
  --pure-profile "${PURE_PROFILE}" \
  --os-profile "${OS_PROFILE_XXS}" \
  --out-dir "${FIGURES_ROOT}/xxs"

echo "EDA-Lite comparison figures written under ${FIGURES_ROOT}/"
