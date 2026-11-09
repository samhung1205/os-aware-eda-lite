"""Reproduce the findings in report/audit_p0_p1_p2.md.

Read-only: uses temporary directories and never writes into the repository.
Standard library only. Run from the repository root:

    python3 scripts/audit_repro.py            # all cases
    python3 scripts/audit_repro.py P0-1 P1-5  # selected cases

Each case prints REPRODUCED when the audited defect is still present, or
FIXED when the current code no longer shows it.
"""

from __future__ import annotations

import csv
import io
import itertools
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.eda_lite.cost_model import (  # noqa: E402
    estimate_schedule_metrics,
    estimate_subgraph_sram_kb,
    make_cost_config,
    make_os_profiles,
    subgraph_objective_cost,
)
from src.eda_lite.model_loader import LayerProfile, load_model_profile  # noqa: E402
from src.eda_lite.run_simulation import run_simulation_with_config  # noqa: E402
from src.eda_lite.schedulers import (  # noqa: E402
    dp_schedule,
    greedy_schedule,
    is_feasible_subgraph,
    layerwise_schedule,
)
from src.ros2_runtime.analyze_runtime import build_runtime_summary, load_runtime_rows  # noqa: E402
from src.ros2_runtime.build_os_profiles import build_os_profile_payload  # noqa: E402

PROFILES = {
    "xxs": REPO / "data/model_profiles/mobilevit_xxs_simplified.json",
    "s": REPO / "data/model_profiles/mobilevit_s_simplified.json",
}
SRAM_CFG = REPO / "experiments/eda_lite/mobilevit_sram_sweep.json"
RUNTIME_CFG = REPO / "experiments/eda_lite/mobilevit_runtime_aware_sweep.json"
RUNTIME_PROFILES = REPO / "experiments/eda_lite/runtime_os_profiles.json"


def _verdict(case: str, reproduced: bool, detail: str) -> bool:
    print(f"[{case}] {'REPRODUCED' if reproduced else 'FIXED'}: {detail}")
    return reproduced


def _names(schedule) -> str:
    return " | ".join("+".join(layer.name for layer in sg) for sg in schedule.subgraphs)


def _cost(subgraphs, sram, os_name, cfg=None, profiles=None) -> float:
    return estimate_schedule_metrics(
        subgraphs, sram_kb=sram, os_profile_name=os_name, cost_config=cfg, os_profiles=profiles
    ).os_aware_total_cost


