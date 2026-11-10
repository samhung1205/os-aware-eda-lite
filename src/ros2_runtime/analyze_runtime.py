"""Analyze generic ROS2 edge AI runtime CSV metrics.

The analyzer accepts the runtime logging contract documented in the README. It
uses only the Python standard library so it can run in the same lightweight
environment as EDA-Lite.

Measurement definitions (one summary row per configuration + run):

- Warm-up: rows flagged ``warmup=1`` by the detector, plus the first
  ``--warmup-frames`` received rows per run, are excluded. The measurement
  window then starts after the last warm-up frame_id.
- processed frame: a non-dropped row with a latency inside the window.
- dropped frame: a frame of the window that was never processed. The window is
  the publisher log (``<run_id>.publisher.csv``) when present, otherwise the
  observed frame_id range. Explicit ``dropped`` rows and frame_id gaps are merged
  as a set union, so a frame is counted at most once.
- deadline miss: a processed frame with ``latency_ms > deadline_ms``. Dropped
  frames are never deadline misses; the miss rate is divided by processed frames
  and therefore cannot exceed 100%.
- latency statistics are over processed, non-warm-up frames of one run:
  ``avg_latency_ms`` is the mean end-to-end latency (publish -> inference done);
  ``p95_latency_ms`` / ``p99_latency_ms`` use the nearest-rank method (no
  interpolation); ``jitter_ms`` is the *population standard deviation of the
  per-frame end-to-end latency*. It is not RFC 3550 / inter-arrival jitter and
  says nothing about the spacing between frames.
- ``avg_cpu_percent`` averages ``psutil.Process.cpu_percent()`` of the detector
  process (per process, can exceed 100 on several cores; psutil reports 0.0 for
  the first call). ``avg_memory_mb`` averages the detector's RSS.
- run conditions: ``<run_id>.meta.json`` next to the detector CSV (written by
  ``src.ros2_runtime.run_metadata``) supplies ``measurement_class`` and the
  effective memory limit; runs without it are ``measurement_class=unknown``.

Provenance: ``main`` also writes ``<summary stem>.manifest.json`` with the
SHA-256 of the summary and of every raw input (see ``src/provenance.py``).
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from html import escape
from math import ceil
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable

from src.provenance import CLASS_UNKNOWN, write_summary_manifest


GROUP_FIELDS = [
    "scenario",
    "model_name",
    "input_fps",
    "qos_depth",
    "fake_delay_ms",
    "resource_profile",
]

# Rows without a run_id column/value are legacy rows. Each legacy CSV file is
# treated as one run, identified as "legacy:<csv path as given on the CLI>".
LEGACY_RUN_PREFIX = "legacy:"

PUBLISHER_SUFFIX = ".publisher.csv"
NUMERIC_GROUP_FIELDS = {"input_fps": float, "qos_depth": int, "fake_delay_ms": int}

# frame_accounting values written to the summary.
ACCOUNTING_PUBLISHER = "publisher_log"   # complete: includes leading/trailing drops
ACCOUNTING_RANGE = "frame_id_range"      # lower bound: leading/trailing drops unknown
ACCOUNTING_EXPLICIT = "explicit_only"    # lower bound: only explicit dropped rows
ACCOUNTING_UNAVAILABLE = "unavailable"   # drops unknown; drop columns are left empty

SUMMARY_FIELDS = [
    *GROUP_FIELDS,
    "run_id",
    "total_rows",
    "processed_frames",
    "dropped_frames",
    "drop_rate_pct",
    "deadline_misses",
    "deadline_miss_rate_pct",
    "avg_latency_ms",
    "p95_latency_ms",
    "p99_latency_ms",
    "jitter_ms",
    "avg_inference_ms",
    "avg_cpu_percent",
    "avg_memory_mb",
    # Added in Phase 1 / Batch 1; appended so existing columns keep their order.
    "deadline_ms",
    "effective_miss_rate_pct",
    "published_frames",
    "frame_accounting",
    "warmup_frames_excluded",
    "avg_transport_ms",
    "avg_preprocess_ms",
    "avg_artificial_delay_ms",
    "p95_inference_ms",
    "timing_schema",
    # Added in Phase 1 / Batch 3 (run metadata, see src/ros2_runtime/run_metadata.py).
    "measurement_class",
    "memory_limit_mb",
    "host_memory_mb",
    "run_metadata",
    # Added in Phase 2 / Batch 2 (baseline benchmark).
    "p50_latency_ms",
    "p50_transport_ms",
    "p95_transport_ms",
    "p50_inference_ms",
    "avg_service_ms",
    "offered_fps",
    "processed_fps",
    "max_memory_mb",
]

RUN_METADATA_SUFFIX = ".meta.json"
RUNTIME_PROBE_SUFFIX = ".probe.json"

FIGURE_METRICS = [
    ("avg_latency_ms", "Average latency (ms)", "ros2_avg_latency.svg"),
    ("p95_latency_ms", "P95 latency (ms)", "ros2_p95_latency.svg"),
    ("deadline_miss_rate_pct", "Deadline miss rate (%)", "ros2_deadline_miss_rate.svg"),
    ("drop_rate_pct", "Frame drop rate (%)", "ros2_drop_rate.svg"),
]


@dataclass(frozen=True)
class RuntimeRow:
    scenario: str
    model_name: str
    input_fps: str
    qos_depth: str
    fake_delay_ms: str
    resource_profile: str
    frame_id: int | None
    latency_ms: float | None
    inference_ms: float | None
    deadline_miss: bool
    dropped: bool
    cpu_percent: float | None
    memory_mb: float | None
    run_id: str = ""
    legacy_run: bool = False
    source: str = ""
    deadline_ms: float | None = None
    warmup: bool = False
    transport_ms: float | None = None
    preprocess_ms: float | None = None
    artificial_delay_ms: float | None = None
    timing_schema: str = "legacy"
    published_at_ns: int | None = None
    completed_at_ns: int | None = None

    @property
    def processed(self) -> bool:
        return not self.dropped and self.latency_ms is not None

    def config_key(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.scenario,
            self.model_name,
            self.input_fps,
            self.qos_depth,
            self.fake_delay_ms,
            self.resource_profile,
        )

    def group_key(self) -> tuple[str, str, str, str, str, str, str]:
        return (*self.config_key(), self.run_id)


def main() -> None:
    args = _parse_args()
    rows = load_runtime_rows(args.input)
    publisher_frames = load_publisher_frames(args.input)
    run_metadata = load_run_metadata(args.input)
    summary_rows = build_runtime_summary(
        rows,
        publisher_frames=publisher_frames,
        warmup_frames=args.warmup_frames,
        run_metadata=run_metadata,
        publisher_times=load_publisher_times(args.input),
    )
    write_runtime_summary(args.summary_output, summary_rows)
    manifest = write_summary_manifest(
        args.summary_output,
        inputs=collect_input_files(args.input, run_metadata),
        runs=[
            {
                "run_id": row["run_id"],
                "run_metadata": run_metadata.get(row["run_id"], (None, None))[0],
                "measurement_class": row["measurement_class"],
            }
            for row in summary_rows
        ],
        settings={"warmup_frames": args.warmup_frames},
        manifest_path=args.manifest_output,
    )
    print(f"Wrote provenance manifest to {manifest}")

    if args.figures_dir:
        written = write_runtime_svgs(summary_rows, args.figures_dir)
        print(f"Wrote {len(written)} ROS2 SVG figures to {args.figures_dir}")

    incomplete = [row["run_id"] for row in summary_rows if row["frame_accounting"] != ACCOUNTING_PUBLISHER]
    if incomplete:
        print(
            f"Note: {len(incomplete)} run(s) have no publisher log; their drop counts are lower "
            "bounds or unavailable (see frame_accounting)."
        )
    print(f"Wrote {len(summary_rows)} ROS2 summary rows to {args.summary_output}")


def load_runtime_rows(input_paths: Iterable[str | Path]) -> list[RuntimeRow]:
    """Load detector CSV files (publisher logs ``*.publisher.csv`` are skipped)."""

    csv_paths = [path for path in _expand_input_paths(input_paths) if not _is_publisher_log(path)]
    rows: list[RuntimeRow] = []
    for path in csv_paths:
        with path.open("r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            if not reader.fieldnames:
                raise ValueError(f"{path} is missing a CSV header.")
            timing_schema = "v2" if "artificial_delay_ms" in reader.fieldnames else "legacy"
            for raw_row in reader:
                rows.append(_parse_runtime_row(raw_row, source_path=path, timing_schema=timing_schema))
    if not rows:
        raise ValueError("No ROS2 runtime rows found.")
    return rows


def load_run_metadata(input_paths: Iterable[str | Path]) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Load ``<run_id>.meta.json`` files that sit next to the detector CSVs.

    Returns ``{run_id: (path, payload)}``. A metadata file whose ``run_id`` does
    not match its CSV, or two files for one run, raise ValueError.
    """

    found: dict[str, tuple[Path, dict[str, Any]]] = {}
    for csv_path in _expand_input_paths(input_paths):
        if _is_publisher_log(csv_path):
            continue
        meta_path = csv_path.with_name(csv_path.name[: -len(".csv")] + RUN_METADATA_SUFFIX) \
            if csv_path.name.endswith(".csv") else None
        if meta_path is None or not meta_path.is_file():
            continue
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        run_id = str(payload.get("run_id") or "")
        if not run_id:
            raise ValueError(f"{meta_path} has no run_id.")
        if run_id in found and found[run_id][0] != meta_path:
            raise ValueError(f"run_id '{run_id}' has two metadata files: {found[run_id][0]}, {meta_path}.")
        csv_run_ids = _csv_run_ids(csv_path)
        if csv_run_ids and csv_run_ids != {run_id}:
            raise ValueError(f"{meta_path} is for run_id '{run_id}' but {csv_path} contains {sorted(csv_run_ids)}.")
        found[run_id] = (meta_path, payload)
    return found


