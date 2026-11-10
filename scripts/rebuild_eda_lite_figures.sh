#!/usr/bin/env bash
# Rebuild the MobileViT pure vs OS-aware EDA-Lite CSVs and six-line figures.
#
# Provenance (Phase 1 / Batch 3, audit P0-3):
# - Every simulation CSV gets a <name>.provenance.json sidecar (input hashes).
# - Each model only receives OS profiles measured on that model.
# - Figure titles carry [OS profile: UNVERIFIED] / [OS profile: EXAMPLE] when the
#   OS-aware profile is not verified measured data.
# - RUNTIME_SWEEP_CONFIG selects the OS profile source. The default reproduces the
#   teammate-provided runtime-derived figures from the UNVERIFIED legacy profiles.
#   Once scripts/check_runtime_provenance.py reports VERIFIED, use
#   RUNTIME_SWEEP_CONFIG=experiments/eda_lite/mobilevit_runtime_aware_sweep.json
#   (pointed at runtime_os_profiles.json) and measured profile names.
set -euo pipefail

RUNTIME_SWEEP_CONFIG="${RUNTIME_SWEEP_CONFIG:-experiments/eda_lite/mobilevit_runtime_aware_sweep_legacy_unverified.json}"
PURE_PROFILE="${PURE_PROFILE:-pure}"
OS_PROFILE_S="${OS_PROFILE_S:-measured_overload_sweep_mobilevit_s_20_0fps_q5_d150_normal}"
OS_PROFILE_XXS="${OS_PROFILE_XXS:-measured_overload_sweep_mobilevit_xxs_20_0fps_q5_d150_normal}"
FIGURES_ROOT="${FIGURES_ROOT:-results/figures/eda_lite}"
CSV_ROOT="${CSV_ROOT:-results/csv}"

echo "Checking runtime provenance (informational; BLOCKED means no verifiable measured data)..."
set +e
python3 scripts/check_runtime_provenance.py
provenance_status=$?
set -e
if [[ "$provenance_status" -eq 2 ]]; then
  echo "錯誤：provenance 檢查為 BROKEN（檔案與記錄的雜湊不符），停止重建。" >&2
  exit 2
fi

echo "Rebuilding MobileViT pure and OS-aware EDA-Lite CSVs (OS profiles: ${RUNTIME_SWEEP_CONFIG})..."
for model in s xxs; do
  python3 -m src.eda_lite.run_simulation \
    --profile "data/model_profiles/mobilevit_${model}_simplified.json" \
    --config experiments/eda_lite/mobilevit_sram_sweep.json \
    --output "${CSV_ROOT}/eda_lite_mobilevit_${model}_pure.csv"

  python3 -m src.eda_lite.run_simulation \
    --profile "data/model_profiles/mobilevit_${model}_simplified.json" \
    --config "${RUNTIME_SWEEP_CONFIG}" \
    --output "${CSV_ROOT}/eda_lite_mobilevit_${model}_runtime_aware_sweep.csv"
done

echo "Rebuilding six-line comparison figures (${PURE_PROFILE} vs OS-aware)..."
python3 -m src.eda_lite.plot_6lines \
  --model mobilevit_s_simplified_profile_estimate \
  --pure-csv "${CSV_ROOT}/eda_lite_mobilevit_s_pure.csv" \
  --os-csv "${CSV_ROOT}/eda_lite_mobilevit_s_runtime_aware_sweep.csv" \
  --pure-profile "${PURE_PROFILE}" \
  --os-profile "${OS_PROFILE_S}" \
  --out-dir "${FIGURES_ROOT}/s"

python3 -m src.eda_lite.plot_6lines \
  --model mobilevit_xxs_simplified_profile_estimate \
  --pure-csv "${CSV_ROOT}/eda_lite_mobilevit_xxs_pure.csv" \
  --os-csv "${CSV_ROOT}/eda_lite_mobilevit_xxs_runtime_aware_sweep.csv" \
  --pure-profile "${PURE_PROFILE}" \
  --os-profile "${OS_PROFILE_XXS}" \
  --out-dir "${FIGURES_ROOT}/xxs"

echo "EDA-Lite comparison figures written under ${FIGURES_ROOT}/ (provenance sidecars under ${CSV_ROOT}/)"
