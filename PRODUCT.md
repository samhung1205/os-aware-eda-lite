# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary (confirmed 2026-11-17): visitors arriving from a résumé, README or GitHub profile link to the GitHub Pages site — recruiters and software / systems engineers. They open it alone on a laptop, have a few minutes, and judge two things: what was built, and how rigorous the work is.

Secondary: the course instructor and classmates of the Operating Systems final project, and reviewers who check individual numbers against the provenance chain.

## Product Purpose

OS-Aware Edge AI Runtime is an Operating Systems final project. The dashboard presents its measured results: a ROS 2 runtime baseline (75 runs) and a frame-scheduling A/B benchmark (102 runs) for MobileViT on a constrained Linux host, plus a separate page for the EDA-Lite layer-fusion simulator.

Success: within a few minutes a first-time visitor can say what the project measured, when deadline-aware frame dropping helps and when it does not, and that every number traces back to verified raw runs.

## Positioning

A deadline-aware frame scheduler (Deadline-Guard) predicts, before spending inference, whether a queued frame can still finish inside the 100 ms deadline (frame age + estimated service time) and skips the ones that cannot. The finding is a regime boundary, not a blanket win: dropping beats Latest-Frame only when inter-arrival + service time exceeds the deadline. Every figure is backed by a SHA-256 provenance chain from raw per-frame logs to the dashboard bundle.

## Operating Context

- Static site in `dashboard/`, published to GitHub Pages from `main` after both provenance gates pass; also opens directly from disk and through `scripts/serve_dashboard.sh` (127.0.0.1 only).
- Two pages: `index.html` (views: Overview, Baseline, Scheduling, Mechanism, Evidence; hash-routed) and `simulation.html` (EDA-Lite estimates).
- Data arrives as one generated bundle (`dashboard/data/dashboard_data.js`, built by `src/dashboard/build_data.py`); the frontend never edits numbers.

## Capabilities and Constraints

- No build step, no framework, no external resources (tests enforce it); all paths relative and inside `dashboard/`.
- English is the default language; Traditional Chinese through the toggle or `?lang=zh-TW`. English technical terms stay in the Chinese text.
- Light and dark colour schemes follow the system setting.
- Measured ROS 2 results and EDA-Lite simulation estimates must stay visibly separate; estimates are always labelled as estimates.
- Deadline-Guard and Adaptive are reported side by side everywhere (the utilisation switch adds nothing measurable).
- Cross-architecture comparisons are flagged; pilot, legacy-unverified and example inputs never appear.
- Latency-only benchmark with random-init weights on one host: no accuracy, energy or hardware claims.
- Tests pin the information architecture (five views, `href="#<view>"`, `id="view-<view>"`, `simulation.html` link, "Estimates" / "Simulation estimates" wording, a "not found" empty state).

## Brand Commitments

- Name: "OS-Aware Edge AI Runtime" for the project; "EDA-Lite" only for the simulator component.
- Self-hosted open-source web fonts are allowed (confirmed); Chinese text uses system fonts.

## Evidence on Hand

- 177 constrained, provenance-verified runs (75 baseline + 102 formal A/B) in `results/raw/`; aggregate tables in `results/csv/`.
- Architecture diagrams `dashboard/assets/architecture.svg` and `architecture_zh.svg`.
- Research write-up in `docs/RESEARCH_REPORT.md`; data chain in `docs/DATA_PROVENANCE.md`.
- No photographs, logos, testimonials or hardware energy measurements exist; none may be invented.

## Product Principles

1. The finding leads: the regime boundary is shown before anything else.
2. Measured and estimated never share a visual voice.
3. Every claim on screen is a number from the bundle, with its uncertainty.
4. A newcomer can follow it; an expert can audit it.
5. Limits are stated as plainly as results.

## Accessibility & Inclusion

Keyboard-reachable charts and controls, visible focus, a skip link, WCAG AA text contrast in both colour schemes, `prefers-reduced-motion` honoured (already present; must be kept).