def collect_input_files(
    input_paths: Iterable[str | Path],
    run_metadata: dict[str, tuple[Path, dict[str, Any]]],
) -> list[tuple[Path, str]]:
    """Every raw file the summary depends on, as ``(path, kind)``."""

    files = [
        (path, "publisher_csv" if _is_publisher_log(path) else "detector_csv")
        for path in _expand_input_paths(input_paths)
    ]
    files += [(path, "run_metadata") for path, _ in run_metadata.values()]
    # Runtime probe (DDS transport + resource samples), when the run wrote one.
    for path, kind in list(files):
        if kind == "detector_csv" and path.name.endswith(".csv"):
            probe = path.with_name(path.name[: -len(".csv")] + RUNTIME_PROBE_SUFFIX)
            if probe.is_file():
                files.append((probe, "runtime_probe"))
    return files


def _csv_run_ids(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8", newline="") as file:
        return {(row.get("run_id") or "").strip() for row in csv.DictReader(file)} - {""}


def _run_conditions(meta: dict[str, Any] | None) -> dict[str, str]:
    """Summary columns taken from a run's metadata (empty when absent)."""

    if not meta:
        return {"measurement_class": CLASS_UNKNOWN, "memory_limit_mb": "", "host_memory_mb": ""}
    limits = meta.get("resource_limits") or {}
    effective = limits.get("effective") or {}
    memory_max = effective.get("memory_max_bytes")
    host_memory = (meta.get("host") or {}).get("memory_total_mb")
    return {
        "measurement_class": str(limits.get("measurement_class") or CLASS_UNKNOWN),
        "memory_limit_mb": _format_number(memory_max / (1024 * 1024)) if isinstance(memory_max, int) else "",
        "host_memory_mb": "" if host_memory is None else _format_number(float(host_memory)),
    }


def load_publisher_frames(input_paths: Iterable[str | Path]) -> dict[str, list[int]]:
    """Load publisher logs (``<run_id>.publisher.csv``) as {run_id: [frame_id, ...]}."""

    frames: dict[str, list[int]] = {}
    for path in _expand_input_paths(input_paths):
        if not _is_publisher_log(path):
            continue
        with path.open("r", encoding="utf-8", newline="") as file:
            for raw_row in csv.DictReader(file):
                run_id = (raw_row.get("run_id") or "").strip()
                frame_id = _optional_int(raw_row.get("frame_id"))
                if not run_id or frame_id is None:
                    raise ValueError(f"{path}: publisher rows need run_id and frame_id.")
                frames.setdefault(run_id, []).append(frame_id)
    for run_id, frame_ids in frames.items():
        if len(frame_ids) != len(set(frame_ids)):
            raise ValueError(f"Publisher log for run_id '{run_id}' repeats frame_id values.")
    return frames


def load_publisher_times(input_paths: Iterable[str | Path]) -> dict[str, dict[int, int]]:
    """Publisher logs as {run_id: {frame_id: published_at_ns}} (rows without a stamp skipped)."""

    times: dict[str, dict[int, int]] = {}
    for path in _expand_input_paths(input_paths):
        if not _is_publisher_log(path):
            continue
        with path.open("r", encoding="utf-8", newline="") as file:
            for raw_row in csv.DictReader(file):
                run_id = (raw_row.get("run_id") or "").strip()
                frame_id = _optional_int(raw_row.get("frame_id"))
                stamp = _optional_int(raw_row.get("published_at_ns"))
                if run_id and frame_id is not None and stamp is not None:
                    times.setdefault(run_id, {})[frame_id] = stamp
    return times


def _rate_fps(stamps_ns: list[int]) -> float | None:
    """Events per second over the span of the stamps: (n - 1) / (last - first)."""

    if len(stamps_ns) < 2:
        return None
    span = (max(stamps_ns) - min(stamps_ns)) / 1e9
    return None if span <= 0 else (len(stamps_ns) - 1) / span


def _service_ms(row: RuntimeRow) -> float | None:
    parts = (row.preprocess_ms, row.artificial_delay_ms, row.inference_ms)
    return None if any(p is None for p in parts) else sum(parts)  # type: ignore[arg-type]


def build_runtime_summary(
    rows: Iterable[RuntimeRow],
    publisher_frames: dict[str, list[int]] | None = None,
    warmup_frames: int = 0,
    run_metadata: dict[str, tuple[Path, dict[str, Any]]] | None = None,
    publisher_times: dict[str, dict[int, int]] | None = None,
) -> list[dict[str, str]]:
    """Summarise runtime rows with one summary row per configuration and run.

    ``publisher_frames`` maps run_id to published frame ids; ``warmup_frames``
    additionally excludes the first N received rows of every run;
    ``run_metadata`` maps run_id to ``(path, payload)`` of its ``.meta.json``. Raises
    ValueError when rows from different runs cannot be separated safely (see
    validate_run_integrity) or a run reports more than one deadline_ms.
    """

    if warmup_frames < 0:
        raise ValueError("warmup_frames must be non-negative.")
    publisher_frames = publisher_frames or {}
    publisher_times = publisher_times or {}
    run_metadata = run_metadata or {}
    groups: dict[tuple[str, str, str, str, str, str, str], list[RuntimeRow]] = {}
    for row in rows:
        groups.setdefault(row.group_key(), []).append(row)
    validate_run_integrity(groups)

    summary_rows: list[dict[str, str]] = []
    for key in sorted(groups, key=_group_sort_key):
        group_rows = groups[key]
        measured, warmup_excluded, boundary = _measurement_window(group_rows, warmup_frames)
        processed_rows = [row for row in measured if row.processed]
        latencies = [row.latency_ms for row in processed_rows]
        published = publisher_frames.get(key[6]) if not group_rows[0].legacy_run else None
        if published is not None and boundary is not None:
            published = [frame_id for frame_id in published if frame_id > boundary]
        dropped_frames, accounting = _count_dropped(measured, published)
        processed_count = len(processed_rows)
        total_frames = None if dropped_frames is None else processed_count + dropped_frames
        deadline_ms = _run_deadline(group_rows, key)
        deadline_misses = sum(1 for row in processed_rows if row.deadline_miss)
        timing_schemas = {row.timing_schema for row in group_rows}
        meta_path, meta = run_metadata.get(key[6], (None, None))
        conditions = _run_conditions(meta)
        run_times = publisher_times.get(key[6], {})
        offered_stamps = [run_times[f] for f in (published or []) if f in run_times]
        completed_stamps = [row.completed_at_ns for row in processed_rows if row.completed_at_ns is not None]
        transports = _values(processed_rows, "transport_ms")
        inferences = _values(processed_rows, "inference_ms")
        services = [v for v in (_service_ms(row) for row in processed_rows) if v is not None]
        memories = _values(measured, "memory_mb")

        summary_rows.append(
            {
                "scenario": key[0],
                "model_name": key[1],
                "input_fps": key[2],
                "qos_depth": key[3],
                "fake_delay_ms": key[4],
                "resource_profile": key[5],
                "run_id": key[6],
                "total_rows": _format_count(total_frames),
                "processed_frames": str(processed_count),
                "dropped_frames": _format_count(dropped_frames),
                "drop_rate_pct": _format_optional(_rate_pct(dropped_frames, total_frames)),
                "deadline_misses": str(deadline_misses),
                "deadline_miss_rate_pct": _format_optional(_rate_pct(deadline_misses, processed_count)),
                "avg_latency_ms": _format_optional(_average(latencies)),
                "p95_latency_ms": _format_optional(_percentile(latencies, 95)),
                "p99_latency_ms": _format_optional(_percentile(latencies, 99)),
                "jitter_ms": _format_optional(_pstdev(latencies)),
                "avg_inference_ms": _format_optional(_average(_values(processed_rows, "inference_ms"))),
                "avg_cpu_percent": _format_optional(_average(_values(measured, "cpu_percent"))),
                "avg_memory_mb": _format_optional(_average(_values(measured, "memory_mb"))),
                "deadline_ms": _format_optional(deadline_ms),
                "effective_miss_rate_pct": _format_optional(
                    None if dropped_frames is None
                    else _rate_pct(deadline_misses + dropped_frames, total_frames)
                ),
                "published_frames": _format_count(None if published is None else len(published)),
                "frame_accounting": accounting,
                "warmup_frames_excluded": str(warmup_excluded),
                "avg_transport_ms": _format_optional(_average(_values(processed_rows, "transport_ms"))),
                "avg_preprocess_ms": _format_optional(_average(_values(processed_rows, "preprocess_ms"))),
                "avg_artificial_delay_ms": _format_optional(
                    _average(_values(processed_rows, "artificial_delay_ms"))
                ),
                "p95_inference_ms": _format_optional(
                    _percentile(_values(processed_rows, "inference_ms"), 95)
                ),
                "timing_schema": timing_schemas.pop() if len(timing_schemas) == 1 else "mixed",
                **conditions,
                "run_metadata": "" if meta_path is None else Path(meta_path).name,
                "p50_latency_ms": _format_optional(_percentile(latencies, 50)),
                "p50_transport_ms": _format_optional(_percentile(transports, 50)),
                "p95_transport_ms": _format_optional(_percentile(transports, 95)),
                "p50_inference_ms": _format_optional(_percentile(inferences, 50)),
                "avg_service_ms": _format_optional(_average(services)),
                "offered_fps": _format_optional(_rate_fps(offered_stamps)),
                "processed_fps": _format_optional(_rate_fps(completed_stamps)),
                "max_memory_mb": _format_optional(max(memories) if memories else None),
            }
        )
    return summary_rows


def _measurement_window(
    group_rows: list[RuntimeRow], warmup_frames: int
) -> tuple[list[RuntimeRow], int, int | None]:
    """Split off warm-up rows; return (measured rows, excluded count, last warm-up frame_id)."""

    warmup_ids: set[int] = set()
    warmup_rows: set[int] = set()
    received = 0
    for index, row in enumerate(group_rows):
        is_warmup = row.warmup
        if not row.dropped:
            is_warmup = is_warmup or received < warmup_frames
            received += 1
        if is_warmup:
            warmup_rows.add(index)
            if row.frame_id is not None:
                warmup_ids.add(row.frame_id)
    boundary = max(warmup_ids) if warmup_ids else None
    measured = [
        row for index, row in enumerate(group_rows)
        if index not in warmup_rows
        and (boundary is None or row.frame_id is None or row.frame_id > boundary)
    ]
    return measured, len(group_rows) - len(measured), boundary


def _count_dropped(
    measured: list[RuntimeRow], published: list[int] | None
) -> tuple[int | None, str]:
    """Count dropped frames as |window frames - frames received| (set union, no double count)."""

    received_ids = {row.frame_id for row in measured if row.frame_id is not None and not row.dropped}
    explicit_ids = {row.frame_id for row in measured if row.frame_id is not None and row.dropped}
    explicit_without_id = sum(1 for row in measured if row.dropped and row.frame_id is None)
    observed_ids = received_ids | explicit_ids

    if published is not None:
        window = set(published) | observed_ids
        accounting = ACCOUNTING_PUBLISHER
    elif observed_ids:
        window = set(range(min(observed_ids), max(observed_ids) + 1))
        accounting = ACCOUNTING_RANGE
    elif explicit_without_id:
        window = set()
        accounting = ACCOUNTING_EXPLICIT
    else:
        return None, ACCOUNTING_UNAVAILABLE
    return len(window - received_ids) + explicit_without_id, accounting


def _run_deadline(group_rows: list[RuntimeRow], key: tuple[str, ...]) -> float | None:
    deadlines = {row.deadline_ms for row in group_rows if row.deadline_ms is not None}
    if len(deadlines) > 1:
        raise ValueError(
            f"run_id '{key[6]}', config {_describe_config(key)}: rows report several "
            f"deadline_ms values {sorted(deadlines)}; one run must use one deadline."
        )
    return deadlines.pop() if deadlines else None


def _values(rows: list[RuntimeRow], field: str) -> list[float]:
    return [value for value in (getattr(row, field) for row in rows) if value is not None]


def _group_sort_key(key: tuple[str, ...]) -> tuple:
    """Sort numeric fields numerically; non-numeric values sort after them as text."""

    def part(value: str) -> tuple[int, float | str]:
        try:
            return (0, float(value))
        except ValueError:
            return (1, value)

    return (key[0], key[1], part(key[2]), part(key[3]), part(key[4]), key[5], key[6])


def validate_run_integrity(
    groups: dict[tuple[str, ...], list[RuntimeRow]],
) -> None:
    """Reject runtime data whose runs cannot be separated safely.

    - A frame_id may appear only once per (configuration, run). Duplicates mean
      rows from several runs were mixed, e.g. an appended legacy CSV or the same
      run_id copied into two files. They are never silently de-duplicated.
    - Legacy rows (no run_id) are one run per file. frame_id restarts at 0 for
      each detector launch, so a decreasing frame_id inside such a file also means
      several runs were appended into it.
    - An explicit run_id identifies a single launch and therefore one configuration.
    """

    errors: list[str] = []
    configs_by_run: dict[str, set[tuple[str, ...]]] = {}
    for key, group_rows in groups.items():
        run_label = _describe_run(group_rows)
        seen: set[int] = set()
        duplicates: list[int] = []
        previous: int | None = None
        reset_at: tuple[int, int] | None = None
        for row in group_rows:
            if row.frame_id is None:
                continue
            if row.frame_id in seen and row.frame_id not in duplicates:
                duplicates.append(row.frame_id)
            seen.add(row.frame_id)
            if row.legacy_run and previous is not None and row.frame_id < previous and reset_at is None:
                reset_at = (previous, row.frame_id)
            previous = row.frame_id
        if duplicates:
            shown = ", ".join(str(frame_id) for frame_id in duplicates[:5])
            more = f" (+{len(duplicates) - 5} more)" if len(duplicates) > 5 else ""
            errors.append(
                f"{run_label}, config {_describe_config(key)}: duplicate frame_id {shown}{more}."
            )
        elif reset_at is not None:
            errors.append(
                f"{run_label}, config {_describe_config(key)}: frame_id goes back from "
                f"{reset_at[0]} to {reset_at[1]}, so several runs were appended into this file."
            )
        if not group_rows[0].legacy_run:
            configs_by_run.setdefault(group_rows[0].run_id, set()).add(key[:-1])

    for run_id, configs in configs_by_run.items():
        if len(configs) > 1:
            listed = "; ".join(sorted(_describe_config(config) for config in configs))
            errors.append(f"run_id '{run_id}' is used by {len(configs)} configurations: {listed}.")

    if errors:
        raise ValueError(
            "ROS2 runtime data mixes rows from different runs and cannot be separated safely:\n- "
            + "\n- ".join(errors)
            + "\nRe-run with the run_id-enabled logger (one CSV per run), or split the "
            "affected CSV into one file per run before analysis. Rows are never de-duplicated."
        )


def _describe_run(group_rows: list[RuntimeRow]) -> str:
    sources = sorted({row.source for row in group_rows if row.source})
    files = ", ".join(sources) or "unknown file"
    if group_rows[0].legacy_run:
        return f"legacy CSV without run_id ({files})"
    return f"run_id '{group_rows[0].run_id}' ({files})"


def _describe_config(key: tuple[str, ...]) -> str:
    return "/".join(key[: len(GROUP_FIELDS)])


def write_runtime_summary(output_path: str | Path, rows: list[dict[str, str]]) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_runtime_svgs(
    summary_rows: list[dict[str, str]],
    output_dir: str | Path,
) -> list[Path]:
    if not summary_rows:
        raise ValueError("Cannot generate figures from empty summary rows.")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []

    for metric_name, title, filename in FIGURE_METRICS:
        svg = build_bar_chart_svg(summary_rows, metric_name, title)
        figure_path = output_path / filename
        figure_path.write_text(svg, encoding="utf-8")
        written_paths.append(figure_path)

    return written_paths


def build_bar_chart_svg(rows: list[dict[str, str]], metric_name: str, title: str) -> str:
    width = 980
    height = 560
    left = 84
    right = 32
    top = 72
    bottom = 148
    plot_width = width - left - right
    plot_height = height - top - bottom

    raw_values = [_to_float(row.get(metric_name, "")) for row in rows]
    values = [value or 0.0 for value in raw_values]
    max_value = max(values) if values else 1.0
    if max_value == 0:
        max_value = 1.0

    bar_gap = 12
    bar_width = max(12, (plot_width - bar_gap * (len(rows) + 1)) / max(len(rows), 1))

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">',
        "<style>"
        "text{font-family:Arial,sans-serif;fill:#1f2933}"
        ".axis{stroke:#334155;stroke-width:1.2}"
        ".grid{stroke:#d7dee8;stroke-width:1}"
        ".title{font-size:20px;font-weight:700}"
        ".tick{font-size:12px;fill:#52616f}"
        ".label{font-size:12px}"
        "</style>",
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text class="title" x="{width / 2:.1f}" y="34" text-anchor="middle">'
        f"{escape(title)}</text>",
    ]

    for tick_index in range(5):
        ratio = tick_index / 4
        value = max_value * ratio
        y = top + plot_height - ratio * plot_height
        elements.append(
            f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}"/>'
        )
        elements.append(
            f'<text class="tick" x="{left - 10}" y="{y + 4:.1f}" text-anchor="end">'
            f"{_format_number(value)}</text>"
        )

    elements.append(
        f'<line class="axis" x1="{left}" y1="{height - bottom}" '
        f'x2="{width - right}" y2="{height - bottom}"/>'
    )
    elements.append(
        f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}"/>'
    )

    labels = _unique_group_labels(rows)
    for index, row in enumerate(rows):
        value = values[index]
        x = left + bar_gap + index * (bar_width + bar_gap)
        bar_height = 0.0 if max_value == 0 else value / max_value * plot_height
        y = height - bottom - bar_height
        label = labels[index]
        elements.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
            f'height="{bar_height:.1f}" fill="#3d8f5a"/>'
        )
        elements.append(
            f'<text class="tick" x="{x + bar_width / 2:.1f}" y="{y - 6:.1f}" '
            f'text-anchor="middle">{"n/a" if raw_values[index] is None else f"{value:.2f}"}</text>'
        )
        elements.append(
            f'<text class="label" transform="translate({x + bar_width / 2:.1f} '
            f'{height - bottom + 18}) rotate(45)" text-anchor="start">'
            f"{escape(label)}</text>"
        )

    elements.append("</svg>")
    return "\n".join(elements) + "\n"


