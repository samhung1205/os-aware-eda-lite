"""Layer-wise, greedy, DP, and exhaustive fusion schedulers for EDA-Lite.

Every schedule is a partition of the layer sequence into contiguous subgraphs.
A subgraph is feasible when its estimated peak SRAM fits the limit and, if it
has more than one layer, every layer is fusible.

Objective
---------
``dp`` and ``exhaustive`` minimise exactly the reported whole-schedule cost
``cost_model.os_aware_cost`` (see ``estimate_schedule_metrics``)::

    C = E + (alpha*m + delta*d) * L
          + beta * r * max(0, m*L - deadline)
          + gamma * p * P / SRAM

where ``E`` and ``L`` are sums over subgraphs and ``P`` is the max subgraph peak
SRAM. The deadline hinge and ``P`` are not additive over subgraphs, so a plain
"sum of per-subgraph costs" DP optimises a different function (audit P0-1).

Tie-break (identical for ``dp`` and ``exhaustive``): among schedules whose cost
is within ``COST_TIE_TOLERANCE`` (relative) of the minimum, choose the one with
the fewest subgraphs, then the lexicographically smallest list of subgraph end
indices.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Mapping, Sequence

from .cost_model import (
    CostConfig,
    OsRuntimeProfile,
    SubgraphMetrics,
    estimate_subgraph_metrics,
    estimate_subgraph_sram_kb,
    get_os_profile,
    os_aware_cost,
)
from .model_loader import LayerProfile


# Relative tolerance used only to decide whether two schedule costs tie.
COST_TIE_TOLERANCE = 1e-9

# 2^(n-1) partitions; 20 layers is ~5e5 schedules, still a few seconds.
EXHAUSTIVE_MAX_LAYERS = 20


class InfeasibleScheduleError(ValueError):
    """A scheduler found no schedule that fits the SRAM / fusion constraints.

    This is a legitimate experiment outcome (e.g. layerwise at a small SRAM),
    unlike configuration errors, so sweeps record it as an infeasible row.
    """


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
    _assert_schedule_fits(subgraphs, sram_kb, cost_config, scheduler="layerwise")
    return ScheduleResult(scheduler="layerwise", subgraphs=subgraphs)


def greedy_schedule(
    layers: Sequence[LayerProfile],
    sram_kb: float,
    cost_config: CostConfig | None = None,
) -> ScheduleResult:
    """Left to right, take the longest feasible subgraph starting at each layer.

    SRAM feasibility is *not* monotone in the end index: extending a subgraph
    turns the old final output into an intermediate, and a small new output can
    lower the peak. So an SRAM-infeasible extension does not stop the scan; only
    a non-fusible layer (which blocks every longer extension) does. The scan is
    O(n) per start, O(n^2) candidate checks overall. Greedy never backtracks, so
    it can still fail where ``dp`` succeeds; it then raises
    ``InfeasibleScheduleError``.
    """

    subgraphs: list[tuple[LayerProfile, ...]] = []
    index = 0
    while index < len(layers):
        best_end = None
        for end in range(index + 1, len(layers) + 1):
            candidate = tuple(layers[index:end])
            if len(candidate) > 1 and not candidate[-1].fusible:
                break
            if len(candidate) > 1 and not candidate[0].fusible:
                break
            if is_feasible_subgraph(candidate, sram_kb, cost_config):
                best_end = end
        if best_end is None:
            # Not even the single layer fits, so no subgraph can start here.
            peak = estimate_subgraph_sram_kb((layers[index],), cost_config)
            raise InfeasibleScheduleError(
                f"greedy: no feasible subgraph starts at '{layers[index].name}' "
                f"(alone it requires {peak:g}KB SRAM, above limit {sram_kb:g}KB)."
            )
        subgraphs.append(tuple(layers[index:best_end]))
        index = best_end

    _assert_schedule_fits(subgraphs, sram_kb, cost_config, scheduler="greedy")
    return ScheduleResult(scheduler="greedy", subgraphs=tuple(subgraphs))


@dataclass(frozen=True)
class _Label:
    """Partial schedule of a prefix, summarised by the totals the cost needs."""

    energy: float
    latency_ms: float
    peak_sram_kb: float
    ends: tuple[int, ...]


def dp_schedule(
    layers: Sequence[LayerProfile],
    sram_kb: float,
    os_profile_name: str = "normal",
    cost_config: CostConfig | None = None,
    os_profiles: Mapping[str, OsRuntimeProfile] | None = None,
) -> ScheduleResult:
    """Exact minimum of ``os_aware_total_cost`` over contiguous partitions.

    Prefix DP with Pareto labels. A label for prefix ``layers[:j]`` keeps the
    totals ``(E, L, P)`` of one partial schedule. The final cost is
    non-decreasing in each of them (all weights are non-negative) and extending
    a schedule updates them monotonically (sum, sum, max), so a label that is
    no better than another in every relevant coordinate can never lead to a
    strictly cheaper complete schedule and is discarded. Only coordinates with
    a non-zero weight are compared:

    * additive part ``A = E + (alpha*m + delta*d) * L`` - always;
    * ``L`` - only if the deadline hinge is active (``beta * r > 0``);
    * ``P`` - only if memory pressure is active (``gamma * p > 0``).

    The tie-break preference is part of the dominance test (see
    ``_pareto_front``), so dp returns the same schedule as the exhaustive oracle,
    not just the same cost.

    Complexity: O(n^2) candidate subgraphs (metrics precomputed once, O(n^3)),
    then for each prefix j the extensions of all labels of all prefixes i < j,
    i.e. O(n^2 * K) label extensions plus O(K^2) per prefix for the front,
    where K is the largest front. K is bounded by the number of partitions
    (2^(n-1)) in the worst case but stays small in practice because
    non-fusible layers and the SRAM limit cut the candidate chains; the
    MobileViT profiles keep K <= 4 (see report/PHASE1_BATCH2_RESULT.md).
    Exactness is checked against ``exhaustive_schedule`` in the tests.
    """

    config = cost_config or CostConfig()
    profile = get_os_profile(os_profile_name, os_profiles)
    if sram_kb <= 0:
        raise ValueError("sram_kb must be positive.")

    linear_latency_weight = config.alpha * profile.latency_multiplier + config.delta * profile.drop_rate
    use_latency = config.beta * profile.deadline_miss_rate > 0
    use_peak = config.gamma * profile.memory_pressure > 0

    def key(label: _Label) -> tuple[float, ...]:
        coords = [label.energy + linear_latency_weight * label.latency_ms]
        if use_latency:
            coords.append(label.latency_ms)
        if use_peak:
            coords.append(label.peak_sram_kb)
        return tuple(coords)

    candidates = _feasible_candidates(layers, sram_kb, config)
    n_layers = len(layers)
    labels: list[list[_Label]] = [[] for _ in range(n_layers + 1)]
    labels[0] = [_Label(0.0, 0.0, 0.0, ())]

    for end in range(1, n_layers + 1):
        extended: list[_Label] = []
        for start in range(end):
            metrics = candidates.get((start, end))
            if metrics is None:
                continue
            for label in labels[start]:
                extended.append(
                    _Label(
                        energy=label.energy + metrics.estimated_energy,
                        latency_ms=label.latency_ms + metrics.estimated_latency_ms,
                        peak_sram_kb=max(label.peak_sram_kb, metrics.peak_sram_kb),
                        ends=label.ends + (end,),
                    )
                )
        labels[end] = _pareto_front(extended, key)

    if not labels[n_layers]:
        raise InfeasibleScheduleError(
            f"No feasible dp schedule found for SRAM={sram_kb:g}KB."
        )

    def cost(label: _Label) -> float:
        return os_aware_cost(
            estimated_energy=label.energy,
            estimated_latency_ms=label.latency_ms,
            peak_sram_kb=label.peak_sram_kb,
            sram_kb=sram_kb,
            os_profile=profile,
            cost_config=config,
        )

    best = _select_best([(cost(label), label.ends) for label in labels[n_layers]])
    subgraphs = _subgraphs_from_ends(layers, best)
    _assert_schedule_fits(subgraphs, sram_kb, config, scheduler="dp")
    return ScheduleResult(scheduler="dp", subgraphs=subgraphs)


def exhaustive_schedule(
    layers: Sequence[LayerProfile],
    sram_kb: float,
    os_profile_name: str = "normal",
    cost_config: CostConfig | None = None,
    os_profiles: Mapping[str, OsRuntimeProfile] | None = None,
) -> ScheduleResult:
    """Oracle: enumerate all 2^(n-1) contiguous partitions (n <= 20).

    Each feasible partition is scored with the reported cost (same
    accumulation order as ``estimate_schedule_metrics``). Used to verify
    ``dp_schedule``; also selectable as scheduler ``exhaustive``.
    """

    n_layers = len(layers)
    if n_layers == 0:
        raise ValueError("Cannot schedule an empty model.")
    if n_layers > EXHAUSTIVE_MAX_LAYERS:
        raise ValueError(
            f"exhaustive scheduler supports at most {EXHAUSTIVE_MAX_LAYERS} layers, "
            f"got {n_layers}."
        )
    if sram_kb <= 0:
        raise ValueError("sram_kb must be positive.")
    config = cost_config or CostConfig()
    profile = get_os_profile(os_profile_name, os_profiles)
    candidates = _feasible_candidates(layers, sram_kb, config)

    scored: list[tuple[float, tuple[int, ...]]] = []
    for cuts in itertools.product((False, True), repeat=n_layers - 1):
        ends = tuple(i for i, cut in enumerate(cuts, 1) if cut) + (n_layers,)
        starts = (0,) + ends[:-1]
        parts = [candidates.get(bounds) for bounds in zip(starts, ends)]
        if any(part is None for part in parts):
            continue
        energy = sum(part.estimated_energy for part in parts)
        latency = sum(part.estimated_latency_ms for part in parts)
        peak = max(part.peak_sram_kb for part in parts)
        scored.append(
            (
                os_aware_cost(energy, latency, peak, sram_kb, profile, config),
                ends,
            )
        )

    if not scored:
        raise InfeasibleScheduleError(
            f"No feasible exhaustive schedule found for SRAM={sram_kb:g}KB."
        )
    subgraphs = _subgraphs_from_ends(layers, _select_best(scored))
    return ScheduleResult(scheduler="exhaustive", subgraphs=subgraphs)


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


def costs_tie(a: float, b: float) -> bool:
    """Whether two schedule costs are equal up to ``COST_TIE_TOLERANCE``."""

    return abs(a - b) <= COST_TIE_TOLERANCE * max(1.0, abs(a), abs(b))


def _feasible_candidates(
    layers: Sequence[LayerProfile],
    sram_kb: float,
    cost_config: CostConfig,
) -> dict[tuple[int, int], SubgraphMetrics]:
    """Metrics of every feasible contiguous subgraph ``layers[start:end]``."""

    candidates: dict[tuple[int, int], SubgraphMetrics] = {}
    for start in range(len(layers)):
        for end in range(start + 1, len(layers) + 1):
            candidate = tuple(layers[start:end])
            if len(candidate) > 1 and not candidate[-1].fusible:
                break  # every longer subgraph also contains this layer
            if is_feasible_subgraph(candidate, sram_kb, cost_config):
                candidates[(start, end)] = estimate_subgraph_metrics(candidate, cost_config)
    return candidates


def _pareto_front(labels: list[_Label], key) -> list[_Label]:
    """Drop labels that another label beats in every cost coordinate *and* in
    tie-break preference.

    Including the preference ``(len(ends), ends)`` in the dominance test keeps
    the tie-break exact: for any common suffix the dominating prefix yields a
    completion that is no more expensive and is preferred, so the schedule the
    exhaustive oracle would pick is never discarded.
    """

    def preference(label: _Label) -> tuple[int, tuple[int, ...]]:
        return (len(label.ends), label.ends)

    ordered = sorted(labels, key=lambda label: (key(label), preference(label)))
    front: list[tuple[tuple[float, ...], _Label]] = []
    for label in ordered:
        coords = key(label)
        dominated = any(
            preference(kept) <= preference(label)
            and all(kept_c <= c for kept_c, c in zip(kept_coords, coords))
            for kept_coords, kept in front
        )
        if not dominated:
            front.append((coords, label))
    return [label for _, label in front]


def _select_best(scored: list[tuple[float, tuple[int, ...]]]) -> tuple[int, ...]:
    best_cost = min(cost for cost, _ in scored)
    tied = [ends for cost, ends in scored if costs_tie(cost, best_cost)]
    return min(tied, key=lambda ends: (len(ends), ends))


def _subgraphs_from_ends(
    layers: Sequence[LayerProfile],
    ends: tuple[int, ...],
) -> tuple[tuple[LayerProfile, ...], ...]:
    starts = (0,) + ends[:-1]
    return tuple(tuple(layers[start:end]) for start, end in zip(starts, ends))


def _assert_schedule_fits(
    subgraphs: Sequence[Sequence[LayerProfile]],
    sram_kb: float,
    cost_config: CostConfig | None = None,
    scheduler: str = "schedule",
) -> None:
    for subgraph in subgraphs:
        if not is_feasible_subgraph(subgraph, sram_kb, cost_config):
            names = "+".join(layer.name for layer in subgraph)
            peak = estimate_subgraph_sram_kb(subgraph, cost_config)
            raise InfeasibleScheduleError(
                f"{scheduler}: subgraph '{names}' requires {peak:g}KB SRAM, "
                f"above limit {sram_kb:g}KB."
            )
