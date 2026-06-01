"""Check whether ROS2 runtime artifacts are complete enough for reporting."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys


RAW_DIR = Path("results/raw/ros2")
SUMMARY_CSV = Path("results/csv/ros2_runtime_summary.csv")
OS_PROFILES = Path("experiments/eda_lite/runtime_os_profiles.json")

REQUIRED_SUMMARY_FIELDS = {
    "scenario",
    "model_name",
    "input_fps",
    "qos_depth",
    "fake_delay_ms",
    "resource_profile",
    "processed_frames",
    "dropped_frames",
    "drop_rate_pct",
    "deadline_miss_rate_pct",
    "avg_latency_ms",
    "p95_latency_ms",
    "avg_memory_mb",
}


def main() -> int:
    ok = True

    raw_csvs = sorted(path for path in RAW_DIR.glob("*.csv") if path.is_file())
    if raw_csvs:
        print(f"OK raw CSV files: {len(raw_csvs)} under {RAW_DIR}")
    else:
        ok = False
        print(f"MISSING raw CSV files under {RAW_DIR}")

    if SUMMARY_CSV.exists():
        missing_fields, row_count = _inspect_summary(SUMMARY_CSV)
        if missing_fields:
            ok = False
            print(f"INVALID summary CSV missing fields: {', '.join(sorted(missing_fields))}")
        else:
            print(f"OK summary CSV: {SUMMARY_CSV} ({row_count} rows)")
    else:
        ok = False
        print(f"MISSING summary CSV: {SUMMARY_CSV}")

    if OS_PROFILES.exists():
        profile_count = _count_os_profiles(OS_PROFILES)
        print(f"OK OS profile JSON: {OS_PROFILES} ({profile_count} profiles)")
    else:
        ok = False
        print(f"MISSING OS profile JSON: {OS_PROFILES}")

    if not ok:
        print("Runtime provenance is incomplete. Avoid calling runtime-derived values fully auditable measured results.")
        return 1

    print("Runtime provenance is complete enough for measured-result reporting.")
    return 0


def _inspect_summary(path: Path) -> tuple[set[str], int]:
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = set(reader.fieldnames or [])
        rows = list(reader)
    return REQUIRED_SUMMARY_FIELDS.difference(fieldnames), len(rows)


def _count_os_profiles(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    profiles = payload.get("os_profiles")
    if not isinstance(profiles, list):
        raise ValueError(f"{path} is missing list field 'os_profiles'.")
    return len(profiles)


if __name__ == "__main__":
    sys.exit(main())