def _parse_runtime_row(
    raw_row: dict[str, str], source_path: Path, timing_schema: str = "legacy"
) -> RuntimeRow:
    raw_run_id = (raw_row.get("run_id") or "").strip()
    legacy_run = not raw_run_id
    run_id = f"{LEGACY_RUN_PREFIX}{source_path.as_posix()}" if legacy_run else raw_run_id

    latency_ms = _optional_float(raw_row.get("latency_ms"))
    if latency_ms is None:
        published_at_ns = _optional_float(raw_row.get("published_at_ns"))
        completed_at_ns = _optional_float(raw_row.get("completed_at_ns"))
        if published_at_ns is not None and completed_at_ns is not None:
            latency_ms = (completed_at_ns - published_at_ns) / 1_000_000.0

    dropped = _parse_bool(raw_row.get("dropped"))
    deadline_ms = _optional_float(raw_row.get("deadline_ms"))
    # One definition: a processed frame misses iff latency_ms > deadline_ms. The
    # logged flag is only used when deadline_ms is unknown. Dropped frames are
    # counted as drops, never as deadline misses.
    if dropped or latency_ms is None:
        deadline_miss = False
    elif deadline_ms is not None:
        deadline_miss = latency_ms > deadline_ms
    else:
        deadline_miss = _parse_bool(raw_row.get("deadline_miss"))

    return RuntimeRow(
        scenario=_text_or_default(raw_row.get("scenario"), source_path.stem),
        model_name=_text_or_default(raw_row.get("model_name"), "unknown_model"),
        input_fps=_group_number(raw_row.get("input_fps"), "input_fps", "unknown"),
        qos_depth=_group_number(raw_row.get("qos_depth"), "qos_depth", "unknown"),
        fake_delay_ms=_group_number(raw_row.get("fake_delay_ms"), "fake_delay_ms", "0"),
        resource_profile=_text_or_default(raw_row.get("resource_profile"), "normal"),
        frame_id=_optional_int(raw_row.get("frame_id")),
        latency_ms=latency_ms,
        inference_ms=_optional_float(raw_row.get("inference_ms")),
        deadline_miss=deadline_miss,
        dropped=dropped,
        cpu_percent=_optional_float(raw_row.get("cpu_percent")),
        memory_mb=_optional_float(raw_row.get("memory_mb")),
        run_id=run_id,
        legacy_run=legacy_run,
        source=str(source_path),
        deadline_ms=deadline_ms,
        warmup=_parse_bool(raw_row.get("warmup")),
        transport_ms=_optional_float(raw_row.get("transport_ms")),
        preprocess_ms=_optional_float(raw_row.get("preprocess_ms")),
        artificial_delay_ms=_optional_float(raw_row.get("artificial_delay_ms")),
        timing_schema=timing_schema,
        published_at_ns=_optional_int(raw_row.get("published_at_ns")),
        completed_at_ns=_optional_int(raw_row.get("completed_at_ns")),
    )


