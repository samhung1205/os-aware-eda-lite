"""Build EDA-Lite OS pressure profiles from ROS2 runtime summary CSVs.

Calibration (Phase 1 / Batch 3, audit P1-7):

- ``latency_multiplier = avg_latency_ms / baseline`` where the baseline is the
  **same model's** idle run under the **same resource profile** (comparable
  conditions): ``fake_delay_ms == 0``, scenario ``fps_sweep`` preferred, lowest
  ``input_fps``, then lowest ``qos_depth``; repeated runs of that condition are
  averaged. Models are never normalised against each other, so a slower model
  is not reported as "OS pressure". ``--baseline-resource-profile`` makes every
  resource profile of a model use one profile's idle run instead (e.g. to see
  the effect of ``tuned`` relative to ``normal``). An explicit
  ``--baseline-latency-ms`` (one value, or ``MODEL=VALUE`` pairs) overrides it.
- ``memory_pressure = avg_memory_mb / reference_mb`` with a verifiable
  reference, in priority order: ``--memory-reference-mb`` (CLI), the run's
  effective cgroup ``memory.max`` (``memory_limit_mb``), the host's total RAM
  (``host_memory_mb``). Without any reference the builder refuses instead of
  normalising by the largest RSS seen.

Every baseline and reference used is written to ``metadata``. ``main`` also
records the SHA-256 of the summary and its manifest and marks the file
``verified`` only if the chain back to the raw CSVs checks out
(see ``src/provenance.py``); otherwise ``unverified`` with the reasons.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import re
from statistics import mean
import sys
from typing import Any, Iterable

from src.provenance import (
    CLASS_UNKNOWN,
    OS_PROFILE_SCHEMA,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    VALID_MEASUREMENT_CLASSES,
    file_record,
    read_json,
    resolve_ref,
    summary_manifest_path,
    verify_summary_manifest,
    write_json,
)

IDLE_SCENARIO = "fps_sweep"
CALIBRATION = {
    "latency": {
        "method": "per_model_idle_baseline",
        "formula": "latency_multiplier = avg_latency_ms / baseline_latency_ms(model, resource_profile)",
        "reference_condition": "fake_delay_ms=0; scenario fps_sweep preferred; lowest input_fps, then "
        "lowest qos_depth; repeated runs averaged",
        "floor": 0.1,
    },
    "memory": {
        "method": "absolute_reference",
        "formula": "memory_pressure = clamp(avg_memory_mb / memory_reference_mb, 0, 1)",
        "reference_priority": ["cli --memory-reference-mb", "run cgroup memory.max (memory_limit_mb)",
                               "host total RAM (host_memory_mb)"],
    },
}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    summary_rows = load_summary_rows(args.input)
    payload = build_os_profile_payload(
        summary_rows,
        baseline_latency_ms=_parse_baseline_arg(args.baseline_latency_ms),
        memory_reference_mb=args.memory_reference_mb,
        profile_prefix=args.profile_prefix,
        baseline_resource_profile=args.baseline_resource_profile,
    )
    attach_source_provenance(payload, args.input, args.output)
    meta = payload["metadata"]
    if args.require_verified and meta["provenance_status"] != STATUS_VERIFIED:
        print("錯誤：provenance 無法驗證，未寫出 OS profiles：", file=sys.stderr)
        for reason in meta["unverified_reasons"]:
            print(f"  - {reason}", file=sys.stderr)
        return 1
    write_os_profile_payload(args.output, payload)
    print(
        f"Wrote {len(payload['os_profiles'])} OS profiles to {args.output} "
        f"(provenance_status={meta['provenance_status']})"
    )
    for reason in meta["unverified_reasons"]:
        print(f"  UNVERIFIED: {reason}")
    return 0


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
    baseline_latency_ms: float | dict[str, float] | None = None,
    memory_reference_mb: float | None = None,
    profile_prefix: str = "runtime",
    baseline_resource_profile: str | None = None,
) -> dict[str, Any]:
    """Convert runtime summary rows into an OS profile payload with metadata.

    The payload is ``unverified`` until ``attach_source_provenance`` links it to
    a summary file whose manifest verifies.
    """

    rows = list(summary_rows)
    if not rows:
        raise ValueError("Cannot build OS profiles from empty summary rows.")
    if memory_reference_mb is not None and memory_reference_mb <= 0:
        raise ValueError("memory reference must be positive.")

    baselines = _latency_baselines(rows, baseline_latency_ms, baseline_resource_profile)

    profile_names: list[str] = []
    profile_definitions: dict[str, dict[str, float]] = {}
    profile_metadata: dict[str, dict[str, Any]] = {}
    classes: dict[str, str] = {}

    for row in rows:
        profile_name = _unique_name(_profile_name(row, profile_prefix), profile_definitions)
        avg_latency_ms = _required_float(row, "avg_latency_ms")
        deadline_miss_rate_pct = _optional_float(row.get("deadline_miss_rate_pct")) or 0.0
        drop_rate_pct = _drop_rate_pct(row)
        avg_memory_mb = _optional_float(row.get("avg_memory_mb"))
        baseline = baselines[_baseline_key(row, baseline_resource_profile)]

        latency_multiplier = max(CALIBRATION["latency"]["floor"], avg_latency_ms / baseline["latency_ms"])
        deadline_miss_rate = _clamp(deadline_miss_rate_pct / 100.0, 0.0, 1.0)
        drop_rate = _clamp(drop_rate_pct / 100.0, 0.0, 1.0)
        memory_pressure = 0.0
        memory_reference, memory_source = None, "not_measured"
        if avg_memory_mb is not None:
            memory_reference, memory_source = _memory_reference(row, memory_reference_mb)
            memory_pressure = _clamp(avg_memory_mb / memory_reference, 0.0, 1.0)

        measurement_class = (row.get("measurement_class") or "").strip() or CLASS_UNKNOWN
        classes[str(row.get("run_id", ""))] = measurement_class
        profile_names.append(profile_name)
        profile_definitions[profile_name] = {
            "latency_multiplier": round(latency_multiplier, 6),
            "deadline_miss_rate": round(deadline_miss_rate, 6),
            "memory_pressure": round(memory_pressure, 6),
            "drop_rate": round(drop_rate, 6),
        }
        profile_metadata[profile_name] = {
            "model_name": row.get("model_name", ""),
            "run_id": row.get("run_id", ""),
            "scenario": row.get("scenario", ""),
            "input_fps": row.get("input_fps", ""),
            "qos_depth": row.get("qos_depth", ""),
            "fake_delay_ms": row.get("fake_delay_ms", ""),
            "resource_profile": row.get("resource_profile", ""),
            "measurement_class": measurement_class,
            "avg_latency_ms": avg_latency_ms,
            "latency_baseline_ms": baseline["latency_ms"],
            "avg_memory_mb": avg_memory_mb,
            "memory_reference_mb": memory_reference,
            "memory_reference_source": memory_source,
        }

    reasons = ["built from in-memory summary rows; no source summary/manifest recorded"]
    reasons += [
        f"run {run_id or '?'}: measurement_class={cls} (resource limits not verified or no run metadata)"
        for run_id, cls in sorted(classes.items())
        if cls not in VALID_MEASUREMENT_CLASSES
    ]
    return {
        "os_profiles": profile_names,
        "os_profile_definitions": profile_definitions,
        "metadata": {
            "schema": OS_PROFILE_SCHEMA,
            "generator": "src.ros2_runtime.build_os_profiles",
            "provenance_status": STATUS_UNVERIFIED,
            "unverified_reasons": reasons,
            "source_summary": None,
            "source_manifest": None,
            "calibration": {
                **CALIBRATION,
                "baseline_resource_profile": baseline_resource_profile,
            },
            "baselines": list(baselines.values()),
            "profiles": profile_metadata,
        },
    }


def attach_source_provenance(payload: dict[str, Any], summary_path: str | Path, output_path: str | Path) -> None:
    """Record the summary/manifest hashes and decide ``verified`` vs ``unverified``."""

    meta = payload["metadata"]
    base = Path(output_path).resolve().parent
    summary_path = Path(summary_path)
    manifest_path = summary_manifest_path(summary_path)
    meta["source_summary"] = file_record(summary_path, base)
    meta["source_manifest"] = file_record(manifest_path, base) if manifest_path.is_file() else None

    reasons = verify_summary_manifest(manifest_path)
    reasons += [
        f"run {entry['run_id'] or '?'}: measurement_class={entry['measurement_class']}"
        for entry in meta["profiles"].values()
        if entry["measurement_class"] not in VALID_MEASUREMENT_CLASSES
    ]
    if not reasons:
        recorded = resolve_ref(read_json(manifest_path)["summary"]["path"], manifest_path.parent)
        if recorded.resolve() != summary_path.resolve():
            reasons.append(f"manifest {manifest_path} describes {recorded}, not {summary_path}")
    reasons = list(dict.fromkeys(reasons))
    meta["provenance_status"] = STATUS_UNVERIFIED if reasons else STATUS_VERIFIED
    meta["unverified_reasons"] = reasons


def write_os_profile_payload(output_path: str | Path, payload: dict[str, Any]) -> None:
    write_json(output_path, payload)


def _latency_baselines(
    rows: list[dict[str, str]],
    explicit: float | dict[str, float] | None,
    baseline_resource_profile: str | None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return ``{(model, resource_profile): baseline}`` for every key the rows need."""

    needed = sorted({_baseline_key(row, baseline_resource_profile) for row in rows})
    baselines: dict[tuple[str, str], dict[str, Any]] = {}
    for key in needed:
        model, resource = key
        value = explicit.get(model) if isinstance(explicit, dict) else explicit
        if value is not None:
            if value <= 0:
                raise ValueError("baseline latency must be positive.")
            baselines[key] = {"model_name": model, "resource_profile": resource, "latency_ms": float(value),
                              "source": "cli", "condition": None, "run_ids": []}
            continue
        candidates = [
            row for row in rows
            if row.get("model_name", "") == model
            and (resource == "*" or row.get("resource_profile", "") == resource)
            and _number(row.get("fake_delay_ms"), default=0.0) == 0.0
        ]
        if not candidates:
            raise ValueError(
                f"No idle reference run (fake_delay_ms=0) for model '{model}', resource profile "
                f"'{resource}'. Run the fps_sweep for this model, or pass --baseline-latency-ms "
                f"{model}=<ms>; models are never normalised against each other."
            )
        condition = min(_condition(row) for row in candidates)
        reference = [row for row in candidates if _condition(row) == condition]
        baselines[key] = {
            "model_name": model,
            "resource_profile": resource,
            "latency_ms": mean(_required_float(row, "avg_latency_ms") for row in reference),
            "source": "idle_run",
            "condition": {"scenario": reference[0].get("scenario", ""),
                          "input_fps": reference[0].get("input_fps", ""),
                          "qos_depth": reference[0].get("qos_depth", ""),
                          "fake_delay_ms": reference[0].get("fake_delay_ms", "0")},
            "run_ids": sorted(str(row.get("run_id", "")) for row in reference),
        }
    return baselines


