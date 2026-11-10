"""Reproduce the findings in report/audit_p0_p1_p2.md.

Read-only: uses temporary directories and never writes into the repository.
Standard library only. Run from the repository root:

    python3 scripts/audit_repro.py            # all cases
    python3 scripts/audit_repro.py P0-1 P1-5  # selected cases
    python3 scripts/audit_repro.py --strict   # CI: exit 1 if anything is REPRODUCED

Each case prints REPRODUCED when the audited defect is still present, or
FIXED when the current code no longer shows it. BLOCKED means the code-side
fix is in place but verification needs data that only a real ROS2 run can
produce (e.g. raw CSVs for P0-3); it is not a pass.
"""

from __future__ import annotations

import csv
import importlib.util
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

try:  # added in Phase 1 / Batch 1
    from src.ros2_runtime.analyze_runtime import load_publisher_frames  # noqa: E402
except ImportError:  # pragma: no cover - older analyzer
    load_publisher_frames = None
from src.ros2_runtime.build_os_profiles import build_os_profile_payload  # noqa: E402

PROFILES = {
    "xxs": REPO / "data/model_profiles/mobilevit_xxs_simplified.json",
    "s": REPO / "data/model_profiles/mobilevit_s_simplified.json",
}
SRAM_CFG = REPO / "experiments/eda_lite/mobilevit_sram_sweep.json"
RUNTIME_CFG = REPO / "experiments/eda_lite/mobilevit_runtime_aware_sweep.json"
RUNTIME_PROFILES = REPO / "experiments/eda_lite/runtime_os_profiles.legacy_unverified.json"
LEGACY_RUNTIME_CFG = REPO / "experiments/eda_lite/mobilevit_runtime_aware_sweep_legacy_unverified.json"
BLOCKED: set[str] = set()


def _verdict(case: str, reproduced: bool, detail: str, blocked: bool = False) -> bool:
    label = "REPRODUCED" if reproduced else ("BLOCKED" if blocked else "FIXED")
    if blocked and not reproduced:
        BLOCKED.add(case)
    print(f"[{case}] {label}: {detail}")
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
        print(f"  sram=200 greedy: {_names(greedy_schedule(b, 200))}   dp: {_names(dp_schedule(b, 200))}")
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
        rows = run_simulation_with_config(PROFILES["s"], cfg)
        infeasible = [r for r in rows if r.get("feasible") == "false"]
        print(f"  {len(rows)} rows, {len(infeasible)} marked feasible=false "
              f"(e.g. {infeasible[0]['scheduler']}@{infeasible[0]['sram_kb']}KB: "
              f"{infeasible[0]['infeasible_reason']})" if infeasible else f"  {len(rows)} rows")
        return _verdict("P1-2", False, "sweep with sram_kb=[128,256] completes with infeasible rows marked")
    except ValueError as exc:
        return _verdict("P1-2", True, f"sweep with sram_kb=[128,256] aborts: {exc}")


