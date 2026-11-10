"""CLI entry point for running EDA-Lite SRAM sweep simulations."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from collections import Counter
from dataclasses import replace

from src.provenance import (
    SIMULATION_PROVENANCE_SCHEMA,
    STATUS_BUILTIN,
    STATUS_INLINE,
    STATUS_UNVERIFIED,
    assess_os_profile_payload,
    file_record,
    git_state,
    os_profile_models,
    simulation_provenance_path,
    write_json,
)

from .cost_model import estimate_schedule_metrics, make_cost_config, make_os_profiles
from .model_loader import load_model_profile
from .schedulers import (
    InfeasibleScheduleError,
    ScheduleResult,
    dp_schedule,
    exhaustive_schedule,
    greedy_schedule,
    layerwise_schedule,
    serialize_subgraphs,
)


CSV_FIELDS = [
    "model_name",
    "scheduler",
    "sram_kb",
    "os_profile",
    "num_subgraphs",
    "max_fusion_depth",
    "peak_sram_kb",
    "dram_traffic_kb",
    "estimated_energy",
    "estimated_latency_ms",
    "os_aware_total_cost",
    "subgraphs",
    # Appended in Phase 1 / Batch 2; older CSVs without them are still readable.
    "feasible",
    "infeasible_reason",
    "deadline_ms",
    "effective_latency_ms",
    "latency_cost",
    "deadline_cost",
    "memory_pressure_cost",
    "communication_pressure_cost",
    # Appended in Phase 1 / Batch 3: builtin / inline / example / verified / unverified.
    "os_profile_provenance",
]

# Scheduler-dependent columns left empty when a scheduler has no feasible schedule.
_RESULT_FIELDS = [
    "num_subgraphs",
    "max_fusion_depth",
    "peak_sram_kb",
    "dram_traffic_kb",
    "estimated_energy",
    "estimated_latency_ms",
    "os_aware_total_cost",
    "subgraphs",
    "effective_latency_ms",
    "latency_cost",
    "deadline_cost",
    "memory_pressure_cost",
    "communication_pressure_cost",
]


def main() -> None:
    args = _parse_args()
    rows = run_simulation(
        profile_path=args.profile,
        config_path=args.config,
    )
    write_simulation_csv(args.output, rows)
    config = _load_config(args.config)
    config["__config_dir"] = str(Path(args.config).resolve().parent)
    sidecar = write_simulation_provenance(
        args.output, rows, args.config, config, [args.profile], "src.eda_lite.run_simulation"
    )
    print(f"Wrote {len(rows)} simulation rows to {args.output} (provenance: {sidecar})")


def run_simulation(profile_path: str | Path, config_path: str | Path) -> list[dict[str, Any]]:
    config = _load_config(config_path)
    config["__config_dir"] = str(Path(config_path).resolve().parent)
    return run_simulation_with_config(profile_path=profile_path, config=config)


def run_simulation_with_config(
    profile_path: str | Path,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run one model profile against an already-loaded simulation config."""

    model_profile = load_model_profile(profile_path)

    sram_values = _require_number_list(config, "sram_kb")
    scheduler_names = _require_string_list(config, "schedulers")
    raw_os_profile_file, os_profile_path = _load_os_profile_file(config)
    file_status, file_reasons = _os_profile_file_status(raw_os_profile_file, os_profile_path)
    if file_status == STATUS_UNVERIFIED and config.get("allow_unverified_os_profiles") is not True:
        raise ValueError(
            f"OS profile file {os_profile_path} is UNVERIFIED and cannot be used as measured data: "
            + "; ".join(file_reasons)
            + ". Regenerate it from raw ROS2 CSVs (scripts/check_runtime_provenance.py), or set "
            '"allow_unverified_os_profiles": true to run it with rows labelled unverified.'
        )
    raw_os_profiles = _merge_os_profile_definitions(
        config.get("os_profile_definitions"),
        raw_os_profile_file.get("os_profile_definitions"),
    )
    os_profiles = make_os_profiles(raw_os_profiles)
    os_profile_names = _os_profile_names(config, raw_os_profile_file)
    unknown_profiles = [name for name in os_profile_names if name not in os_profiles]
    if unknown_profiles:
        raise ValueError(f"Unknown OS profile(s): {', '.join(unknown_profiles)}.")
    os_profile_names = select_profiles_for_model(
        os_profile_names,
        os_profile_models(raw_os_profile_file) if os_profile_path else {},
        model_profile.model_name,
        model_profile.runtime_model_name,
        explicit="os_profiles" in config,
    )
    inline_names = set(config.get("os_profile_definitions") or {})
    file_names = set(raw_os_profile_file.get("os_profile_definitions") or {})

    def profile_provenance(name: str) -> str:
        if name in inline_names:
            return STATUS_INLINE
        if name in file_names:
            return file_status
        return STATUS_BUILTIN

    base_cost_config = make_cost_config(config.get("cost_model"))
    # Optional sweep dimension: a top-level "deadline_ms" list overrides
    # cost_model.deadline_ms (simulated-latency units, see README).
    if "deadline_ms" in config:
        deadline_values = _require_number_list(config, "deadline_ms")
    else:
        deadline_values = [base_cost_config.deadline_ms]

    rows: list[dict[str, Any]] = []
    for sram_kb in sram_values:
        for deadline_ms in deadline_values:
            cost_config = replace(base_cost_config, deadline_ms=deadline_ms)
            for os_profile_name in os_profile_names:
                for scheduler_name in scheduler_names:
                    row: dict[str, Any] = {
                        "model_name": model_profile.model_name,
                        "scheduler": scheduler_name,
                        "sram_kb": _format_number(sram_kb),
                        "os_profile": os_profile_name,
                        "deadline_ms": _format_number(deadline_ms),
                        "os_profile_provenance": profile_provenance(os_profile_name),
                    }
                    try:
                        schedule = _run_scheduler(
                            scheduler_name=scheduler_name,
                            layers=model_profile.layers,
                            sram_kb=sram_kb,
                            os_profile_name=os_profile_name,
                            cost_config=cost_config,
                            os_profiles=os_profiles,
                        )
                    except InfeasibleScheduleError as exc:
                        row.update({field: "" for field in _RESULT_FIELDS})
                        row.update({"feasible": "false", "infeasible_reason": str(exc)})
                        rows.append(row)
                        continue
                    metrics = estimate_schedule_metrics(
                        schedule.subgraphs,
                        sram_kb=sram_kb,
                        os_profile_name=os_profile_name,
                        cost_config=cost_config,
                        os_profiles=os_profiles,
                    )
                    breakdown = metrics.breakdown
                    row.update(
                        {
                            "num_subgraphs": len(schedule.subgraphs),
                            "max_fusion_depth": schedule.max_fusion_depth,
                            "peak_sram_kb": _format_number(metrics.peak_sram_kb),
                            "dram_traffic_kb": _format_number(metrics.dram_traffic_kb),
                            "estimated_energy": _format_number(metrics.estimated_energy),
                            "estimated_latency_ms": _format_number(metrics.estimated_latency_ms),
                            "os_aware_total_cost": _format_number(metrics.os_aware_total_cost),
                            "subgraphs": serialize_subgraphs(schedule.subgraphs),
                            "feasible": "true",
                            "infeasible_reason": "",
                            "effective_latency_ms": _format_number(
                                breakdown.effective_latency_ms
                            ),
                            "latency_cost": _format_number(breakdown.latency_cost),
                            "deadline_cost": _format_number(breakdown.deadline_cost),
                            "memory_pressure_cost": _format_number(
                                breakdown.memory_pressure_cost
                            ),
                            "communication_pressure_cost": _format_number(
                                breakdown.communication_pressure_cost
                            ),
                        }
                    )
                    rows.append(row)
    return rows


