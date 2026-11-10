#!/usr/bin/env bash
# Phase 3 / Batch 1 pilot: short interleaved A/B runs of the scheduling arms.
#
#   bash experiments/ros2/run_sched_pilot.sh            # REPEATS=3, RUN_SECONDS=40
#
# Schedule (deterministic, written to stdout before anything runs):
#   for repeat r in 1..REPEATS:
#     conditions in PILOT_CONDITIONS order (reversed on even repeats)
#       arms = SCHED_ARMS rotated left by (r - 1 + condition index) -> every arm takes
#       different positions across repeats/conditions, so slow host drift is spread over arms.
#   Each (repeat, condition) is one call of scripts/run_baseline_experiments.sh SWEEPS=sched,
#   i.e. the same taskset / systemd-run (MemoryMax, MemorySwapMax) / nice scope and DDS gates
#   as the Phase 2 baseline. RUN_TAG = <PILOT_TAG>_r<repeat>.
# Requires a clean git tree (the commit is recorded in every meta.json).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

REPEATS="${REPEATS:-3}"
PILOT_CONDITIONS="${PILOT_CONDITIONS:-mobilevit_s:10 mobilevit_s:20 mobilevit_xxs:20 mobilevit_xxs:60}"
ARMS="${SCHED_ARMS:-legacy_qos:1 legacy_qos:5 fifo latest_frame adaptive}"
PILOT_TAG="${PILOT_TAG:-p3b1}"
export RESULTS_DIR="${RESULTS_DIR:-results/raw/ros2_phase3_pilot}"
export RUN_SECONDS="${RUN_SECONDS:-40}"
DRY_RUN="${DRY_RUN:-0}"

if [[ "$DRY_RUN" != "1" && -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "錯誤：git working tree 有未提交的修改；pilot 拒絕執行（meta.json 需記錄乾淨的 commit）。" >&2
  exit 3
fi

rotate() {  # rotate <n> <items...>
  local n="$1"; shift
  local items=("$@") count="$#" i out=()
  for ((i = 0; i < count; i++)); do out+=("${items[$(((i + n) % count))]}"); done
  echo "${out[*]}"
}

read -r -a conditions <<< "$PILOT_CONDITIONS"
read -r -a arms <<< "$ARMS"
plan=()
for ((r = 1; r <= REPEATS; r++)); do
  order=("${conditions[@]}")
  if (( r % 2 == 0 )); then
    order=(); for ((i = ${#conditions[@]} - 1; i >= 0; i--)); do order+=("${conditions[$i]}"); done
  fi
  for c in "${order[@]}"; do
    idx=0; for ((i = 0; i < ${#conditions[@]}; i++)); do [[ "${conditions[$i]}" == "$c" ]] && idx=$i; done
    plan+=("$r|${c%%:*}|${c##*:}|$(rotate $(((r - 1 + idx) % ${#arms[@]})) "${arms[@]}")")
  done
done

echo "Pilot plan (repeat | model | fps | arm order), RUN_SECONDS=${RUN_SECONDS}, RESULTS_DIR=${RESULTS_DIR}:"
printf '  %s\n' "${plan[@]}"
[[ "$DRY_RUN" == "1" ]] && exit 0

for entry in "${plan[@]}"; do
  IFS='|' read -r r model fps arm_order <<< "$entry"
  echo "== $(date -Is) repeat ${r} ${model} ${fps} FPS: ${arm_order}"
  MODELS="$model" SWEEPS=sched INPUT_FPS="$fps" SCHED_ARMS="$arm_order" \
    RUN_TAG="${PILOT_TAG}_r${r}" bash scripts/run_baseline_experiments.sh
done
echo "PILOT_DONE $(date -Is)"
