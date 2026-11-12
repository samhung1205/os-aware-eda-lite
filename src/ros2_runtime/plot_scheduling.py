"""SVG figures for the Phase 3 / Batch 2 formal scheduling benchmark (standard library only).

    python3 -m src.ros2_runtime.plot_scheduling --runs results/csv/ros2_phase3_formal_runs.csv \
        --paired results/csv/ros2_phase3_formal_paired.csv \
        --dynamic-arms results/csv/ros2_phase3_formal_dynamic_arms.csv \
        --figures-dir results/figures/ros2_phase3_formal

Figures (each mark has an SVG <title> tooltip; light / dark via prefers-color-scheme):

- ``effective_miss_by_condition.svg``: small multiples, one panel per condition; bar =
  mean effective miss across runs, dots = individual runs (the run is the unit);
- ``on_time_fps_by_condition.svg``: same layout for on-time FPS;
- ``paired_<condition>.svg``: forest plot of within-block differences (mean, 95 % t-interval,
  per-block dots) for the pre-registered comparisons;
- ``dynamic_phases.svg``: effective miss per phase of the dynamic-rate condition, per arm.

Colours: the documented reference categorical palette in fixed arm order (identity
follows the arm in every figure).
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from statistics import mean
from typing import Any

ARMS = ["legacy_q1", "legacy_q5", "fifo_c5_q10", "latest_q10", "guard_c5_q10", "adaptive_c5_q10"]
ARM_LABEL = {"legacy_q1": "Legacy d1", "legacy_q5": "Legacy d5", "fifo_c5_q10": "FIFO",
             "latest_q10": "Latest", "guard_c5_q10": "Deadline-Guard", "adaptive_c5_q10": "Adaptive"}
LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"]
COMPARISONS = [  # (arm, reference) pre-registered in report/PHASE3_BATCH2_RESULT.md §1
    ("adaptive_c5_q10", "latest_q10"), ("adaptive_c5_q10", "guard_c5_q10"),
    ("guard_c5_q10", "latest_q10"), ("latest_q10", "legacy_q1"), ("adaptive_c5_q10", "legacy_q1"),
]

STYLE = """<style>
.s{fill:#fcfcfb}.t1{fill:#0b0b0b}.t2{fill:#52514e}.mu{fill:#898781}.g{stroke:#e1e0d9}.ax{stroke:#c3c2b7}
%s
.dot{stroke:#fcfcfb;stroke-width:1.5}.rd{fill:#fcfcfb;stroke:#0b0b0b}
@media (prefers-color-scheme: dark){.s{fill:#1a1a19}.t1{fill:#f0efec}.t2{fill:#c3c2b7}.g{stroke:#2c2c2a}
.ax{stroke:#383835}%s.dot{stroke:#1a1a19}.rd{fill:#1a1a19;stroke:#f0efec}}
text{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums}
</style>"""


def _style() -> str:
    light = "".join(f".a{i}{{fill:{c};stroke:{c}}}" for i, c in enumerate(LIGHT))
    dark = "".join(f".a{i}{{fill:{c};stroke:{c}}}" for i, c in enumerate(DARK))
    return STYLE % (light, dark)


def _f(v: Any) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _group_titles(svg: str) -> str:
    """``<circle ..><title>t</title></circle>`` -> ``<g><title>t</title><circle ../></g>``.

    Same tooltip in browsers; some non-browser SVG renderers (ImageMagick MSVG) skip a
    circle that has a child element.
    """

    return re.sub(r"<circle([^>]*)><title>(.*?)</title></circle>", r"<g><title>\2</title><circle\1/></g>", svg)


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _read(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def condition_label(row: dict[str, str]) -> str:
    model = "S" if row["model_name"].endswith("_s") else "XXS"
    if row.get("scenario") == "sched_dynamic":
        sched = row.get("fps_schedule", "")
        rates = "-".join(f"{float(seg.split('@')[0]):g}" for seg in sched.split(",") if "@" in seg)
        return f"{model} dynamic {rates} FPS" if rates else f"{model} dynamic"
    fps = f"{float(row['input_fps']):g}"
    delay = int(float(row["fake_delay_ms"]))
    return f"{model} {fps} FPS" + (f" +{delay} ms" if delay else "")


def _nice_max(v: float) -> float:
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500):
        if v <= step * 5:
            return step * 5 if v > step * 4 else step * max(1, -(-v // step))
    return v


def _ticks(vmax: float) -> list[float]:
    step = vmax / 4
    return [step * i for i in range(5)]


def _legend(x: float, y: float) -> str:
    out, cx = [], x
    for i, arm in enumerate(ARMS):
        out.append(f'<rect class="a{i}" x="{cx}" y="{y - 9}" width="10" height="10" rx="2"/>'
                   f'<text class="t2" x="{cx + 14}" y="{y}" font-size="12">{ARM_LABEL[arm]}</text>')
        cx += 24 + 7.2 * len(ARM_LABEL[arm])
    return "".join(out)


def small_multiples(runs: list[dict[str, str]], metric: str, title: str, unit: str) -> str:
    conds: dict[str, dict[str, list[float]]] = {}
    for r in runs:
        v = _f(r.get(metric))
        if v is not None:
            conds.setdefault(condition_label(r), {}).setdefault(r["scheduler_arm"], []).append(v)
    order = sorted(conds, key=lambda c: (("dynamic" in c), "XXS" in c, float(c.split()[1]) if "dynamic" not in c else 0))
    cols = 3
    pw, ph = 300, 210
    rows_n = -(-len(order) // cols)
    width, height = 40 + cols * pw, 80 + rows_n * (ph + 40)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(title)}">', _style(),
             f'<rect class="s" width="{width}" height="{height}"/>',
             f'<text class="t1" x="20" y="28" font-size="16" font-weight="600">{_esc(title)}</text>',
             _legend(20, 54)]
    for idx, cond in enumerate(order):
        ox, oy = 20 + (idx % cols) * pw, 80 + (idx // cols) * (ph + 40)
        data = conds[cond]
        vmax = _nice_max(max((max(v) for v in data.values()), default=1) or 1)
        px, py, pwid, phei = ox + 40, oy + 24, pw - 60, ph - 50
        parts.append(f'<text class="t1" x="{ox}" y="{oy + 12}" font-size="13" font-weight="600">{_esc(cond)}</text>')
        for t in _ticks(vmax):
            y = py + phei - t / vmax * phei
            parts.append(f'<line class="g" x1="{px}" x2="{px + pwid}" y1="{y:.1f}" y2="{y:.1f}" stroke-width="1"/>'
                         f'<text class="mu" x="{px - 6}" y="{y + 4:.1f}" font-size="10" text-anchor="end">{t:g}</text>')
        slot = pwid / len(ARMS)
        for i, arm in enumerate(ARMS):
            vals = data.get(arm, [])
            if not vals:
                continue
            m = mean(vals)
            bw = slot - 8
            x = px + i * slot + 4
            h = max(0.0, m / vmax * phei)
            y = py + phei - h
            tip = f"{cond} · {ARM_LABEL[arm]}: mean {m:.2f}{unit} (n={len(vals)}; runs " + \
                  ", ".join(f"{v:.1f}" for v in vals) + ")"
            parts.append(f'<path class="a{i}" fill-opacity="0.35" stroke-width="0" '
                         f'd="M{x:.1f},{py + phei:.1f} V{y + min(4, h):.1f} q0,-{min(4, h):.1f} {min(4, h):.1f},-{min(4, h):.1f} '
                         f'H{x + bw - min(4, h):.1f} q{min(4, h):.1f},0 {min(4, h):.1f},{min(4, h):.1f} V{py + phei:.1f} Z">'
                         f'<title>{_esc(tip)}</title></path>')
            for j, v in enumerate(vals):
                dx = x + bw / 2 + (j - (len(vals) - 1) / 2) * 5
                parts.append(f'<circle class="rd" fill="#fcfcfb" stroke="#0b0b0b" stroke-width="1.2" '
                             f'cx="{dx:.1f}" cy="{py + phei - v / vmax * phei:.1f}" r="3">'
                             f'<title>{_esc(f"{ARM_LABEL[arm]} run {j + 1}: {v:.2f}{unit}")}</title></circle>')
        parts.append(f'<line class="ax" x1="{px}" x2="{px + pwid}" y1="{py + phei}" y2="{py + phei}" stroke-width="1"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def forest(paired: list[dict[str, str]], runs: list[dict[str, str]], cond: str, metric: str,
           title: str, unit: str) -> str:
    rows = []
    for arm, ref in COMPARISONS:
        rec = next((p for p in paired if condition_label(p) == cond and p["scheduler_arm"] == arm
                    and p["reference_arm"] == ref), None)
        if rec is None:
            continue
        # per-block differences for the dots
        blocks: dict[str, dict[str, float]] = {}
        for r in runs:
            if condition_label(r) == cond and r["scheduler_arm"] in (arm, ref):
                v = _f(r.get(metric))
                if v is not None:
                    blocks.setdefault(r["run_tag"], {})[r["scheduler_arm"]] = v
        dots = [b[arm] - b[ref] for b in blocks.values() if arm in b and ref in b]
        rows.append((f"{ARM_LABEL[arm]} − {ARM_LABEL[ref]}", _f(rec[f"d_{metric}_mean"]),
                     _f(rec.get(f"d_{metric}_ci95_lo")), _f(rec.get(f"d_{metric}_ci95_hi")), dots, rec["n_blocks"]))
    span = max([abs(v) for r in rows for v in (r[1], r[2], r[3], *r[4]) if v is not None] + [1.0])
    span = _nice_max(span)
    width, rh = 760, 34
    height = 90 + rh * len(rows) + 30
    lx, px, pw = 20, 250, 470
    def X(v): return px + (v + span) / (2 * span) * pw
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(title)}">', _style(),
             f'<rect class="s" width="{width}" height="{height}"/>',
             f'<text class="t1" x="{lx}" y="28" font-size="16" font-weight="600">{_esc(title)}</text>',
             f'<text class="t2" x="{lx}" y="48" font-size="12">mean within-block difference, 95% t-interval '
             f'(line), individual blocks (dots); left of 0 = first arm lower</text>']
    top = 70
    for t in (-span, -span / 2, 0, span / 2, span):
        parts.append(f'<line class="{"ax" if t == 0 else "g"}" x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{top}" '
                     f'y2="{top + rh * len(rows)}" stroke-width="1"/>'
                     f'<text class="mu" x="{X(t):.1f}" y="{top + rh * len(rows) + 16}" font-size="10" '
                     f'text-anchor="middle">{t:+g}{unit}</text>')
    for k, (label, m, lo, hi, dots, n) in enumerate(rows):
        y = top + rh * k + rh / 2
        parts.append(f'<text class="t1" x="{lx}" y="{y + 4:.1f}" font-size="12">{_esc(label)} (n={n})</text>')
        if lo is not None and hi is not None:
            parts.append(f'<line class="a0" stroke="#2a78d6" x1="{X(lo):.1f}" x2="{X(hi):.1f}" y1="{y:.1f}" y2="{y:.1f}" stroke-width="2"/>')
        for d in dots:
            parts.append(f'<circle class="mu" fill="#898781" cx="{X(d):.1f}" cy="{y + 9:.1f}" r="3" fill-opacity="0.7">'
                         f'<title>block difference {d:+.2f}{unit}</title></circle>')
        if m is not None:
            tip = f"{label}: mean {m:+.2f}{unit}" + (f", 95% CI [{lo:+.2f}, {hi:+.2f}]" if lo is not None else "")
            parts.append(f'<circle class="a0 dot" fill="#2a78d6" stroke="#fcfcfb" stroke-width="1.5" '
                         f'cx="{X(m):.1f}" cy="{y:.1f}" r="5"><title>{_esc(tip)}</title></circle>')
    parts.append("</svg>")
    return "\n".join(parts)


def dynamic_chart(arms_rows: list[dict[str, str]], title: str) -> str:
    phases = sorted({int(r["phase"]) for r in arms_rows})
    target = {int(r["phase"]): r["target_fps"] for r in arms_rows}
    data = {(r["scheduler_arm"], int(r["phase"])): r for r in arms_rows}
    vmax = _nice_max(max([_f(r["effective_miss_pct_max"]) or 0 for r in arms_rows] + [1]))
    width, height = 820, 330
    px, py, pw, ph = 60, 80, 740, 200
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(title)}">', _style(),
             f'<rect class="s" width="{width}" height="{height}"/>',
             f'<text class="t1" x="20" y="28" font-size="16" font-weight="600">{_esc(title)}</text>', _legend(20, 54)]
    for t in _ticks(vmax):
        y = py + ph - t / vmax * ph
        parts.append(f'<line class="g" x1="{px}" x2="{px + pw}" y1="{y:.1f}" y2="{y:.1f}" stroke-width="1"/>'
                     f'<text class="mu" x="{px - 6}" y="{y + 4:.1f}" font-size="10" text-anchor="end">{t:g}%</text>')
    gw = pw / len(phases)
    for p in phases:
        gx = px + p * gw
        parts.append(f'<text class="t2" x="{gx + gw / 2:.1f}" y="{py + ph + 18}" font-size="12" text-anchor="middle">'
                     f'phase {p + 1}: {float(target[p]):g} FPS</text>')
        slot = (gw - 30) / len(ARMS)
        for i, arm in enumerate(ARMS):
            r = data.get((arm, p))
            if not r:
                continue
            m = _f(r["effective_miss_pct_mean"]) or 0.0
            lo, hi = _f(r["effective_miss_pct_min"]), _f(r["effective_miss_pct_max"])
            x = gx + 15 + i * slot + 1
            h = m / vmax * ph
            tip = f"phase {p + 1} · {ARM_LABEL[arm]}: mean {m:.2f}% (min {lo:.2f}, max {hi:.2f}, n={r['n_runs']})"
            parts.append(f'<rect class="a{i}" x="{x:.1f}" y="{py + ph - h:.1f}" width="{slot - 2:.1f}" '
                         f'height="{h:.1f}" rx="2" stroke-width="0"><title>{_esc(tip)}</title></rect>')
            if lo is not None and hi is not None:
                cx = x + (slot - 2) / 2
                parts.append(f'<line class="t2" style="stroke:currentColor" x1="{cx:.1f}" x2="{cx:.1f}" '
                             f'y1="{py + ph - lo / vmax * ph:.1f}" y2="{py + ph - hi / vmax * ph:.1f}" '
                             f'stroke="#898781" stroke-width="1.5"/>')
    parts.append(f'<line class="ax" x1="{px}" x2="{px + pw}" y1="{py + ph}" y2="{py + ph}" stroke-width="1"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", required=True)
    parser.add_argument("--paired", required=True)
    parser.add_argument("--dynamic-arms", default="")
    parser.add_argument("--figures-dir", required=True)
    args = parser.parse_args(argv)
    runs, paired = _read(args.runs), _read(args.paired)
    out = Path(args.figures_dir)
    out.mkdir(parents=True, exist_ok=True)
    figures = {
        "effective_miss_by_condition.svg": small_multiples(
            runs, "effective_miss_rate_pct", "Effective miss rate (%) per arm — mean across runs, dots = runs", "%"),
        "on_time_fps_by_condition.svg": small_multiples(
            runs, "on_time_fps", "On-time FPS per arm — mean across runs, dots = runs", " FPS"),
    }
    for cond in sorted({condition_label(r) for r in paired}):
        slug = cond.lower().replace(" ", "_").replace("+", "d").replace("@", "x").replace(",", "-")
        figures[f"paired_{slug}.svg"] = forest(
            paired, runs, cond, "effective_miss_rate_pct",
            f"{cond}: paired difference in effective miss (pp)", " pp")
    if args.dynamic_arms:
        figures["dynamic_phases.svg"] = dynamic_chart(
            _read(args.dynamic_arms), "Dynamic load S 10-20-10 FPS: effective miss (%) per phase (bar = mean, line = min–max)")
    for name, svg in figures.items():
        (out / name).write_text(_group_titles(svg) + "\n", encoding="utf-8")
    print(f"{len(figures)} figures -> {out}")


if __name__ == "__main__":
    main()