def select_profiles_for_model(
    names: list[str],
    profile_models: dict[str, str | None],
    model_name: str,
    runtime_model_name: str | None,
    explicit: bool,
) -> list[str]:
    """Keep only OS profiles measured on this model (model-agnostic ones always pass).

    Runtime-derived profiles carry the ROS2 model they were measured on. They are
    applied only to the simulation model with the same ``runtime_model_name``:
    names taken from the profile file are filtered, explicitly configured names
    that belong to another model raise ValueError.
    """

    specific = {name: model for name, model in profile_models.items() if model}
    used_specific = [name for name in names if name in specific]
    if not used_specific:
        return list(names)
    if runtime_model_name is None:
        raise ValueError(
            f"OS profiles {used_specific[:3]}... are model-specific, but model profile "
            f"'{model_name}' has no 'runtime_model_name' to match them against."
        )
    mismatched = [name for name in used_specific if specific[name] != runtime_model_name]
    if explicit and mismatched:
        raise ValueError(
            f"OS profile(s) {', '.join(mismatched)} were measured on another model, not "
            f"'{runtime_model_name}'; runtime-aware simulation must not mix models."
        )
    selected = [name for name in names if name not in mismatched]
    if not selected:
        raise ValueError(f"No OS profiles measured on '{runtime_model_name}' in the profile file.")
    return selected


def describe_os_profile_source(config: dict[str, Any]) -> dict[str, Any] | None:
    """Path, hash and provenance status of the config's ``os_profile_file`` (None if unused)."""

    payload, path = _load_os_profile_file(config)
    if path is None:
        return None
    status, reasons = _os_profile_file_status(payload, path)
    return {"path": path, "provenance_status": status, "unverified_reasons": reasons}


