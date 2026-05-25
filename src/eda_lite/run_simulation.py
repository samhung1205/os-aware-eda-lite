"""CLI entry point for running EDA-Lite SRAM sweep simulations."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from .cost_model import estimate_schedule_metrics, make_cost_config, make_os_profiles
from .model_loader import load_model_profile
from .schedulers import (
    ScheduleResult,
    dp_schedule,
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
]


def main() -> None:
    args = _parse_args()
    rows = run_simulation(
        profile_path=args.profile,
        config_path=args.config,
    )
    write_simulation_csv(args.output, rows)
    print(f"Wrote {len(rows)} simulation rows to {args.output}")


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
    raw_os_profile_file = _load_os_profile_file(config)
    raw_os_profiles = _merge_os_profile_definitions(
        config.get("os_profile_definitions"),
        raw_os_profile_file.get("os_profile_definitions"),
    )
    os_profiles = make_os_profiles(raw_os_profiles)
    os_profile_names = _os_profile_names(config, raw_os_profile_file)
    cost_config = make_cost_config(config.get("cost_model"))

    rows: list[dict[str, Any]] = []
    for sram_kb in sram_values:
        for os_profile_name in os_profile_names:
            for scheduler_name in scheduler_names:
                schedule = _run_scheduler(
                    scheduler_name=scheduler_name,
                    layers=model_profile.layers,
                    sram_kb=sram_kb,
                    os_profile_name=os_profile_name,
                    cost_config=cost_config,
                    os_profiles=os_profiles,
                )
                metrics = estimate_schedule_metrics(
                    schedule.subgraphs,
                    sram_kb=sram_kb,
                    os_profile_name=os_profile_name,
                    cost_config=cost_config,
                    os_profiles=os_profiles,
                )
                rows.append(
                    {
                        "model_name": model_profile.model_name,
                        "scheduler": schedule.scheduler,
                        "sram_kb": _format_number(sram_kb),
                        "os_profile": os_profile_name,
                        "num_subgraphs": len(schedule.subgraphs),
                        "max_fusion_depth": schedule.max_fusion_depth,
                        "peak_sram_kb": _format_number(metrics.peak_sram_kb),
                        "dram_traffic_kb": _format_number(metrics.dram_traffic_kb),
                        "estimated_energy": _format_number(metrics.estimated_energy),
                        "estimated_latency_ms": _format_number(metrics.estimated_latency_ms),
                        "os_aware_total_cost": _format_number(metrics.os_aware_total_cost),
                        "subgraphs": serialize_subgraphs(schedule.subgraphs),
                    }
                )
    return rows


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
    raise ValueError(f"Unknown scheduler '{scheduler_name}'.")


def _load_config(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as file:
        raw_config = json.load(file)
    if not isinstance(raw_config, dict):
        raise ValueError("Simulation config must be a JSON object.")
    return raw_config


def _load_os_profile_file(config: dict[str, Any]) -> dict[str, Any]:
    os_profile_file = config.get("os_profile_file")
    if os_profile_file is None:
        return {}
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
    return raw_profile_file


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
