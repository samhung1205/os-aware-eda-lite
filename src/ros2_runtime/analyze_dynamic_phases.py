"""Per-phase analysis of dynamic-input-rate scheduling runs (Phase 3 / Batch 2).

    python3 -m src.ros2_runtime.analyze_dynamic_phases --raw-dir results/raw/ros2_phase3_formal \
        --phases-output results/csv/ros2_phase3_formal_dynamic_phases.csv \
        --arms-output results/csv/ros2_phase3_formal_dynamic_arms.csv \
        --paired-output results/csv/ros2_phase3_formal_dynamic_paired.csv \
        [--reference-arm latest_q10 ...] [--transient-s 3]

Input: every run under ``--raw-dir`` whose ``<run_id>.meta.json`` has a non-empty
``experiment.fps_schedule`` (``"<fps>@<s>,..."``), i.e. the publisher changed its rate
during the run. Fixed-rate runs are ignored.

Phase of a frame = schedule segment at ``published_at_ns - published_at_ns(frame 0)``
(the publisher switches its timer at the same offsets, measured from frame 0). Frames
up to the last warm-up frame are excluded (same window rule as ``analyze_runtime``).
Every published frame in the window has exactly one outcome: processed on time,
processed late (``latency_ms > deadline_ms``), or dropped (explicit drop row of any
reason, or no detector row at all). Per (run, phase):

- ``published``, ``processed``, ``on_time``, ``late``, ``dropped``, ``end_of_run_lost``
  (drop rows ``shutdown_pending`` / ``shutdown_inflight`` plus frames published after the
  detector's last row — only possible in the last phase);
- ``effective_miss_pct`` = (late + dropped) / published; ``effective_miss_excl_tail_pct``
  removes ``end_of_run_lost`` from both;
- ``offered_fps`` measured from publisher timestamps, ``on_time_fps`` = offered x (1 - eff);
- P50 / P95 / P99 latency and P50 frame age at start of the processed frames;
- ``transient_*``: the same counts for the frames published in the first ``--transient-s``
  seconds of the phase (phase 0 excluded: no step) -> reaction to the rate step.

``--arms-output``: mean / sample SD / min / max across runs per (arm, phase).
``--paired-output``: per phase, arm - reference within the same block (run_tag), mean /
SD / 95 % t-interval / min / max over blocks. The run is the statistical unit.
Standard library only; read-only on its inputs; writes a SHA-256 manifest.
"""

from __future__ import annotations

import argparse
import csv
import json
from math import ceil
from pathlib import Path
from statistics import mean, stdev
from typing import Any

from src.provenance import sha256_file
from src.ros2_runtime.aggregate_scheduling import _paired_stats, _write_csv

END_OF_RUN_REASONS = {"shutdown_pending", "shutdown_inflight"}
PHASE_METRICS = [
    "offered_fps", "on_time_fps", "effective_miss_pct", "effective_miss_excl_tail_pct",
    "drop_pct", "late_pct", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms",
    "p50_frame_age_at_start_ms", "transient_effective_miss_pct", "transient_p99_latency_ms",
]


def parse_schedule(text: str) -> list[tuple[float, float]]:
    """Same grammar as run_log.parse_fps_schedule ("<fps>@<s>,..."); [] when empty."""

    text = (text or "").strip()
    if not text or text.lower() == "none":
        return []
    out = []
    for part in text.split(","):
        fps, seconds = part.split("@")
        out.append((float(fps), float(seconds)))
    return out


def schedule_phase(schedule: list[tuple[float, float]], elapsed_s: float) -> int:
    """Identical to run_log.schedule_phase (the analyzer must not import the ROS package)."""

    start = 0.0
    for index, (_, seconds) in enumerate(schedule):
        if elapsed_s < start + seconds:
            return index
        start += seconds
    return len(schedule) - 1


def phase_starts(schedule: list[tuple[float, float]]) -> list[float]:
    starts, t = [], 0.0
    for _, seconds in schedule:
        starts.append(t)
        t += seconds
    return starts


def _pct(n: int, d: int) -> float | None:
    return None if d <= 0 else 100.0 * n / d


def _q(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, ceil(q / 100.0 * len(ordered)) - 1)]


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.6g}"