def case_p1_3() -> bool:
    """OS-aware experiment semantics: no true baseline, ties reported as wins, hard-coded profiles."""
    from src.eda_lite import cost_model

    pure = cost_model.OS_PROFILES.get("pure")
    pure_ok = pure is not None and pure.latency_multiplier == 1.0 and (
        pure.deadline_miss_rate, pure.memory_pressure, pure.drop_rate) == (0.0, 0.0, 0.0)
    print(f"  built-in 'pure' profile (m=1, no OS pressure): {pure_ok}")

    plot_src = (REPO / "src/eda_lite/plot_6lines.py").read_text(encoding="utf-8")
    hardcoded = "d150" in plot_src or '== "normal"' in plot_src
    print(f"  plot_6lines hard-codes profile selection: {hardcoded}")

    from src.eda_lite.analyze_results import build_summary_rows, load_result_rows
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r.csv"
        path.write_text(
            "model_name,scheduler,sram_kb,os_profile,num_subgraphs,max_fusion_depth,peak_sram_kb,"
            "dram_traffic_kb,estimated_energy,estimated_latency_ms,os_aware_total_cost,subgraphs\n"
            "t,layerwise,256,normal,2,1,1,10,10,1,30,a | b\n"
            "t,greedy,256,normal,1,2,1,5,5,1,20,a+b\n"
            "t,dp,256,normal,1,2,1,5,5,1,20,a+b\n", encoding="utf-8")
        best = build_summary_rows(load_result_rows(path))[0]["best_scheduler"]
    print(f"  greedy and dp tie at cost 20 -> best_scheduler={best!r}")

    # Facts about the repository data (not pass/fail criteria): with the fixed
    # cost model, do OS profiles or the deadline change any MobileViT schedule?
    for key, path in PROFILES.items():
        base = run_simulation_with_config(path, _load_cfg(RUNTIME_CFG))
        cfg_nob = _load_cfg(RUNTIME_CFG)
        cfg_nob["cost_model"]["beta"] = 0.0
        nob = run_simulation_with_config(path, cfg_nob)
        beta_changes_cost = sum(x["os_aware_total_cost"] != y["os_aware_total_cost"] for x, y in zip(base, nob))
        dp_per_sram: dict[str, set[str]] = {}
        groups: dict[tuple[str, str], dict[str, dict]] = {}
        for row in base:
            groups.setdefault((row["sram_kb"], row["os_profile"]), {})[row["scheduler"]] = row
            if row["scheduler"] == "dp":
                dp_per_sram.setdefault(row["sram_kb"], set()).add(row["subgraphs"])
        dp_eq_greedy = sum(g["dp"]["subgraphs"] == g["greedy"]["subgraphs"] for g in groups.values())
        print(f"  {key} (measured_* profiles): deadline term changes cost in {beta_changes_cost}/{len(base)} rows; "
              f"distinct DP schedules per SRAM={ {k: len(v) for k, v in dp_per_sram.items()} }; "
              f"dp==greedy partitions {dp_eq_greedy}/{len(groups)} (reported as ties)")
    print("  note: on these coarse profiles fusion lowers energy, latency and the deadline term together;")
    print("        only SRAM feasibility changes schedules (see report/PHASE1_BATCH2_RESULT.md).")
    reproduced = not pure_ok or hardcoded or best != "greedy=dp"
    return _verdict("P1-3", reproduced,
                    "no pure baseline / ties reported as greedy wins / hard-coded plot profiles")


def case_p1_4_sim() -> bool:
    """EDA-Lite deadline penalty ignores latency_multiplier; deadline not recorded per row."""
    layer = (LayerProfile("a", "Conv", 10, 10, 1, 2e9, True),)  # ~20 ms simulated latency
    profiles = make_os_profiles({
        "m2": {"latency_multiplier": 2.0, "deadline_miss_rate": 0.5, "memory_pressure": 0.0}})
    cc = make_cost_config({"deadline_ms": 33.3})
    m = estimate_schedule_metrics([layer], 1024, "m2", cc, profiles)
    expected = cc.alpha * 2 * m.estimated_latency_ms + 0.5 * cc.beta * (2 * m.estimated_latency_ms - 33.3)
    got = m.os_aware_total_cost - m.estimated_energy
    print(f"  L={m.estimated_latency_ms:.3f}ms, m=2, D=33.3: latency+deadline cost={got:.3f} "
          f"(effective-latency definition: {expected:.3f})")
    rows = run_simulation_with_config(PROFILES["xxs"], _load_cfg(SRAM_CFG))
    recorded = "deadline_ms" in rows[0] and rows[0]["deadline_ms"] == "33.3"
    print(f"  simulation rows record deadline_ms: {recorded}")
    return _verdict("P1-4S", abs(got - expected) > 1e-9 or not recorded,
                    "deadline penalty uses raw latency / deadline not recorded")


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
        rows = load_runtime_rows([tmp])
        if load_publisher_frames is None:  # analyzer without publisher-log support
            return build_runtime_summary(rows)
        return build_runtime_summary(rows, publisher_frames=load_publisher_frames([tmp]))


def _with_run_id(run_id: str, rows: str) -> str:
    return "run_id," + HEADER + "".join(f"{run_id},{line}" for line in rows.splitlines(True))


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
    received = "".join(_row(i) for i in range(40, 100))
    files = {"r.csv": _with_run_id("r", received)}
    if load_publisher_frames is not None:  # older analyzers would read the log as detector rows
        files["r.publisher.csv"] = ("run_id,frame_id,published_at_ns\n"
                                    + "".join(f"r,{i},{i}\n" for i in range(100)))
    with_log = _summary(files)[0]
    print(f"  frames 0..39 lost, publisher log 0..99: {_short(with_log)}, "
          f"accounting={with_log.get('frame_accounting', '-')}")
    no_log = _summary({"a.csv": HEADER + received})[0]
    print(f"  same, no publisher log              : dropped={no_log['dropped_frames']}, "
          f"accounting={no_log.get('frame_accounting', '(not reported)')}")
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
    reproduced = (
        with_log["dropped_frames"] != "40"
        or no_log.get("frame_accounting") != "frame_id_range"
        or mixed["dropped_frames"] != "9"
        or len(split) == 2
        or crashed
    )
    return _verdict("P1-5", reproduced,
                    "leading drops invisible / explicit drops disable gap inference / key not normalised")


