#!/usr/bin/env bash
# Phase 3 / Batch 2: formal interleaved A/B benchmark of the scheduling arms.
#
#   DRY_RUN=1 bash experiments/ros2/run_sched_formal.sh   # print the plan only
#   bash experiments/ros2/run_sched_formal.sh             # run it (clean git tree required)
#
# FORMAL_CONDITIONS: space-separated "name|model|input_fps|fake_delay_ms|fps_schedule|blocks"
#   (fps_schedule may be "-" = fixed rate; see run_sched_sweep.sh FPS_SCHEDULE).
# Schedule (deterministic, printed before anything runs):
#   ROUNDS = max(blocks). A condition with b blocks runs in b rounds spread evenly over
#   1..ROUNDS (b = ROUNDS -> every round; b = 3 of 5 -> rounds 1, 3, 5), so every condition
#   is measured across the whole session, not in one time slot.
#   Inside a round the conditions are rotated by (round - 1); the arm order of each block is
#   SCHED_ARMS rotated by (round - 1 + condition index) mod n_arms, so every arm takes
#   different positions across blocks (slow host drift is spread over the arms).
#   One block = one (condition, round) = every arm once, back to back, in one
#   scripts/run_baseline_experiments.sh SWEEPS=sched call (same taskset / systemd-run
#   MemoryMax + MemorySwapMax / nice scope and DDS probe gate as Phase 2 / Batch 2).
#   RUN_TAG = <FORMAL_TAG>_<name>_b<k> (k = block number of that condition) identifies the
#   block for the paired analysis.
# Before EVERY block: the git tree must be clean (the commit + dirty flag go to every
# meta.json) and the host must pass src/ros2_runtime/host_load_gate.py on CPU_SET and its SMT
# siblings (decisions appended to $RESULTS_DIR/load_gate.jsonl). A busy host stops the batch
# (exit 4) instead of measuring under load.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

FORMAL_CONDITIONS="${FORMAL_CONDITIONS:-s20|mobilevit_s|20|0|-|5 s10|mobilevit_s|10|0|-|3 s30|mobilevit_s|30|0|-|3 xxs30d25|mobilevit_xxs|30|25|-|3 sdyn|mobilevit_s|10|0|10@20,20@20,10@20|3}"
ARMS="${SCHED_ARMS:-legacy_qos:1 legacy_qos:5 fifo latest_frame deadline_guard adaptive}"
FORMAL_TAG="${FORMAL_TAG:-p3b2}"
export RESULTS_DIR="${RESULTS_DIR:-results/raw/ros2_phase3_formal}"
export RUN_SECONDS="${RUN_SECONDS:-65}"
DRY_RUN="${DRY_RUN:-0}"
LOAD_GATE="${LOAD_GATE:-1}"
LOAD_MAX_BUSY_PCT="${LOAD_MAX_BUSY_PCT:-15}"
LOAD_MAX_LOADAVG="${LOAD_MAX_LOADAVG:-6}"
LOAD_MAX_WAIT_S="${LOAD_MAX_WAIT_S:-1800}"

if [[ "$DRY_RUN" != "1" && -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "錯誤：git working tree 有未提交的修改；formal benchmark 拒絕執行（meta.json 需記錄乾淨的 commit）。" >&2
  exit 3
fi

rotate() {  # rotate <n> <items...>
  local n="$1"; shift
  local items=("$@") count="$#" i out=()
  for ((i = 0; i < count; i++)); do out+=("${items[$(((i + n) % count))]}"); done
  echo "${out[*]}"
}

read -r -a conditions <<< "$FORMAL_CONDITIONS"
read -r -a arms <<< "$ARMS"
rounds=0
for c in "${conditions[@]}"; do
  IFS='|' read -r _ _ _ _ _ b <<< "$c"
  [[ "$b" =~ ^[1-9][0-9]*$ ]] || { echo "錯誤：condition '$c' 的 blocks 不是正整數。" >&2; exit 2; }
  (( b > rounds )) && rounds=$b
done

# in_round <blocks> <round> -> prints the block number k if the condition runs in this round
in_round() {
  local b="$1" r="$2" i target
  for ((i = 0; i < b; i++)); do
    if (( b == 1 )); then target=1; else target=$(( (i * (rounds - 1) * 2 + (b - 1)) / ((b - 1) * 2) + 1 )); fi
    if (( target == r )); then echo $((i + 1)); return 0; fi
  done
  return 1
}

plan=()
for ((r = 1; r <= rounds; r++)); do
  order=($(rotate $(((r - 1) % ${#conditions[@]})) "${conditions[@]}"))
  for c in "${order[@]}"; do
    IFS='|' read -r name model fps delay schedule b <<< "$c"
    k=$(in_round "$b" "$r") || continue
    idx=0; for ((i = 0; i < ${#conditions[@]}; i++)); do [[ "${conditions[$i]}" == "$c" ]] && idx=$i; done
    plan+=("$r|$name|$k|$model|$fps|$delay|$schedule|$(rotate $(((r - 1 + idx) % ${#arms[@]})) "${arms[@]}")")
  done
done

echo "Formal plan (round | condition | block | model | fps | delay | schedule | arm order),"
echo "  RUN_SECONDS=${RUN_SECONDS}, RESULTS_DIR=${RESULTS_DIR}, ${#plan[@]} blocks x ${#arms[@]} arms:"
printf '  %s\n' "${plan[@]}"
[[ "$DRY_RUN" == "1" ]] && exit 0

mkdir -p "$RESULTS_DIR"
for entry in "${plan[@]}"; do
  IFS='|' read -r r name k model fps delay schedule arm_order <<< "$entry"
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "錯誤：執行期間 git working tree 被修改；停止於 round ${r} ${name} block ${k} 之前。" >&2
    exit 3
  fi
  if [[ "$LOAD_GATE" == "1" ]]; then
    if ! "${PYTHON_BIN:-python3}" -m src.ros2_runtime.host_load_gate --cpus "${CPU_SET:?CPU_SET is required}" \
        --max-busy-pct "$LOAD_MAX_BUSY_PCT" --max-loadavg "$LOAD_MAX_LOADAVG" \
        --max-wait-s "$LOAD_MAX_WAIT_S" --log "$RESULTS_DIR/load_gate.jsonl" \
        --label "${FORMAL_TAG}_${name}_b${k}"; then
      echo "錯誤：主機持續高負載，停止於 round ${r} ${name} block ${k} 之前（未量測）。" >&2
      exit 4
    fi
  fi
  [[ "$schedule" == "-" ]] && schedule=""
  echo "== $(date -Is) round ${r} ${name} block ${k} (${model} ${fps} FPS d${delay} ${schedule:-fixed}): ${arm_order}"
  MODELS="$model" SWEEPS=sched INPUT_FPS="$fps" FAKE_DELAY_MS="$delay" FPS_SCHEDULE="$schedule" \
    SCHED_ARMS="$arm_order" RUN_TAG="${FORMAL_TAG}_${name}_b${k}" bash scripts/run_baseline_experiments.sh
done
echo "FORMAL_DONE $(date -Is)"
