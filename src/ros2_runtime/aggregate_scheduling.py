"""Aggregate Phase 3 scheduling-policy runs (one row per run -> per arm across runs).

Input: the per-run summary written by ``analyze_runtime`` for the scheduling runs, plus
the ``<run_id>.meta.json`` / ``<run_id>.probe.json`` files next to the raw CSVs.

- ``--runs-output``: one row per run = summary + arm / block / position from the run
  metadata + probe fields (DDS verification, CPU, cgroup memory) + derived figures.
- ``--conditions-output``: one row per (model, fps, delay, arm): n runs and mean / sample
  SD / min / max **across runs** (the run is the unit; frames are never pooled).
- ``--paired-output``: per (model, fps, delay, block, arm) the difference to the reference
  arm (``--reference-arm``, default ``legacy_q1``) **run in the same block** (same RUN_TAG,
  i.e. the same interleaved sequence a few minutes apart), then mean / min / max of those
  within-block differences. This is the A/B view that is robust to slow host drift.
- ``<conditions stem>.manifest.json``: SHA-256 of the summary, its manifest, every meta /
  probe file and every output.

Derived per run: ``utilization = offered_fps * avg_service_ms / 1000``;
``on_time_fps = offered_fps * (1 - effective_miss_rate_pct / 100)`` (frames per second that
were processed within the deadline).

Standard library only. Read-only on its inputs.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, stdev
from typing import Any

from src.provenance import sha256_file
from src.ros2_runtime.aggregate_baseline import PROBE_FIELDS, _f, _fmt, probe_fields

ARM_KEYS = ["model_name", "input_fps", "fake_delay_ms", "scheduler_arm"]
META_FIELDS = ["scheduler_arm", "run_tag", "arm_position", "sched_arms"]
METRICS = [
    "offered_fps", "processed_fps", "on_time_fps", "published_frames", "processed_frames",
    "dropped_frames", "drop_rate_pct", "app_policy_drop_rate_pct", "app_policy_dropped_frames",
    "dds_unreceived_frames", "tail_unobserved_frames", "shutdown_unfinished_frames",
    "deadline_miss_rate_pct", "effective_miss_rate_pct",
    "avg_latency_ms", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "jitter_ms",
    "avg_queue_wait_ms", "p50_queue_wait_ms", "p95_queue_wait_ms",
    "avg_frame_age_at_start_ms", "p50_frame_age_at_start_ms", "p95_frame_age_at_start_ms",
    "avg_transport_ms", "p95_transport_ms", "avg_inference_ms", "avg_service_ms", "utilization",
    "max_queue_len", "avg_cpu_percent", "detector_cpu_pct", "max_memory_mb", "cgroup_memory_peak_mb",
]
PAIRED_METRICS = [
    "processed_fps", "on_time_fps", "drop_rate_pct", "deadline_miss_rate_pct",
    "effective_miss_rate_pct", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms",
    "p50_frame_age_at_start_ms", "avg_service_ms",
]


def derive(row: dict[str, Any]) -> dict[str, str]:
    service, offered = _f(row.get("avg_service_ms")), _f(row.get("offered_fps"))
    eff = _f(row.get("effective_miss_rate_pct"))
    rho = None if service is None or offered is None else offered * service / 1000.0
    on_time = None if offered is None or eff is None else offered * (1.0 - eff / 100.0)
    return {"utilization": _fmt(rho), "on_time_fps": _fmt(on_time)}


def build_run_rows(
    summary_rows: list[dict[str, str]], raw_dir: Path
) -> tuple[list[dict[str, Any]], list[Path]]:
    rows, used = [], []
    for row in summary_rows:
        meta_path = raw_dir / f"{row['run_id']}.meta.json"
        probe_path = raw_dir / f"{row['run_id']}.probe.json"
        if not meta_path.is_file():
            raise ValueError(f"run {row['run_id']}: {meta_path} is missing (arm/block unknown).")
        experiment = json.loads(meta_path.read_text(encoding="utf-8")).get("experiment") or {}
        missing = [k for k in ("scheduler_arm", "run_tag") if not experiment.get(k)]
        if missing:
            raise ValueError(f"run {row['run_id']}: meta.json has no {', '.join(missing)}.")
        if str(experiment.get("scheduler_policy")) != row["scheduler_policy"]:
            raise ValueError(f"run {row['run_id']}: meta scheduler_policy "
                             f"{experiment.get('scheduler_policy')} != logged {row['scheduler_policy']}.")
        used.append(meta_path)
        probe = None
        if probe_path.is_file():
            probe = json.loads(probe_path.read_text(encoding="utf-8"))
            used.append(probe_path)
        out = dict(row)
        out.update({k: str(experiment.get(k, "")) for k in META_FIELDS})
        out.update(probe_fields(probe, probe.get("probe_cpus_allowed", []) if probe else []))
        out.update(derive(row))
        rows.append(out)
    return rows, used


def _arm_key(row: dict[str, Any]) -> tuple:
    return (row["model_name"], float(row["input_fps"]), int(row["fake_delay_ms"]), row["scheduler_arm"])


def _stats(prefix: str, values: list[float]) -> dict[str, str]:
    return {
        f"{prefix}_mean": _fmt(mean(values)) if values else "",
        f"{prefix}_sd": _fmt(stdev(values)) if len(values) > 1 else "",
        f"{prefix}_min": _fmt(min(values)) if values else "",
        f"{prefix}_max": _fmt(max(values)) if values else "",
    }


def build_conditions(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in run_rows:
        groups.setdefault(_arm_key(row), []).append(row)
    out = []
    for key in sorted(groups):
        runs = groups[key]
        rec: dict[str, Any] = dict(zip(ARM_KEYS, key))
        rec["scheduler_policy"] = ";".join(sorted({r["scheduler_policy"] for r in runs}))
        rec["qos_depth"] = ";".join(sorted({r["qos_depth"] for r in runs}))
        rec["scheduler_params"] = ";".join(sorted({r["scheduler_params"] for r in runs})) or ""
        rec["intra_op_threads"] = ";".join(sorted({r.get("intra_op_threads", "") for r in runs}))
        rec["n_runs"] = len(runs)
        rec["run_ids"] = ";".join(sorted(r["run_id"] for r in runs))
        rec["all_dds_verified"] = str(all(r.get("dds_verified") == "true" for r in runs)).lower()
        rec["measurement_classes"] = ";".join(sorted({r.get("measurement_class", "") for r in runs}))
        for metric in METRICS:
            rec.update(_stats(metric, [v for v in (_f(r.get(metric)) for r in runs) if v is not None]))
        out.append(rec)
    return out


def build_paired(run_rows: list[dict[str, Any]], reference_arm: str) -> list[dict[str, Any]]:
    """Differences arm - reference within the same block (model, fps, delay, run_tag)."""

    blocks: dict[tuple, dict[str, dict[str, Any]]] = {}
    for row in run_rows:
        block = (row["model_name"], float(row["input_fps"]), int(row["fake_delay_ms"]), row["run_tag"])
        arms = blocks.setdefault(block, {})
        if row["scheduler_arm"] in arms:
            raise ValueError(f"block {block} has two runs of arm {row['scheduler_arm']}.")
        arms[row["scheduler_arm"]] = row
    diffs: dict[tuple, list[dict[str, float | None]]] = {}
    for block, arms in blocks.items():
        ref = arms.get(reference_arm)
        if ref is None:
            continue
        for arm, row in arms.items():
            if arm == reference_arm:
                continue
            delta = {}
            for metric in PAIRED_METRICS:
                a, b = _f(row.get(metric)), _f(ref.get(metric))
                delta[metric] = None if a is None or b is None else a - b
            diffs.setdefault((*block[:3], arm), []).append(delta)
    out = []
    for key in sorted(diffs):
        rec: dict[str, Any] = dict(zip(ARM_KEYS, key))
        rec["reference_arm"] = reference_arm
        rec["n_blocks"] = len(diffs[key])
        for metric in PAIRED_METRICS:
            values = [d[metric] for d in diffs[key] if d[metric] is not None]
            stats = _stats(f"d_{metric}", values)
            rec.update({k: v for k, v in stats.items() if not k.endswith("_sd")})
        out.append(rec)
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        fields += [k for k in row if k not in fields]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", required=True)
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--runs-output", required=True)
    parser.add_argument("--conditions-output", required=True)
    parser.add_argument("--paired-output", required=True)
    parser.add_argument("--reference-arm", default="legacy_q1")
    args = parser.parse_args(argv)

    summary_path, raw_dir = Path(args.summary), Path(args.raw_dir)
    with summary_path.open(encoding="utf-8", newline="") as f:
        summary_rows = list(csv.DictReader(f))
    run_rows, used = build_run_rows(summary_rows, raw_dir)
    outputs = {
        Path(args.runs_output): run_rows,
        Path(args.conditions_output): build_conditions(run_rows),
        Path(args.paired_output): build_paired(run_rows, args.reference_arm),
    }
    for path, rows in outputs.items():
        _write_csv(path, rows)
    summary_manifest = summary_path.with_name(summary_path.stem + ".manifest.json")
    inputs = [summary_path, *([summary_manifest] if summary_manifest.is_file() else []), *used]
    manifest = {
        "generator": "src.ros2_runtime.aggregate_scheduling",
        "reference_arm": args.reference_arm,
        "inputs": [{"path": str(p), "sha256": sha256_file(p)} for p in inputs],
        "outputs": [{"path": str(p), "sha256": sha256_file(p)} for p in outputs],
        "probe_fields": PROBE_FIELDS,
    }
    manifest_path = Path(args.conditions_output).with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{len(run_rows)} runs -> {', '.join(str(p) for p in outputs)}; manifest {manifest_path}")


if __name__ == "__main__":
    main()