def case_p1_6() -> bool:
    """inference_ms includes the artificial delay; warm-up frames pollute statistics."""
    spec = importlib.util.spec_from_file_location(
        "run_log_audit", REPO / "src/ros2_uav_pipeline/mobilevit_uav_pipeline/run_log.py")
    run_log = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_log)
    header = getattr(run_log, "DETECTOR_CSV_HEADER", None)
    detector = (REPO / "src/ros2_uav_pipeline/mobilevit_uav_pipeline/mobilevit_detector_node.py").read_text(encoding="utf-8")
    if header is None or "artificial_delay_ms" not in header:
        return _verdict("P1-6", True, "detector CSV has no separate artificial_delay_ms / warm-up columns")
    base = dict(run_id="r", scenario="overload_sweep", model_name="mobilevit_xxs", input_fps="20.0",
                qos_depth="5", fake_delay_ms="80", resource_profile="normal", deadline_ms="100",
                latency_ms="95", transport_ms="2", preprocess_ms="3", artificial_delay_ms="80",
                inference_ms="10", warmup="0", dropped="0")
    lines = [",".join(header)]
    for i in range(10):
        row = {**base, "frame_id": i, **({"warmup": "1", "latency_ms": "900"} if i < 2 else {})}
        lines.append(",".join(str(row.get(c, "")) for c in header))
    s = _summary({"r.csv": "\n".join(lines) + "\n"})[0]
    print(f"  80 ms injected delay, 10 ms model: avg_inference_ms={s['avg_inference_ms']}, "
          f"avg_artificial_delay_ms={s.get('avg_artificial_delay_ms', '-')}")
    print(f"  2 warm-up frames at 900 ms: warmup_frames_excluded={s.get('warmup_frames_excluded', '-')}, "
          f"p99_latency_ms={s['p99_latency_ms']}")
    mixed_clocks = "get_clock()" in detector or detector.count("time.perf_counter_ns()") < 4
    print(f"  detector clocks: wall clock for cross-process stamps, perf_counter for stages: {not mixed_clocks}")
    return _verdict("P1-6", s["avg_inference_ms"] != "10" or s["p99_latency_ms"] != "95" or mixed_clocks,
                    "artificial delay / warm-up / clock semantics mixed into timing statistics")


def case_launch() -> bool:
    """A failed detector leaves the launch running until timeout, reported as success."""
    launch = (REPO / "src/ros2_uav_pipeline/launch/mobilevit_uav_pipeline.launch.py").read_text(encoding="utf-8")
    common = REPO / "experiments/ros2/run_common.sh"
    shutdown = "OnProcessExit" in launch and "Shutdown" in launch
    strict = common.exists() and '-ne 124' in common.read_text(encoding="utf-8")
    print(f"  launch shuts down when a node exits: {shutdown}; "
          f"scripts treat any non-timeout end as failure: {strict}")
    return _verdict("LAUNCH", not (shutdown and strict),
                    "detector start-up failure is indistinguishable from a normal timed run")


