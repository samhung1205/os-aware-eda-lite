"""Aggregate a ROS2 baseline (Phase 2 / Batch 2) across independent runs.

Input: the per-run summary written by ``analyze_runtime`` (one row per run) plus the
``<run_id>.probe.json`` files next to the raw CSVs. Outputs:

- ``--runs-output``: one row per run = summary metrics + probe (DDS verification,
  per-node CPU, cgroup memory, host interference) + derived capacity figures.
- ``--conditions-output``: one row per condition (scenario, model, fps, qos, delay):
  number of runs and mean / sample SD / min / max **across runs** of each metric.
  The run, not the frame, is the unit of replication; frames are never pooled.
- ``--figures-dir``: SVG charts (mean across runs, min–max whiskers, every run as a dot).
- ``<conditions stem>.manifest.json``: SHA-256 of the summary, its manifest, every probe
  file and the outputs.

Derived quantities (per run):

- ``capacity_fps = 1000 / avg_service_ms`` where service = preprocess + artificial delay +
  inference of one frame in the single-threaded detector callback.
- ``utilization = offered_fps * avg_service_ms / 1000`` (rho). rho > 1 means the detector
  cannot keep up on average: frames are necessarily discarded by the KEEP_LAST queue.
- ``expected_overload_drop_pct = 100 * max(0, 1 - 1/rho)``: drop rate a lossless transport
  with a saturated detector would show. Comparing it with the measured drop rate separates
  overload drops (match) from transport loss (drops while rho < 1).
- ``drop_cause``: ``none`` / ``overload`` (rho >= 1) / ``below_capacity`` (drops while rho < 1:
  transport loss or bursts overflowing a short queue).

Standard library only. Read-only on its inputs.
"""

from __future__ import annotations

import argparse
import csv
import json
from html import escape
from math import sqrt
from pathlib import Path
from statistics import mean, stdev
from typing import Any

from src.provenance import sha256_file

CONDITION_KEYS = ["scenario", "model_name", "input_fps", "qos_depth", "fake_delay_ms"]
METRICS = [
    "offered_fps", "processed_fps", "published_frames", "processed_frames", "dropped_frames",
    "drop_rate_pct", "deadline_miss_rate_pct", "effective_miss_rate_pct",
    "avg_latency_ms", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "jitter_ms",
    "avg_transport_ms", "p50_transport_ms", "p95_transport_ms",
    "avg_preprocess_ms", "avg_artificial_delay_ms", "avg_inference_ms", "p50_inference_ms",
    "p95_inference_ms", "avg_service_ms", "capacity_fps", "utilization", "expected_overload_drop_pct",
    "avg_cpu_percent", "detector_cpu_pct", "publisher_cpu_pct", "avg_memory_mb", "max_memory_mb",
    "cgroup_memory_peak_mb", "sibling_cpu_busy_max_pct", "loadavg_1m_max",
]
PROBE_FIELDS = [
    "dds_verified", "detector_udp_sockets", "publisher_udp_sockets", "shm_segment_max_bytes",
    "detector_cpu_pct", "publisher_cpu_pct", "detector_nice", "cpus_allowed",
    "cgroup_memory_peak_mb", "cgroup_swap_max_bytes", "allowed_cpu_busy_max_pct",
    "sibling_cpu_busy_max_pct", "loadavg_1m_max", "udp_rcvbuf_errors_delta",
]
DERIVED = ["capacity_fps", "utilization", "expected_overload_drop_pct", "drop_cause"]

# Reference categorical palette (dataviz skill, light mode), fixed order: model identity.
MODEL_COLORS = {"mobilevit_xxs": "#2a78d6", "mobilevit_s": "#eb6834"}
STAGE_COLORS = [("avg_transport_ms", "transport + queue", "#2a78d6"),
                ("avg_preprocess_ms", "preprocess", "#1baf7a"),
                ("avg_artificial_delay_ms", "artificial delay", "#eda100"),
                ("avg_inference_ms", "inference", "#eb6834")]
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def _f(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: float | None, digits: int = 4) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}g}" if abs(value) < 1e4 else f"{value:.0f}"