def write_simulation_provenance(
    output_path: str | Path,
    rows: list[dict[str, Any]],
    config_path: str | Path,
    config: dict[str, Any],
    model_profile_paths: list[str | Path],
    generator: str,
) -> Path:
    """Write ``<output stem>.provenance.json`` linking a simulation CSV to its inputs."""

    sidecar = simulation_provenance_path(output_path)
    base = sidecar.resolve().parent
    source = describe_os_profile_source(config)
    os_profile_file = None
    if source is not None:
        os_profile_file = {
            **file_record(source["path"], base),
            "provenance_status": source["provenance_status"],
            "unverified_reasons": source["unverified_reasons"],
        }
    write_json(
        sidecar,
        {
            "schema": SIMULATION_PROVENANCE_SCHEMA,
            "generator": generator,
            "git": git_state(),
            "output": file_record(output_path, base),
            "config": file_record(config_path, base),
            "model_profiles": [file_record(path, base) for path in model_profile_paths],
            "os_profile_file": os_profile_file,
            "rows": len(rows),
            "rows_by_os_profile_provenance": dict(
                sorted(Counter(str(row.get("os_profile_provenance", "")) for row in rows).items())
            ),
            "os_profiles": sorted({str(row["os_profile"]) for row in rows}),
        },
    )
    return sidecar


def write_simulation_csv(output_path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _run_scheduler(
    scheduler_name: str,
    layers,
    sram_kb: float,
    os_profile_name: str,
    cost_config,
    os_profiles,
) -> ScheduleResult:
    if scheduler_name == "layerwise":
        return layerwise_schedule(layers, sram_kb=sram_kb, cost_config=cost_config)
    if scheduler_name == "greedy":
        return greedy_schedule(layers, sram_kb=sram_kb, cost_config=cost_config)
    if scheduler_name == "dp":
        return dp_schedule(
            layers,
            sram_kb=sram_kb,
            os_profile_name=os_profile_name,
            cost_config=cost_config,
            os_profiles=os_profiles,
        )
    if scheduler_name == "exhaustive":
        return exhaustive_schedule(
            layers,
            sram_kb=sram_kb,
            os_profile_name=os_profile_name,
            cost_config=cost_config,
            os_profiles=os_profiles,
        )
    raise ValueError(f"Unknown scheduler '{scheduler_name}'.")


def _load_config(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as file:
        raw_config = json.load(file)
    if not isinstance(raw_config, dict):
        raise ValueError("Simulation config must be a JSON object.")
    return raw_config


def _os_profile_file_status(payload: dict[str, Any], path: Path | None) -> tuple[str | None, list[str]]:
    if path is None:
        return None, []
    return assess_os_profile_payload(payload, path)


def _load_os_profile_file(config: dict[str, Any]) -> tuple[dict[str, Any], Path | None]:
    os_profile_file = config.get("os_profile_file")
    if os_profile_file is None:
        return {}, None
    if not isinstance(os_profile_file, str) or not os_profile_file.strip():
        raise ValueError("os_profile_file must be a non-empty string.")

    path = Path(os_profile_file)
    if not path.is_absolute():
        config_dir = Path(str(config.get("__config_dir", ".")))
        path = config_dir / path

    with path.open("r", encoding="utf-8") as file:
        raw_profile_file = json.load(file)
    if not isinstance(raw_profile_file, dict):
        raise ValueError("OS profile file must be a JSON object.")
    return raw_profile_file, path


def _merge_os_profile_definitions(
    inline_profiles,
    file_profiles,
) -> dict[str, Any] | None:
    merged_profiles: dict[str, Any] = {}
    for profile_source in (file_profiles, inline_profiles):
        if profile_source is None:
            continue
        if not isinstance(profile_source, dict):
            raise ValueError("os_profile_definitions must be a JSON object.")
        merged_profiles.update(profile_source)
    return merged_profiles or None


def _os_profile_names(
    config: dict[str, Any],
    raw_os_profile_file: dict[str, Any],
) -> list[str]:
    if "os_profiles" in config:
        return _require_string_list(config, "os_profiles")
    if "os_profiles" in raw_os_profile_file:
        return _require_string_list(raw_os_profile_file, "os_profiles")
    raise ValueError("Config requires a non-empty list 'os_profiles'.")


def _require_number_list(config: dict[str, Any], field_name: str) -> list[float]:
    value = config.get(field_name)
    if not isinstance(value, list) or not value:
        raise ValueError(f"Config requires a non-empty list '{field_name}'.")
    values: list[float] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{field_name}[{index}] must be a number.")
        if item <= 0:
            raise ValueError(f"{field_name}[{index}] must be positive.")
        values.append(float(item))
    return values


def _require_string_list(config: dict[str, Any], field_name: str) -> list[str]:
    value = config.get(field_name)
    if not isinstance(value, list) or not value:
        raise ValueError(f"Config requires a non-empty list '{field_name}'.")
    values: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name}[{index}] must be a non-empty string.")
        values.append(item)
    return values


def _format_number(value: float) -> str:
    return f"{value:.6g}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run EDA-Lite fusion simulation.")
    parser.add_argument("--profile", required=True, help="Path to model profile JSON.")
    parser.add_argument("--config", required=True, help="Path to simulation config JSON.")
    parser.add_argument("--output", required=True, help="Path to output CSV.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