def case_p1_7() -> bool:
    """OS profile normalisation uses one global baseline across models."""
    rows = [
        dict(scenario="fps_sweep", model_name=m, input_fps="20", qos_depth="5", fake_delay_ms="0",
             resource_profile="normal", avg_latency_ms=str(lat), deadline_miss_rate_pct="0",
             drop_rate_pct="0", avg_memory_mb=str(mem), memory_limit_mb="2048", run_id=f"idle_{m}")
        for m, lat, mem in (("mobilevit_xxs", 40, 300), ("mobilevit_s", 120, 600))
    ]
    defs = build_os_profile_payload(rows, profile_prefix="measured")["os_profile_definitions"]
    for name, d in defs.items():
        print(f"  idle {name}: {d}")
    s_idle = defs["measured_fps_sweep_mobilevit_s_20fps_q5_d0_normal"]["latency_multiplier"]
    s_mem = defs["measured_fps_sweep_mobilevit_s_20fps_q5_d0_normal"]["memory_pressure"]
    no_ref = [dict(r, memory_limit_mb="") for r in rows]
    try:
        build_os_profile_payload(no_ref, profile_prefix="measured")
        max_rss_fallback = True
    except ValueError:
        max_rss_fallback = False
    legacy = _load_cfg(LEGACY_RUNTIME_CFG) if LEGACY_RUNTIME_CFG.exists() else _load_cfg(RUNTIME_CFG)
    xxs_profiles = {r["os_profile"] for r in run_simulation_with_config(PROFILES["xxs"], legacy)}
    mixed = any("mobilevit_s_" in name for name in xxs_profiles)
    real = json.loads(RUNTIME_PROFILES.read_text(encoding="utf-8"))["os_profile_definitions"]
    mem = [d["memory_pressure"] for d in real.values()]
    print(f"  memory_pressure for 600 MB with a 2048 MB limit: {s_mem}; "
          f"max-RSS fallback without a reference: {max_rss_fallback}")
    print(f"  XXS runtime-aware sweep uses MobileViT-S profiles: {mixed} ({len(xxs_profiles)} profiles)")
    print(f"  legacy (unverified) profiles still carry the old calibration: memory_pressure "
          f"{min(mem)}..{max(mem)} (not regenerable without raw data)")
    return _verdict("P1-7", s_idle > 1.0 or max_rss_fallback or mixed,
                    "idle MobileViT-S gets latency_multiplier > 1 from XXS baseline / max-RSS memory / "
                    "profiles mixed across models")


def case_p0_3() -> bool:
    """Runtime-derived inputs are not reproducible and a tracked CSV is stale."""
    proc = subprocess.run([sys.executable, "scripts/check_runtime_provenance.py"], cwd=REPO,
                          capture_output=True, text=True)
    print("  " + proc.stdout.strip().replace("\n", "\n  "))
    tracked = REPO / "results/csv/eda_lite_mobilevit_runtime_aware_sweep.csv"
    regen = run_simulation_with_config(PROFILES["xxs"], _load_cfg(RUNTIME_CFG))
    stale = False
    if tracked.exists():
        with tracked.open(encoding="utf-8", newline="") as f:
            tracked_rows = list(csv.DictReader(f))
        key = lambda r: (r["os_profile"], r["sram_kb"], r["scheduler"], r["os_aware_total_cost"], r["subgraphs"])  # noqa: E731
        stale = sorted(map(key, tracked_rows)) != sorted(map(key, regen))
        print(f"  tracked {tracked.name}: {len(tracked_rows)} rows; regeneration from the default "
              f"config matches: {not stale}")
    default_sources = {r.get("os_profile_provenance") for r in regen}
    unlabeled_default = not default_sources <= {"example", "verified"}
    legacy_cfg = _load_cfg(LEGACY_RUNTIME_CFG) if LEGACY_RUNTIME_CFG.exists() else None
    silently_used = False
    if legacy_cfg is not None:
        strict = dict(legacy_cfg)
        strict.pop("allow_unverified_os_profiles", None)
        try:
            run_simulation_with_config(PROFILES["xxs"], strict)
            silently_used = True
        except ValueError:
            pass
        labels = {r["os_profile_provenance"] for r in run_simulation_with_config(PROFILES["xxs"], legacy_cfg)}
        silently_used = silently_used or labels != {"unverified"}
    false_pass = proc.returncode == 0 and not any((REPO / "results/raw/ros2").glob("*.csv"))
    print(f"  default config OS profile sources: {sorted(default_sources)}; unverified profiles usable "
          f"without opt-in/label: {silently_used}; check passes without raw data: {false_pass}")
    reproduced = stale or unlabeled_default or silently_used or false_pass or proc.returncode == 2
    return _verdict(
        "P0-3", reproduced,
        "measured_* profiles lack raw CSV/summary; tracked runtime-aware CSV is stale"
        + ("" if reproduced else " -- mechanism fixed; raw ROS2 data still missing (needs a real run)"),
        blocked=proc.returncode == 1,
    )


