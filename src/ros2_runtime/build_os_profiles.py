"""Build EDA-Lite OS pressure profiles from ROS2 runtime summary CSVs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
from typing import Any, Iterable


def main() -> None:
    args = _parse_args()
    summary_rows = load_summary_rows(args.input)
    payload = build_os_profile_payload(
        summary_rows,
        baseline_latency_ms=args.baseline_latency_ms,
        memory_reference_mb=args.memory_reference_mb,
        profile_prefix=args.profile_prefix,
    )
    write_os_profile_payload(args.output, payload)
    print(f"Wrote {len(payload['os_profiles'])} OS profiles to {args.output}")


def load_summary_rows(input_path: str | Path) -> list[dict[str, str]]:
    path = Path(input_path)
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError("Runtime summary CSV is missing a header row.")
        rows = list(reader)
    if not rows:
        raise ValueError("Runtime summary CSV contains no rows.")
    return rows


def build_os_profile_payload(
    summary_rows: Iterable[dict[str, str]],
    baseline_latency_ms: float | None = None,
    memory_reference_mb: float | None = None,
    profile_prefix: str = "runtime",
) -> dict[str, Any]:
    rows = list(summary_rows)
    if not rows:
        raise ValueError("Cannot build OS profiles from empty summary rows.")

    latencies = [_required_float(row, "avg_latency_ms") for row in rows]
    baseline = baseline_latency_ms if baseline_latency_ms is not None else min(latencies)
    if baseline <= 0:
        raise ValueError("baseline latency must be positive.")

    memory_values = [_optional_float(row.get("avg_memory_mb")) for row in rows]
    present_memory_values = [value for value in memory_values if value is not None]
    memory_reference = memory_reference_mb
    if memory_reference is None and present_memory_values:
        memory_reference = max(present_memory_values)

    profile_names: list[str] = []
    profile_definitions: dict[str, dict[str, float]] = {}

    for row in rows:
        profile_name = _unique_name(_profile_name(row, profile_prefix), profile_definitions)
        avg_latency_ms = _required_float(row, "avg_latency_ms")
        deadline_miss_rate_pct = _optional_float(row.get("deadline_miss_rate_pct")) or 0.0
        drop_rate_pct = _drop_rate_pct(row)
        avg_memory_mb = _optional_float(row.get("avg_memory_mb"))

        latency_multiplier = max(0.1, avg_latency_ms / baseline)
        deadline_miss_rate = _clamp(deadline_miss_rate_pct / 100.0, 0.0, 1.0)
        drop_rate = _clamp(drop_rate_pct / 100.0, 0.0, 1.0)
        memory_pressure = 0.0
        if avg_memory_mb is not None and memory_reference is not None and memory_reference > 0:
            memory_pressure = _clamp(avg_memory_mb / memory_reference, 0.0, 1.0)

        profile_names.append(profile_name)
        profile_definitions[profile_name] = {
            "latency_multiplier": round(latency_multiplier, 6),
            "deadline_miss_rate": round(deadline_miss_rate, 6),
            "memory_pressure": round(memory_pressure, 6),
            "drop_rate": round(drop_rate, 6),
        }

    return {
        "os_profiles": profile_names,
        "os_profile_definitions": profile_definitions,
    }


def write_os_profile_payload(output_path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
        file.write("\n")


def _profile_name(row: dict[str, str], prefix: str) -> str:
    parts = [
        prefix,
        row.get("scenario", "scenario"),
        row.get("model_name", "model"),
        f"{row.get('input_fps', 'fps')}fps",
        f"q{row.get('qos_depth', 'qos')}",
        f"d{row.get('fake_delay_ms', '0')}",
        row.get("resource_profile", "normal"),
    ]
    joined = "_".join(str(part) for part in parts if str(part).strip())
    return _slugify(joined)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "runtime_profile"


def _unique_name(name: str, existing: dict[str, Any]) -> str:
    if name not in existing:
        return name
    suffix = 2
    while f"{name}_{suffix}" in existing:
        suffix += 1
    return f"{name}_{suffix}"


def _required_float(row: dict[str, str], field_name: str) -> float:
    value = _optional_float(row.get(field_name))
    if value is None:
        raise ValueError(f"Runtime summary row is missing numeric '{field_name}'.")
    return value


def _optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)


def _drop_rate_pct(row: dict[str, str]) -> float:
    """Return the run's drop rate.

    Summaries written before drop accounting existed have no ``drop_rate_pct``
    column and keep the documented default of 0. A present but empty value means
    the analyzer could not determine drops (frame_accounting=unavailable); it is
    rejected instead of being treated as 0%.
    """

    if "drop_rate_pct" not in row:
        return 0.0
    value = _optional_float(row.get("drop_rate_pct"))
    if value is None:
        raise ValueError(
            f"Runtime summary row for run_id '{row.get('run_id', '')}' has no drop_rate_pct "
            f"(frame_accounting={row.get('frame_accounting', 'unknown')}); refusing to assume 0%."
        )
    return value


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build EDA-Lite OS profiles from ROS2 runtime summary CSV."
    )
    parser.add_argument("--input", required=True, help="Path to ROS2 runtime summary CSV.")
    parser.add_argument("--output", required=True, help="Path to output OS profile JSON.")
    parser.add_argument(
        "--baseline-latency-ms",
        type=float,
        default=None,
        help="Latency baseline for multiplier calculation. Defaults to the minimum average latency.",
    )
    parser.add_argument(
        "--memory-reference-mb",
        type=float,
        default=None,
        help="Memory reference for memory_pressure. Defaults to max avg_memory_mb in the summary.",
    )
    parser.add_argument(
        "--profile-prefix",
        default="runtime",
        help="Prefix for generated OS profile names.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