def probe_fields(probe: dict[str, Any] | None, allowed: list[int]) -> dict[str, Any]:
    if not probe:
        return {k: "" for k in PROBE_FIELDS}
    nodes = probe.get("nodes") or {}
    det, pub = nodes.get("detector") or {}, nodes.get("publisher") or {}
    busy = {int(k): v for k, v in ((probe.get("host") or {}).get("watched_cpus_busy_pct") or {}).items()
            if v is not None}
    allowed_busy = [v for c, v in busy.items() if c in allowed]
    sibling_busy = [v for c, v in busy.items() if c not in allowed]
    dds = probe.get("dds") or {}
    cg = probe.get("cgroup_usage") or {}
    return {
        "dds_verified": str(bool(dds.get("verified"))).lower(),
        "detector_udp_sockets": det.get("max_udp_sockets", ""),
        "publisher_udp_sockets": pub.get("max_udp_sockets", ""),
        "shm_segment_max_bytes": max(dds.get("shm_segment_sizes") or [0]) or "",
        "detector_cpu_pct": det.get("avg_cpu_percent_sampled", ""),
        "publisher_cpu_pct": pub.get("avg_cpu_percent_sampled", ""),
        "detector_nice": ",".join(str(n) for n in det.get("nice", [])),
        "cpus_allowed": ";".join(det.get("cpus_allowed", [])),
        "cgroup_memory_peak_mb": cg.get("memory_peak_mb", ""),
        "cgroup_swap_max_bytes": cg.get("max_swap_current_bytes", ""),
        "allowed_cpu_busy_max_pct": max(allowed_busy) if allowed_busy else "",
        "sibling_cpu_busy_max_pct": max(sibling_busy) if sibling_busy else "",
        "loadavg_1m_max": (probe.get("host") or {}).get("loadavg_1m_max", ""),
        "udp_rcvbuf_errors_delta": ((probe.get("host") or {}).get("udp_snmp_delta") or {}).get("RcvbufErrors", ""),
    }


def derive(row: dict[str, Any]) -> dict[str, Any]:
    service, offered, drop = _f(row.get("avg_service_ms")), _f(row.get("offered_fps")), _f(row.get("drop_rate_pct"))
    capacity = None if not service else 1000.0 / service
    rho = None if service is None or offered is None else offered * service / 1000.0
    expected = None if rho is None else 100.0 * max(0.0, 1.0 - 1.0 / rho) if rho > 0 else 0.0
    if drop is None or rho is None:
        cause = "unknown"
    elif drop == 0:
        cause = "none"
    elif rho >= 1.0:
        cause = "overload"
    else:
        cause = "below_capacity"
    return {"capacity_fps": _fmt(capacity), "utilization": _fmt(rho),
            "expected_overload_drop_pct": _fmt(expected), "drop_cause": cause}


def build_run_rows(summary_rows: list[dict[str, str]], raw_dir: Path) -> tuple[list[dict[str, Any]], list[Path]]:
    rows, probes = [], []
    for row in summary_rows:
        probe_path = raw_dir / f"{row['run_id']}.probe.json"
        probe = None
        if probe_path.is_file():
            probe = json.loads(probe_path.read_text(encoding="utf-8"))
            probes.append(probe_path)
        allowed = probe.get("probe_cpus_allowed", []) if probe else []
        out = dict(row)
        out.update(probe_fields(probe, allowed))
        out.update(derive(row))
        rows.append(out)
    return rows, probes


def _cond_key(row: dict[str, Any]) -> tuple:
    return (row["scenario"], row["model_name"], float(row["input_fps"]), int(row["qos_depth"]),
            int(row["fake_delay_ms"]))