def _group_number(value: str | None, field: str, default: str) -> str:
    """Canonical text for numeric grouping keys, so '20' and '20.0' are one group.

    input_fps keeps the float spelling the detector logs ('20.0'); qos_depth and
    fake_delay_ms use integers when integral. Non-numeric text is kept as-is.
    """

    text = _text_or_default(value, default).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    if NUMERIC_GROUP_FIELDS[field] is int and number.is_integer():
        return str(int(number))
    return repr(number)


def _is_publisher_log(path: Path) -> bool:
    return path.name.endswith(PUBLISHER_SUFFIX)


def _expand_input_paths(input_paths: Iterable[str | Path]) -> list[Path]:
    paths: list[Path] = []
    for input_path in input_paths:
        path = Path(input_path)
        if path.is_dir():
            paths.extend(sorted(path.glob("*.csv")))
        else:
            paths.append(path)
    if not paths:
        raise ValueError("No input CSV paths provided.")
    return paths


def _group_label(row: dict[str, str]) -> str:
    model = row['model_name'].replace("mobilevit_", "")
    scenario = row['scenario'].replace("_sweep", "")
    return f"{scenario} {model} {row['input_fps']}fps q{row['qos_depth']} d{row['fake_delay_ms']}"


def _unique_group_labels(rows: list[dict[str, str]]) -> list[str]:
    """Append a run ordinal when several runs share the same configuration label."""

    labels = [_group_label(row) for row in rows]
    totals = {label: labels.count(label) for label in labels}
    seen: dict[str, int] = {}
    unique: list[str] = []
    for label in labels:
        if totals[label] == 1:
            unique.append(label)
            continue
        seen[label] = seen.get(label, 0) + 1
        unique.append(f"{label} run{seen[label]}")
    return unique


