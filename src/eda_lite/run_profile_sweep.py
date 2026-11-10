"""Batch runner for comparing multiple simplified model profiles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .run_simulation import (
    run_simulation_with_config,
    write_simulation_csv,
    write_simulation_provenance,
)


def main() -> None:
    args = _parse_args()
    rows = run_profile_sweep(args.config)
    write_simulation_csv(args.output, rows)
    config_path = Path(args.config)
    config = _load_profile_sweep_config(config_path)
    simulation_config = _require_dict(config, "simulation")
    simulation_config.setdefault("__config_dir", str(config_path.resolve().parent))
    profiles = [_resolve_path(config_path.parent, p) for p in _require_string_list(config, "profiles")]
    sidecar = write_simulation_provenance(
        args.output, rows, config_path, simulation_config, profiles, "src.eda_lite.run_profile_sweep"
    )
    print(f"Wrote {len(rows)} multi-profile simulation rows to {args.output} (provenance: {sidecar})")


def run_profile_sweep(config_path: str | Path) -> list[dict[str, Any]]:
    """Run all profiles listed in a profile-sweep config."""

    config_path = Path(config_path)
    config = _load_profile_sweep_config(config_path)
    profiles = _require_string_list(config, "profiles")
    simulation_config = _require_dict(config, "simulation")
    simulation_config.setdefault("__config_dir", str(config_path.resolve().parent))

    rows: list[dict[str, Any]] = []
    for profile in profiles:
        profile_path = _resolve_path(config_path.parent, profile)
        rows.extend(
            run_simulation_with_config(
                profile_path=profile_path,
                config=simulation_config,
            )
        )
    return rows


def _load_profile_sweep_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as file:
        raw_config = json.load(file)
    if not isinstance(raw_config, dict):
        raise ValueError("Profile sweep config must be a JSON object.")
    return raw_config


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


def _require_dict(config: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = config.get(field_name)
    if not isinstance(value, dict):
        raise ValueError(f"Config requires an object '{field_name}'.")
    return value


def _resolve_path(base_dir: Path, path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run EDA-Lite multi-profile sweep.")
    parser.add_argument("--config", required=True, help="Path to profile sweep JSON config.")
    parser.add_argument("--output", required=True, help="Path to output CSV.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