def build_conditions(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in run_rows:
        groups.setdefault(_cond_key(row), []).append(row)
    out = []
    for key in sorted(groups):
        runs = groups[key]
        rec: dict[str, Any] = dict(zip(CONDITION_KEYS, key))
        rec["n_runs"] = len(runs)
        rec["run_ids"] = ";".join(sorted(r["run_id"] for r in runs))
        rec["all_dds_verified"] = str(all(r.get("dds_verified") == "true" for r in runs)).lower()
        rec["measurement_classes"] = ";".join(sorted({r.get("measurement_class", "") for r in runs}))
        rec["drop_causes"] = ";".join(sorted({r["drop_cause"] for r in runs}))
        for metric in METRICS:
            values = [v for v in (_f(r.get(metric)) for r in runs) if v is not None]
            rec[f"{metric}_mean"] = _fmt(mean(values)) if values else ""
            rec[f"{metric}_sd"] = _fmt(stdev(values)) if len(values) > 1 else ""
            rec[f"{metric}_min"] = _fmt(min(values)) if values else ""
            rec[f"{metric}_max"] = _fmt(max(values)) if values else ""
        out.append(rec)
    return out


# ---------------------------------------------------------------- SVG charts

def _nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    exp = 10 ** int(f"{value:e}".split("e")[1])
    for step in (1, 2, 2.5, 5, 10):
        if step * exp >= value:
            return step * exp
    return 10 * exp


def _wrap(text: str, width: int) -> list[str]:
    lines, cur = [], ""
    for part in text.split("; "):
        cand = part if not cur else f"{cur}; {part}"
        if len(cand) > width and cur:
            lines.append(cur + ";")
            cur = part
        else:
            cur = cand
    return lines + ([cur] if cur else [])


def line_chart(title: str, subtitle: str, x_label: str, y_label: str,
               series: list[dict[str, Any]], x_ticks: list[float], y_max: float | None = None,
               reference_diagonal: bool = False, log_x: bool = False) -> str:
    """series: {name, color, dash, points: [(x, mean, lo, hi, [run values])]}"""

    sub = _wrap(subtitle, 92)
    w, ml, mr, mb = 640, 64, 150, 52
    mt = 50 + 15 * len(sub)
    h = 340 + mt
    pw, ph = w - ml - mr, h - mt - mb
    all_y = [v for s in series for p in s["points"] for v in [p[3], *p[4]] if v is not None]
    ymax = y_max if y_max is not None else _nice_max(max(all_y + [1e-9]) * 1.08)
    xmin, xmax = min(x_ticks), max(x_ticks)
    pad = (xmax - xmin) * 0.05 or 1

    def sx(x: float) -> float:
        return ml + (x - xmin + pad) / (xmax - xmin + 2 * pad) * pw

    def sy(y: float) -> float:
        return mt + ph - max(0.0, min(y, ymax)) / ymax * ph

    e = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
         f'font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="12">',
         f'<rect width="{w}" height="{h}" fill="{SURFACE}"/>',
         f'<text x="{ml}" y="24" font-size="15" font-weight="600" fill="{INK}">{escape(title)}</text>',
         *[f'<text x="{ml}" y="{42 + 15 * i}" fill="{INK2}">{escape(t)}</text>' for i, t in enumerate(sub)]]
    for i in range(6):
        yv = ymax * i / 5
        e.append(f'<line x1="{ml}" x2="{ml + pw}" y1="{sy(yv):.1f}" y2="{sy(yv):.1f}" stroke="{GRID}" stroke-width="1"/>')
        e.append(f'<text x="{ml - 8}" y="{sy(yv) + 4:.1f}" text-anchor="end" fill="{INK2}">{_fmt(yv, 3)}</text>')
    for xv in x_ticks:
        e.append(f'<text x="{sx(xv):.1f}" y="{mt + ph + 18}" text-anchor="middle" fill="{INK2}">{_fmt(xv, 3)}</text>')
    e.append(f'<text x="{ml + pw / 2}" y="{h - 12}" text-anchor="middle" fill="{INK2}">{escape(x_label)}</text>')
    e.append(f'<text transform="translate(16 {mt + ph / 2}) rotate(-90)" text-anchor="middle" fill="{INK2}">{escape(y_label)}</text>')
    if reference_diagonal:
        top = min(xmax, ymax)
        e.append(f'<line x1="{sx(xmin):.1f}" y1="{sy(xmin):.1f}" x2="{sx(top):.1f}" y2="{sy(top):.1f}" '
                 f'stroke="{INK2}" stroke-width="1" stroke-dasharray="4 4"/>')
        e.append(f'<text x="{sx(top) - 4:.1f}" y="{sy(top) - 6:.1f}" text-anchor="end" fill="{INK2}">processed = offered</text>')
    legend_y = mt + 4
    label_ys: list[float] = []
    for s in series:
        pts = [p for p in s["points"] if p[1] is not None]
        dash = f' stroke-dasharray="{s["dash"]}"' if s.get("dash") else ""
        if len(pts) > 1:
            path = " ".join(f"{'M' if i == 0 else 'L'}{sx(p[0]):.1f},{sy(p[1]):.1f}" for i, p in enumerate(pts))
            e.append(f'<path d="{path}" fill="none" stroke="{s["color"]}" stroke-width="2"{dash}/>')
        for p in pts:
            x = sx(p[0])
            if p[2] is not None and p[3] is not None and p[3] > p[2]:
                e.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{sy(p[2]):.1f}" y2="{sy(p[3]):.1f}" stroke="{s["color"]}" stroke-width="1.5"/>')
            for v in p[4]:
                e.append(f'<circle cx="{x + 6:.1f}" cy="{sy(v):.1f}" r="2.5" fill="{s["color"]}" fill-opacity="0.55"/>')
            tip = f'{s["name"]} @ {_fmt(p[0], 3)}: mean {_fmt(p[1])} (runs: {", ".join(_fmt(v) for v in p[4])})'
            e.append(f'<circle cx="{x:.1f}" cy="{sy(p[1]):.1f}" r="4.5" fill="{s["color"]}" stroke="{SURFACE}" stroke-width="2">'
                     f'<title>{escape(tip)}</title></circle>')
        if pts:
            last = pts[-1]
            ly = sy(last[1]) + 4
            while any(abs(ly - other) < 13 for other in label_ys):
                ly -= 13
            label_ys.append(ly)
            e.append(f'<text x="{sx(last[0]) + 12:.1f}" y="{ly:.1f}" fill="{INK}">{escape(s["short"])}</text>')
        e.append(f'<line x1="{ml + pw + 24}" x2="{ml + pw + 44}" y1="{legend_y}" y2="{legend_y}" stroke="{s["color"]}" stroke-width="2"{dash}/>')
        e.append(f'<text x="{ml + pw + 50}" y="{legend_y + 4}" fill="{INK}">{escape(s["name"])}</text>')
        legend_y += 18
    e.append(f'<text x="{ml + pw + 24}" y="{legend_y + 10}" fill="{INK2}" font-size="11">dot = one run;</text>')
    e.append(f'<text x="{ml + pw + 24}" y="{legend_y + 24}" fill="{INK2}" font-size="11">whisker = min–max</text>')
    e.append("</svg>")
    return "\n".join(e) + "\n"


