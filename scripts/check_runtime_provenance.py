"""Verify the measured-data chain: raw ROS2 CSVs -> summary -> OS profiles -> simulation CSVs.

    python3 scripts/check_runtime_provenance.py [--root REPO]

Exit status:
    0  VERIFIED  raw CSVs + run metadata -> summary manifest -> runtime_os_profiles.json
                 all hash-match, and no simulation provenance sidecar is stale
    1  BLOCKED   a link is missing (e.g. no raw ROS2 data in the repository); needs a real
                 ROS2 run, never synthetic data
    2  BROKEN    files exist but do not match their recorded hashes, a sidecar is stale, or
                 the measured profiles fail verification

Legacy/example OS profile files are reported for information; they never make the
check pass. Standard library only; read-only.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.provenance import (  # noqa: E402
    STATUS_VERIFIED,
    assess_os_profile_payload,
    check_file_record,
    read_json,
    resolve_ref,
    summary_manifest_path,
    verify_summary_manifest,
)

RAW_DIR = Path("results/raw/ros2")
SUMMARY_CSV = Path("results/csv/ros2_runtime_summary.csv")
OS_PROFILES = Path("experiments/eda_lite/runtime_os_profiles.json")
INFO_PROFILE_FILES = (
    Path("experiments/eda_lite/runtime_os_profiles.legacy_unverified.json"),
    Path("experiments/eda_lite/runtime_os_profiles.example.json"),
)
SIDECAR_GLOB = "results/csv/*.provenance.json"
ROS2_FIGURES = Path("results/figures/ros2")

VERIFIED, BLOCKED, BROKEN = 0, 1, 2
_LABEL = {VERIFIED: "VERIFIED", BLOCKED: "BLOCKED", BROKEN: "BROKEN"}


def check(root: Path) -> tuple[int, list[str]]:
    lines: list[str] = []
    blocked: list[str] = []
    broken: list[str] = []

    # 1. raw ROS2 data
    raw_dir = root / RAW_DIR
    detector = sorted(p for p in raw_dir.glob("*.csv") if not p.name.endswith(".publisher.csv"))
    publisher = sorted(raw_dir.glob("*.publisher.csv"))
    meta = sorted(raw_dir.glob("*.meta.json"))
    if detector:
        lines.append(f"OK      raw: {len(detector)} detector CSV, {len(publisher)} publisher logs, "
                     f"{len(meta)} run metadata files under {RAW_DIR}")
    else:
        blocked.append(f"no raw ROS2 detector CSVs under {RAW_DIR}")
        lines.append(f"MISSING raw: no detector CSVs under {RAW_DIR}")

    # 2. runtime summary + manifest
    summary = root / SUMMARY_CSV
    manifest = summary_manifest_path(summary)
    if not summary.is_file():
        blocked.append(f"{SUMMARY_CSV} missing")
        lines.append(f"MISSING summary: {SUMMARY_CSV}")
    elif not manifest.is_file():
        blocked.append(f"{manifest.relative_to(root)} missing (summary cannot be traced to raw CSVs)")
        lines.append(f"MISSING summary manifest: {manifest.relative_to(root)}")
    else:
        problems = verify_summary_manifest(manifest)
        if problems:
            broken.extend(f"summary manifest: {p}" for p in problems)
            lines.extend(f"BROKEN  summary manifest: {p}" for p in problems)
        else:
            lines.append(f"OK      summary {SUMMARY_CSV} verifies against raw inputs")

    # 3. measured OS profiles
    profiles = root / OS_PROFILES
    if not profiles.is_file():
        blocked.append(f"{OS_PROFILES} missing (no verified measured OS profiles)")
        lines.append(f"MISSING measured OS profiles: {OS_PROFILES}")
    else:
        payload = read_json(profiles)
        status, reasons = assess_os_profile_payload(payload, profiles)
        if status == STATUS_VERIFIED:
            recorded = resolve_ref(payload["metadata"]["source_summary"]["path"], profiles.parent)
            if recorded.resolve() != summary.resolve():
                broken.append(f"{OS_PROFILES} was built from {recorded}, not {SUMMARY_CSV}")
            lines.append(f"OK      measured OS profiles: {OS_PROFILES} "
                         f"({len(payload.get('os_profiles', []))} profiles, verified)")
        else:
            broken.extend(f"{OS_PROFILES}: {r}" for r in reasons)
            lines.append(f"BROKEN  {OS_PROFILES}: status={status}")
            lines.extend(f"          - {r}" for r in reasons)

    # 4. informational profile files (never count as measured)
    for path in INFO_PROFILE_FILES:
        full = root / path
        if full.is_file():
            payload = read_json(full)
            status, reasons = assess_os_profile_payload(payload, full)
            lines.append(f"INFO    {path}: {len(payload.get('os_profiles', []))} profiles, "
                         f"status={status.upper()} (not measured evidence)")
            lines.extend(f"          - {r}" for r in reasons[:1])

    # 5. simulation sidecars: detect stale CSVs / changed OS profile files
    for sidecar in sorted(root.glob(SIDECAR_GLOB)):
        record = read_json(sidecar)
        base = sidecar.parent
        problems = check_file_record(record.get("output"), base, "output CSV")
        problems += check_file_record(record.get("config"), base, "config")
        for item in record.get("model_profiles") or []:
            problems += check_file_record(item, base, "model profile")
        source = record.get("os_profile_file")
        if source:
            problems += check_file_record(source, base, "OS profile file")
        name = sidecar.relative_to(root)
        status = (source or {}).get("provenance_status", "builtin/inline only")
        if problems:
            broken.extend(f"{name}: {p}" for p in problems)
            lines.append(f"STALE   {name}: " + "; ".join(problems))
        else:
            lines.append(f"OK      {name}: rows={record.get('rows')} os_profile_source={status}")

    # 6. ROS2 figures without a verified summary
    figures = sorted((root / ROS2_FIGURES).glob("*.svg"))
    if figures and (blocked or broken):
        lines.append(f"INFO    {len(figures)} figures under {ROS2_FIGURES} have no verifiable source "
                     "data: UNVERIFIED")

    if broken:
        code = BROKEN
    elif blocked:
        code = BLOCKED
    else:
        code = VERIFIED
    lines.append(f"STATUS: {_LABEL[code]}")
    for reason in broken + blocked:
        lines.append(f"  - {reason}")
    if code == BLOCKED:
        lines.append("Runtime-derived values are not verifiable measured results. Re-run the ROS2 "
                     "experiments on real hardware (see report/runtime_result_provenance.md); do not "
                     "substitute synthetic data.")
    return code, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(REPO), help="Repository root (default: this repo).")
    args = parser.parse_args(argv)
    code, lines = check(Path(args.root).resolve())
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
