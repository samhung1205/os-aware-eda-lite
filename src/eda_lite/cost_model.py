"""Cost model for EDA-Lite fusion simulation.

All energy and latency values produced here are estimates for comparison only.
They are not hardware measurements.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .model_loader import LayerProfile


@dataclass(frozen=True)
class CostConfig:
    """Tunable constants for the lightweight EDA-Lite estimator."""

    dram_energy_per_kb: float = 1.0
    compute_energy_per_mmac: float = 0.05
    dram_latency_per_kb_ms: float = 0.001
    compute_latency_per_mmac_ms: float = 0.01
    subgraph_overhead_ms: float = 0.02
    weight_tile_kb: float = 64.0
    alpha: float = 1.0
    beta: float = 100.0
    gamma: float = 50.0
    delta: float = 75.0
    deadline_ms: float = 33.3


@dataclass(frozen=True)
class OsRuntimeProfile:
    """Aggregated OS pressure values used by the OS-aware cost term."""

    name: str
    latency_multiplier: float
    deadline_miss_rate: float
    memory_pressure: float
    drop_rate: float = 0.0


@dataclass(frozen=True)
class SubgraphMetrics:
    peak_sram_kb: float
    dram_traffic_kb: float
    estimated_energy: float
    estimated_latency_ms: float


@dataclass(frozen=True)
class ScheduleMetrics:
    peak_sram_kb: float
    dram_traffic_kb: float
    estimated_energy: float
    estimated_latency_ms: float
    os_aware_total_cost: float


OS_PROFILES: dict[str, OsRuntimeProfile] = {
    "normal": OsRuntimeProfile(
        name="normal",
        latency_multiplier=1.0,
        deadline_miss_rate=0.02,
        memory_pressure=0.20,
        drop_rate=0.0,
    ),
    "high_latency": OsRuntimeProfile(
        name="high_latency",
        latency_multiplier=1.35,
        deadline_miss_rate=0.18,
        memory_pressure=0.35,
        drop_rate=0.08,
    ),
    "high_memory_pressure": OsRuntimeProfile(
        name="high_memory_pressure",
        latency_multiplier=1.10,
        deadline_miss_rate=0.08,
        memory_pressure=0.85,
        drop_rate=0.03,
    ),
}


def make_cost_config(raw_config: dict[str, float] | None = None) -> CostConfig:
    """Build a cost config from optional JSON values."""

    if raw_config is None:
        return CostConfig()
    valid_fields = CostConfig.__dataclass_fields__
    unknown_fields = set(raw_config).difference(valid_fields)
    if unknown_fields:
        fields = ", ".join(sorted(unknown_fields))
        raise ValueError(f"Unknown cost model config fields: {fields}.")
    return CostConfig(**raw_config)


def make_os_profiles(
    raw_profiles: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, OsRuntimeProfile]:
    """Build OS runtime profiles by merging defaults with optional custom profiles."""

    profiles = dict(OS_PROFILES)
    if raw_profiles is None:
        return profiles

    for name, raw_profile in raw_profiles.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("OS profile names must be non-empty strings.")
        if not isinstance(raw_profile, Mapping):
            raise ValueError(f"OS profile '{name}' must be a JSON object.")

        latency_multiplier = _require_non_negative_number(
            raw_profile.get("latency_multiplier"),
            f"os_profile_definitions.{name}.latency_multiplier",
        )
        deadline_miss_rate = _require_fraction(
            raw_profile.get("deadline_miss_rate"),
            f"os_profile_definitions.{name}.deadline_miss_rate",
        )
        memory_pressure = _require_fraction(
            raw_profile.get("memory_pressure"),
            f"os_profile_definitions.{name}.memory_pressure",
        )
        drop_rate = _optional_fraction(
            raw_profile.get("drop_rate"),
            f"os_profile_definitions.{name}.drop_rate",
        )
        profiles[name] = OsRuntimeProfile(
            name=name,
            latency_multiplier=latency_multiplier,
            deadline_miss_rate=deadline_miss_rate,
            memory_pressure=memory_pressure,
            drop_rate=drop_rate,
        )
    return profiles


def get_os_profile(
    name: str,
    os_profiles: Mapping[str, OsRuntimeProfile] | None = None,
) -> OsRuntimeProfile:
    profiles = os_profiles or OS_PROFILES
    try:
        return profiles[name]
    except KeyError as exc:
        known = ", ".join(sorted(profiles))
        raise ValueError(f"Unknown OS profile '{name}'. Expected one of: {known}.") from exc


def estimate_subgraph_metrics(
    layers: Sequence[LayerProfile],
    cost_config: CostConfig | None = None,
) -> SubgraphMetrics:
    """Estimate SRAM, DRAM traffic, energy, and latency for one subgraph."""

    if not layers:
        raise ValueError("Cannot estimate metrics for an empty subgraph.")

    config = cost_config or CostConfig()
    peak_sram_kb = estimate_subgraph_sram_kb(layers, config)
    dram_traffic_kb = estimate_subgraph_dram_traffic_kb(layers)
    compute_mmac = sum(layer.compute_macs for layer in layers) / 1_000_000.0

    estimated_energy = (
        dram_traffic_kb * config.dram_energy_per_kb
        + compute_mmac * config.compute_energy_per_mmac
    )
    estimated_latency_ms = (
        dram_traffic_kb * config.dram_latency_per_kb_ms
        + compute_mmac * config.compute_latency_per_mmac_ms
        + config.subgraph_overhead_ms
    )

    return SubgraphMetrics(
        peak_sram_kb=peak_sram_kb,
        dram_traffic_kb=dram_traffic_kb,
        estimated_energy=estimated_energy,
        estimated_latency_ms=estimated_latency_ms,
    )


def estimate_schedule_metrics(
    subgraphs: Sequence[Sequence[LayerProfile]],
    sram_kb: float,
    os_profile_name: str = "normal",
    cost_config: CostConfig | None = None,
    os_profiles: Mapping[str, OsRuntimeProfile] | None = None,
) -> ScheduleMetrics:
    """Estimate aggregate metrics for a schedule."""

    if sram_kb <= 0:
        raise ValueError("sram_kb must be positive.")
    if not subgraphs:
        raise ValueError("Cannot estimate metrics for an empty schedule.")

    config = cost_config or CostConfig()
    os_profile = get_os_profile(os_profile_name, os_profiles)
    subgraph_metrics = [estimate_subgraph_metrics(subgraph, config) for subgraph in subgraphs]

    peak_sram_kb = max(metric.peak_sram_kb for metric in subgraph_metrics)
    dram_traffic_kb = sum(metric.dram_traffic_kb for metric in subgraph_metrics)
    estimated_energy = sum(metric.estimated_energy for metric in subgraph_metrics)
    estimated_latency_ms = sum(metric.estimated_latency_ms for metric in subgraph_metrics)
    os_aware_total_cost = os_aware_cost(
        estimated_energy=estimated_energy,
        estimated_latency_ms=estimated_latency_ms,
        peak_sram_kb=peak_sram_kb,
        sram_kb=sram_kb,
        os_profile=os_profile,
        cost_config=config,
    )

    return ScheduleMetrics(
        peak_sram_kb=peak_sram_kb,
        dram_traffic_kb=dram_traffic_kb,
        estimated_energy=estimated_energy,
        estimated_latency_ms=estimated_latency_ms,
        os_aware_total_cost=os_aware_total_cost,
    )


def estimate_subgraph_sram_kb(
    layers: Sequence[LayerProfile],
    cost_config: CostConfig | None = None,
) -> float:
    """Estimate peak SRAM for a fused subgraph.

    We model activations explicitly and assume weights can be streamed in tiles.
    This keeps the simulator aligned with the project scope: it is a lightweight
    SRAM-pressure estimator, not a full memory planner.
    """

    if not layers:
        return 0.0

    config = cost_config or CostConfig()
    first_input_kb = layers[0].input_kb
    final_output_kb = layers[-1].output_kb
    intermediate_outputs = [layer.output_kb for layer in layers[:-1]]
    max_intermediate_kb = max(intermediate_outputs, default=0.0)
    max_weight_tile_kb = min(max(layer.weight_kb for layer in layers), config.weight_tile_kb)
    return first_input_kb + final_output_kb + max_intermediate_kb + max_weight_tile_kb


def estimate_subgraph_dram_traffic_kb(layers: Sequence[LayerProfile]) -> float:
    """Estimate DRAM traffic for a subgraph.

    Fused internal activation reads/writes are omitted, while weights are still
    counted as DRAM traffic because this simulator does not model weight caching.
    """

    if not layers:
        return 0.0
    weight_traffic_kb = sum(layer.weight_kb for layer in layers)
    return layers[0].input_kb + layers[-1].output_kb + weight_traffic_kb


def os_aware_cost(
    estimated_energy: float,
    estimated_latency_ms: float,
    peak_sram_kb: float,
    sram_kb: float,
    os_profile: OsRuntimeProfile,
    cost_config: CostConfig | None = None,
) -> float:
    """Combine simulated compiler cost with coarse OS runtime pressure."""

    config = cost_config or CostConfig()
    latency_cost = config.alpha * estimated_latency_ms * os_profile.latency_multiplier
    deadline_excess_ms = max(0.0, estimated_latency_ms - config.deadline_ms)
    deadline_cost = config.beta * os_profile.deadline_miss_rate * deadline_excess_ms
    memory_pressure_cost = config.gamma * os_profile.memory_pressure * (peak_sram_kb / sram_kb)
    communication_pressure_cost = config.delta * os_profile.drop_rate * estimated_latency_ms
    return (
        estimated_energy
        + latency_cost
        + deadline_cost
        + memory_pressure_cost
        + communication_pressure_cost
    )


def subgraph_objective_cost(
    layers: Sequence[LayerProfile],
    sram_kb: float,
    os_profile_name: str = "normal",
    cost_config: CostConfig | None = None,
    os_profiles: Mapping[str, OsRuntimeProfile] | None = None,
) -> float:
    """Cost used by the DP scheduler for a candidate fused subgraph."""

    metrics = estimate_subgraph_metrics(layers, cost_config)
    os_profile = get_os_profile(os_profile_name, os_profiles)
    return os_aware_cost(
        estimated_energy=metrics.estimated_energy,
        estimated_latency_ms=metrics.estimated_latency_ms,
        peak_sram_kb=metrics.peak_sram_kb,
        sram_kb=sram_kb,
        os_profile=os_profile,
        cost_config=cost_config,
    )


def max_fusion_depth(subgraphs: Iterable[Sequence[LayerProfile]]) -> int:
    return max((len(subgraph) for subgraph in subgraphs), default=0)


def _require_non_negative_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a number.")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative.")
    return float(value)


def _require_fraction(value: Any, field_name: str) -> float:
    number = _require_non_negative_number(value, field_name)
    if number > 1:
        raise ValueError(f"{field_name} must be between 0 and 1.")
    return number


def _optional_fraction(value: Any, field_name: str) -> float:
    if value is None:
        return 0.0
    return _require_fraction(value, field_name)
