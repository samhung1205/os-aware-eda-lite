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

Phase 3 / Batch 2 additions (Batch 1 outputs are unchanged when none of them is used):

- conditions and blocks are also keyed by ``scenario`` (``sched_dynamic`` runs never pair
  with fixed-rate runs of the same nominal FPS); ``fps_schedule`` comes from meta.json;
- ``--reference-arm`` may be repeated: one set of paired rows per reference;
- ``--paired-stats``: per paired row also the across-block SD, a two-sided 95 % Student-t
  interval of the mean difference (``t_{0.975,n-1} * SD / sqrt(n)``), the number of blocks
  with a negative / positive difference and the exact two-sided sign-flip (paired
  permutation) p-value over the 2^n sign assignments (n = blocks; with n = 5 the smallest
  possible value is 0.0625, so it is reported as a consistency measure, not a test with
  nominal power);
- derived ``effective_miss_excl_tail_pct``: the effective miss rate after removing the
  frames that were only lost because the run was stopped (``shutdown_unfinished_frames``
  + ``tail_unobserved_frames``) from numerator and denominator (end-of-run sensitivity).

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
OPTIONAL_META_FIELDS = ["fps_schedule"]  # Phase 3 / Batch 2 (absent in Batch 1 meta.json)
# two-sided 95 % Student-t critical values, df = 1..30 (beyond: normal 1.96)
T975 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
        2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
        2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]
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
    "effective_miss_excl_tail_pct",
]
PAIRED_METRICS = [
    "processed_fps", "on_time_fps", "drop_rate_pct", "deadline_miss_rate_pct",
    "effective_miss_rate_pct", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms",
    "p50_frame_age_at_start_ms", "avg_service_ms",
]
PAIRED_METRICS_B2 = PAIRED_METRICS + [
    "avg_latency_ms", "avg_frame_age_at_start_ms", "app_policy_drop_rate_pct",
    "effective_miss_excl_tail_pct", "detector_cpu_pct", "max_memory_mb",
]


def derive(row: dict[str, Any]) -> dict[str, str]:
    service, offered = _f(row.get("avg_service_ms")), _f(row.get("offered_fps"))
    eff = _f(row.get("effective_miss_rate_pct"))
    rho = None if service is None or offered is None else offered * service / 1000.0
    on_time = None if offered is None or eff is None else offered * (1.0 - eff / 100.0)
    out = {"utilization": _fmt(rho), "on_time_fps": _fmt(on_time)}
    if "shutdown_unfinished_frames" in row:  # Batch 2 sensitivity column (summary has the counts)
        out["effective_miss_excl_tail_pct"] = _fmt(effective_miss_excl_tail(row))
    return out


def effective_miss_excl_tail(row: dict[str, Any]) -> float | None:
    """(misses + drops - end-of-run losses) / (frames - end-of-run losses), in %."""

    total, dropped = _f(row.get("total_rows")), _f(row.get("dropped_frames"))
    misses = _f(row.get("deadline_misses"))
    if total is None or dropped is None or misses is None:
        return None
    tail = (_f(row.get("shutdown_unfinished_frames")) or 0.0) + (_f(row.get("tail_unobserved_frames")) or 0.0)
    denom = total - tail
    return None if denom <= 0 else 100.0 * (misses + dropped - tail) / denom


def _scenario(row: dict[str, Any]) -> str:
    return row.get("scenario", "") or ""


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
        out.update({k: str(experiment[k]) for k in OPTIONAL_META_FIELDS if k in experiment})
        out.update(probe_fields(probe, probe.get("probe_cpus_allowed", []) if probe else []))
        out.update(derive(row))
        rows.append(out)
    return rows, used


def _arm_key(row: dict[str, Any], with_scenario: bool = False) -> tuple:
    key = (row["model_name"], float(row["input_fps"]), int(row["fake_delay_ms"]), row["scheduler_arm"])
    return ((_scenario(row),) + key) if with_scenario else key


def _stats(prefix: str, values: list[float]) -> dict[str, str]:
    return {
        f"{prefix}_mean": _fmt(mean(values)) if values else "",
        f"{prefix}_sd": _fmt(stdev(values)) if len(values) > 1 else "",
        f"{prefix}_min": _fmt(min(values)) if values else "",
        f"{prefix}_max": _fmt(max(values)) if values else "",
    }


def build_conditions(run_rows: list[dict[str, Any]], with_scenario: bool = False) -> list[dict[str, Any]]:
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in run_rows:
        groups.setdefault(_arm_key(row, with_scenario), []).append(row)
    keys = (["scenario"] if with_scenario else []) + ARM_KEYS
    out = []
    for key in sorted(groups):
        runs = groups[key]
        rec: dict[str, Any] = dict(zip(keys, key))
        if with_scenario:
            rec["fps_schedule"] = ";".join(sorted({r.get("fps_schedule", "") for r in runs}))
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


def t_crit_975(df: int) -> float:
    return T975[df - 1] if 1 <= df <= len(T975) else 1.96