def stacked_bar_chart(title: str, subtitle: str, bars: list[tuple[str, dict[str, float]]]) -> str:
    w, ml, mr, mt, bh, gap = 760, 250, 30, 84, 16, 8
    h = mt + len(bars) * (bh + gap) + 40
    pw = w - ml - mr
    total_max = _nice_max(max(sum(v.values()) for _, v in bars) * 1.05)

    def sx(v: float) -> float:
        return v / total_max * pw

    e = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
         f'font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="12">',
         f'<rect width="{w}" height="{h}" fill="{SURFACE}"/>',
         f'<text x="16" y="24" font-size="15" font-weight="600" fill="{INK}">{escape(title)}</text>',
         f'<text x="16" y="42" fill="{INK2}">{escape(subtitle)}</text>']
    lx = 16
    for _, label, color in STAGE_COLORS:
        e.append(f'<rect x="{lx}" y="54" width="12" height="12" rx="2" fill="{color}"/>')
        e.append(f'<text x="{lx + 17}" y="64" fill="{INK}">{escape(label)}</text>')
        lx += 30 + 7 * len(label)
    for i in range(6):
        v = total_max * i / 5
        x = ml + sx(v)
        e.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{mt - 6}" y2="{h - 34}" stroke="{GRID}"/>')
        e.append(f'<text x="{x:.1f}" y="{h - 20}" text-anchor="middle" fill="{INK2}">{_fmt(v, 3)}</text>')
    e.append(f'<text x="{ml + pw / 2}" y="{h - 4}" text-anchor="middle" fill="{INK2}">mean latency component across runs (ms)</text>')
    for i, (label, parts) in enumerate(bars):
        y = mt + i * (bh + gap)
        e.append(f'<text x="{ml - 8}" y="{y + bh - 4}" text-anchor="end" fill="{INK}">{escape(label)}</text>')
        x = ml
        for key, name, color in STAGE_COLORS:
            v = parts.get(key, 0.0)
            if v <= 0:
                continue
            width = max(sx(v) - 2, 0.5)
            e.append(f'<rect x="{x:.1f}" y="{y}" width="{width:.1f}" height="{bh}" rx="2" fill="{color}">'
                     f'<title>{escape(f"{label}: {name} {v:.1f} ms")}</title></rect>')
            x += sx(v)
        e.append(f'<text x="{x + 4:.1f}" y="{y + bh - 4}" fill="{INK2}">{sum(parts.values()):.0f}</text>')
    e.append("</svg>")
    return "\n".join(e) + "\n"