def _load_cfg(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["__config_dir"] = str(path.parent)
    return cfg


# ---------------------------------------------------------------- EDA-Lite


def _exhaustive_best(layers, sram, os_name, cc, profiles) -> float:
    """Exact minimum of the reported cost over all contiguous partitions (small n only)."""
    best = float("inf")
    n = len(layers)
    for cuts in itertools.product((False, True), repeat=n - 1):
        bounds = [0] + [i for i, cut in enumerate(cuts, 1) if cut] + [n]
        subgraphs = [tuple(layers[a:b]) for a, b in zip(bounds, bounds[1:])]
        if all(is_feasible_subgraph(sg, sram, cc) for sg in subgraphs):
            best = min(best, _cost(subgraphs, sram, os_name, cc, profiles))
    return best


def case_p0_1() -> bool:
    """DP optimises a per-subgraph surrogate, not the reported schedule cost."""
    cfg = _load_cfg(SRAM_CFG)
    cc = make_cost_config(cfg["cost_model"])
    rt = json.loads(RUNTIME_PROFILES.read_text(encoding="utf-8"))
    profiles = make_os_profiles(rt["os_profile_definitions"])
    max_gap = 0.0
    repo_suboptimal = 0
    cases = 0
    for path in PROFILES.values():
        layers = load_model_profile(path).layers
        for sram in cfg["sram_kb"]:
            for os_name in cfg["os_profiles"] + rt["os_profiles"]:
                dp = dp_schedule(layers, sram, os_name, cc, profiles)
                reported = _cost(dp.subgraphs, sram, os_name, cc, profiles)
                surrogate = sum(
                    subgraph_objective_cost(sg, sram, os_name, cc, profiles) for sg in dp.subgraphs
                )
                max_gap = max(max_gap, abs(surrogate - reported))
                repo_suboptimal += reported > _exhaustive_best(layers, sram, os_name, cc, profiles) + 1e-9
                cases += 1
    print(f"  repo configs: DP worse than exhaustive optimum in {repo_suboptimal}/{cases} cases "
          f"(latent); max |per-subgraph surrogate - reported cost| = {max_gap:.3f}")

    # Toy: per-subgraph deadline hinge sees 0 excess; the reported cost sees total latency.
    toy_cc = make_cost_config({"deadline_ms": 5.0})
    toy_profiles = make_os_profiles(
        {"p": {"latency_multiplier": 1.0, "deadline_miss_rate": 1.0, "memory_pressure": 0.0}}
    )
    toy = (
        LayerProfile("a", "Conv", 10, 10, 1, 300e6, True),
        LayerProfile("b", "Conv", 10, 10, 1, 300e6, True),
    )
    dp_cost = _cost(dp_schedule(toy, 1024, "p", toy_cc, toy_profiles).subgraphs, 1024, "p", toy_cc, toy_profiles)
    gr_cost = _cost(greedy_schedule(toy, 1024, toy_cc).subgraphs, 1024, "p", toy_cc, toy_profiles)
    print(f"  toy: dp reported cost={dp_cost:.3f}  greedy reported cost={gr_cost:.3f}")
    return _verdict("P0-1", repo_suboptimal > 0 or dp_cost > gr_cost + 1e-9,
                    "DP does not minimise the cost it reports (dp > greedy on toy)")


def case_p1_1() -> bool:
    """Greedy stops at the first infeasible extension although SRAM(l..k) is not monotone."""
    a = (
        LayerProfile("l0", "Conv", 10, 100, 1, 1e6, True),
        LayerProfile("l1", "Conv", 100, 150, 1, 1e6, True),
        LayerProfile("l2", "Conv", 150, 10, 1, 1e6, True),
    )
    print("  SRAM(l0)=%g SRAM(l0+l1)=%g SRAM(l0+l1+l2)=%g" % tuple(
        estimate_subgraph_sram_kb(a[:k]) for k in (1, 2, 3)))
    g, d = greedy_schedule(a, 255), dp_schedule(a, 255)
    print(f"  sram=255 greedy: {_names(g)}   dp: {_names(d)}")
    suboptimal = len(g.subgraphs) > len(d.subgraphs)

    b = (
        LayerProfile("l0", "Conv", 10, 150, 1, 1e6, True),
        LayerProfile("l1", "Conv", 150, 150, 1, 1e6, True),
        LayerProfile("l2", "Conv", 150, 10, 1, 1e6, True),
    )
    try:
        greedy_schedule(b, 200)
        crashed = False
    except ValueError as exc:
        crashed = True
        print(f"  sram=200 greedy raises '{exc}' while dp finds: {_names(dp_schedule(b, 200))}")
    return _verdict("P1-1", suboptimal or crashed, "greedy misses longer feasible fusions / falsely fails")


def case_p1_2() -> bool:
    """One infeasible scheduler aborts the whole sweep (no per-row infeasible marker)."""
    cfg = _load_cfg(SRAM_CFG)
    cfg["sram_kb"] = [128, 256]
    try:
        run_simulation_with_config(PROFILES["s"], cfg)
        return _verdict("P1-2", False, "sweep with sram_kb=[128,256] completes")
    except ValueError as exc:
        return _verdict("P1-2", True, f"sweep with sram_kb=[128,256] aborts: {exc}")


def case_p1_3() -> bool:
    """OS-aware terms never change a decision on the repository configs."""
    reproduced = True
    for key, path in PROFILES.items():
        base = run_simulation_with_config(path, _load_cfg(RUNTIME_CFG))
        cfg_nob = _load_cfg(RUNTIME_CFG)
        cfg_nob["cost_model"]["beta"] = 0.0
        nob = run_simulation_with_config(path, cfg_nob)
        beta_dead = all(x["os_aware_total_cost"] == y["os_aware_total_cost"] for x, y in zip(base, nob))
        dp_per_sram: dict[str, set[str]] = {}
        dp_eq_greedy = 0
        groups: dict[tuple[str, str], dict[str, dict]] = {}
        for row in base:
            groups.setdefault((row["sram_kb"], row["os_profile"]), {})[row["scheduler"]] = row
            if row["scheduler"] == "dp":
                dp_per_sram.setdefault(row["sram_kb"], set()).add(row["subgraphs"])
        for g in groups.values():
            dp_eq_greedy += g["dp"]["subgraphs"] == g["greedy"]["subgraphs"]
        max_lat = max(float(r["estimated_latency_ms"]) for r in base)
        layers = load_model_profile(path).layers
        max_peak = max(
            estimate_subgraph_sram_kb(layers[i:j])
            for i in range(len(layers)) for j in range(i + 1, len(layers) + 1)
            if is_feasible_subgraph(layers[i:j], 1e12)
        )
        print(f"  {key}: beta=0 identical={beta_dead}; max est. latency={max_lat}ms (< deadline 33.3); "
              f"distinct DP schedules per SRAM={ {k: len(v) for k, v in dp_per_sram.items()} }; "
              f"dp==greedy partitions {dp_eq_greedy}/{len(groups)}; max candidate SRAM={max_peak:g}KB")
        reproduced &= beta_dead and all(len(v) == 1 for v in dp_per_sram.values())
    return _verdict("P1-3", reproduced, "deadline term is dead and OS profiles never change a schedule")


# ---------------------------------------------------------------- ROS2 runtime

HEADER = ("scenario,model_name,input_fps,qos_depth,fake_delay_ms,resource_profile,frame_id,"
          "published_at_ns,received_at_ns,completed_at_ns,latency_ms,inference_ms,deadline_miss,"
          "dropped,cpu_percent,memory_mb\n")


def _row(fid, lat="20", fps="20.0", miss=0, drop=0) -> str:
    return f"qos_sweep,mobilevit_xxs,{fps},5,0,normal,{fid},0,0,0,{lat},10,{miss},{drop},50,300\n"


def _summary(files: dict[str, str]) -> list[dict[str, str]]:
    with tempfile.TemporaryDirectory() as tmp:
        for name, body in files.items():
            (Path(tmp) / name).write_text(body, encoding="utf-8")
        return build_runtime_summary(load_runtime_rows([tmp]))


def _short(s: dict[str, str]) -> str:
    keys = ("input_fps", "processed_frames", "dropped_frames", "drop_rate_pct",
            "deadline_misses", "deadline_miss_rate_pct")
    return ", ".join(f"{k}={s[k]}" for k in keys)


def case_p0_2() -> bool:
    """Detector appends to an existing CSV and frame_id restarts at 0 per run."""
    run1 = "".join(_row(i) for i in range(0, 100, 2))   # 50 received, 49 gaps
    run2 = "".join(_row(i) for i in range(100))         # clean run
    alone = _summary({"a.csv": HEADER + run1})[0]
    print(f"  run1 alone : {_short(alone)}")
    try:
        merged = _summary({"a.csv": HEADER + run1 + run2})[0]
    except ValueError as exc:
        print(f"  run1+run2 appended (legacy, no run_id) -> rejected: {str(exc).splitlines()[1]}")
        # With run_id the same two runs are summarised separately.
        def with_run_id(run_id: str, rows: str) -> str:
            return "run_id," + HEADER + "".join(f"{run_id},{line}" for line in rows.splitlines(True))

        tagged = _summary({"r1.csv": with_run_id("r1", run1), "r2.csv": with_run_id("r2", run2)})
        for s in tagged:
            print(f"  run_id={s['run_id']}: {_short(s)}")
        separated = [s["dropped_frames"] for s in tagged] == [alone["dropped_frames"], "0"]
        return _verdict("P0-2", not separated, "appended legacy runs are rejected; run_id runs are separated")
    print(f"  run1+run2  : {_short(merged)}")
    return _verdict("P0-2", merged["dropped_frames"] == "0" and alone["dropped_frames"] != "0",
                    "appended runs hide drops (set() de-duplicates restarted frame_ids)")


def case_p1_4() -> bool:
    """Deadline misses counted on dropped rows; rate divided by processed frames only."""
    s = _summary({"a.csv": HEADER + _row(0) + _row(1) + _row(2, lat="", miss=1, drop=1)
                  + _row(3, lat="", miss=1, drop=1)})[0]
    print(f"  {_short(s)}")
    return _verdict("P1-4", s["deadline_miss_rate_pct"] == "100",
                    "2 on-time processed frames reported as 100% deadline miss")


def case_p1_5() -> bool:
    """frame_id gap inference corner cases and group-key normalisation."""
    lead = _summary({"a.csv": HEADER + "".join(_row(i) for i in range(40, 100))})[0]
    print(f"  frames 0..39 never received: {_short(lead)}")
    mixed = _summary({"a.csv": HEADER + _row(0) + _row(1, lat="", drop=1) + _row(10)})[0]
    print(f"  explicit drop + gap 2..9   : {_short(mixed)}")
    # Same file (= same run) so only the fps spelling differs.
    split = _summary({"a.csv": HEADER + _row(0, fps="20") + _row(1, fps="20.0")})
    print(f"  '20' vs '20.0' -> {len(split)} groups")
    try:
        _summary({"a.csv": HEADER + _row(0, fps="20"),
                  "b.csv": "scenario,model_name,frame_id,latency_ms\nqos_sweep,mobilevit_xxs,0,20\n"})
        crashed = False
    except TypeError as exc:
        crashed = True
        print(f"  missing input_fps column in one file -> TypeError: {exc}")
    return _verdict("P1-5", lead["dropped_frames"] == "0" or len(split) == 2 or crashed,
                    "leading drops invisible / explicit drops disable gap inference / key not normalised")


def case_p1_7() -> bool:
    """OS profile normalisation uses one global baseline across models."""
    rows = [
        dict(scenario="fps_sweep", model_name=m, input_fps="20", qos_depth="5", fake_delay_ms="0",
             resource_profile="normal", avg_latency_ms=str(lat), deadline_miss_rate_pct="0",
             drop_rate_pct="0", avg_memory_mb=str(mem))
        for m, lat, mem in (("mobilevit_xxs", 40, 300), ("mobilevit_s", 120, 600))
    ]
    defs = build_os_profile_payload(rows, profile_prefix="measured")["os_profile_definitions"]
    for name, d in defs.items():
        print(f"  idle {name}: {d}")
    real = json.loads(RUNTIME_PROFILES.read_text(encoding="utf-8"))["os_profile_definitions"]
    mem = [d["memory_pressure"] for d in real.values()]
    print(f"  checked-in measured profiles: memory_pressure range {min(mem)}..{max(mem)}")
    s_idle = defs["measured_fps_sweep_mobilevit_s_20fps_q5_d0_normal"]["latency_multiplier"]
    return _verdict("P1-7", s_idle > 1.0, "idle MobileViT-S gets latency_multiplier > 1 from XXS baseline")


def case_p0_3() -> bool:
    """Runtime-derived inputs are not reproducible and a tracked CSV is stale."""
    proc = subprocess.run([sys.executable, "scripts/check_runtime_provenance.py"], cwd=REPO,
                          capture_output=True, text=True)
    print("  " + proc.stdout.strip().replace("\n", "\n  "))
    tracked = REPO / "results/csv/eda_lite_mobilevit_runtime_aware_sweep.csv"
    stale = False
    if tracked.exists():
        with tracked.open(encoding="utf-8", newline="") as f:
            tracked_profiles = {r["os_profile"] for r in csv.DictReader(f)}
        regen = run_simulation_with_config(PROFILES["xxs"], _load_cfg(RUNTIME_CFG))
        regen_profiles = {r["os_profile"] for r in regen}
        stale = tracked_profiles != regen_profiles
        print(f"  tracked {tracked.name}: profiles={sorted(tracked_profiles)[:2]}...; "
              f"current config regenerates {len(regen)} rows with {len(regen_profiles)} measured_* profiles")
    return _verdict("P0-3", proc.returncode != 0 or stale,
                    "measured_* profiles lack raw CSV/summary; tracked runtime-aware CSV is stale")


CASES = {
    "P0-1": case_p0_1,
    "P0-2": case_p0_2,
    "P0-3": case_p0_3,
    "P1-1": case_p1_1,
    "P1-2": case_p1_2,
    "P1-3": case_p1_3,
    "P1-4": case_p1_4,
    "P1-5": case_p1_5,
    "P1-7": case_p1_7,
}


def main(argv: list[str]) -> int:
    selected = argv or list(CASES)
    unknown = [c for c in selected if c not in CASES]
    if unknown:
        print(f"Unknown case(s): {', '.join(unknown)}. Known: {', '.join(CASES)}")
        return 2
    results = {}
    for case in selected:
        print(f"\n== {case}: {CASES[case].__doc__.strip()}")
        results[case] = CASES[case]()
    still = [c for c, r in results.items() if r]
    print(f"\nSummary: {len(still)}/{len(results)} reproduced: {', '.join(still) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