def _baseline_key(row: dict[str, str], baseline_resource_profile: str | None) -> tuple[str, str]:
    resource = baseline_resource_profile or row.get("resource_profile", "")
    return (row.get("model_name", ""), resource)


def _condition(row: dict[str, str]) -> tuple:
    return (
        0 if row.get("scenario", "") == IDLE_SCENARIO else 1,
        row.get("scenario", ""),
        _number(row.get("input_fps"), default=float("inf")),
        _number(row.get("qos_depth"), default=float("inf")),
    )


def _memory_reference(row: dict[str, str], cli_reference: float | None) -> tuple[float, str]:
    if cli_reference is not None:
        return float(cli_reference), "cli"
    for field, source in (("memory_limit_mb", "cgroup_memory_max"), ("host_memory_mb", "host_total_ram")):
        value = _optional_float(row.get(field))
        if value is not None and value > 0:
            return value, source
    raise ValueError(
        f"Run '{row.get('run_id', '?')}' has avg_memory_mb but no verifiable memory reference "
        "(no cgroup memory limit or host RAM in its run metadata). Pass --memory-reference-mb "
        "with the real limit; normalising by the largest RSS seen is no longer supported."
    )


def _parse_baseline_arg(values: list[str] | None) -> float | dict[str, float] | None:
    if not values:
        return None
    if len(values) == 1 and "=" not in values[0]:
        return float(values[0])
    result: dict[str, float] = {}
    for item in values:
        if "=" not in item:
            raise ValueError("Use one number, or MODEL=VALUE pairs, for --baseline-latency-ms.")
        model, value = item.split("=", 1)
        result[model.strip()] = float(value)
    return result


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
    if value is None or not str(value).strip():
        return None
    return float(value)


def _number(value: str | None, default: float) -> float:
    parsed = _optional_float(value)
    return default if parsed is None else parsed


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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build EDA-Lite OS profiles from ROS2 runtime summary CSV."
    )
    parser.add_argument("--input", required=True, help="Path to ROS2 runtime summary CSV.")
    parser.add_argument("--output", required=True, help="Path to output OS profile JSON.")
    parser.add_argument(
        "--baseline-latency-ms",
        nargs="+",
        default=None,
        help="Override the per-model idle baseline: one value for every model, or MODEL=VALUE pairs.",
    )
    parser.add_argument(
        "--baseline-resource-profile",
        default=None,
        help="Use this resource profile's idle run as every resource profile's baseline "
        "(default: each resource profile uses its own idle run).",
    )
    parser.add_argument(
        "--memory-reference-mb",
        type=float,
        default=None,
        help="Memory limit used for memory_pressure. Default: the run's cgroup memory.max, "
        "else the host's total RAM, from run metadata.",
    )
    parser.add_argument(
        "--profile-prefix",
        default="runtime",
        help="Prefix for generated OS profile names.",
    )
    parser.add_argument(
        "--require-verified",
        action="store_true",
        help="Fail (write nothing) unless the summary verifies back to raw CSVs and run metadata.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