def _points(conds: list[dict[str, Any]], runs: list[dict[str, Any]], scenario: str, model: str,
            x_field: str, metric: str, **fixed: Any) -> list[tuple]:
    pts = []
    for c in conds:
        if c["scenario"] != scenario or c["model_name"] != model:
            continue
        if any(c[k] != v for k, v in fixed.items()):
            continue
        run_vals = [v for v in (_f(r.get(metric)) for r in runs
                                if _cond_key(r) == (c["scenario"], c["model_name"], c["input_fps"],
                                                    c["qos_depth"], c["fake_delay_ms"])) if v is not None]
        pts.append((float(c[x_field]), _f(c[f"{metric}_mean"]), _f(c[f"{metric}_min"]),
                    _f(c[f"{metric}_max"]), run_vals))
    return sorted(pts)


SHORT = {"mobilevit_xxs": "XXS", "mobilevit_s": "S"}


def write_figures(conds: list[dict[str, Any]], runs: list[dict[str, Any]], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    models = [m for m in MODEL_COLORS if any(c["model_name"] == m for c in conds)]
    written: list[Path] = []
    n_note = "constrained: CPU 12,14 / MemoryMax 4G / swap 0; Fast DDS SHM profile; mean of independent runs"

    def save(name: str, svg: str) -> None:
        path = out_dir / name
        path.write_text(svg, encoding="utf-8")
        written.append(path)

    def model_series(scenario: str, x_field: str, metric: str, **fixed: Any) -> list[dict[str, Any]]:
        return [{"name": m, "short": SHORT.get(m, m), "color": MODEL_COLORS[m], "dash": "",
                 "points": _points(conds, runs, scenario, m, x_field, metric, **fixed)} for m in models]

    fps_x = sorted({c["input_fps"] for c in conds if c["scenario"] == "fps_sweep"})
    if fps_x:
        save("fps_throughput.svg", line_chart(
            "Processed vs offered frame rate", n_note, "offered input rate (FPS, QoS depth 5, no delay)",
            "processed FPS", model_series("fps_sweep", "input_fps", "processed_fps"), fps_x,
            reference_diagonal=True))
        save("fps_drop_rate.svg", line_chart(
            "Drop rate vs input rate", n_note, "input rate (FPS)", "dropped frames (%)",
            model_series("fps_sweep", "input_fps", "drop_rate_pct"), fps_x, y_max=100))
        lat_series = []
        for m in models:
            for metric, dash, lab in (("p50_latency_ms", "", "P50"), ("p99_latency_ms", "5 4", "P99")):
                lat_series.append({"name": f"{m} {lab}", "short": f"{SHORT.get(m, m)} {lab}",
                                   "color": MODEL_COLORS[m], "dash": dash,
                                   "points": _points(conds, runs, "fps_sweep", m, "input_fps", metric)})
        save("fps_latency.svg", line_chart(
            "End-to-end latency vs input rate", n_note + "; deadline 100 ms", "input rate (FPS)",
            "latency (ms)", lat_series, fps_x))
    qos_x = sorted({float(c["qos_depth"]) for c in conds if c["scenario"] == "qos_sweep"})
    if qos_x:
        save("qos_latency_p50.svg", line_chart(
            "P50 latency vs subscriber queue depth (20 FPS)", n_note, "KEEP_LAST depth",
            "P50 latency (ms)", model_series("qos_sweep", "qos_depth", "p50_latency_ms"), qos_x))
        save("qos_drop_rate.svg", line_chart(
            "Drop rate vs subscriber queue depth (20 FPS)", n_note, "KEEP_LAST depth",
            "dropped frames (%)", model_series("qos_sweep", "qos_depth", "drop_rate_pct"), qos_x, y_max=100))
    ov_x = sorted({float(c["fake_delay_ms"]) for c in conds if c["scenario"] == "overload_sweep"})
    if ov_x:
        save("overload_p50_latency.svg", line_chart(
            "P50 latency vs injected delay (20 FPS, depth 5)", n_note, "artificial delay per frame (ms)",
            "P50 latency (ms)", model_series("overload_sweep", "fake_delay_ms", "p50_latency_ms"), ov_x))
        save("overload_effective_miss.svg", line_chart(
            "Effective miss rate vs injected delay (20 FPS)", n_note + "; (misses + drops) / frames",
            "artificial delay per frame (ms)", "effective miss rate (%)",
            model_series("overload_sweep", "fake_delay_ms", "effective_miss_rate_pct"), ov_x, y_max=100))
        save("overload_drop_rate.svg", line_chart(
            "Drop rate vs injected delay (20 FPS)", n_note, "artificial delay per frame (ms)",
            "dropped frames (%)", model_series("overload_sweep", "fake_delay_ms", "drop_rate_pct"), ov_x, y_max=100))
    bars = []
    for c in conds:
        label = (f"{SHORT.get(c['model_name'], c['model_name'])} {c['scenario'].split('_')[0]} "
                 f"{_fmt(c['input_fps'], 3)}fps q{c['qos_depth']} d{c['fake_delay_ms']}")
        bars.append((label, {k: _f(c[f"{k}_mean"]) or 0.0 for k, _, _ in STAGE_COLORS}))
    if bars:
        save("latency_breakdown.svg", stacked_bar_chart(
            "Where the end-to-end latency goes", "transport = publish → callback start (DDS + executor queue wait); "
            "artificial delay is injected sleep, not inference", bars))
    return written


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for k in row:
            if k not in fields:
                fields.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--summary", required=True, help="analyze_runtime summary CSV (one row per run)")
    p.add_argument("--raw-dir", required=True, help="directory with <run_id>.probe.json")
    p.add_argument("--runs-output", required=True)
    p.add_argument("--conditions-output", required=True)
    p.add_argument("--figures-dir", default="")
    p.add_argument("--run-tag-filter", default="", help="only runs whose run_id contains this text")
    args = p.parse_args(argv)

    summary = Path(args.summary)
    with summary.open(encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if args.run_tag_filter in r["run_id"]]
    if not rows:
        raise SystemExit("no summary rows")
    run_rows, probes = build_run_rows(rows, Path(args.raw_dir))
    conds = build_conditions(run_rows)
    _write_csv(Path(args.runs_output), run_rows)
    _write_csv(Path(args.conditions_output), conds)
    figures = write_figures(conds, run_rows, Path(args.figures_dir)) if args.figures_dir else []
    manifest_path = Path(args.conditions_output).with_suffix(".manifest.json")
    summary_manifest = summary.with_suffix(".manifest.json")
    inputs = [summary] + ([summary_manifest] if summary_manifest.is_file() else []) + probes
    manifest = {
        "schema": "ros2_baseline_aggregate/v1",
        "run_tag_filter": args.run_tag_filter,
        "inputs": [{"path": str(x), "sha256": sha256_file(x)} for x in inputs],
        "outputs": [{"path": str(x), "sha256": sha256_file(x)}
                    for x in [Path(args.runs_output), Path(args.conditions_output), *figures]],
        "runs": len(run_rows), "conditions": len(conds),
        "runs_without_probe": [r["run_id"] for r in run_rows if r.get("dds_verified") == ""],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{len(run_rows)} runs, {len(conds)} conditions, {len(figures)} figures; manifest {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
