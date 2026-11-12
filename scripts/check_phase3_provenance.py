"""Phase 3 provenance gate: formal scheduling A/B data -> summary -> aggregates (Phase 3 / Batch 2).

    python3 scripts/check_phase3_provenance.py [--root REPO] [--raw-dir ...] [--summary ...]
        [--manifest <aggregate or dynamic manifest> ...] [--expect-runs N]

Independent of ``check_runtime_provenance.py`` (Phase 2): a Phase 2 VERIFIED status says
nothing about the Phase 3 data. Checks, for every run under ``--raw-dir``:

1. files: detector CSV + ``.publisher.csv`` + ``.meta.json`` + ``.probe.json`` exist;
2. code: ``git.dirty == false``; one ``git.commit`` for the whole dataset; that commit is
   in this repository, is an ancestor of HEAD, and the runtime code
   (``RUNTIME_PATHS``: nodes, launch, scheduler, sweep / driver scripts, metadata / probe /
   load gate) is byte-identical between it and HEAD (so the committed code is the code
   that produced the data);
3. controls identical across runs: ``measurement_class=constrained``, requested and
   effective CPUs / MemoryMax / MemorySwapMax, nice, ROS_DOMAIN_ID, RMW, DDS XML SHA-256,
   python / torch / timm versions, model weights, deadline, warm-up, run length,
   intra-op threads, queue capacity, DDS depth of the app arms, adaptive / guard
   parameters (``CONTROL_KEYS``);
4. runtime: ``probe.dds.verified``; the detector CSV reports the policy in meta.json and
   one ``scheduler_params`` / ``intra_op_threads`` value; every block (``run_tag``) holds
   every arm of its ``sched_arms`` exactly once;
5. derived data: the summary manifest verifies against the raw files and covers exactly
   the raw runs; every ``--manifest`` (aggregate / dynamic-phase) hash-matches its inputs
   and outputs.

Exit 0 VERIFIED, 1 BLOCKED (something missing), 2 BROKEN (mismatch / dirty / changed
controls). Standard library + git; read-only.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.provenance import check_file_record, read_json, verify_summary_manifest  # noqa: E402

VERIFIED, BLOCKED, BROKEN = 0, 1, 2
_LABEL = {VERIFIED: "VERIFIED", BLOCKED: "BLOCKED", BROKEN: "BROKEN"}

RAW_DIR = "results/raw/ros2_phase3_formal"
SUMMARY = "results/csv/ros2_phase3_formal_summary.csv"
MANIFESTS = (
    "results/csv/ros2_phase3_formal_arms.manifest.json",
    "results/csv/ros2_phase3_formal_dynamic_phases.manifest.json",
)
RUNTIME_PATHS = (
    "src/ros2_uav_pipeline",
    "experiments/ros2/run_sched_sweep.sh",
    "experiments/ros2/run_sched_formal.sh",
    "experiments/ros2/run_common.sh",
    "experiments/ros2/fastdds_shm_large.xml",
    "scripts/run_baseline_experiments.sh",
    "src/ros2_runtime/run_metadata.py",
    "src/ros2_runtime/runtime_probe.py",
    "src/ros2_runtime/host_load_gate.py",
)
# (label, path into meta.json) that must hold one value across the whole dataset
CONTROL_KEYS = (
    ("measurement_class", ("resource_limits", "measurement_class")),
    ("requested cpus", ("resource_limits", "requested", "cpus")),
    ("requested memory_max", ("resource_limits", "requested", "memory_max_bytes")),
    ("effective cpus", ("resource_limits", "effective", "cpus_allowed")),
    ("effective memory_max", ("resource_limits", "effective", "memory_max_bytes")),
    ("effective swap max", ("resource_limits", "effective", "memory_swap_max_bytes")),
    ("nice", ("process", "nice")),
    ("ROS_DOMAIN_ID", ("ros2", "ROS_DOMAIN_ID")),
    ("RMW", ("ros2", "RMW_IMPLEMENTATION")),
    ("DDS XML sha256", ("dds_profile", "sha256")),
    ("python", ("python", "version")),
    ("torch", ("packages", "torch")),
    ("timm", ("packages", "timm")),
    ("kernel", ("host", "kernel_release")),
    ("model weights", ("experiment", "model_weights")),
    ("deadline_ms", ("experiment", "deadline_ms")),
    ("warmup_frames", ("experiment", "warmup_frames")),
    ("run_seconds", ("experiment", "run_seconds")),
    ("intra_op_threads", ("experiment", "intra_op_threads")),
    ("queue_capacity", ("experiment", "queue_capacity")),
    ("fifo_overflow", ("experiment", "fifo_overflow")),
    ("adaptive_window", ("experiment", "adaptive_window")),
    ("adaptive_quantile", ("experiment", "adaptive_quantile")),
    ("adaptive_margin_ms", ("experiment", "adaptive_margin_ms")),
    ("adaptive_overload_threshold", ("experiment", "adaptive_overload_threshold")),
)
ARM_POLICY = {"legacy_qos": "legacy_q", "fifo": "fifo_c", "latest_frame": "latest_q",
              "adaptive": "adaptive_c", "deadline_guard": "guard_c"}


def _get(payload: dict, path: tuple[str, ...]):
    for key in path:
        if not isinstance(payload, dict):
            return None
        payload = payload.get(key)
    return payload


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def check(root: Path, raw_rel: str, summary_rel: str, manifests: list[str],
          expect_runs: int | None) -> tuple[int, list[str]]:
    lines: list[str] = []
    blocked: list[str] = []
    broken: list[str] = []
    raw = root / raw_rel
    detector = sorted(p for p in raw.glob("*.csv") if not p.name.endswith(".publisher.csv"))
    if not detector:
        blocked.append(f"no detector CSVs under {raw_rel}")
    failed = sorted(raw.glob("*.failed"))
    if failed:
        lines.append(f"INFO    {len(failed)} *.failed files (ignored by the analyzer): "
                     + ", ".join(p.name for p in failed[:4]))
    if expect_runs is not None and len(detector) != expect_runs:
        broken.append(f"{len(detector)} runs under {raw_rel}, expected {expect_runs}")

    metas: dict[str, dict] = {}
    for csv_path in detector:
        run_id = csv_path.stem
        missing = [suffix for suffix in (".publisher.csv", ".meta.json", ".probe.json")
                   if not (raw / f"{run_id}{suffix}").is_file()]
        if missing:
            blocked.append(f"{run_id}: missing {', '.join(missing)}")
            continue
        meta = read_json(raw / f"{run_id}.meta.json")
        probe = read_json(raw / f"{run_id}.probe.json")
        metas[run_id] = meta
        if meta.get("run_id") != run_id:
            broken.append(f"{run_id}: meta.json run_id {meta.get('run_id')}")
        if (meta.get("git") or {}).get("dirty") is not False:
            broken.append(f"{run_id}: git.dirty={meta.get('git', {}).get('dirty')}")
        if not (probe.get("dds") or {}).get("verified"):
            broken.append(f"{run_id}: probe dds.verified is not true")
        exp = meta.get("experiment") or {}
        with csv_path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        policies = {r.get("scheduler_policy") for r in rows}
        params = {r.get("scheduler_params") for r in rows}
        threads = {r.get("intra_op_threads") for r in rows}
        ids = {r.get("run_id") for r in rows}
        if ids != {run_id}:
            broken.append(f"{run_id}: CSV run_id column {sorted(ids)[:3]}")
        if policies != {exp.get("scheduler_policy")}:
            broken.append(f"{run_id}: CSV policy {sorted(policies)} != meta {exp.get('scheduler_policy')}")
        if len(params) != 1 or len(threads) != 1:
            broken.append(f"{run_id}: several scheduler_params / intra_op_threads values in one run")
        prefix = ARM_POLICY.get(str(exp.get("scheduler_policy")), "?")
        if not str(exp.get("scheduler_arm", "")).startswith(prefix):
            broken.append(f"{run_id}: arm {exp.get('scheduler_arm')} does not match policy {exp.get('scheduler_policy')}")

    if metas:
        commits = {(m.get("git") or {}).get("commit") for m in metas.values()}
        if len(commits) != 1:
            broken.append(f"{len(commits)} different git commits in one dataset: {sorted(map(str, commits))}")
        else:
            commit = commits.pop()
            if _git(root, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
                broken.append(f"commit {commit} is not in this repository")
            elif _git(root, "merge-base", "--is-ancestor", commit, "HEAD").returncode != 0:
                broken.append(f"commit {commit} is not an ancestor of HEAD")
            else:
                diff = _git(root, "diff", "--name-only", commit, "HEAD", "--", *RUNTIME_PATHS)
                changed = [p for p in diff.stdout.split() if p]
                if diff.returncode != 0 or changed:
                    broken.append(f"runtime code changed since measurement commit {commit[:9]}: {changed}")
                else:
                    lines.append(f"OK      code: {len(metas)} runs at {commit[:9]} (dirty=false); runtime code "
                                 f"unchanged {commit[:9]}..HEAD")
        for label, path in CONTROL_KEYS:
            values = {json.dumps(_get(m, path), sort_keys=True) for m in metas.values()}
            if len(values) != 1:
                broken.append(f"control '{label}' differs across runs: {sorted(values)[:4]}")
        if all(_get(m, ("resource_limits", "measurement_class")) == "constrained" for m in metas.values()):
            lines.append(f"OK      controls: {len(CONTROL_KEYS)} keys identical across {len(metas)} runs, all constrained")
        else:
            broken.append("not every run is measurement_class=constrained")
        app_depths = {(m.get("experiment") or {}).get("qos_depth") for m in metas.values()
                      if (m.get("experiment") or {}).get("scheduler_policy") != "legacy_qos"}
        if len(app_depths) > 1:
            broken.append(f"application arms use several DDS depths: {sorted(map(str, app_depths))}")
        blocks: dict[tuple, list[str]] = {}
        expected: dict[tuple, str] = {}
        for m in metas.values():
            exp = m.get("experiment") or {}
            key = (exp.get("scenario"), exp.get("model_name"), exp.get("input_fps"), exp.get("fake_delay_ms"),
                   exp.get("fps_schedule", ""), exp.get("run_tag"))
            policy = str(exp.get("scheduler_policy"))
            blocks.setdefault(key, []).append(f"legacy_qos:{exp.get('qos_depth')}" if policy == "legacy_qos" else policy)
            expected[key] = str(exp.get("sched_arms", ""))
        incomplete = [f"{key[-1]}: {sorted(arms)} != {sorted(expected[key].split())}"
                      for key, arms in blocks.items() if sorted(arms) != sorted(expected[key].split())]
        if incomplete:
            broken.extend(f"incomplete block {x}" for x in incomplete)
        else:
            lines.append(f"OK      blocks: {len(blocks)} blocks, every arm exactly once per block")

    summary = root / summary_rel
    manifest = summary.with_name(f"{summary.stem}.manifest.json")
    if not summary.is_file() or not manifest.is_file():
        blocked.append(f"{summary_rel} or its manifest is missing")
    else:
        problems = verify_summary_manifest(manifest)
        broken.extend(f"summary manifest: {p}" for p in problems)
        with summary.open(encoding="utf-8", newline="") as f:
            summary_ids = {r["run_id"] for r in csv.DictReader(f)}
        if summary_ids != set(metas):
            broken.append(f"summary covers {len(summary_ids)} runs, raw dir has {len(metas)} "
                          f"(diff {sorted(summary_ids ^ set(metas))[:3]})")
        if not problems and summary_ids == set(metas):
            lines.append(f"OK      summary {summary_rel} verifies against {len(summary_ids)} raw runs")
    for rel in manifests:
        path = root / rel
        if not path.is_file():
            blocked.append(f"{rel} missing")
            continue
        payload = read_json(path)
        problems = []
        for record in payload.get("inputs", []) + payload.get("outputs", []):
            problems += check_file_record(record, root, rel)
        broken.extend(problems)
        if not problems:
            lines.append(f"OK      {rel}: {len(payload.get('inputs', []))} inputs, "
                         f"{len(payload.get('outputs', []))} outputs hash-match")

    code = BROKEN if broken else BLOCKED if blocked else VERIFIED
    lines.append(f"STATUS: {_LABEL[code]}")
    lines.extend(f"  - {reason}" for reason in broken + blocked)
    return code, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(REPO))
    parser.add_argument("--raw-dir", default=RAW_DIR)
    parser.add_argument("--summary", default=SUMMARY)
    parser.add_argument("--manifest", action="append", default=None)
    parser.add_argument("--expect-runs", type=int, default=None)
    args = parser.parse_args(argv)
    code, lines = check(Path(args.root).resolve(), args.raw_dir, args.summary,
                        list(args.manifest) if args.manifest else list(MANIFESTS), args.expect_runs)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