def case_p1_8() -> bool:
    """Run conditions (limits, RMW, QoS, versions) are not recorded; fallback runs are labelled 'normal'."""
    from src.ros2_runtime.run_metadata import classify_limits, collect_run_metadata

    requested = {"cpus": [0, 1], "memory_max_bytes": 2 * 1024**3}
    unreadable = classify_limits(requested, {"cpus_allowed": None, "memory_max_bytes": None})[1]
    ignored = classify_limits(requested, {"cpus_allowed": [0, 1], "memory_max_bytes": "max"})[1]
    applied = classify_limits(requested, {"cpus_allowed": [0, 1], "memory_max_bytes": 2 * 1024**3})[1]
    meta = collect_run_metadata("audit", "normal", "0,1", "2G", effective={"cpus_allowed": None,
                                "memory_max_bytes": None})
    fields = ("git", "host", "python", "packages", "ros2", "qos", "network_sysctl", "resource_limits")
    missing = [f for f in fields if f not in meta]
    scripts = {name: (REPO / name).read_text(encoding="utf-8") for name in (
        "scripts/run_baseline_experiments.sh", "scripts/run_os_tuned_experiments.sh",
        "experiments/ros2/run_fps_sweep.sh", "experiments/ros2/run_qos_sweep.sh",
        "experiments/ros2/run_overload_sweep.sh")}
    runs_sudo = any(line.strip().startswith("sudo ") for text in scripts.values() for line in text.splitlines())
    fallback_ok = all('RESOURCE_PROFILE="$UNCONSTRAINED_PROFILE"' in scripts[n] for n in (
        "scripts/run_baseline_experiments.sh", "scripts/run_os_tuned_experiments.sh"))
    captures = all("run_capture_metadata" in scripts[n] for n in scripts if n.startswith("experiments/"))
    print(f"  limits requested but unreadable -> {unreadable}; requested but not in effect -> {ignored}; "
          f"verified -> {applied}")
    print(f"  metadata sections missing: {missing or '-'}; RMW recorded: "
          f"{'RMW_IMPLEMENTATION' in meta['ros2']}; rmem_default recorded: "
          f"{'net.core.rmem_default' in meta['network_sysctl']}")
    print(f"  scripts run sudo: {runs_sudo}; unconstrained fallback relabelled: {fallback_ok}; "
          f"every sweep run captures metadata: {captures}")
    reproduced = (unreadable == "constrained" or ignored == "constrained" or applied != "constrained"
                  or bool(missing) or runs_sudo or not fallback_ok or not captures)
    return _verdict("P1-8", reproduced,
                    "run conditions unrecorded; unconstrained fallback labelled as constrained"
                    + ("" if reproduced else " -- code fixed; taskset/cgroup read-back still needs a "
                       "Linux ROS2 run to confirm"),
                    blocked=True)


def case_p2_1() -> bool:
    """No CI: tests, shell syntax and audit regressions are only run by hand."""
    workflow = REPO / ".github/workflows/ci.yml"
    text = workflow.read_text(encoding="utf-8") if workflow.exists() else ""
    checks = {name: f"scripts/ci_checks.sh {name}" in text
              for name in ("tests", "shell", "audit", "provenance")}
    print(f"  workflow present: {workflow.exists()}; steps: {checks}")
    return _verdict("P2-1", not (text and all(checks.values())),
                    "no CI workflow running tests, bash -n, audit --strict and the provenance gate")


def case_p2_2() -> bool:
    """Dependencies unpinned; simulator vs ROS 2 requirements not separated."""
    sim = REPO / "requirements-sim.txt"
    ros = REPO / "requirements-ros2.txt"
    env = REPO / "environment.yml"
    pins = []
    if ros.exists():
        pins = [ln.strip() for ln in ros.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.lstrip().startswith(("#", "-"))]
    sim_pkgs = []
    if sim.exists():
        sim_pkgs = [ln for ln in sim.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.lstrip().startswith("#")]
    unpinned = [p for p in pins if "==" not in p]
    env_text = env.read_text(encoding="utf-8") if env.exists() else ""
    print(f"  requirements-sim.txt packages: {sim_pkgs or 'none (stdlib)'}; ros2 pins: {pins}; "
          f"unpinned: {unpinned}; environment.yml python=3.10 + humble: "
          f"{'python=3.10' in env_text and 'ros-humble' in env_text}")
    ok = (sim.exists() and not sim_pkgs and pins and not unpinned
          and "python=3.10" in env_text and "ros-humble" in env_text)
    return _verdict("P2-2", not ok, "unpinned ROS 2 node dependencies / no stdlib-only simulator requirement")