def _text_or_default(value: str | None, default: str) -> str:
    if value is None or not value.strip():
        return default
    return value


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "miss", "dropped"}


def _optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)


def _optional_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    return int(value)


def _to_float(value: str) -> float | None:
    if not value:
        return None
    return float(value)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return mean(values)


def _pstdev(values: list[float]) -> float | None:
    if len(values) <= 1:
        return 0.0 if values else None
    return pstdev(values)


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = max(0, ceil(percentile / 100 * len(sorted_values)) - 1)
    return sorted_values[index]


def _rate_pct(count: int | None, total: int | None) -> float | None:
    """Percentage, or None (unknown) when the count or a non-zero total is missing."""

    if count is None or not total:
        return None
    return count / total * 100.0


def _format_count(value: int | None) -> str:
    return "" if value is None else str(value)


def _format_optional(value: float | None) -> str:
    if value is None:
        return ""
    return _format_number(value)


def _format_number(value: float) -> str:
    return f"{value:.6g}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze ROS2 runtime CSV metrics.")
    parser.add_argument(
        "--input",
        nargs="+",
        required=True,
        help="One or more ROS2 runtime CSV files or directories containing CSV files.",
    )
    parser.add_argument("--summary-output", required=True, help="Path to output summary CSV.")
    parser.add_argument(
        "--figures-dir",
        default=None,
        help="Optional directory for SVG runtime figures.",
    )
    parser.add_argument(
        "--warmup-frames",
        type=int,
        default=0,
        help="Also exclude the first N received frames of every run (in addition to rows "
        "the detector flagged warmup=1). Default: 0.",
    )
    parser.add_argument(
        "--manifest-output",
        default=None,
        help="Provenance manifest path. Default: <summary stem>.manifest.json next to the summary.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
