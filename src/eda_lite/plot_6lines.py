"""Six-line comparison charts: compiler-only baseline vs one OS-aware profile.

The baseline uses the ``pure`` OS profile (latency multiplier 1.0, no deadline,
memory, or communication pressure). Both profiles are chosen on the command
line; nothing is hard-coded here.
"""

import argparse
import csv
from pathlib import Path
from src.eda_lite.analyze_results import _parse_result_row, ResultRow, _format_number, PLOT_METRICS

def build_combined_chart(rows, metric_name, title, y_label, filename):
    series = {}
    for row in rows:
        if not row.feasible:
            continue
        series.setdefault(row.text("scheduler"), []).append(
            (row.number("sram_kb"), row.number(metric_name))
        )
        
    width = 920
    height = 560
    left = 100
    right = 28
    top = 72
    bottom = 82
    plot_width = width - left - right
    plot_height = height - top - bottom

    x_values = sorted({point[0] for points in series.values() for point in points})
    y_values = [point[1] for points in series.values() for point in points]
    min_x, max_x = min(x_values), max(x_values)
    min_y, max_y = min(0.0, min(y_values)), max(y_values)
    if max_y == min_y: max_y = min_y + 1.0

    def x_pos(v): return left + (v - min_x) / (max_x - min_x) * plot_width if max_x > min_x else left + plot_width/2
    def y_pos(v): return top + (max_y - v) / (max_y - min_y) * plot_height

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<style>text{font-family:Arial,sans-serif;fill:#1f2933}.axis{stroke:#334155;stroke-width:1.2}.grid{stroke:#d7dee8;stroke-width:1}.label{font-size:14px}.tick{font-size:12px;fill:#52616f}.title{font-size:20px;font-weight:700}.legend{font-size:13px}</style>",
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text class="title" x="{width / 2:.1f}" y="34" text-anchor="middle">{title}</text>',
    ]

    for i in range(5):
        v = min_y + (max_y - min_y) * (i / 4)
        y = y_pos(v)
        elements.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}"/>')
        elements.append(f'<text class="tick" x="{left - 10}" y="{y + 4:.1f}" text-anchor="end">{_format_number(v)}</text>')

    elements.append(f'<line class="axis" x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}"/>')
    elements.append(f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}"/>')

    for x_val in x_values:
        x = x_pos(x_val)
        elements.append(f'<line class="axis" x1="{x:.1f}" y1="{height - bottom}" x2="{x:.1f}" y2="{height - bottom + 5}"/>')
        elements.append(f'<text class="tick" x="{x:.1f}" y="{height - bottom + 24}" text-anchor="middle">{_format_number(x_val)}</text>')

    styles = {
        "layerwise (Pure)": ("#2f6fbb", "", 8, 0.3),
        "greedy (Pure)": ("#c4472e", "6,4", 7, 0.3),
        "dp (Pure)": ("#3d8f5a", "2,2", 6, 0.3),
        "layerwise (OS-Aware)": ("#2f6fbb", "", 4, 1.0),
        "greedy (OS-Aware)": ("#c4472e", "6,4", 3, 1.0),
        "dp (OS-Aware)": ("#3d8f5a", "2,2", 2, 1.0),
    }

    for scheduler, points in series.items():
        color, dash, r, opac = styles.get(scheduler, ("#000", "", 4, 1.0))
        pts = " ".join(f"{x_pos(x):.1f},{y_pos(y):.1f}" for x, y in sorted(points))
        dash_str = f' stroke-dasharray="{dash}"' if dash else ""
        elements.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.4" stroke-opacity="{opac}"{dash_str} points="{pts}"/>')
        for x, y in sorted(points):
            elements.append(f'<circle cx="{x_pos(x):.1f}" cy="{y_pos(y):.1f}" r="{r}" fill="{color}" fill-opacity="{opac}"/>')

    lx, ly = left + 10, top + 10
    for i, scheduler in enumerate(series):
        color, _, _, opac = styles.get(scheduler, ("#000", "", 4, 1.0))
        y = ly + i * 20
        elements.append(f'<rect x="{lx}" y="{y-10}" width="14" height="14" fill="{color}" fill-opacity="{opac}"/>')
        elements.append(f'<text class="legend" x="{lx + 22}" y="{y+2}">{scheduler}</text>')

    elements.append(f'<text class="label" x="{width / 2:.1f}" y="{height - 24}" text-anchor="middle">SRAM (KB)</text>')
    elements.append(f'<text class="label" transform="translate(26 {height / 2:.1f}) rotate(-90)" text-anchor="middle">{y_label}</text>')
    elements.append("</svg>\n")

    out = Path(filename)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(elements), encoding="utf-8")


def generate_6line_charts(model, pure_csv, os_csv, os_profile_name, out_dir, pure_profile_name="pure"):
    def load(path):
        with open(path) as f:
            return [_parse_result_row(r) for r in csv.DictReader(f)]

    rows_pure = load(pure_csv)
    rows_os = load(os_csv)
    for path, rows, profile in ((pure_csv, rows_pure, pure_profile_name), (os_csv, rows_os, os_profile_name)):
        if not any(r.text("os_profile") == profile and r.text("model_name") == model for r in rows):
            raise ValueError(f"No rows for model '{model}' and OS profile '{profile}' in {path}.")

    combined = []
    for r in rows_pure:
        if r.text("os_profile") == pure_profile_name and r.text("model_name") == model:
            d = r.values.copy()
            d["scheduler"] += " (Pure)"
            combined.append(ResultRow(d))
            
    for r in rows_os:
        if r.text("os_profile") == os_profile_name and r.text("model_name") == model:
            d = r.values.copy()
            d["scheduler"] += " (OS-Aware)"
            combined.append(ResultRow(d))

    for metric_name, y_label, filename in PLOT_METRICS:
        title = f"{model} - {y_label}"
        build_combined_chart(combined, metric_name, title, y_label, f"{out_dir}/{filename}")

def _parse_args():
    parser = argparse.ArgumentParser(description="Six-line pure vs OS-aware EDA-Lite charts.")
    parser.add_argument("--model", required=True, help="model_name to plot.")
    parser.add_argument("--pure-csv", required=True, help="Simulation CSV containing the pure profile.")
    parser.add_argument("--os-csv", required=True, help="Simulation CSV containing the OS-aware profile.")
    parser.add_argument("--os-profile", required=True, help="OS-aware profile to compare against pure.")
    parser.add_argument("--pure-profile", default="pure", help="Baseline profile name. Default: pure.")
    parser.add_argument("--out-dir", required=True, help="Output directory for SVG figures.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    generate_6line_charts(
        args.model,
        args.pure_csv,
        args.os_csv,
        args.os_profile,
        args.out_dir,
        pure_profile_name=args.pure_profile,
    )
