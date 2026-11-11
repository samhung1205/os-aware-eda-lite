#!/usr/bin/env bash
# ci_checks.sh - the checks GitHub Actions runs (.github/workflows/ci.yml), runnable locally.
#
#   bash scripts/ci_checks.sh all            # tests + shell + audit + provenance
#   bash scripts/ci_checks.sh tests          # unit / integration tests (stdlib only, verbose)
#   bash scripts/ci_checks.sh shell          # bash -n on every shell script
#   bash scripts/ci_checks.sh audit          # audit regressions: fails if any case is REPRODUCED
#   bash scripts/ci_checks.sh provenance     # runtime provenance gates: Phase 2 + Phase 3 (see below)
#   bash scripts/ci_checks.sh dashboard      # dashboard data bundle is current with the verified tables
#   bash scripts/ci_checks.sh repeat [N]     # run the test suite N times (default 5), keep every log
#
# Needs only python3 (3.10+), bash and git. No ROS 2, no pip packages.
# PYTHON overrides the interpreter; CI_LOG_DIR is where test logs are kept (default ci-logs/).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
PYTHON="${PYTHON:-python3}"
CI_LOG_DIR="${CI_LOG_DIR:-ci-logs}"
export PYTHONFAULTHANDLER=1      # dump tracebacks of all threads on a hard crash / hang signal
export PYTHONDONTWRITEBYTECODE=1 # never create __pycache__ in the checkout
export PYTHONHASHSEED=0          # deterministic set/dict iteration across runs

run_tests() {
  local log="$1"
  mkdir -p "$(dirname "$log")"
  echo "== tests: $("$PYTHON" --version 2>&1) -> $log"
  # -v names every test, so a failure/error in the log always says which test it was.
  if "$PYTHON" -m unittest discover -s tests -v >"$log" 2>&1; then
    tail -n 3 "$log"
  else
    local status=$?
    echo "!! test suite failed (exit $status). Failures/errors with tracebacks:" >&2
    # unittest prints the FAIL/ERROR blocks after the first ===== separator, then
    # the summary: show all of it so the CI log alone is enough to diagnose.
    sed -n '/^=\{20,\}$/,$p' "$log" >&2
    return "$status"
  fi
}

check_tests() {
  run_tests "$CI_LOG_DIR/tests.log"
}

check_repeat() {
  local n="${1:-5}" i failed=0
  for ((i = 1; i <= n; i++)); do
    if ! run_tests "$CI_LOG_DIR/repeat_${i}.log"; then
      failed=$((failed + 1))
    fi
  done
  echo "== repeat: $failed/$n runs failed (logs in $CI_LOG_DIR/repeat_*.log)"
  [[ "$failed" -eq 0 ]]
}

check_shell() {
  local f status=0
  while IFS= read -r -d '' f; do
    if bash -n "$f"; then
      echo "ok   $f"
    else
      echo "FAIL $f" >&2
      status=1
    fi
  done < <(git ls-files -z -- '*.sh' 2>/dev/null || find . -name '*.sh' -not -path './.venv/*' -print0)
  return "$status"
}

check_audit() {
  "$PYTHON" scripts/audit_repro.py --strict
}

# Runtime provenance gate.
#   exit 0 VERIFIED -> accepted only if real raw ROS 2 CSVs and run metadata are committed;
#                      a VERIFIED status without raw data means something was faked: fail.
#   exit 1 BLOCKED  -> expected while no real ROS 2 measurements exist: reported, not failed.
#                      CI never turns BLOCKED into VERIFIED.
#   exit 2 BROKEN   -> hash mismatch / stale sidecar / unverified limits: fail.
check_provenance() {
  local status=0
  "$PYTHON" scripts/check_runtime_provenance.py || status=$?
  local raw_csvs meta
  raw_csvs=$(find results/raw/ros2 -maxdepth 1 -name '*.csv' ! -name '*.publisher.csv' 2>/dev/null | wc -l | tr -d ' ')
  meta=$(find results/raw/ros2 -maxdepth 1 -name '*.meta.json' 2>/dev/null | wc -l | tr -d ' ')
  case "$status" in
    0)
      if [[ "$raw_csvs" -eq 0 || "$meta" -eq 0 ]]; then
        echo "!! provenance reported VERIFIED but results/raw/ros2 has ${raw_csvs} raw CSV(s) and ${meta} meta.json file(s)." >&2
        return 1
      fi
      echo "== provenance: VERIFIED (${raw_csvs} raw CSV(s), ${meta} run metadata file(s))"
      ;;
    1)
      echo "== provenance: BLOCKED (expected until real ROS 2 runs are committed; not a pass, not a failure)"
      if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
        echo "::warning title=Runtime provenance BLOCKED::No verified ROS 2 measurements yet (raw CSVs: ${raw_csvs}). Simulation results must not be reported as measured."
      fi
      ;;
    *)
      echo "!! provenance BROKEN (exit ${status})" >&2
      return "$status"
      ;;
  esac
  # Phase 3 formal scheduling benchmark: its own gate (a Phase 2 VERIFIED says nothing about it).
  local p3=0
  if [[ -f scripts/check_phase3_provenance.py ]]; then
    "$PYTHON" scripts/check_phase3_provenance.py || p3=$?
  else
    p3=1
  fi
  case "$p3" in
    0) echo "== phase 3 provenance: VERIFIED" ;;
    1) echo "== phase 3 provenance: BLOCKED (formal scheduling data not present; not a pass, not a failure)" ;;
    *) echo "!! phase 3 provenance BROKEN (exit ${p3})" >&2; return "$p3" ;;
  esac
}

# Phase 4 dashboard: the committed bundle (dashboard/data/) must equal a fresh build from the
# verified tables. Exit 1 BLOCKED / 2 BROKEN / 3 STALE all fail the check.
# Before that, the Phase 2 / Phase 3 tables are rebuilt from the raw runs into a temp dir and
# compared with the committed ones (scripts/check_table_regeneration.py), so CI covers
# raw runs -> tables -> dashboard bundle.
check_dashboard() {
  "$PYTHON" scripts/check_table_regeneration.py
  "$PYTHON" -m src.dashboard.build_data --check
}

cmd="${1:-all}"
shift || true
case "$cmd" in
  tests) check_tests ;;
  repeat) check_repeat "$@" ;;
  shell) check_shell ;;
  audit) check_audit ;;
  provenance) check_provenance ;;
  dashboard) check_dashboard ;;
  all)
    check_tests
    check_shell
    check_audit
    check_provenance
    check_dashboard
    ;;
  *)
    echo "usage: $0 {all|tests|repeat [N]|shell|audit|provenance|dashboard}" >&2
    exit 2
    ;;
esac
