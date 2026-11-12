"""Build the dashboard data bundle from verified Phase 2 / Phase 3 tables (Phase 4).

    python3 -m src.dashboard.build_data            # write dashboard/data/*
    python3 -m src.dashboard.build_data --check    # exit 3 if the committed bundle is stale

Reads only:

* Phase 2 / Batch 2 baseline: ``results/csv/ros2_baseline_{runs,conditions}.csv``
  (verified through ``ros2_baseline_conditions.manifest.json`` and the runtime summary
  manifest down to ``results/raw/ros2``);
* Phase 3 / Batch 2 formal A/B: ``results/csv/ros2_phase3_formal_{runs,arms,paired}.csv``
  and ``..._dynamic_{arms,paired}.csv`` (verified through their manifests and the
  formal summary manifest down to ``results/raw/ros2_phase3_formal``);
* run metadata (``*.meta.json``) of those formal runs, for the control-variable table;
* EDA-Lite *simulation estimates* ``results/csv/eda_lite_mobilevit_profile_sweep.csv``
  (built-in OS profiles only, verified through its ``.provenance.json`` sidecar) for the
  separate simulation page.

Pilot, legacy-unverified and example data are never read: any source path containing
one of ``FORBIDDEN_PATH_TOKENS`` or any run id outside the formal run tags is an error.
Every KPI and finding sentence is computed here from those tables; nothing is typed in.

Writes ``dashboard_data.json`` (canonical), ``dashboard_data.js`` (the same object as
``window.DASHBOARD_DATA`` so the page also works from ``file://``) and
``dashboard_data.manifest.json`` (SHA-256 of every input and output). The output is
deterministic: no timestamps, no git HEAD, sorted keys.

Exit codes: 0 OK / CURRENT, 1 BLOCKED (an input is missing), 2 BROKEN (hash mismatch,
excluded data, inconsistent tables), 3 STALE (``--check`` only). Nothing is written
unless every check passes. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.provenance import sha256_file, verify_summary_manifest  # noqa: E402

SCHEMA = "dashboard_data/v1"
GENERATOR = "src.dashboard.build_data"
OK, BLOCKED, BROKEN, STALE = 0, 1, 2, 3
STATUS_LABEL = {OK: "OK", BLOCKED: "BLOCKED", BROKEN: "BROKEN", STALE: "STALE"}

OUTPUT_DIR = "dashboard/data"
OUTPUT_JSON = "dashboard_data.json"
OUTPUT_JS = "dashboard_data.js"
OUTPUT_MANIFEST = "dashboard_data.manifest.json"

# --- sources (repo-relative) -------------------------------------------------------------
P2_RUNS = "results/csv/ros2_baseline_runs.csv"
P2_CONDITIONS = "results/csv/ros2_baseline_conditions.csv"
P2_AGG_MANIFEST = "results/csv/ros2_baseline_conditions.manifest.json"
P2_SUMMARY_MANIFEST = "results/csv/ros2_runtime_summary.manifest.json"
P2_RAW_DIR = "results/raw/ros2"

P3_RUNS = "results/csv/ros2_phase3_formal_runs.csv"
P3_ARMS = "results/csv/ros2_phase3_formal_arms.csv"
P3_PAIRED = "results/csv/ros2_phase3_formal_paired.csv"
P3_AGG_MANIFEST = "results/csv/ros2_phase3_formal_arms.manifest.json"
P3_DYN_ARMS = "results/csv/ros2_phase3_formal_dynamic_arms.csv"
P3_DYN_PAIRED = "results/csv/ros2_phase3_formal_dynamic_paired.csv"
P3_DYN_MANIFEST = "results/csv/ros2_phase3_formal_dynamic_phases.manifest.json"
P3_SUMMARY_MANIFEST = "results/csv/ros2_phase3_formal_summary.manifest.json"
P3_RAW_DIR = "results/raw/ros2_phase3_formal"

SIM_SWEEP = "results/csv/eda_lite_mobilevit_profile_sweep.csv"
SIM_SIDECAR = "results/csv/eda_lite_mobilevit_profile_sweep.provenance.json"

FORBIDDEN_PATH_TOKENS = ("pilot", "legacy_unverified", "example", "runtime_aware")
P2_RUN_ID = re.compile(r"_b2(r|cap_r)[123]$")
P3_RUN_ID = re.compile(r"_p3b2_[a-z0-9]+_b[1-9]$")

# Design facts of the benchmark (not results): arm catalogue and the pre-specified primary condition.
ARMS = OrderedDict([
    ("legacy_q1", {"label": "Legacy · depth 1", "short": "Legacy d1", "family": "legacy", "slot": 5,
                   "summary": "Inference inside the DDS callback; KEEP_LAST depth 1 is the only queue."}),
    ("legacy_q5", {"label": "Legacy · depth 5", "short": "Legacy d5", "family": "legacy", "slot": 6,
                   "summary": "Inference inside the DDS callback; KEEP_LAST depth 5 is the only queue."}),
    ("fifo_c5_q10", {"label": "FIFO", "short": "FIFO", "family": "application", "slot": 4,
                     "summary": "Application queue (capacity 5), oldest frame first, reject newest when full."}),
    ("latest_q10", {"label": "Latest-Frame", "short": "Latest", "family": "application", "slot": 1,
                    "summary": "Always serve the newest frame; older queued frames are superseded."}),
    ("guard_c5_q10", {"label": "Deadline-Guard", "short": "Guard", "family": "application", "slot": 2,
                      "summary": "Newest frame that can still meet its deadline; drop frames predicted to miss."}),
    ("adaptive_c5_q10", {"label": "Adaptive", "short": "Adaptive", "family": "application", "slot": 3,
                         "summary": "Deadline-Guard plus a utilisation switch: EDF when ρ̂ < 1, newest feasible when ρ̂ ≥ 1."}),
])
PRIMARY_CONDITION = "s20"
METRICS_PAIRED = ("effective_miss_rate_pct", "on_time_fps", "p99_latency_ms", "drop_rate_pct",
                  "deadline_miss_rate_pct", "avg_service_ms", "p50_frame_age_at_start_ms")
METRICS_DYN_PAIRED = ("effective_miss_pct", "on_time_fps", "p99_latency_ms", "drop_pct", "late_pct",
                      "transient_effective_miss_pct")
# meta.json keys that must be identical across a dataset (shown on the Evidence page)
CONTROL_KEYS = (
    ("Host CPU", ("host", "cpu_model")),
    ("Kernel", ("host", "kernel_release")),
    ("CPU affinity (effective)", ("resource_limits", "effective", "cpus_allowed")),
    ("MemoryMax (effective, bytes)", ("resource_limits", "effective", "memory_max_bytes")),
    ("MemorySwapMax (effective, bytes)", ("resource_limits", "effective", "memory_swap_max_bytes")),
    ("Measurement class", ("resource_limits", "measurement_class")),
    ("nice", ("process", "nice")),
    ("ROS distro", ("ros2", "ROS_DISTRO")),
    ("RMW", ("ros2", "RMW_IMPLEMENTATION")),
    ("ROS_DOMAIN_ID", ("ros2", "ROS_DOMAIN_ID")),
    ("Fast DDS profile SHA-256", ("dds_profile", "sha256")),
    ("DDS SHM-only", ("dds_profile", "parsed", "shm_only")),
    ("Python", ("python", "version")),
    ("torch", ("packages", "torch")),
    ("timm", ("packages", "timm")),
    ("Model weights", ("experiment", "model_weights")),
    ("Deadline (ms)", ("experiment", "deadline_ms")),
    ("Warm-up frames", ("experiment", "warmup_frames")),
    ("Run length (s)", ("experiment", "run_seconds")),
)
P3_EXTRA_CONTROL_KEYS = (
    ("intra-op threads", ("experiment", "intra_op_threads")),
    ("App queue capacity", ("experiment", "queue_capacity")),
    ("Adaptive window", ("experiment", "adaptive_window")),
    ("Adaptive quantile", ("experiment", "adaptive_quantile")),
    ("Adaptive margin (ms)", ("experiment", "adaptive_margin_ms")),
    ("Adaptive overload threshold", ("experiment", "adaptive_overload_threshold")),
)


class DashboardDataError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# --- helpers -----------------------------------------------------------------------------

def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _r(value: Any, nd: int = 3) -> float | None:
    x = _num(value)
    if x is None:
        return None
    y = round(x, nd)
    return 0.0 if y == 0 else y


def _int(value: Any) -> int | None:
    x = _num(value)
    return None if x is None else int(round(x))


def _fmt(x: float | None, nd: int = 1, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    s = f"{x:+.{nd}f}" if signed else f"{x:.{nd}f}"
    return s.replace("-", "−")


class Sources:
    """Records every file the bundle depends on (path + SHA-256), refusing excluded data."""

    def __init__(self, root: Path):
        self.root = root
        self.records: dict[str, dict[str, str]] = {}

    def path(self, rel: str, role: str) -> Path:
        lowered = rel.lower()
        for token in FORBIDDEN_PATH_TOKENS:
            if token in lowered:
                raise DashboardDataError(BROKEN, f"{rel}: excluded data source ('{token}') cannot feed the dashboard")
        full = self.root / rel
        if not full.is_file():
            raise DashboardDataError(BLOCKED, f"{rel} is missing ({role})")
        if rel not in self.records:
            self.records[rel] = {"path": rel, "sha256": sha256_file(full), "role": role}
        return full

    def csv(self, rel: str, role: str) -> list[dict[str, str]]:
        with self.path(rel, role).open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            raise DashboardDataError(BLOCKED, f"{rel} has no rows ({role})")
        return rows

    def json(self, rel: str, role: str) -> Any:
        with self.path(rel, role).open(encoding="utf-8") as fh:
            return json.load(fh)


def _verify_aggregate_manifest(src: Sources, manifest_rel: str, must_cover: tuple[str, ...]) -> int:
    manifest = src.json(manifest_rel, "aggregate manifest")
    outputs = {o.get("path"): o.get("sha256") for o in manifest.get("outputs") or []}
    for rel in must_cover:
        if rel not in outputs:
            raise DashboardDataError(BROKEN, f"{manifest_rel} does not list {rel} as an output")
    records = list(manifest.get("inputs") or []) + list(manifest.get("outputs") or [])
    for rec in records:
        rel = rec.get("path") or ""
        if any(t in rel.lower() for t in FORBIDDEN_PATH_TOKENS):
            raise DashboardDataError(BROKEN, f"{manifest_rel}: lists excluded data {rel}")
        full = src.root / rel
        if not full.is_file():
            raise DashboardDataError(BLOCKED, f"{manifest_rel}: {rel} is missing")
        if sha256_file(full) != rec.get("sha256"):
            raise DashboardDataError(BROKEN, f"{manifest_rel}: {rel} no longer matches its recorded SHA-256")
    return len(records)


def _verify_summary_manifest(src: Sources, manifest_rel: str) -> int:
    src.path(manifest_rel, "runtime summary manifest")
    problems = verify_summary_manifest(src.root / manifest_rel)
    if problems:
        missing = [p for p in problems if "missing" in p]
        raise DashboardDataError(BLOCKED if missing and len(missing) == len(problems) else BROKEN,
                                 f"{manifest_rel}: " + "; ".join(problems[:5]))
    manifest = json.loads((src.root / manifest_rel).read_text(encoding="utf-8"))
    return len(manifest.get("inputs") or [])


def _get(d: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def _controls(src: Sources, raw_dir: str, run_ids: list[str], keys) -> tuple[list[dict], Counter]:
    values: dict[str, Counter] = {label: Counter() for label, _ in keys}
    commits: Counter = Counter()
    for run_id in run_ids:
        meta = src.json(f"{raw_dir}/{run_id}.meta.json", "run metadata")
        for label, path in keys:
            values[label][json.dumps(_get(meta, path), sort_keys=True)] += 1
        commits[(str(_get(meta, ("git", "commit")) or "")[:9], bool(_get(meta, ("git", "dirty"))))] += 1
    table = []
    for label, _ in keys:
        counter = values[label]
        table.append({
            "label": label,
            "values": [json.loads(v) for v in sorted(counter)],
            "identical": len(counter) == 1,
            "runs": sum(counter.values()),
        })
    return table, commits


def _parse_counts(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for part in (text or "").split(";"):
        if ":" in part:
            key, val = part.rsplit(":", 1)
            n = _int(val)
            if key and n is not None:
                out[key.strip()] = n
    return out


def _condition_id(model: str, fps: Any, delay: Any, schedule: str) -> str:
    short = {"mobilevit_s": "s", "mobilevit_xxs": "xxs"}.get(model)
    if short is None:
        raise DashboardDataError(BROKEN, f"unknown model {model!r}")
    if schedule:
        return f"{short}dyn"
    cid = f"{short}{int(float(fps))}"
    d = int(float(delay or 0))
    return cid + (f"d{d}" if d else "")


def _condition_label(model: str, fps: Any, delay: Any, schedule: str) -> str:
    name = {"mobilevit_s": "S", "mobilevit_xxs": "XXS"}[model]
    if schedule:
        steps = [s.split("@")[0] for s in schedule.split(",")]
        return f"{name} · {'→'.join(steps)} FPS"
    label = f"{name} · {int(float(fps))} FPS"
    d = int(float(delay or 0))
    return label + (f" + {d} ms" if d else "")


def _stats(row: dict[str, str], prefix: str, nd: int = 3) -> dict[str, Any]:
    return {k: _r(row.get(f"{prefix}_{k}"), nd) for k in ("mean", "sd", "min", "max")}


def _paired_entry(row: dict[str, str], metric: str) -> dict[str, Any]:
    p = f"d_{metric}_"
    return {
        "mean": _r(row.get(p + "mean")), "sd": _r(row.get(p + "sd")),
        "lo": _r(row.get(p + "ci95_lo")), "hi": _r(row.get(p + "ci95_hi")),
        "min": _r(row.get(p + "min")), "max": _r(row.get(p + "max")),
        "n_neg": _int(row.get(p + "n_neg")), "n_pos": _int(row.get(p + "n_pos")),
        "signflip_p": _r(row.get(p + "signflip_p"), 4),
    }


# --- Phase 2 baseline --------------------------------------------------------------------

def build_baseline(src: Sources) -> tuple[dict[str, Any], list[str]]:
    chain = _verify_summary_manifest(src, P2_SUMMARY_MANIFEST)
    chain += _verify_aggregate_manifest(src, P2_AGG_MANIFEST, (P2_RUNS, P2_CONDITIONS))
    runs = src.csv(P2_RUNS, "Phase 2 per-run baseline table")
    conds = src.csv(P2_CONDITIONS, "Phase 2 per-condition baseline table")
    run_ids = []
    for r in runs:
        rid = r["run_id"]
        if not P2_RUN_ID.search(rid):
            raise DashboardDataError(BROKEN, f"{P2_RUNS}: run {rid} is not a Phase 2 / Batch 2 formal run")
        if r.get("measurement_class") != "constrained" or r.get("dds_verified") != "true":
            raise DashboardDataError(BROKEN, f"{P2_RUNS}: run {rid} is not constrained + DDS-verified")
        run_ids.append(rid)
    if len(set(run_ids)) != len(run_ids):
        raise DashboardDataError(BROKEN, f"{P2_RUNS}: duplicate run ids")
    listed = sum(_int(c["n_runs"]) or 0 for c in conds)
    if listed != len(run_ids):
        raise DashboardDataError(BROKEN, f"{P2_CONDITIONS} covers {listed} runs, {P2_RUNS} has {len(run_ids)}")

    conditions = []
    for c in conds:
        if c.get("measurement_classes") != "constrained" or c.get("all_dds_verified") != "true":
            raise DashboardDataError(BROKEN, f"{P2_CONDITIONS}: condition not constrained + DDS-verified")
        model = c["model_name"]
        conditions.append({
            "family": c["scenario"].replace("_sweep", ""),
            "model": model,
            "input_fps": _r(c["input_fps"], 1),
            "qos_depth": _int(c["qos_depth"]),
            "delay_ms": _int(c["fake_delay_ms"]),
            "n_runs": _int(c["n_runs"]),
            "drop_cause": c["drop_causes"],
            "offered_fps": _stats(c, "offered_fps"),
            "processed_fps": _stats(c, "processed_fps"),
            "capacity_fps": _stats(c, "capacity_fps"),
            "utilization": _stats(c, "utilization"),
            "drop_rate_pct": _stats(c, "drop_rate_pct"),
            "expected_overload_drop_pct": _stats(c, "expected_overload_drop_pct"),
            "deadline_miss_rate_pct": _stats(c, "deadline_miss_rate_pct"),
            "effective_miss_rate_pct": _stats(c, "effective_miss_rate_pct"),
            "p50_latency_ms": _stats(c, "p50_latency_ms"),
            "p95_latency_ms": _stats(c, "p95_latency_ms"),
            "p99_latency_ms": _stats(c, "p99_latency_ms"),
            "avg_transport_ms": _stats(c, "avg_transport_ms"),
            "avg_preprocess_ms": _stats(c, "avg_preprocess_ms"),
            "avg_artificial_delay_ms": _stats(c, "avg_artificial_delay_ms"),
            "avg_inference_ms": _stats(c, "avg_inference_ms"),
            "avg_service_ms": _stats(c, "avg_service_ms"),
            "detector_cpu_pct": _stats(c, "detector_cpu_pct", 1),
            "max_memory_mb": _stats(c, "max_memory_mb", 1),
            "cgroup_memory_peak_mb": _stats(c, "cgroup_memory_peak_mb", 1),
        })

    run_rows = [{
        "run_id": r["run_id"], "family": r["scenario"].replace("_sweep", ""), "model": r["model_name"],
        "input_fps": _r(r["input_fps"], 1), "qos_depth": _int(r["qos_depth"]), "delay_ms": _int(r["fake_delay_ms"]),
        "processed_fps": _r(r["processed_fps"]), "drop_rate_pct": _r(r["drop_rate_pct"]),
        "effective_miss_rate_pct": _r(r["effective_miss_rate_pct"]), "p99_latency_ms": _r(r["p99_latency_ms"]),
        "capacity_fps": _r(r["capacity_fps"]), "utilization": _r(r["utilization"]),
    } for r in runs]

    capacity = {}
    for model in sorted({r["model_name"] for r in runs}):
        vals = [_num(r["capacity_fps"]) for r in runs
                if r["model_name"] == model and _int(r["fake_delay_ms"]) == 0 and _num(r["capacity_fps"]) is not None]
        svc = [_num(r["avg_service_ms"]) for r in runs
               if r["model_name"] == model and _int(r["fake_delay_ms"]) == 0 and _num(r["avg_service_ms"]) is not None]
        sat = [_num(r["processed_fps"]) for r in runs
               if r["model_name"] == model and _int(r["fake_delay_ms"]) == 0
               and (_num(r["utilization"]) or 0) >= 1.0 and _num(r["processed_fps"]) is not None]
        if not vals or not sat:
            raise DashboardDataError(BLOCKED, f"{P2_RUNS}: no delay-0 / overloaded runs for {model}")
        capacity[model] = {
            "definition": ("saturated throughput = processed FPS of delay-0 runs with ρ ≥ 1 "
                           "(the detector is never idle); service capacity = 1000 / mean service time, all delay-0 runs"),
            "n_runs": len(sat), "mean": _r(sum(sat) / len(sat), 2), "min": _r(min(sat), 2), "max": _r(max(sat), 2),
            "service_capacity": {"n_runs": len(vals), "mean": _r(sum(vals) / len(vals), 2),
                                 "min": _r(min(vals), 2), "max": _r(max(vals), 2)},
            "service_ms_mean": _r(sum(svc) / len(svc), 2),
        }

    below = [r for r in runs if (_num(r["utilization"]) or 0) < 1.0]
    over = [r for r in runs if (_num(r["utilization"]) or 0) >= 1.0 and _num(r["expected_overload_drop_pct"]) is not None]
    drop_model = {
        "below_capacity_runs": len(below),
        "below_capacity_max_drop_pct": _r(max(_num(r["drop_rate_pct"]) or 0 for r in below)),
        "overloaded_runs": len(over),
        "overloaded_mean_abs_gap_pp": _r(sum(abs(_num(r["drop_rate_pct"]) - _num(r["expected_overload_drop_pct"]))
                                             for r in over) / len(over), 2) if over else None,
        "overloaded_max_abs_gap_pp": _r(max(abs(_num(r["drop_rate_pct"]) - _num(r["expected_overload_drop_pct"]))
                                            for r in over), 2) if over else None,
    }
    for r in run_rows:
        src_row = next(x for x in runs if x["run_id"] == r["run_id"])
        r["expected_overload_drop_pct"] = _r(src_row["expected_overload_drop_pct"])
        r["p50_latency_ms"] = _r(src_row["p50_latency_ms"])

    controls, commits = _controls(src, P2_RAW_DIR, run_ids, CONTROL_KEYS)
    tags = Counter("capacity extension" if "_b2cap_" in rid else "formal grid" for rid in run_ids)
    baseline = {
        "n_runs": len(run_ids), "n_conditions": len(conditions), "run_groups": dict(sorted(tags.items())),
        "conditions": conditions, "runs": run_rows, "capacity": capacity, "drop_model": drop_model, "controls": controls,
        "commits": [{"commit": c, "dirty": d, "runs": n} for (c, d), n in sorted(commits.items())],
        "chain_records_verified": chain,
    }
    return baseline, run_ids


# --- Phase 3 formal A/B ------------------------------------------------------------------

def build_scheduling(src: Sources) -> dict[str, Any]:
    chain = _verify_summary_manifest(src, P3_SUMMARY_MANIFEST)
    chain += _verify_aggregate_manifest(src, P3_AGG_MANIFEST, (P3_RUNS, P3_ARMS, P3_PAIRED))
    chain += _verify_aggregate_manifest(src, P3_DYN_MANIFEST, (P3_DYN_ARMS, P3_DYN_PAIRED))
    runs = src.csv(P3_RUNS, "Phase 3 formal per-run table")
    arms = src.csv(P3_ARMS, "Phase 3 formal per-arm table")
    paired = src.csv(P3_PAIRED, "Phase 3 formal paired differences")
    dyn_arms = src.csv(P3_DYN_ARMS, "Phase 3 dynamic per-phase table")
    dyn_paired = src.csv(P3_DYN_PAIRED, "Phase 3 dynamic per-phase paired differences")

    conditions: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    run_rows, run_ids, blocks = [], [], {}
    for r in runs:
        rid = r["run_id"]
        if not P3_RUN_ID.search(rid) or not r.get("run_tag", "").startswith("p3b2_"):
            raise DashboardDataError(BROKEN, f"{P3_RUNS}: run {rid} is not a Phase 3 / Batch 2 formal run")
        if r.get("measurement_class") != "constrained" or r.get("dds_verified") != "true":
            raise DashboardDataError(BROKEN, f"{P3_RUNS}: run {rid} is not constrained + DDS-verified")
        arm = r["scheduler_arm"]
        if arm not in ARMS:
            raise DashboardDataError(BROKEN, f"{P3_RUNS}: unknown arm {arm}")
        cid = _condition_id(r["model_name"], r["input_fps"], r["fake_delay_ms"], r.get("fps_schedule", ""))
        conditions.setdefault(cid, {
            "id": cid, "label": _condition_label(r["model_name"], r["input_fps"], r["fake_delay_ms"], r.get("fps_schedule", "")),
            "model": r["model_name"], "input_fps": _r(r["input_fps"], 1), "delay_ms": _int(r["fake_delay_ms"]),
            "fps_schedule": r.get("fps_schedule", ""), "deadline_ms": _r(r["deadline_ms"], 1),
            "dynamic": bool(r.get("fps_schedule")), "primary": cid == PRIMARY_CONDITION,
        })
        blocks.setdefault(cid, {}).setdefault(r["run_tag"], []).append(arm)
        run_ids.append(rid)
        run_rows.append({
            "condition": cid, "arm": arm, "block": r["run_tag"], "position": _int(r["arm_position"]),
            "effective_miss_rate_pct": _r(r["effective_miss_rate_pct"]), "on_time_fps": _r(r["on_time_fps"]),
            "p99_latency_ms": _r(r["p99_latency_ms"]), "drop_rate_pct": _r(r["drop_rate_pct"]),
            "deadline_miss_rate_pct": _r(r["deadline_miss_rate_pct"]), "avg_service_ms": _r(r["avg_service_ms"]),
            "decisions": _parse_counts(r.get("scheduler_decisions", "")),
            "policy_drops": _parse_counts(r.get("policy_drop_reasons", "")),
        })
    if len(set(run_ids)) != len(run_ids):
        raise DashboardDataError(BROKEN, f"{P3_RUNS}: duplicate run ids")
    for cid, by_block in blocks.items():
        for tag, arms_in_block in by_block.items():
            if sorted(arms_in_block) != sorted(ARMS):
                raise DashboardDataError(BROKEN, f"{P3_RUNS}: block {tag} does not hold every arm exactly once")
        conditions[cid]["n_blocks"] = len(by_block)
        conditions[cid]["n_runs"] = len(by_block) * len(ARMS)
    if PRIMARY_CONDITION not in conditions:
        raise DashboardDataError(BLOCKED, f"primary condition {PRIMARY_CONDITION} is missing from {P3_RUNS}")
    # stable presentation order: fixed-rate S by FPS, XXS, then dynamic
    order = sorted(conditions, key=lambda c: (conditions[c]["dynamic"], conditions[c]["model"] != "mobilevit_s",
                                              conditions[c]["input_fps"] or 0))

    arm_rows = []
    seen = Counter()
    for a in arms:
        cid = _condition_id(a["model_name"], a["input_fps"], a["fake_delay_ms"], a.get("fps_schedule", ""))
        arm = a["scheduler_arm"]
        if cid not in conditions or arm not in ARMS:
            raise DashboardDataError(BROKEN, f"{P3_ARMS}: row ({cid}, {arm}) has no formal runs")
        if a.get("measurement_classes") != "constrained" or a.get("all_dds_verified") != "true":
            raise DashboardDataError(BROKEN, f"{P3_ARMS}: ({cid}, {arm}) not constrained + DDS-verified")
        for rid in a["run_ids"].split(";"):
            if not P3_RUN_ID.search(rid):
                raise DashboardDataError(BROKEN, f"{P3_ARMS}: ({cid}, {arm}) includes non-formal run {rid}")
        n = _int(a["n_runs"])
        if n != conditions[cid]["n_blocks"]:
            raise DashboardDataError(BROKEN, f"{P3_ARMS}: ({cid}, {arm}) n_runs={n} != blocks {conditions[cid]['n_blocks']}")
        seen[cid] += 1
        eff = _stats(a, "effective_miss_rate_pct")
        drop = _stats(a, "drop_rate_pct")
        arm_rows.append({
            "condition": cid, "arm": arm, "n_runs": n,
            "utilization": _stats(a, "utilization"),
            "processed_fps": _stats(a, "processed_fps"), "on_time_fps": _stats(a, "on_time_fps"),
            "drop_rate_pct": drop, "deadline_miss_rate_pct": _stats(a, "deadline_miss_rate_pct"),
            "effective_miss_rate_pct": eff,
            "late_share_pct": _r((eff["mean"] or 0) - (drop["mean"] or 0)),
            "effective_miss_excl_tail_pct": _stats(a, "effective_miss_excl_tail_pct"),
            "p50_latency_ms": _stats(a, "p50_latency_ms"), "p95_latency_ms": _stats(a, "p95_latency_ms"),
            "p99_latency_ms": _stats(a, "p99_latency_ms"),
            "p50_frame_age_at_start_ms": _stats(a, "p50_frame_age_at_start_ms"),
            "avg_queue_wait_ms": _stats(a, "avg_queue_wait_ms"),
            "max_queue_len": _stats(a, "max_queue_len"),
            "avg_service_ms": _stats(a, "avg_service_ms"), "avg_inference_ms": _stats(a, "avg_inference_ms"),
            "detector_cpu_pct": _stats(a, "detector_cpu_pct", 1), "max_memory_mb": _stats(a, "max_memory_mb", 1),
            "dds_unreceived_frames": _stats(a, "dds_unreceived_frames", 1),
            "app_policy_drop_rate_pct": _stats(a, "app_policy_drop_rate_pct"),
        })
    for cid in conditions:
        if seen[cid] != len(ARMS):
            raise DashboardDataError(BROKEN, f"{P3_ARMS}: condition {cid} has {seen[cid]} arms, expected {len(ARMS)}")

    paired_rows = []
    for p in paired:
        cid = _condition_id(p["model_name"], p["input_fps"], p["fake_delay_ms"], p.get("fps_schedule", ""))
        arm, ref = p["scheduler_arm"], p["reference_arm"]
        if cid not in conditions or arm not in ARMS or ref not in ARMS:
            raise DashboardDataError(BROKEN, f"{P3_PAIRED}: row ({cid}, {arm} − {ref}) has no formal runs")
        n = _int(p["n_blocks"])
        if n != conditions[cid]["n_blocks"]:
            raise DashboardDataError(BROKEN, f"{P3_PAIRED}: ({cid}, {arm} − {ref}) n_blocks={n} != {conditions[cid]['n_blocks']}")
        cross = ARMS[arm]["family"] != ARMS[ref]["family"]
        paired_rows.append({
            "condition": cid, "arm": arm, "reference": ref, "n_blocks": n,
            "comparison": "cross_architecture" if cross else "same_architecture",
            "metrics": {m: _paired_entry(p, m) for m in METRICS_PAIRED},
        })

    dyn_cid = next((c for c in conditions if conditions[c]["dynamic"]), None)
    dynamic = {"condition": dyn_cid, "phases": [], "paired": []}
    if dyn_cid:
        for d in dyn_arms:
            if d["scheduler_arm"] not in ARMS:
                raise DashboardDataError(BROKEN, f"{P3_DYN_ARMS}: unknown arm {d['scheduler_arm']}")
            dynamic["phases"].append({
                "arm": d["scheduler_arm"], "phase": _int(d["phase"]), "target_fps": _r(d["target_fps"], 1),
                "n_runs": _int(d["n_runs"]),
                "effective_miss_pct": _stats(d, "effective_miss_pct"), "on_time_fps": _stats(d, "on_time_fps"),
                "drop_pct": _stats(d, "drop_pct"), "late_pct": _stats(d, "late_pct"),
                "p99_latency_ms": _stats(d, "p99_latency_ms"),
                "transient_effective_miss_pct": _stats(d, "transient_effective_miss_pct"),
            })
        for d in dyn_paired:
            if d["scheduler_arm"] not in ARMS or d["reference_arm"] not in ARMS:
                raise DashboardDataError(BROKEN, f"{P3_DYN_PAIRED}: unknown arm")
            cross = ARMS[d["scheduler_arm"]]["family"] != ARMS[d["reference_arm"]]["family"]
            dynamic["paired"].append({
                "phase": _int(d["phase"]), "arm": d["scheduler_arm"], "reference": d["reference_arm"],
                "n_blocks": _int(d["n_blocks"]), "comparison": "cross_architecture" if cross else "same_architecture",
                "metrics": {m: _paired_entry(d, m) for m in METRICS_DYN_PAIRED},
            })
        dynamic["phases"].sort(key=lambda x: (x["phase"], list(ARMS).index(x["arm"])))
        dynamic["paired"].sort(key=lambda x: (x["phase"], x["reference"], x["arm"]))

    controls, commits = _controls(src, P3_RAW_DIR, run_ids, CONTROL_KEYS + P3_EXTRA_CONTROL_KEYS)
    arm_rows.sort(key=lambda x: (order.index(x["condition"]), list(ARMS).index(x["arm"])))
    paired_rows.sort(key=lambda x: (order.index(x["condition"]), x["reference"], x["arm"]))
    run_rows.sort(key=lambda x: (order.index(x["condition"]), x["block"], list(ARMS).index(x["arm"])))
    return {
        "n_runs": len(run_ids), "n_blocks": sum(c["n_blocks"] for c in conditions.values()),
        "conditions": [conditions[c] for c in order], "arms_table": arm_rows, "paired": paired_rows,
        "runs": run_rows, "dynamic": dynamic, "controls": controls,
        "commits": [{"commit": c, "dirty": d, "runs": n} for (c, d), n in sorted(commits.items())],
        "chain_records_verified": chain,
    }


# --- derived views -----------------------------------------------------------------------

def _find(rows, **kw):
    for row in rows:
        if all(row.get(k) == v for k, v in kw.items()):
            return row
    return None


def _require(rows, **kw):
    row = _find(rows, **kw)
    if row is None:
        raise DashboardDataError(BLOCKED, f"required row missing: {kw}")
    return row


def build_mechanism(sched: dict[str, Any]) -> dict[str, Any]:
    arms_t, paired = sched["arms_table"], sched["paired"]
    feasibility = []
    for cond in sched["conditions"]:
        if cond["dynamic"]:
            continue
        cid = cond["id"]
        latest = _require(arms_t, condition=cid, arm="latest_q10")
        guard = _require(arms_t, condition=cid, arm="guard_c5_q10")
        deadline = cond["deadline_ms"]
        inter = 1000.0 / cond["input_fps"]
        service = latest["avg_service_ms"]["mean"]
        rho = latest["utilization"]["mean"]
        overloaded = rho is not None and rho >= 1.0
        late_window = max(0.0, inter - (deadline - service))
        predicted = 100.0 * late_window / inter if overloaded else 0.0
        d = _require(paired, condition=cid, arm="guard_c5_q10", reference="latest_q10")["metrics"]["effective_miss_rate_pct"]
        feasibility.append({
            "condition": cid, "deadline_ms": deadline, "inter_arrival_ms": _r(inter, 2),
            "service_ms": _r(service, 2), "age_bound_ms": _r(inter + service, 2), "utilization": _r(rho),
            "overloaded": overloaded, "late_window_ms": _r(late_window, 2),
            "predicted_latest_late_pct": _r(predicted, 2),
            "observed_latest_deadline_miss_pct": latest["deadline_miss_rate_pct"]["mean"],
            "observed_guard_deadline_miss_pct": guard["deadline_miss_rate_pct"]["mean"],
            "guard_minus_latest_eff_pp": d,
            "regime": ("not overloaded: the worker is usually idle when a frame arrives" if not overloaded else
                       "overloaded and inter-arrival + service > deadline: by the first-order bound, the newest frame can be too old to finish in time"
                       if late_window > 0 else
                       "overloaded but inter-arrival + service ≤ deadline: by the first-order bound, the newest frame can still finish in time"),
        })

    decisions = []
    for cond in sched["conditions"]:
        for arm in ("latest_q10", "guard_c5_q10", "adaptive_c5_q10"):
            rows = [r for r in sched["runs"] if r["condition"] == cond["id"] and r["arm"] == arm]
            keys = sorted({k for r in rows for k in r["decisions"]} | {k for r in rows for k in r["policy_drops"]})
            decisions.append({
                "condition": cond["id"], "arm": arm, "n_runs": len(rows),
                "decisions": {k: _r(sum(r["decisions"].get(k, 0) for r in rows) / len(rows), 1)
                              for k in sorted({k for r in rows for k in r["decisions"]})},
                "policy_drops": {k: _r(sum(r["policy_drops"].get(k, 0) for r in rows) / len(rows), 1)
                                 for k in sorted({k for r in rows for k in r["policy_drops"]})},
                "keys": keys,
            })
    return {
        "feasibility": feasibility, "decisions": decisions,
        "model_note": ("First-order model, not fitted: under overload the worker frees at a random phase "
                       "relative to arrivals, so the newest frame's age is ~uniform on [0, inter-arrival). "
                       "Latest-Frame misses when age > deadline − service."),
    }


def build_kpis(base: dict[str, Any], sched: dict[str, Any], mech: dict[str, Any]) -> tuple[dict, list[dict]]:
    paired = sched["paired"]

    def pd(cid, arm, ref, metric="effective_miss_rate_pct"):
        row = _require(paired, condition=cid, arm=arm, reference=ref)
        return {**row["metrics"][metric], "n_blocks": row["n_blocks"], "condition": cid, "arm": arm,
                "reference": ref, "metric": metric, "source": P3_PAIRED}

    dyn_cid = sched["dynamic"]["condition"]
    kpis = {
        "guard_vs_latest_primary": pd(PRIMARY_CONDITION, "guard_c5_q10", "latest_q10"),
        "adaptive_vs_latest_primary": pd(PRIMARY_CONDITION, "adaptive_c5_q10", "latest_q10"),
        "adaptive_vs_guard_primary": pd(PRIMARY_CONDITION, "adaptive_c5_q10", "guard_c5_q10"),
        "guard_vs_latest_primary_ontime": pd(PRIMARY_CONDITION, "guard_c5_q10", "latest_q10", "on_time_fps"),
        "guard_vs_latest_primary_p99": pd(PRIMARY_CONDITION, "guard_c5_q10", "latest_q10", "p99_latency_ms"),
        "guard_vs_latest_primary_drop": pd(PRIMARY_CONDITION, "guard_c5_q10", "latest_q10", "drop_rate_pct"),
        "guard_vs_latest_primary_late": pd(PRIMARY_CONDITION, "guard_c5_q10", "latest_q10", "deadline_miss_rate_pct"),
    }
    if dyn_cid:
        kpis["guard_vs_latest_dynamic"] = pd(dyn_cid, "guard_c5_q10", "latest_q10")
        kpis["adaptive_vs_latest_dynamic"] = pd(dyn_cid, "adaptive_c5_q10", "latest_q10")
        kpis["adaptive_vs_guard_dynamic"] = pd(dyn_cid, "adaptive_c5_q10", "guard_c5_q10")
    ag = [r["metrics"]["effective_miss_rate_pct"] for r in paired
          if r["arm"] == "adaptive_c5_q10" and r["reference"] == "guard_c5_q10"]
    kpis["adaptive_vs_guard_all"] = {
        "conditions": len(ag), "max_abs_mean": _r(max(abs(x["mean"]) for x in ag)),
        "all_ci_include_zero": all(x["lo"] <= 0 <= x["hi"] for x in ag), "source": P3_PAIRED,
    }
    null_conds = [f["condition"] for f in mech["feasibility"]
                  if _require(paired, condition=f["condition"], arm="guard_c5_q10", reference="latest_q10")
                  ["metrics"]["effective_miss_rate_pct"]["lo"] <= 0
                  <= _require(paired, condition=f["condition"], arm="guard_c5_q10", reference="latest_q10")
                  ["metrics"]["effective_miss_rate_pct"]["hi"]]
    kpis["guard_vs_latest_null_conditions"] = null_conds
    kpis["capacity"] = base["capacity"]
    kpis["runs"] = {"phase2": base["n_runs"], "phase3": sched["n_runs"], "total": base["n_runs"] + sched["n_runs"],
                    "phase3_blocks": sched["n_blocks"]}
    pf = _require(mech["feasibility"], condition=PRIMARY_CONDITION)
    kpis["primary_feasibility"] = pf

    label = {c["id"]: c["label"] for c in sched["conditions"]}
    g, a, ag1 = kpis["guard_vs_latest_primary"], kpis["adaptive_vs_latest_primary"], kpis["adaptive_vs_guard_primary"]
    s_cap, x_cap = base["capacity"].get("mobilevit_s"), base["capacity"].get("mobilevit_xxs")
    dm = base["drop_model"]
    findings = [
        {"id": "capacity", "kind": "measured",
         "title": "Throughput saturates at the service-time limit; below capacity, drops stay near zero",
         "text": (f"With the Fast DDS SHM profile verified at run time, saturated MobileViT-S processes "
                  f"{_fmt(s_cap['mean'])} FPS ({_fmt(s_cap['min'])}–{_fmt(s_cap['max'])}, n={s_cap['n_runs']} runs) and "
                  f"MobileViT-XXS {_fmt(x_cap['mean'])} FPS ({_fmt(x_cap['min'])}–{_fmt(x_cap['max'])}, n={x_cap['n_runs']} runs). "
                  f"Below capacity the worst run drops {_fmt(dm['below_capacity_max_drop_pct'], 2)}% of frames "
                  f"({dm['below_capacity_runs']} runs); above it the measured drop rate stays within "
                  f"{_fmt(dm['overloaded_mean_abs_gap_pp'])} pp on average of the 1 − 1/ρ prediction "
                  f"({dm['overloaded_runs']} runs).") if s_cap and x_cap else ""},
        {"id": "guard", "kind": "measured",
         "title": "Dropping frames predicted to miss the deadline lowers effective miss",
         "text": (f"At {label[PRIMARY_CONDITION]} (primary condition, n={g['n_blocks']} paired blocks) Deadline-Guard lowers "
                  f"effective miss vs Latest-Frame by {_fmt(-g['mean'])} pp (95% CI {_fmt(g['lo'])} to {_fmt(g['hi'])} pp; "
                  f"{g['n_neg']}/{g['n_blocks']} blocks lower) and Adaptive by {_fmt(-a['mean'])} pp "
                  f"({_fmt(a['lo'])} to {_fmt(a['hi'])}; {a['n_neg']}/{a['n_blocks']}).")},
        {"id": "adaptive", "kind": "measured",
         "title": "Adaptive's utilisation switch adds no measurable benefit",
         "text": (f"Adaptive − Deadline-Guard at {label[PRIMARY_CONDITION]}: {_fmt(ag1['mean'], 2, True)} pp "
                  f"(95% CI {_fmt(ag1['lo'], 2)} to {_fmt(ag1['hi'], 2)}; {ag1['n_neg']} lower / {ag1['n_pos']} higher). "
                  f"Across all {kpis['adaptive_vs_guard_all']['conditions']} conditions |Δ| ≤ "
                  f"{_fmt(kpis['adaptive_vs_guard_all']['max_abs_mean'], 2)} pp and every CI includes 0. "
                  "Not an equivalence test.")},
        {"id": "regime", "kind": "measured",
         "title": "Among the tested conditions, the benefit appears in one load regime",
         "text": (f"It appears when the system is overloaded and inter-arrival + service exceeds the deadline "
                  f"({label[PRIMARY_CONDITION]}: {_fmt(pf['inter_arrival_ms'])} + {_fmt(pf['service_ms'])} ms > "
                  f"{_fmt(pf['deadline_ms'], 0)} ms). Guard − Latest CI includes 0 at: "
                  + ", ".join(label[c] for c in null_conds) + ".")},
    ]
    if dyn_cid:
        gd = kpis["guard_vs_latest_dynamic"]
        findings.append({
            "id": "dynamic", "kind": "measured", "title": "Same ordering under a load step",
            "text": (f"{label[dyn_cid]} (n={gd['n_blocks']} blocks): Guard − Latest {_fmt(gd['mean'], 1, True)} pp "
                     f"({_fmt(gd['lo'])} to {_fmt(gd['hi'])}; {gd['n_neg']}/{gd['n_blocks']} blocks lower); "
                     f"Adaptive − Guard {_fmt(kpis['adaptive_vs_guard_dynamic']['mean'], 2, True)} pp.")})
    return kpis, findings


def build_simulation(src: Sources) -> dict[str, Any]:
    sidecar = src.json(SIM_SIDECAR, "simulation provenance sidecar")
    out = sidecar.get("output") or {}
    full = src.path(SIM_SWEEP, "EDA-Lite simulation estimates")
    if sha256_file(full) != out.get("sha256"):
        raise DashboardDataError(BROKEN, f"{SIM_SWEEP} no longer matches {SIM_SIDECAR}")
    rows = src.csv(SIM_SWEEP, "EDA-Lite simulation estimates")
    data = []
    for r in rows:
        if r.get("os_profile_provenance") != "builtin":
            raise DashboardDataError(BROKEN, f"{SIM_SWEEP}: row with os_profile_provenance="
                                             f"{r.get('os_profile_provenance')} (only built-in profiles are shown)")
        data.append({
            "model": "mobilevit_s" if r["model_name"].startswith("mobilevit_s_") else "mobilevit_xxs",
            "scheduler": r["scheduler"], "sram_kb": _int(r["sram_kb"]), "os_profile": r["os_profile"],
            "feasible": r["feasible"] == "true", "num_subgraphs": _int(r["num_subgraphs"]),
            "max_fusion_depth": _int(r["max_fusion_depth"]), "peak_sram_kb": _r(r["peak_sram_kb"], 1),
            "dram_traffic_kb": _r(r["dram_traffic_kb"], 1), "estimated_energy": _r(r["estimated_energy"], 2),
            "estimated_latency_ms": _r(r["estimated_latency_ms"], 3), "os_aware_total_cost": _r(r["os_aware_total_cost"], 2),
            "subgraphs": r["subgraphs"],
        })
    data.sort(key=lambda x: (x["model"], x["os_profile"], x["sram_kb"], x["scheduler"]))
    return {
        "kind": "simulation_estimate",
        "note": ("EDA-Lite outputs are cost-model estimates (simplified MobileViT block profiles, built-in OS profiles). "
                 "They are not hardware measurements and are not linked to the ROS 2 measurements."),
        "config": (sidecar.get("config") or {}).get("path"),
        "rows": data,
    }


EXCLUDED = [
    {"path": "results/raw/ros2_phase3_pilot/, results/csv/ros2_phase3_pilot_*",
     "reason": "Phase 3 / Batch 1 pilot (40 s runs, dirty tree): Phase 3 gate reports BROKEN by design; preliminary only."},
    {"path": "experiments/eda_lite/runtime_os_profiles.legacy_unverified.json, results/figures/ros2/*.svg",
     "reason": "Teammate-provided legacy values without raw data: UNVERIFIED."},
    {"path": "experiments/eda_lite/runtime_os_profiles.example.json",
     "reason": "Illustrative example profiles, not measured."},
    {"path": "results/csv/eda_lite_*runtime_aware*",
     "reason": "Simulation driven by example / unverified OS profiles."},
]


def build_bundle(root: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    src = Sources(root)
    base, _ = build_baseline(src)
    sched = build_scheduling(src)
    mech = build_mechanism(sched)
    kpis, findings = build_kpis(base, sched, mech)
    sim = build_simulation(src)
    arms = [{"id": k, **v} for k, v in ARMS.items()]
    bundle = {
        "schema": SCHEMA, "generator": GENERATOR,
        "primary_condition": PRIMARY_CONDITION,
        "arms": arms, "kpis": kpis, "findings": findings,
        "baseline": base, "scheduling": sched, "mechanism": mech, "simulation": sim,
        "excluded": EXCLUDED,
        "sources": sorted(src.records.values(), key=lambda r: r["path"]),
    }
    return bundle, sorted(src.records.values(), key=lambda r: r["path"])


def render(bundle: dict[str, Any], inputs: list[dict[str, str]]) -> dict[str, bytes]:
    text = json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    js = ("// Generated by python3 -m src.dashboard.build_data - do not edit.\n"
          "window.DASHBOARD_DATA = " + json.dumps(bundle, ensure_ascii=False, sort_keys=True) + ";\n")
    files = {OUTPUT_JSON: text.encode("utf-8"), OUTPUT_JS: js.encode("utf-8")}
    manifest = {
        "schema": "dashboard_data_manifest/v1", "generator": GENERATOR,
        "inputs": [{"path": r["path"], "sha256": r["sha256"]} for r in inputs],
        "outputs": [{"path": f"{OUTPUT_DIR}/{name}", "sha256": hashlib.sha256(body).hexdigest()}
                    for name, body in sorted(files.items())],
    }
    files[OUTPUT_MANIFEST] = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode("utf-8")
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(REPO), help="repository root (default: this checkout)")
    ap.add_argument("--output-dir", default=None, help=f"default: <root>/{OUTPUT_DIR}")
    ap.add_argument("--check", action="store_true", help="verify the existing bundle is current; write nothing")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    out_dir = Path(args.output_dir) if args.output_dir else root / OUTPUT_DIR
    try:
        bundle, inputs = build_bundle(root)
    except DashboardDataError as exc:
        print(f"{STATUS_LABEL[exc.status]}: {exc}", file=sys.stderr)
        return exc.status
    files = render(bundle, inputs)
    if args.check:
        stale = [n for n, body in files.items()
                 if not (out_dir / n).is_file() or (out_dir / n).read_bytes() != body]
        if stale:
            print("STALE: " + ", ".join(stale) + " differ from the sources; run python3 -m src.dashboard.build_data",
                  file=sys.stderr)
            return STALE
        print(f"CURRENT: dashboard data matches {len(inputs)} verified inputs")
        return OK
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (out_dir / name).write_bytes(body)
    k = bundle["kpis"]
    print(f"OK: wrote {', '.join(sorted(files))} to {out_dir} "
          f"({len(inputs)} inputs; Phase 2 {k['runs']['phase2']} runs, Phase 3 {k['runs']['phase3']} runs)")
    return OK


if __name__ == "__main__":
    sys.exit(main())
