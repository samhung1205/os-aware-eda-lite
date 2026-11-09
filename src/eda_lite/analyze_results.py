"""Analyze EDA-Lite simulation CSVs and generate report-ready SVG figures."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Iterable

from .schedulers import costs_tie


SUMMARY_FIELDS = [
    "model_name",
    "os_profile",
    "sram_kb",
    "best_scheduler",
    "best_os_aware_total_cost",
    "layerwise_dram_traffic_kb",
    "best_dram_traffic_kb",
    "dram_reduction_pct",
    "layerwise_estimated_energy",
    "best_estimated_energy",
    "energy_reduction_pct",
    "layerwise_estimated_latency_ms",
    "best_estimated_latency_ms",
    "latency_reduction_pct",
    "best_num_subgraphs",
    "best_max_fusion_depth",
    # Appended in Phase 1 / Batch 2.
    "deadline_ms",
    "num_tied_schedulers",
    "tied_same_partition",
    "feasible_schedulers",
    "infeasible_schedulers",
    "baseline_status",
]


PLOT_METRICS = [
    ("dram_traffic_kb", "DRAM traffic (KB)", "dram_traffic_by_sram.svg"),
    ("estimated_energy", "Estimated energy", "estimated_energy_by_sram.svg"),
    ("estimated_latency_ms", "Estimated latency (ms)", "estimated_latency_by_sram.svg"),
    ("max_fusion_depth", "Max fusion depth", "fusion_depth_by_sram.svg"),
]


NUMERIC_FIELDS = {
    "sram_kb",
    "num_subgraphs",
    "max_fusion_depth",
    "peak_sram_kb",
    "dram_traffic_kb",
    "estimated_energy",
    "estimated_latency_ms",
    "os_aware_total_cost",
    "effective_latency_ms",
    "latency_cost",
    "deadline_cost",
    "memory_pressure_cost",
    "communication_pressure_cost",
}


SCHEDULER_COLORS = {
    "layerwise": "#2f6fbb",
    "greedy": "#c4472e",
    "dp": "#3d8f5a",
}


@dataclass(frozen=True)
class ResultRow:
    values: dict[str, str | float]

    def text(self, field_name: str) -> str:
        value = self.values[field_name]
        return str(value)

    def number(self, field_name: str) -> float:
        value = self.values[field_name]
        if not isinstance(value, float):
            raise ValueError(f"Field '{field_name}' is not numeric.")
        return value

    @property
    def feasible(self) -> bool:
        """Rows from CSVs without a ``feasible`` column are feasible (legacy)."""

        return str(self.values.get("feasible", "") or "true").strip().lower() != "false"


def main() -> None:
    args = _parse_args()
    rows = load_result_rows(args.input)
    summary_rows = build_summary_rows(rows)
    write_summary_csv(args.summary_output, summary_rows)
    written_figures = write_metric_svgs(
        rows=rows,
        output_dir=args.figures_dir,
        os_profile=args.plot_os_profile,
        model_name=args.plot_model,
        deadline_ms=args.plot_deadline_ms,
    )
    print(f"Wrote {len(summary_rows)} summary rows to {args.summary_output}")
    print(f"Wrote {len(written_figures)} SVG figures to {args.figures_dir}")


def load_result_rows(input_path: str | Path) -> list[ResultRow]:
    """Load simulation CSV rows and convert known numeric fields."""

    path = Path(input_path)
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError("Input CSV is missing a header row.")
        rows = [_parse_result_row(row) for row in reader]
    if not rows:
        raise ValueError("Input CSV contains no result rows.")
    return rows


def build_summary_rows(rows: Iterable[ResultRow]) -> list[dict[str, str]]:
    """Build one best-scheduler summary row per model, OS profile, SRAM, deadline.

    * Infeasible rows never win; a group with no feasible scheduler gets an
      empty ``best_scheduler``.
    * Schedulers whose cost ties the minimum (``costs_tie``) are all reported,
      joined with ``=`` in CSV order (e.g. ``greedy=dp``), instead of letting
      ``min()`` silently pick the first one. ``best_*`` metrics come from the
      first tied scheduler; ``tied_same_partition`` says whether the tied
      schedulers chose the same partition.
    * Reductions are relative to ``layerwise``; when it is missing or
      infeasible the reduction columns stay empty and ``baseline_status`` says why.
    """

    groups: dict[tuple[str, str, float, str], list[ResultRow]] = {}
    for row in rows:
        key = (
            row.text("model_name"),
            row.text("os_profile"),
            row.number("sram_kb"),
            str(row.values.get("deadline_ms", "") or ""),
        )
        groups.setdefault(key, []).append(row)

    summary_rows: list[dict[str, str]] = []
    for key in sorted(groups, key=_group_sort_key):
        group_rows = groups[key]
        feasible_rows = [row for row in group_rows if row.feasible]
        layerwise_rows = [row for row in group_rows if row.text("scheduler") == "layerwise"]
        if not layerwise_rows:
            baseline_status = "missing"
            layerwise = None
        elif not layerwise_rows[0].feasible:
            baseline_status = "infeasible"
            layerwise = None
        else:
            baseline_status = "ok"
            layerwise = layerwise_rows[0]

        summary: dict[str, str] = {field: "" for field in SUMMARY_FIELDS}
        summary.update(
            {
                "model_name": key[0],
                "os_profile": key[1],
                "sram_kb": _format_number(key[2]),
                "deadline_ms": key[3],
                "feasible_schedulers": ";".join(r.text("scheduler") for r in feasible_rows),
                "infeasible_schedulers": ";".join(
                    r.text("scheduler") for r in group_rows if not r.feasible
                ),
                "baseline_status": baseline_status,
                "num_tied_schedulers": "0",
            }
        )
        if layerwise is not None:
            for metric in ("dram_traffic_kb", "estimated_energy", "estimated_latency_ms"):
                summary[f"layerwise_{metric}"] = _format_number(layerwise.number(metric))

        if feasible_rows:
            best_cost = min(row.number("os_aware_total_cost") for row in feasible_rows)
            tied = [
                row
                for row in feasible_rows
                if costs_tie(row.number("os_aware_total_cost"), best_cost)
            ]
            best = tied[0]
            summary.update(
                {
                    "best_scheduler": "=".join(row.text("scheduler") for row in tied),
                    "best_os_aware_total_cost": _format_number(best_cost),
                    "num_tied_schedulers": str(len(tied)),
                    "tied_same_partition": str(
                        len({row.text("subgraphs") for row in tied}) == 1
                    ).lower(),
                    "best_num_subgraphs": _format_number(best.number("num_subgraphs")),
                    "best_max_fusion_depth": _format_number(best.number("max_fusion_depth")),
                }
            )
            for metric, reduction in (
                ("dram_traffic_kb", "dram_reduction_pct"),
                ("estimated_energy", "energy_reduction_pct"),
                ("estimated_latency_ms", "latency_reduction_pct"),
            ):
                summary[f"best_{metric}"] = _format_number(best.number(metric))
                if layerwise is not None:
                    summary[reduction] = _format_number(
                        _reduction_pct(layerwise.number(metric), best.number(metric))
                    )
        summary_rows.append(summary)
    return summary_rows


def _group_sort_key(key: tuple[str, str, float, str]) -> tuple:
    deadline = key[3]
    try:
        deadline_sort: tuple = (0, float(deadline))
    except ValueError:
        deadline_sort = (1, deadline)
    return (key[0], key[1], key[2], deadline_sort)


def write_summary_csv(output_path: str | Path, rows: list[dict[str, str]]) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_metric_svgs(
    rows: Iterable[ResultRow],
    output_dir: str | Path,
    os_profile: str,
    model_name: str | None = None,
    deadline_ms: str | None = None,
) -> list[Path]:
    """Write SVG line charts for key metrics for one OS profile and model.

    Infeasible rows have no metrics and are left out of the lines.
    """

    selected_rows = [row for row in rows if row.text("os_profile") == os_profile]
    if not selected_rows:
        raise ValueError(f"No rows found for OS profile '{os_profile}'.")

    if deadline_ms is not None:
        selected_rows = [
            row for row in selected_rows if _same_number(row.values.get("deadline_ms"), deadline_ms)
        ]
        if not selected_rows:
            raise ValueError(f"No rows found for deadline_ms={deadline_ms}.")
    deadlines = sorted({str(row.values.get("deadline_ms", "") or "") for row in selected_rows})
    if len(deadlines) > 1:
        raise ValueError(
            "Plotting requires one deadline at a time. "
            f"Use --plot-deadline-ms with one of: {', '.join(deadlines)}."
        )

    if model_name is not None:
        selected_rows = [row for row in selected_rows if row.text("model_name") == model_name]
        if not selected_rows:
            raise ValueError(
                f"No rows found for model '{model_name}' and OS profile '{os_profile}'."
            )

    model_names = sorted({row.text("model_name") for row in selected_rows})
    if len(model_names) > 1:
        names = ", ".join(model_names)
        raise ValueError(
            "Plotting requires one model at a time. "
            f"Use --plot-model with one of: {names}."
        )

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []
    plot_model_name = model_names[0]

    for metric_name, y_label, filename in PLOT_METRICS:
        svg = build_line_chart_svg(
            rows=selected_rows,
            metric_name=metric_name,
            title=f"{plot_model_name} - {y_label}",
            x_label="SRAM (KB)",
            y_label=y_label,
        )
        figure_path = output_path / filename
        figure_path.write_text(svg, encoding="utf-8")
        written_paths.append(figure_path)

    return written_paths


def build_line_chart_svg(
    rows: Iterable[ResultRow],
    metric_name: str,
    title: str,
    x_label: str,
    y_label: str,
) -> str:
    """Build a simple SVG line chart without external plotting dependencies."""

    series = _series_by_scheduler(rows, metric_name)
    if not series:
        raise ValueError("Cannot build chart from empty data.")

    width = 920
    height = 560
    left = 88
    right = 28
    top = 72
    bottom = 82
    plot_width = width - left - right
    plot_height = height - top - bottom

    x_values = sorted({point[0] for points in series.values() for point in points})
    y_values = [point[1] for points in series.values() for point in points]
    min_x = min(x_values)
    max_x = max(x_values)
    min_y = min(0.0, min(y_values))
    max_y = max(y_values)
    if max_y == min_y:
        max_y = min_y + 1.0

    def x_pos(value: float) -> float:
        if max_x == min_x:
            return left + plot_width / 2
        return left + (value - min_x) / (max_x - min_x) * plot_width

    def y_pos(value: float) -> float:
        return top + (max_y - value) / (max_y - min_y) * plot_height

    elements: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">',
        "<style>"
        "text{font-family:Arial,sans-serif;fill:#1f2933}"
        ".axis{stroke:#334155;stroke-width:1.2}"
        ".grid{stroke:#d7dee8;stroke-width:1}"
        ".label{font-size:14px}"
        ".tick{font-size:12px;fill:#52616f}"
        ".title{font-size:20px;font-weight:700}"
        ".legend{font-size:13px}"
        "</style>",
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text class="title" x="{width / 2:.1f}" y="34" text-anchor="middle">'
        f"{escape(title)}</text>",
    ]

    for tick_index in range(5):
        ratio = tick_index / 4
        value = min_y + (max_y - min_y) * ratio
        y = y_pos(value)
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

    for x_value in x_values:
        x = x_pos(x_value)
        elements.append(
            f'<line class="axis" x1="{x:.1f}" y1="{height - bottom}" '
            f'x2="{x:.1f}" y2="{height - bottom + 5}"/>'
        )
        elements.append(
            f'<text class="tick" x="{x:.1f}" y="{height - bottom + 24}" '
            f'text-anchor="middle">{_format_number(x_value)}</text>'
        )

    scheduler_styles = {
        "layerwise": {"dash": "", "r": 6, "opacity": 0.9},
        "greedy": {"dash": "6,4", "r": 5, "opacity": 0.8},
        "dp": {"dash": "2,2", "r": 4, "opacity": 1.0},
    }

    for scheduler, points in series.items():
        color = SCHEDULER_COLORS.get(scheduler, "#64748b")
        style = scheduler_styles.get(scheduler, {"dash": "", "r": 4, "opacity": 0.8})
        dash_attr = f' stroke-dasharray="{style["dash"]}"' if style["dash"] else ""
        
        coordinate_pairs = " ".join(
            f"{x_pos(x):.1f},{y_pos(y):.1f}" for x, y in sorted(points)
        )
        elements.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="2.4" '
            f'stroke-opacity="{style["opacity"]}"{dash_attr} '
            f'points="{coordinate_pairs}"/>'
        )
        for x, y in sorted(points):
            elements.append(
                f'<circle cx="{x_pos(x):.1f}" cy="{y_pos(y):.1f}" r="{style["r"]}" '
                f'fill="{color}" fill-opacity="{style["opacity"]}"/>'
            )

    legend_x = left + 10
    legend_y = top + 18
    for index, scheduler in enumerate(series):
        y = legend_y + index * 22
        color = SCHEDULER_COLORS.get(scheduler, "#64748b")
        elements.append(f'<rect x="{legend_x}" y="{y - 10}" width="14" height="14" fill="{color}"/>')
        elements.append(
            f'<text class="legend" x="{legend_x + 22}" y="{y + 2}">'
            f"{escape(scheduler)}</text>"
        )

    elements.append(
        f'<text class="label" x="{width / 2:.1f}" y="{height - 24}" text-anchor="middle">'
        f"{escape(x_label)}</text>"
    )
    elements.append(
        f'<text class="label" transform="translate(22 {height / 2:.1f}) rotate(-90)" '
        f'text-anchor="middle">{escape(y_label)}</text>'
    )
    elements.append("</svg>")
    return "\n".join(elements) + "\n"


def _parse_result_row(raw_row: dict[str, Any]) -> ResultRow:
    values: dict[str, str | float] = {}
    for field_name, value in raw_row.items():
        if value is None:
            values[field_name] = ""
        elif field_name in NUMERIC_FIELDS and value.strip() != "":
            values[field_name] = float(value)
        else:
            values[field_name] = value
    return ResultRow(values=values)


def _series_by_scheduler(
    rows: Iterable[ResultRow],
    metric_name: str,
) -> dict[str, list[tuple[float, float]]]:
    series: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        if not row.feasible:
            continue
        series.setdefault(row.text("scheduler"), []).append(
            (row.number("sram_kb"), row.number(metric_name))
        )
    return series


def _same_number(value: Any, expected: str) -> bool:
    try:
        return float(str(value)) == float(expected)
    except ValueError:
        return str(value) == expected


def _reduction_pct(baseline: float, candidate: float) -> float:
    if baseline == 0:
        return 0.0
    return (baseline - candidate) / baseline * 100.0


def _format_number(value: float) -> str:
    return f"{value:.6g}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze EDA-Lite simulation results.")
    parser.add_argument("--input", required=True, help="Path to simulation CSV.")
    parser.add_argument("--summary-output", required=True, help="Path to summary CSV.")
    parser.add_argument("--figures-dir", required=True, help="Directory for SVG figures.")
    parser.add_argument(
        "--plot-os-profile",
        default="normal",
        help="OS profile to plot. Default: normal.",
    )
    parser.add_argument(
        "--plot-model",
        default=None,
        help="Model name to plot when the input CSV contains multiple models.",
    )
    parser.add_argument(
        "--plot-deadline-ms",
        default=None,
        help="Deadline to plot when the input CSV sweeps deadline_ms.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
