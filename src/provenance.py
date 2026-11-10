"""Provenance helpers for the measured-data chain.

    raw ROS2 CSVs (+ publisher logs + <run_id>.meta.json)
      -> results/csv/ros2_runtime_summary.csv  (+ .manifest.json: input hashes)
      -> experiments/eda_lite/runtime_os_profiles.json  (metadata: summary hash)
      -> EDA-Lite simulation CSV  (+ .provenance.json: profile-file hash)

Every link records the SHA-256 of the files it was built from, so a later step
can verify that its inputs still exist and are unchanged. Paths inside a JSON
record are stored relative to the directory of that JSON file.

Standard library only. Nothing here fabricates or repairs data: a link that
cannot be verified is reported, never assumed.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable

SUMMARY_MANIFEST_SCHEMA = "ros2_runtime_summary_manifest/v1"
OS_PROFILE_SCHEMA = "eda_lite_os_profiles/v2"
SIMULATION_PROVENANCE_SCHEMA = "eda_lite_simulation_provenance/v1"

# Provenance status of an OS profile source (also written per simulation row
# in the ``os_profile_provenance`` column).
STATUS_VERIFIED = "verified"      # measured, full hash chain back to raw CSVs checks out
STATUS_UNVERIFIED = "unverified"  # runtime-derived but the chain is missing or broken
STATUS_EXAMPLE = "example"        # illustrative values, never measured
STATUS_BUILTIN = "builtin"        # pure / normal / high_latency / high_memory_pressure
STATUS_INLINE = "inline"          # defined inline in a simulation config

# Run-level measurement classes written by src.ros2_runtime.run_metadata.
CLASS_CONSTRAINED = "constrained"                    # every requested limit verified in effect
CLASS_UNCONSTRAINED = "unconstrained"                # no limit requested
CLASS_CONSTRAINT_UNVERIFIED = "constraint_unverified"  # requested, could not be verified
CLASS_CONSTRAINT_FAILED = "constraint_failed"        # requested, verified NOT in effect
CLASS_UNKNOWN = "unknown"                            # no run metadata at all
VALID_MEASUREMENT_CLASSES = {CLASS_CONSTRAINED, CLASS_UNCONSTRAINED}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_ref(path: str | Path, base_dir: str | Path) -> str:
    """Path of ``path`` relative to ``base_dir`` in POSIX form."""

    return Path(os.path.relpath(Path(path).resolve(), Path(base_dir).resolve())).as_posix()


def resolve_ref(ref: str, base_dir: str | Path) -> Path:
    path = Path(ref)
    return path if path.is_absolute() else (Path(base_dir) / path)


def file_record(path: str | Path, base_dir: str | Path, **extra: Any) -> dict[str, Any]:
    path = Path(path)
    return {"path": relative_ref(path, base_dir), "sha256": sha256_file(path), **extra}


def check_file_record(record: Any, base_dir: str | Path, label: str) -> list[str]:
    """Return problems with a ``{path, sha256}`` record (empty list = OK)."""

    if not isinstance(record, dict) or not record.get("path") or not record.get("sha256"):
        return [f"{label}: no path/sha256 recorded"]
    path = resolve_ref(str(record["path"]), base_dir)
    if not path.is_file():
        return [f"{label}: {record['path']} is missing"]
    actual = sha256_file(path)
    if actual != record["sha256"]:
        return [f"{label}: {record['path']} changed (sha256 {actual[:12]} != recorded {str(record['sha256'])[:12]})"]
    return []


def git_state(cwd: str | Path | None = None) -> dict[str, Any]:
    """Current git commit and whether the work tree has uncommitted changes."""

    def _git(*args: str) -> str | None:
        try:
            proc = subprocess.run(
                ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10, check=False
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout.strip() if proc.returncode == 0 else None

    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain", "--untracked-files=no") if commit else None
    return {"commit": commit, "dirty": None if status is None else bool(status)}


def read_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: str | Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, sort_keys=False)
        file.write("\n")


def summary_manifest_path(summary_path: str | Path) -> Path:
    """``results/csv/ros2_runtime_summary.csv`` -> ``.../ros2_runtime_summary.manifest.json``."""

    path = Path(summary_path)
    return path.with_name(f"{path.stem}.manifest.json")


def simulation_provenance_path(csv_path: str | Path) -> Path:
    """``results/csv/x.csv`` -> ``results/csv/x.provenance.json``."""

    path = Path(csv_path)
    return path.with_name(f"{path.stem}.provenance.json")


# ---------------------------------------------------------------------------
# raw CSV -> runtime summary
# ---------------------------------------------------------------------------


def write_summary_manifest(
    summary_path: str | Path,
    inputs: Iterable[tuple[str | Path, str]],
    runs: Iterable[dict[str, Any]],
    settings: dict[str, Any],
    manifest_path: str | Path | None = None,
) -> Path:
    """Record the summary hash and the hash of every raw input it was built from.

    ``inputs`` are ``(path, kind)`` pairs with kind ``detector_csv``,
    ``publisher_csv`` or ``run_metadata``. ``runs`` lists one entry per summary
    row: ``{run_id, run_metadata (path or None), measurement_class}``.
    """

    manifest_path = Path(manifest_path) if manifest_path else summary_manifest_path(summary_path)
    base = manifest_path.parent
    manifest = {
        "schema": SUMMARY_MANIFEST_SCHEMA,
        "generator": "src.ros2_runtime.analyze_runtime",
        "git": git_state(),
        "settings": settings,
        "summary": file_record(summary_path, base),
        "inputs": [file_record(path, base, kind=kind) for path, kind in inputs],
        "runs": [
            {
                **run,
                "run_metadata": None if not run.get("run_metadata") else relative_ref(run["run_metadata"], base),
            }
            for run in runs
        ],
    }
    write_json(manifest_path, manifest)
    return manifest_path


def verify_summary_manifest(manifest_path: str | Path) -> list[str]:
    """Return every reason the summary cannot be traced to raw data (empty = verified)."""

    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        return [f"summary manifest {manifest_path} is missing"]
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema") != SUMMARY_MANIFEST_SCHEMA:
        return [f"{manifest_path}: not a {SUMMARY_MANIFEST_SCHEMA} manifest"]
    base = manifest_path.parent
    problems = check_file_record(manifest.get("summary"), base, "summary")
    inputs = manifest.get("inputs") or []
    if not any(item.get("kind") == "detector_csv" for item in inputs if isinstance(item, dict)):
        problems.append("manifest lists no raw detector CSV")
    for item in inputs:
        problems.extend(check_file_record(item, base, f"raw input ({(item or {}).get('kind', '?')})"))
    for run in manifest.get("runs") or []:
        run_id = run.get("run_id", "?")
        if not run.get("run_metadata"):
            problems.append(f"run {run_id}: no run metadata (<run_id>.meta.json)")
        cls = run.get("measurement_class", CLASS_UNKNOWN)
        if cls not in VALID_MEASUREMENT_CLASSES:
            problems.append(f"run {run_id}: measurement_class={cls} (resource limits not verified)")
    return problems


# ---------------------------------------------------------------------------
# runtime summary -> OS profile JSON
# ---------------------------------------------------------------------------


def assess_os_profile_payload(payload: dict[str, Any], payload_path: str | Path) -> tuple[str, list[str]]:
    """Return ``(status, reasons)`` for an OS profile JSON file.

    A file is ``verified`` only if it declares so *and* its recorded summary and
    manifest still hash-match and the manifest verifies down to the raw CSVs.
    Files without a metadata block are legacy files of unknown origin.
    """

    meta = payload.get("metadata")
    if not isinstance(meta, dict):
        return STATUS_UNVERIFIED, ["no metadata block: legacy file, source chain unknown"]
    declared = meta.get("provenance_status")
    if declared == STATUS_EXAMPLE:
        return STATUS_EXAMPLE, []
    if declared != STATUS_VERIFIED:
        reasons = meta.get("unverified_reasons") or [f"declared provenance_status={declared!r}"]
        return STATUS_UNVERIFIED, [str(reason) for reason in reasons]

    base = Path(payload_path).parent
    problems = check_file_record(meta.get("source_summary"), base, "source summary")
    problems += check_file_record(meta.get("source_manifest"), base, "source manifest")
    if not problems:
        manifest_path = resolve_ref(meta["source_manifest"]["path"], base)
        problems += verify_summary_manifest(manifest_path)
    if problems:
        return STATUS_UNVERIFIED, problems
    return STATUS_VERIFIED, []


def os_profile_models(payload: dict[str, Any]) -> dict[str, str | None]:
    """Map each profile name in the file to the runtime model it was measured on."""

    meta = payload.get("metadata")
    profiles = meta.get("profiles") if isinstance(meta, dict) else None
    result: dict[str, str | None] = {}
    for name in payload.get("os_profile_definitions") or {}:
        entry = profiles.get(name) if isinstance(profiles, dict) else None
        model = entry.get("model_name") if isinstance(entry, dict) else None
        result[name] = str(model) if model else None
    return result
