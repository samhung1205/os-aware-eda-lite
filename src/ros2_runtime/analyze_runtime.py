"""Analyze generic ROS2 edge AI runtime CSV metrics.

The analyzer accepts the runtime logging contract documented in the README. It
uses only the Python standard library so it can run in the same lightweight
environment as EDA-Lite.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from html import escape
from math import ceil
from pathlib import Path
from statistics import mean, pstdev
from typing import Iterable


GROUP_FIELDS = [
    "scenario",
    "model_name",
    "input_fps",
    "qos_depth",
    "fake_delay_ms",
    "resource_profile",
]

SUMMARY_FIELDS = [
    *GROUP_FIELDS,
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
]

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

    def group_key(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.scenario,
            self.model_name,
            self.input_fps,
            self.qos_depth,
            self.fake_delay_ms,
            self.resource_profile,
        )


def main() -> None:
    args = _parse_args()
    rows = load_runtime_rows(args.input)
    summary_rows = build_runtime_summary(rows)
    write_runtime_summary(args.summary_output, summary_rows)

    if args.figures_dir:
        written = write_runtime_svgs(summary_rows, args.figures_dir)
        print(f"Wrote {len(written)} ROS2 SVG figures to {args.figures_dir}")

    print(f"Wrote {len(summary_rows)} ROS2 summary rows to {args.summary_output}")


def load_runtime_rows(input_paths: Iterable[str | Path]) -> list[RuntimeRow]:
    """Load one or more ROS2 runtime CSV files."""

    csv_paths = _expand_input_paths(input_paths)
    rows: list[RuntimeRow] = []
    for path in csv_paths:
        with path.open("r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            if not reader.fieldnames:
                raise ValueError(f"{path} is missing a CSV header.")
            for raw_row in reader:
                rows.append(_parse_runtime_row(raw_row, source_path=path))
    if not rows:
        raise ValueError("No ROS2 runtime rows found.")
    return rows


def build_runtime_summary(rows: Iterable[RuntimeRow]) -> list[dict[str, str]]:
    groups: dict[tuple[str, str, str, str, str, str], list[RuntimeRow]] = {}
    for row in rows:
        groups.setdefault(row.group_key(), []).append(row)

    summary_rows: list[dict[str, str]] = []
    for key in sorted(groups):
        group_rows = groups[key]
        processed_rows = [
            row for row in group_rows if not row.dropped and row.latency_ms is not None
        ]
        latencies = [row.latency_ms for row in processed_rows if row.latency_ms is not None]
        inference_times = [
            row.inference_ms for row in processed_rows if row.inference_ms is not None
        ]
        cpu_values = [row.cpu_percent for row in group_rows if row.cpu_percent is not None]
        memory_values = [row.memory_mb for row in group_rows if row.memory_mb is not None]
        explicit_drops = sum(1 for row in group_rows if row.dropped)
        inferred_drops = 0 if explicit_drops else _infer_frame_id_drops(group_rows)
        dropped_frames = explicit_drops + inferred_drops
        deadline_misses = sum(1 for row in group_rows if row.deadline_miss)
        processed_count = len(processed_rows)
        total_frames = processed_count + dropped_frames

        summary_rows.append(
            {
                "scenario": key[0],
                "model_name": key[1],
                "input_fps": key[2],
                "qos_depth": key[3],
                "fake_delay_ms": key[4],
                "resource_profile": key[5],
                "total_rows": str(total_frames),
                "processed_frames": str(processed_count),
                "dropped_frames": str(dropped_frames),
                "drop_rate_pct": _format_number(_rate_pct(dropped_frames, total_frames)),
                "deadline_misses": str(deadline_misses),
                "deadline_miss_rate_pct": _format_number(
                    _rate_pct(deadline_misses, max(processed_count, 1))
                ),
                "avg_latency_ms": _format_optional(_average(latencies)),
                "p95_latency_ms": _format_optional(_percentile(latencies, 95)),
                "p99_latency_ms": _format_optional(_percentile(latencies, 99)),
                "jitter_ms": _format_optional(_pstdev(latencies)),
                "avg_inference_ms": _format_optional(_average(inference_times)),
                "avg_cpu_percent": _format_optional(_average(cpu_values)),
                "avg_memory_mb": _format_optional(_average(memory_values)),
            }
        )
    return summary_rows


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

    values = [_to_float(row.get(metric_name, "")) or 0.0 for row in rows]
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

    for index, row in enumerate(rows):
        value = values[index]
        x = left + bar_gap + index * (bar_width + bar_gap)
        bar_height = 0.0 if max_value == 0 else value / max_value * plot_height
        y = height - bottom - bar_height
        label = _group_label(row)
        elements.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
            f'height="{bar_height:.1f}" fill="#3d8f5a"/>'
        )
        elements.append(
            f'<text class="tick" x="{x + bar_width / 2:.1f}" y="{y - 6:.1f}" '
            f'text-anchor="middle">{_format_number(value)}</text>'
        )
        elements.append(
            f'<text class="label" transform="translate({x + bar_width / 2:.1f} '
            f'{height - bottom + 18}) rotate(45)" text-anchor="start">'
            f"{escape(label)}</text>"
        )

    elements.append("</svg>")
    return "\n".join(elements) + "\n"


def _parse_runtime_row(raw_row: dict[str, str], source_path: Path) -> RuntimeRow:
    latency_ms = _optional_float(raw_row.get("latency_ms"))
    if latency_ms is None:
        published_at_ns = _optional_float(raw_row.get("published_at_ns"))
        completed_at_ns = _optional_float(raw_row.get("completed_at_ns"))
        if published_at_ns is not None and completed_at_ns is not None:
            latency_ms = (completed_at_ns - published_at_ns) / 1_000_000.0

    dropped = _parse_bool(raw_row.get("dropped"))
    deadline_miss = _parse_bool(raw_row.get("deadline_miss"))
    deadline_ms = _optional_float(raw_row.get("deadline_ms"))
    if not deadline_miss and deadline_ms is not None and latency_ms is not None:
        deadline_miss = latency_ms > deadline_ms

    return RuntimeRow(
        scenario=_text_or_default(raw_row.get("scenario"), source_path.stem),
        model_name=_text_or_default(raw_row.get("model_name"), "unknown_model"),
        input_fps=_text_or_default(raw_row.get("input_fps"), "unknown"),
        qos_depth=_text_or_default(raw_row.get("qos_depth"), "unknown"),
        fake_delay_ms=_text_or_default(raw_row.get("fake_delay_ms"), "0"),
        resource_profile=_text_or_default(raw_row.get("resource_profile"), "normal"),
        frame_id=_optional_int(raw_row.get("frame_id")),
        latency_ms=latency_ms,
        inference_ms=_optional_float(raw_row.get("inference_ms")),
        deadline_miss=deadline_miss,
        dropped=dropped,
        cpu_percent=_optional_float(raw_row.get("cpu_percent")),
        memory_mb=_optional_float(raw_row.get("memory_mb")),
    )


def _infer_frame_id_drops(rows: list[RuntimeRow]) -> int:
    frame_ids = sorted({row.frame_id for row in rows if row.frame_id is not None})
    if len(frame_ids) <= 1:
        return 0

    dropped = 0
    previous = frame_ids[0]
    for frame_id in frame_ids[1:]:
        if frame_id > previous + 1:
            dropped += frame_id - previous - 1
        previous = frame_id
    return dropped


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
    return (
        f"{row['scenario']} {row['model_name']} "
        f"{row['input_fps']}fps q{row['qos_depth']} d{row['fake_delay_ms']}"
    )


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


def _rate_pct(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return count / total * 100.0


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
    return parser.parse_args()


if __name__ == "__main__":
    main()