def sign_flip_p(values: list[float]) -> float | None:
    """Exact two-sided paired permutation p-value of the mean (all 2^n sign flips)."""

    n = len(values)
    if n == 0 or n > 20:
        return None
    observed = abs(sum(values))
    hits = 0
    for mask in range(1 << n):
        total = sum(-v if mask >> i & 1 else v for i, v in enumerate(values))
        hits += abs(total) >= observed - 1e-12
    return hits / (1 << n)


def _paired_stats(prefix: str, values: list[float]) -> dict[str, str]:
    n = len(values)
    out = {f"{prefix}_sd": _fmt(stdev(values)) if n > 1 else ""}
    if n > 1:
        half = t_crit_975(n - 1) * stdev(values) / n ** 0.5
        out[f"{prefix}_ci95_lo"] = _fmt(mean(values) - half)
        out[f"{prefix}_ci95_hi"] = _fmt(mean(values) + half)
    else:
        out[f"{prefix}_ci95_lo"] = out[f"{prefix}_ci95_hi"] = ""
    out[f"{prefix}_n_neg"] = str(sum(v < 0 for v in values))
    out[f"{prefix}_n_pos"] = str(sum(v > 0 for v in values))
    p = sign_flip_p(values)
    out[f"{prefix}_signflip_p"] = "" if p is None else _fmt(p)
    return out


def build_paired(run_rows: list[dict[str, Any]], reference_arm: str, with_scenario: bool = False,
                 metrics: list[str] | None = None, paired_stats: bool = False) -> list[dict[str, Any]]:
    """Differences arm - reference within the same block (model, fps, delay, run_tag)."""

    metrics = metrics or PAIRED_METRICS
    keys = (["scenario"] if with_scenario else []) + ARM_KEYS
    blocks: dict[tuple, dict[str, dict[str, Any]]] = {}
    schedules: dict[tuple, set[str]] = {}
    for row in run_rows:
        block = (row["model_name"], float(row["input_fps"]), int(row["fake_delay_ms"]), row["run_tag"])
        if with_scenario:
            block = (_scenario(row),) + block
            schedules.setdefault(block[:-1], set()).add(row.get("fps_schedule", ""))
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
            for metric in metrics:
                a, b = _f(row.get(metric)), _f(ref.get(metric))
                delta[metric] = None if a is None or b is None else a - b
            diffs.setdefault((*block[:-1], arm), []).append(delta)
    out = []
    for key in sorted(diffs):
        rec: dict[str, Any] = dict(zip(keys, key))
        if with_scenario:
            rec["fps_schedule"] = ";".join(sorted(schedules.get(key[:-1], set())))
        rec["reference_arm"] = reference_arm
        rec["n_blocks"] = len(diffs[key])
        for metric in metrics:
            values = [d[metric] for d in diffs[key] if d[metric] is not None]
            stats = _stats(f"d_{metric}", values)
            rec.update({k: v for k, v in stats.items() if not k.endswith("_sd")})
            if paired_stats:
                rec.update(_paired_stats(f"d_{metric}", values))
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
    parser.add_argument("--reference-arm", action="append", default=None,
                        help="Reference arm of the paired differences (repeatable; default legacy_q1).")
    parser.add_argument("--by-scenario", action="store_true",
                        help="Key conditions / blocks by scenario too (Phase 3 / Batch 2).")
    parser.add_argument("--paired-stats", action="store_true",
                        help="Add SD, 95%% t-interval, sign counts and sign-flip p (Batch 2 metric set).")
    args = parser.parse_args(argv)
    references = args.reference_arm or ["legacy_q1"]

    summary_path, raw_dir = Path(args.summary), Path(args.raw_dir)
    with summary_path.open(encoding="utf-8", newline="") as f:
        summary_rows = list(csv.DictReader(f))
    run_rows, used = build_run_rows(summary_rows, raw_dir)
    metrics = PAIRED_METRICS_B2 if args.paired_stats else PAIRED_METRICS
    paired = [rec for ref in references
              for rec in build_paired(run_rows, ref, args.by_scenario, metrics, args.paired_stats)]
    outputs = {
        Path(args.runs_output): run_rows,
        Path(args.conditions_output): build_conditions(run_rows, args.by_scenario),
        Path(args.paired_output): paired,
    }
    for path, rows in outputs.items():
        _write_csv(path, rows)
    summary_manifest = summary_path.with_name(summary_path.stem + ".manifest.json")
    inputs = [summary_path, *([summary_manifest] if summary_manifest.is_file() else []), *used]
    manifest = {
        "generator": "src.ros2_runtime.aggregate_scheduling",
        "reference_arm": references[0] if len(references) == 1 else references,
        "inputs": [{"path": str(p), "sha256": sha256_file(p)} for p in inputs],
        "outputs": [{"path": str(p), "sha256": sha256_file(p)} for p in outputs],
        "probe_fields": PROBE_FIELDS,
    }
    manifest_path = Path(args.conditions_output).with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{len(run_rows)} runs -> {', '.join(str(p) for p in outputs)}; manifest {manifest_path}")


if __name__ == "__main__":
    main()
