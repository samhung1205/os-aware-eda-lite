"""Layer-wise, greedy, and DP fusion schedulers for EDA-Lite."""

from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Mapping, Sequence

from .cost_model import (
    CostConfig,
    OsRuntimeProfile,
    estimate_subgraph_sram_kb,
    subgraph_objective_cost,
)
from .model_loader import LayerProfile


@dataclass(frozen=True)
class ScheduleResult:
    scheduler: str
    subgraphs: tuple[tuple[LayerProfile, ...], ...]

    @property
    def max_fusion_depth(self) -> int:
        return max((len(subgraph) for subgraph in self.subgraphs), default=0)


def layerwise_schedule(
    layers: Sequence[LayerProfile],
    sram_kb: float,
    cost_config: CostConfig | None = None,
) -> ScheduleResult:
    """Schedule each layer as a separate subgraph."""

    subgraphs = tuple((layer,) for layer in layers)
    _assert_schedule_fits(subgraphs, sram_kb, cost_config)
    return ScheduleResult(scheduler="layerwise", subgraphs=subgraphs)


def greedy_schedule(
    layers: Sequence[LayerProfile],
    sram_kb: float,
    cost_config: CostConfig | None = None,
) -> ScheduleResult:
    """Fuse the longest feasible contiguous region from left to right."""

    subgraphs: list[tuple[LayerProfile, ...]] = []
    index = 0
    while index < len(layers):
        best_end = index + 1
        candidate_end = best_end
        while candidate_end <= len(layers):
            candidate = tuple(layers[index:candidate_end])
            if not is_feasible_subgraph(candidate, sram_kb, cost_config):
                break
            best_end = candidate_end
            candidate_end += 1
        subgraphs.append(tuple(layers[index:best_end]))
        index = best_end

    _assert_schedule_fits(subgraphs, sram_kb, cost_config)
    return ScheduleResult(scheduler="greedy", subgraphs=tuple(subgraphs))


def dp_schedule(
    layers: Sequence[LayerProfile],
    sram_kb: float,
    os_profile_name: str = "normal",
    cost_config: CostConfig | None = None,
    os_profiles: Mapping[str, OsRuntimeProfile] | None = None,
) -> ScheduleResult:
    """Find the minimum-cost contiguous fusion partition with dynamic programming."""

    n_layers = len(layers)
    dp = [inf] * (n_layers + 1)
    previous = [-1] * (n_layers + 1)
    dp[0] = 0.0

    for end in range(1, n_layers + 1):
        for start in range(end - 1, -1, -1):
            candidate = tuple(layers[start:end])
            if not is_feasible_subgraph(candidate, sram_kb, cost_config):
                continue
            candidate_cost = subgraph_objective_cost(
                candidate,
                sram_kb=sram_kb,
                os_profile_name=os_profile_name,
                cost_config=cost_config,
                os_profiles=os_profiles,
            )
            total_cost = dp[start] + candidate_cost
            if total_cost < dp[end]:
                dp[end] = total_cost
                previous[end] = start

    if previous[n_layers] == -1:
        raise ValueError(f"No feasible DP schedule found for SRAM={sram_kb:g}KB.")

    subgraphs_reversed: list[tuple[LayerProfile, ...]] = []
    cursor = n_layers
    while cursor > 0:
        start = previous[cursor]
        if start < 0:
            raise ValueError("DP schedule reconstruction failed.")
        subgraphs_reversed.append(tuple(layers[start:cursor]))
        cursor = start

    subgraphs = tuple(reversed(subgraphs_reversed))
    _assert_schedule_fits(subgraphs, sram_kb, cost_config)
    return ScheduleResult(scheduler="dp", subgraphs=subgraphs)


def is_feasible_subgraph(
    layers: Sequence[LayerProfile],
    sram_kb: float,
    cost_config: CostConfig | None = None,
) -> bool:
    """Return whether a candidate contiguous subgraph fits the fusion constraints."""

    if not layers or sram_kb <= 0:
        return False
    if len(layers) > 1 and not all(layer.fusible for layer in layers):
        return False
    return estimate_subgraph_sram_kb(layers, cost_config) <= sram_kb


def serialize_subgraphs(subgraphs: Sequence[Sequence[LayerProfile]]) -> str:
    """Serialize subgraphs for compact CSV output."""

    return " | ".join("+".join(layer.name for layer in subgraph) for subgraph in subgraphs)


def _assert_schedule_fits(
    subgraphs: Sequence[Sequence[LayerProfile]],
    sram_kb: float,
    cost_config: CostConfig | None = None,
) -> None:
    for subgraph in subgraphs:
        if not is_feasible_subgraph(subgraph, sram_kb, cost_config):
            names = "+".join(layer.name for layer in subgraph)
            peak = estimate_subgraph_sram_kb(subgraph, cost_config)
            raise ValueError(
                f"Subgraph '{names}' requires {peak:g}KB SRAM, above limit {sram_kb:g}KB."
            )
