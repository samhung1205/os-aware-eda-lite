"""Rebuild the Phase 2 / Phase 3 result tables from raw runs and compare them with the committed ones.

    python3 scripts/check_table_regeneration.py [--keep DIR]

Runs the same commands that produced ``results/csv/ros2_*`` (docs/DATA_PROVENANCE.md) into a
temporary directory -- the committed files are never touched -- then compares:

* every Phase 3 formal table and ``ros2_baseline_conditions.csv``: byte-identical;
* ``ros2_runtime_summary.csv`` / ``ros2_baseline_runs.csv`` (Phase 2, written before Phase 3
  added analyzer columns): every committed column has identical values in every row; the
  newer analyzer may only *add* columns.

Exit 0 when everything matches, 1 otherwise. Standard library only; ~30 s.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REFS = ["--reference-arm", "latest_q10", "--reference-arm", "guard_c5_q10", "--reference-arm", "legacy_q1"]
EXACT = ["ros2_phase3_formal_summary", "ros2_phase3_formal_runs", "ros2_phase3_formal_arms",
         "ros2_phase3_formal_paired", "ros2_phase3_formal_dynamic_phases", "ros2_phase3_formal_dynamic_arms",
         "ros2_phase3_formal_dynamic_paired", "ros2_baseline_conditions"]
COLUMNS = ["ros2_runtime_summary", "ros2_baseline_runs"]


def commands(out: Path) -> list[list[str]]:
    p3, p2 = "results/raw/ros2_phase3_formal", "results/raw/ros2"
    o = lambda name: str(out / f"{name}.csv")  # noqa: E731
    py = [sys.executable, "-m"]
    return [
        py + ["src.ros2_runtime.analyze_runtime", "--input", p3, "--summary-output", o("ros2_phase3_formal_summary"),
              "--warmup-frames", "10"],
        py + ["src.ros2_runtime.aggregate_scheduling", "--summary", o("ros2_phase3_formal_summary"), "--raw-dir", p3,
              "--runs-output", o("ros2_phase3_formal_runs"), "--conditions-output", o("ros2_phase3_formal_arms"),
              "--paired-output", o("ros2_phase3_formal_paired"), "--by-scenario", "--paired-stats", *REFS],
        py + ["src.ros2_runtime.analyze_dynamic_phases", "--raw-dir", p3,
              "--phases-output", o("ros2_phase3_formal_dynamic_phases"), "--arms-output", o("ros2_phase3_formal_dynamic_arms"),
              "--paired-output", o("ros2_phase3_formal_dynamic_paired"), *REFS],
        py + ["src.ros2_runtime.analyze_runtime", "--input", p2, "--summary-output", o("ros2_runtime_summary")],
        py + ["src.ros2_runtime.aggregate_baseline", "--summary", o("ros2_runtime_summary"), "--raw-dir", p2,
              "--runs-output", o("ros2_baseline_runs"), "--conditions-output", o("ros2_baseline_conditions"),
              "--figures-dir", str(out / "figures")],
    ]


def _rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def compare(out: Path) -> list[str]:
    problems = []
    for name in EXACT:
        if (out / f"{name}.csv").read_bytes() != (REPO / "results/csv" / f"{name}.csv").read_bytes():
            problems.append(f"{name}.csv differs from the committed file")
        else:
            print(f"OK      {name}.csv byte-identical")
    for name in COLUMNS:
        new_cols, new = _rows(out / f"{name}.csv")
        old_cols, old = _rows(REPO / "results/csv" / f"{name}.csv")
        missing = [c for c in old_cols if c not in new_cols]
        bad = [(i, c) for i, (a, b) in enumerate(zip(new, old)) for c in old_cols if a.get(c) != b[c]]
        if missing or bad or len(new) != len(old):
            problems.append(f"{name}.csv: {len(new)} vs {len(old)} rows, missing columns {missing[:3]}, "
                            f"{len(bad)} differing cells {bad[:3]}")
        else:
            print(f"OK      {name}.csv: {len(old)} rows x {len(old_cols)} committed columns identical "
                  f"(+{len(new_cols) - len(old_cols)} columns added by the current analyzer)")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--keep", help="write the regenerated tables here instead of a temporary directory")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="regen_") as tmp:
        out = Path(args.keep) if args.keep else Path(tmp)
        out.mkdir(parents=True, exist_ok=True)
        for cmd in commands(out):
            proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
            if proc.returncode != 0:
                print(f"FAILED  {' '.join(cmd[2:4])}\n{proc.stderr}", file=sys.stderr)
                return 1
        problems = compare(out)
    for p in problems:
        print(f"DIFF    {p}", file=sys.stderr)
    print("STATUS: " + ("REPRODUCED" if not problems else "MISMATCH"))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