def case_p2_3() -> bool:
    """Caches and .DS_Store files are tracked by git."""
    try:
        proc = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True,
                              timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return _verdict("P2-3", False, f"git unavailable ({exc}); cannot inspect the index", blocked=True)
    if proc.returncode != 0:
        return _verdict("P2-3", False, "not a git checkout; cannot inspect the index", blocked=True)
    junk = [f for f in proc.stdout.splitlines()
            if "__pycache__/" in f or f.endswith((".pyc", ".DS_Store")) or Path(f).name.startswith("~$")]
    print(f"  tracked cache / OS / lock files: {len(junk)} {junk[:5]}")
    return _verdict("P2-3", bool(junk), "__pycache__ / .pyc / .DS_Store / Office lock files tracked")


def case_p2_6() -> bool:
    """Detector falls back to another model; launch accepts an unused model_path; profiles unchecked."""
    pipeline = REPO / "src/ros2_uav_pipeline/mobilevit_uav_pipeline"
    spec = importlib.util.spec_from_file_location("audit_run_log", pipeline / "run_log.py")
    run_log = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_log)
    calls = []

    def fake_create(name, pretrained):
        calls.append((name, pretrained))
        raise RuntimeError(f"Unknown model ({name})")

    strict_helper = hasattr(run_log, "create_model_strict")
    fell_back = True
    if strict_helper:
        try:
            run_log.create_model_strict("mobilevit_typo", fake_create)
        except RuntimeError:
            fell_back = len(calls) != 1
    detector = (pipeline / "mobilevit_detector_node.py").read_text(encoding="utf-8")
    fallback_in_node = ("self.model_name = 'mobilevit_xxs'" in detector
                        or "create_model_strict(" not in detector)
    launch = (REPO / "src/ros2_uav_pipeline/launch/mobilevit_uav_pipeline.launch.py").read_text(encoding="utf-8")
    import ast
    declared = []
    for node in ast.walk(ast.parse(launch)):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "ARGUMENTS" for t in node.targets):
            declared = [elt.elts[0].value for elt in node.value.elts]
    sweeps = "".join(p.read_text(encoding="utf-8") for p in (REPO / "experiments/ros2").glob("run_*_sweep.sh"))
    unused_model_path = "model_path" in declared or "model_path:=" in sweeps
    broken = [
        LayerProfile("a", "Conv", 10, 20, 1, 1, True),
        LayerProfile("b", "Conv", 30, 30, 1, 1, True),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "broken.json"
        path.write_text(json.dumps({"model_name": "broken", "layers": [
            {"name": l.name, "op_type": l.op_type, "input_kb": l.input_kb, "output_kb": l.output_kb,
             "weight_kb": l.weight_kb, "compute_macs": l.compute_macs, "fusible": l.fusible}
            for l in broken]}), encoding="utf-8")
        try:
            load_model_profile(path)
            chain_unchecked = True
        except ValueError:
            chain_unchecked = False
    print(f"  model load failure falls back: helper={strict_helper}, fell_back={fell_back}, "
          f"fallback code in node={fallback_in_node}")
    print(f"  unused model_path declared/forwarded: {unused_model_path}; "
          f"output_kb -> input_kb mismatch accepted: {chain_unchecked}")
    return _verdict("P2-6", fell_back or fallback_in_node or unused_model_path or chain_unchecked,
                    "silent model fallback / unused model_path / unchecked profile chain")


CASES = {
    "P0-1": case_p0_1,
    "P0-2": case_p0_2,
    "P0-3": case_p0_3,
    "P1-1": case_p1_1,
    "P1-2": case_p1_2,
    "P1-3": case_p1_3,
    "P1-4": case_p1_4,
    "P1-4S": case_p1_4_sim,
    "P1-5": case_p1_5,
    "P1-6": case_p1_6,
    "P1-7": case_p1_7,
    "P1-8": case_p1_8,
    "LAUNCH": case_launch,
    "P2-1": case_p2_1,
    "P2-2": case_p2_2,
    "P2-3": case_p2_3,
    "P2-6": case_p2_6,
}


def main(argv: list[str]) -> int:
    # --strict (used by CI): exit 1 if any audited defect is REPRODUCED. BLOCKED cases
    # (code fixed, real ROS 2 data missing) do not fail the run but are listed.
    strict = "--strict" in argv
    argv = [a for a in argv if a != "--strict"]
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
    blocked = [c for c in results if c in BLOCKED]
    if blocked:
        print(f"Blocked on real ROS2 data (code fixed, not verified by measurement): {', '.join(blocked)}")
    return 1 if strict and still else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