def _f(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def analyze_run(detector_rows: list[dict[str, str]], publisher: dict[int, int],
                schedule: list[tuple[float, float]], deadline_ms: float,
                transient_s: float) -> list[dict[str, Any]]:
    """Per-phase outcome counts of one run (see module docstring)."""

    if not publisher:
        raise ValueError("no publisher log: phases need publish timestamps.")
    by_frame: dict[int, dict[str, str]] = {}
    for row in detector_rows:
        if row.get("frame_id", "") == "":
            continue
        fid = int(row["frame_id"])
        if fid in by_frame:
            raise ValueError(f"frame_id {fid} has two detector rows.")
        by_frame[fid] = row
    warm = [fid for fid, row in by_frame.items() if row.get("warmup") == "1"]
    boundary = max(warm) if warm else -1
    last_seen = max(by_frame) if by_frame else -1
    t0 = publisher[min(publisher)]
    starts = phase_starts(schedule)
    phases: dict[int, dict[str, Any]] = {
        i: {"phase": i, "target_fps": fps, "scheduled_s": seconds, "published": 0, "processed": 0,
            "on_time": 0, "late": 0, "dropped": 0, "end_of_run_lost": 0, "latencies": [], "ages": [],
            "stamps": [], "tr_published": 0, "tr_bad": 0, "tr_latencies": []}
        for i, (fps, seconds) in enumerate(schedule)
    }
    for fid in sorted(publisher):
        if fid <= boundary:
            continue
        elapsed = (publisher[fid] - t0) / 1e9
        p = phases[schedule_phase(schedule, elapsed)]
        p["published"] += 1
        p["stamps"].append(publisher[fid])
        transient = p["phase"] > 0 and elapsed - starts[p["phase"]] < transient_s
        row = by_frame.get(fid)
        bad = True
        if row is None:
            p["dropped"] += 1
            if fid > last_seen:
                p["end_of_run_lost"] += 1
        elif row.get("dropped") == "1":
            p["dropped"] += 1
            if row.get("drop_reason") in END_OF_RUN_REASONS:
                p["end_of_run_lost"] += 1
        else:
            latency = float(row["latency_ms"])
            p["processed"] += 1
            p["latencies"].append(latency)
            age = _f(row.get("frame_age_at_start_ms"))
            if age is not None:
                p["ages"].append(age)
            if latency > deadline_ms:
                p["late"] += 1
            else:
                p["on_time"] += 1
                bad = False
            if transient:
                p["tr_latencies"].append(latency)
        if transient:
            p["tr_published"] += 1
            p["tr_bad"] += bad
    out = []
    for i in sorted(phases):
        p = phases[i]
        n, stamps = p["published"], p["stamps"]
        offered = None if len(stamps) < 2 else (len(stamps) - 1) / ((stamps[-1] - stamps[0]) / 1e9)
        eff = _pct(p["late"] + p["dropped"], n)
        tail_n = n - p["end_of_run_lost"]
        out.append({
            "phase": i, "target_fps": p["target_fps"], "scheduled_s": p["scheduled_s"],
            "published": n, "processed": p["processed"], "on_time": p["on_time"], "late": p["late"],
            "dropped": p["dropped"], "end_of_run_lost": p["end_of_run_lost"],
            "offered_fps": offered, "effective_miss_pct": eff,
            "effective_miss_excl_tail_pct": _pct(p["late"] + p["dropped"] - p["end_of_run_lost"], tail_n),
            "drop_pct": _pct(p["dropped"], n), "late_pct": _pct(p["late"], n),
            "on_time_fps": None if offered is None or eff is None else offered * (1 - eff / 100.0),
            "p50_latency_ms": _q(p["latencies"], 50), "p95_latency_ms": _q(p["latencies"], 95),
            "p99_latency_ms": _q(p["latencies"], 99), "p50_frame_age_at_start_ms": _q(p["ages"], 50),
            "transient_published": p["tr_published"] if i > 0 else None,
            "transient_effective_miss_pct": _pct(p["tr_bad"], p["tr_published"]) if i > 0 else None,
            "transient_p99_latency_ms": _q(p["tr_latencies"], 99) if i > 0 else None,
        })
    return out


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def collect(raw_dir: Path, transient_s: float) -> tuple[list[dict[str, Any]], list[Path]]:
    rows, used = [], []
    for meta_path in sorted(raw_dir.glob("*.meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        exp = meta.get("experiment") or {}
        schedule = parse_schedule(str(exp.get("fps_schedule", "")))
        if not schedule:
            continue
        run_id = meta["run_id"]
        det_path = raw_dir / f"{run_id}.csv"
        pub_path = raw_dir / f"{run_id}.publisher.csv"
        detector = _read_csv(det_path)
        publisher = {int(r["frame_id"]): int(r["published_at_ns"]) for r in _read_csv(pub_path)}
        used += [meta_path, det_path, pub_path]
        for rec in analyze_run(detector, publisher, schedule, float(exp.get("deadline_ms", 100)), transient_s):
            rows.append({
                "run_id": run_id, "model_name": exp.get("model_name", ""),
                "fps_schedule": exp.get("fps_schedule", ""), "scheduler_arm": exp.get("scheduler_arm", ""),
                "scheduler_policy": exp.get("scheduler_policy", ""), "run_tag": exp.get("run_tag", ""),
                "arm_position": exp.get("arm_position", ""), "git_commit": (meta.get("git") or {}).get("commit", ""),
                "git_dirty": str((meta.get("git") or {}).get("dirty", "")).lower(),
                **{k: (_fmt(v) if isinstance(v, float) else ("" if v is None else v)) for k, v in rec.items()},
            })
    return rows, used


def arms_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r["model_name"], r["fps_schedule"], r["scheduler_arm"], int(r["phase"])), []).append(r)
    out = []
    for key in sorted(groups):
        runs = groups[key]
        rec: dict[str, Any] = dict(zip(["model_name", "fps_schedule", "scheduler_arm", "phase"], key))
        rec["target_fps"] = runs[0]["target_fps"]
        rec["n_runs"] = len(runs)
        for m in PHASE_METRICS:
            vals = [v for v in (_f(r.get(m)) for r in runs) if v is not None]
            rec[f"{m}_mean"] = _fmt(mean(vals)) if vals else ""
            rec[f"{m}_sd"] = _fmt(stdev(vals)) if len(vals) > 1 else ""
            rec[f"{m}_min"] = _fmt(min(vals)) if vals else ""
            rec[f"{m}_max"] = _fmt(max(vals)) if vals else ""
        out.append(rec)
    return out


def paired_table(rows: list[dict[str, Any]], references: list[str]) -> list[dict[str, Any]]:
    blocks: dict[tuple, dict[str, dict[str, Any]]] = {}
    for r in rows:
        arms = blocks.setdefault((r["model_name"], r["fps_schedule"], int(r["phase"]), r["run_tag"]), {})
        if r["scheduler_arm"] in arms:
            raise ValueError(f"block {r['run_tag']} phase {r['phase']} has two runs of {r['scheduler_arm']}.")
        arms[r["scheduler_arm"]] = r
    out = []
    for ref in references:
        diffs: dict[tuple, list[dict[str, float | None]]] = {}
        for block, arms in blocks.items():
            if ref not in arms:
                continue
            for arm, r in arms.items():
                if arm == ref:
                    continue
                d = {}
                for m in PHASE_METRICS:
                    a, b = _f(r.get(m)), _f(arms[ref].get(m))
                    d[m] = None if a is None or b is None else a - b
                diffs.setdefault((*block[:3], arm), []).append(d)
        for key in sorted(diffs):
            rec: dict[str, Any] = dict(zip(["model_name", "fps_schedule", "phase", "scheduler_arm"], key))
            rec["reference_arm"] = ref
            rec["n_blocks"] = len(diffs[key])
            for m in PHASE_METRICS:
                vals = [d[m] for d in diffs[key] if d[m] is not None]
                rec[f"d_{m}_mean"] = _fmt(mean(vals)) if vals else ""
                rec[f"d_{m}_min"] = _fmt(min(vals)) if vals else ""
                rec[f"d_{m}_max"] = _fmt(max(vals)) if vals else ""
                rec.update(_paired_stats(f"d_{m}", vals))
            out.append(rec)
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--phases-output", required=True)
    parser.add_argument("--arms-output", required=True)
    parser.add_argument("--paired-output", required=True)
    parser.add_argument("--reference-arm", action="append", default=None)
    parser.add_argument("--transient-s", type=float, default=3.0)
    args = parser.parse_args(argv)
    rows, used = collect(Path(args.raw_dir), args.transient_s)
    if not rows:
        raise SystemExit(f"no dynamic (fps_schedule) runs under {args.raw_dir}")
    outputs = {
        Path(args.phases_output): rows,
        Path(args.arms_output): arms_table(rows),
        Path(args.paired_output): paired_table(rows, args.reference_arm or ["latest_q10"]),
    }
    for path, table in outputs.items():
        _write_csv(path, table)
    manifest = {
        "generator": "src.ros2_runtime.analyze_dynamic_phases",
        "transient_s": args.transient_s,
        "reference_arms": args.reference_arm or ["latest_q10"],
        "inputs": [{"path": str(p), "sha256": sha256_file(p)} for p in used],
        "outputs": [{"path": str(p), "sha256": sha256_file(p)} for p in outputs],
    }
    manifest_path = Path(args.phases_output).with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{len(rows)} run-phase rows -> {', '.join(str(p) for p in outputs)}; manifest {manifest_path}")


if __name__ == "__main__":
    main()
