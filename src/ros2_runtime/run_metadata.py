"""Record the conditions of one ROS2 run in ``<run_id>.meta.json``.

The sweep scripts call this once per run, *inside* the same taskset /
systemd-run scope that the ROS2 launch inherits, so the effective CPU
affinity and cgroup limits it reads are the ones the nodes run under.

Requested limits (what the wrapper asked for) and effective limits (what the
kernel reports) are recorded separately. ``measurement_class`` is
``constrained`` only when every requested limit was read back and matches:

- ``unconstrained``: no limit was requested;
- ``constrained``: every requested limit verified in effect;
- ``constraint_unverified``: a requested limit could not be read back
  (no cgroup v2, no ``sched_getaffinity``, e.g. macOS);
- ``constraint_failed``: a requested limit was read back and is NOT in effect
  (e.g. ``systemd-run --user`` without memory-controller delegation).

Nothing here changes system settings or needs sudo; network buffer sysctls
are only read. Standard library only.

    python3 -m src.ros2_runtime.run_metadata --output results/raw/ros2/<run_id>.meta.json \\
        --run-id <run_id> --resource-profile normal \\
        --requested-cpus 0,1 --requested-memory-max 2G \\
        --param scenario=fps_sweep --param input_fps=20 --require-applied
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Any, Callable

from src.provenance import (
    CLASS_CONSTRAINED,
    CLASS_CONSTRAINT_FAILED,
    CLASS_CONSTRAINT_UNVERIFIED,
    CLASS_UNCONSTRAINED,
    VALID_MEASUREMENT_CLASSES,
    git_state,
    sha256_file,
    write_json,
)

SCHEMA = "ros2_run_metadata/v1"
EXIT_LIMITS_NOT_APPLIED = 3

# QoS used by the checked-in nodes (src/ros2_uav_pipeline). A unit test checks
# that the node sources still match this description.
NODE_QOS = {
    "topic": "image_raw",
    "publisher": {"reliability": "reliable", "history": "keep_last", "depth": 10,
                  "source": "image_stream_node: create_publisher(Image, 'image_raw', 10)"},
    "subscription": {"reliability": "best_effort", "history": "keep_last", "depth": "qos_depth",
                     "source": "mobilevit_detector_node: QoSProfile(BEST_EFFORT, KEEP_LAST, qos_depth)"},
    "effective_reliability": "best_effort (reliable publisher + best-effort subscription)",
}

ROS_ENV_VARS = (
    "ROS_DISTRO", "ROS_VERSION", "ROS_PYTHON_VERSION", "RMW_IMPLEMENTATION", "ROS_DOMAIN_ID",
    "ROS_LOCALHOST_ONLY", "ROS_AUTOMATIC_DISCOVERY_RANGE", "FASTDDS_BUILTIN_TRANSPORTS",
    "FASTRTPS_DEFAULT_PROFILES_FILE", "FASTDDS_DEFAULT_PROFILES_FILE", "RMW_FASTRTPS_USE_QOS_FROM_XML",
    "CYCLONEDDS_URI",
)
NET_SYSCTLS = ("rmem_max", "rmem_default", "wmem_max", "wmem_default")
PACKAGES = ("torch", "timm", "numpy", "opencv-python", "opencv-python-headless", "psutil")

TRANSPORT_NOTE = (
    "Network buffer sysctls are recorded as read, not assumed effective. Publisher and "
    "detector run on one host; Fast DDS may use its shared-memory transport there, in which "
    "case UDP socket buffers do not affect delivery. RMW_IMPLEMENTATION unset means the "
    "distribution default RMW was used."
)

_SIZE_UNITS = {"": 1, "B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}


def parse_size_bytes(text: str | None) -> int | None:
    """Parse a systemd-style size (``2G``, ``512M``, ``1048576``); None for empty/max."""

    if text is None:
        return None
    value = str(text).strip().upper()
    if not value or value in {"MAX", "INFINITY"}:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([BKMGT]?)I?B?", value)
    if not match:
        raise ValueError(f"Cannot parse size '{text}'. Use e.g. 2G, 512M or a byte count.")
    return int(float(match.group(1)) * _SIZE_UNITS[match.group(2)])


def parse_cpu_list(text: str | None) -> list[int] | None:
    """Parse ``0,1,4-6`` into ``[0, 1, 4, 5, 6]``; None for empty."""

    if text is None or not str(text).strip():
        return None
    cpus: set[int] = set()
    for part in str(text).split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            cpus.update(range(int(start), int(end) + 1))
        elif part:
            cpus.add(int(part))
    return sorted(cpus)


def read_effective_limits(
    proc_root: str | Path = "/proc",
    cgroup_root: str | Path = "/sys/fs/cgroup",
    affinity: Callable[[], set[int]] | None = None,
) -> dict[str, Any]:
    """Read the CPU affinity and cgroup v2 limits of the current process.

    Values that cannot be read are None (never guessed). ``memory_max_bytes``
    is the tightest ``memory.max`` on the path from the process's cgroup to the
    root, i.e. the limit the kernel enforces.
    """

    notes: list[str] = []
    cpus: list[int] | None = None
    get_affinity = affinity or getattr(os, "sched_getaffinity", None)
    if get_affinity is not None:
        try:
            cpus = sorted(get_affinity(0) if affinity is None else get_affinity())
        except OSError as exc:
            notes.append(f"sched_getaffinity failed: {exc}")
    else:
        notes.append("CPU affinity not readable on this platform (no sched_getaffinity)")

    cgroup_path = None
    cgroup_file = Path(proc_root) / "self" / "cgroup"
    try:
        for line in cgroup_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("0::"):
                cgroup_path = line[3:].strip() or "/"
    except OSError:
        notes.append(f"{cgroup_file} not readable (not Linux?)")
    if cgroup_file.exists() and cgroup_path is None:
        notes.append("no cgroup v2 entry in /proc/self/cgroup (cgroup v1 or hybrid)")

    memory_max_bytes: int | str | None = None
    memory_max_own: str | None = None
    memory_swap_max_bytes: int | str | None = None
    cpu_max: str | None = None
    if cgroup_path is not None:
        node = Path(cgroup_root) / cgroup_path.lstrip("/")
        memory_max_own = _read_text(node / "memory.max")
        cpu_max = _read_text(node / "cpu.max")
        memory_max_bytes = _tightest_limit(node, Path(cgroup_root), "memory.max")
        if memory_max_bytes is None:
            notes.append("memory.max not readable (memory controller not enabled for this cgroup?)")
        # Informational: with swap on the host, memory.max alone lets the run page out
        # instead of being OOM-killed. Not part of measurement_class.
        memory_swap_max_bytes = _tightest_limit(node, Path(cgroup_root), "memory.swap.max")

    return {
        "cpus_allowed": cpus,
        "cgroup_path": cgroup_path,
        "memory_max_bytes": memory_max_bytes,
        "memory_max_own": memory_max_own,
        "memory_swap_max_bytes": memory_swap_max_bytes,
        "cpu_max": cpu_max,
        "notes": notes,
    }


def _tightest_limit(node: Path, cgroup_root: Path, filename: str) -> int | str | None:
    """Tightest ``filename`` value from ``node`` up to the root: bytes, ``"max"`` or None (unreadable)."""

    limits = []
    seen_any = False
    for level in [node, *node.parents]:
        raw = _read_text(level / filename)
        if raw is not None:
            seen_any = True
            limit = parse_size_bytes(raw)
            if limit is not None:
                limits.append(limit)
        if level == cgroup_root:
            break
    if limits:
        return min(limits)
    return "max" if seen_any else None


def dds_profile_info(environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Record the Fast DDS XML profile (path + SHA-256) the run was started with, if any.

    The DDS transport (UDP vs shared memory, segment size) changes frame delivery for
    large images, so the exact profile file is part of the run conditions.
    """

    env = os.environ if environ is None else environ
    path = env.get("FASTRTPS_DEFAULT_PROFILES_FILE") or env.get("FASTDDS_DEFAULT_PROFILES_FILE")
    if not path:
        return {"path": None, "sha256": None,
                "note": "no Fast DDS XML profile: RMW default transports (Humble Fast DDS: UDPv4 + SHM)"}
    try:
        digest = sha256_file(path)
    except OSError as exc:
        return {"path": path, "sha256": None, "note": f"profile not readable: {exc}"}
    return {"path": path, "sha256": digest, "parsed": parse_fastdds_profile(path)}


def parse_fastdds_profile(path: str) -> dict[str, Any]:
    """Static summary of a Fast DDS XML profile: transports of the default participant.

    This only shows what the file asks for; whether the running processes used it is
    checked at run time by ``src/ros2_runtime/runtime_probe.py`` (``<run_id>.probe.json``).
    """

    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        return {"valid_xml": False, "error": str(exc)}

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    descriptors: dict[str, dict[str, Any]] = {}
    default_participant: dict[str, Any] | None = None
    for elem in root.iter():
        if local(elem.tag) == "transport_descriptor":
            fields = {local(child.tag): (child.text or "").strip() for child in elem}
            tid = fields.get("transport_id", "")
            descriptors[tid] = {"type": fields.get("type"),
                                "segment_size": int(fields["segment_size"])
                                if fields.get("segment_size", "").isdigit() else None}
        elif local(elem.tag) == "participant" and elem.get("is_default_profile") == "true":
            user = [(e.text or "").strip() for e in elem.iter() if local(e.tag) == "transport_id"]
            builtin = [(e.text or "").strip().lower() for e in elem.iter()
                       if local(e.tag) == "useBuiltinTransports"]
            default_participant = {"profile_name": elem.get("profile_name"),
                                   "user_transports": user,
                                   "use_builtin_transports": None if not builtin else builtin[0] == "true"}
    shm_only = bool(
        default_participant
        and default_participant["use_builtin_transports"] is False
        and default_participant["user_transports"]
        and all((descriptors.get(t) or {}).get("type") == "SHM" for t in default_participant["user_transports"])
    )
    segment = None
    if shm_only:
        sizes = [descriptors[t]["segment_size"] for t in default_participant["user_transports"]
                 if descriptors[t]["segment_size"]]
        segment = max(sizes) if sizes else None
    return {"valid_xml": True, "transport_descriptors": descriptors,
            "default_participant": default_participant, "shm_only": shm_only,
            "shm_segment_size": segment}


def classify_limits(requested: dict[str, Any], effective: dict[str, Any]) -> tuple[dict[str, bool | None], str]:
    """Compare requested and effective limits; return ``(applied, measurement_class)``."""

    applied: dict[str, bool | None] = {}
    req_cpus = requested.get("cpus")
    if req_cpus is not None:
        eff_cpus = effective.get("cpus_allowed")
        applied["cpu"] = None if eff_cpus is None else sorted(eff_cpus) == sorted(req_cpus)
    req_mem = requested.get("memory_max_bytes")
    if req_mem is not None:
        eff_mem = effective.get("memory_max_bytes")
        if eff_mem is None:
            applied["memory"] = None
        else:
            applied["memory"] = isinstance(eff_mem, int) and eff_mem == req_mem
    if not applied:
        return applied, CLASS_UNCONSTRAINED
    if any(value is False for value in applied.values()):
        return applied, CLASS_CONSTRAINT_FAILED
    if any(value is None for value in applied.values()):
        return applied, CLASS_CONSTRAINT_UNVERIFIED
    return applied, CLASS_CONSTRAINED


def collect_run_metadata(
    run_id: str,
    resource_profile: str,
    requested_cpus: str | None = None,
    requested_memory_max: str | None = None,
    params: dict[str, str] | None = None,
    effective: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requested = {
        "cpus": parse_cpu_list(requested_cpus),
        "memory_max": (requested_memory_max or "").strip() or None,
        "memory_max_bytes": parse_size_bytes(requested_memory_max),
    }
    effective = effective if effective is not None else read_effective_limits()
    applied, measurement_class = classify_limits(requested, effective)
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": git_state(),
        "host": _host_info(),
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation(),
                   "executable": sys.executable},
        "packages": {name: _package_version(name) for name in PACKAGES},
        "ros2": {name: os.environ.get(name) for name in ROS_ENV_VARS},
        "dds_profile": dds_profile_info(),
        "process": {"nice": os.nice(0) if hasattr(os, "nice") else None},
        "qos": NODE_QOS,
        "network_sysctl": {f"net.core.{name}": _read_int(Path("/proc/sys/net/core") / name) for name in NET_SYSCTLS},
        "transport_note": TRANSPORT_NOTE,
        "resource_profile": resource_profile,
        "resource_limits": {
            "requested": requested,
            "effective": effective,
            "applied": applied,
            "measurement_class": measurement_class,
        },
        "experiment": dict(params or {}),
    }


def _host_info() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "kernel_release": platform.release(),
        "kernel_version": platform.version(),
        "machine": platform.machine(),
        "cpu_model": _cpu_model(),
        "logical_cpus": os.cpu_count(),
        "memory_total_mb": _host_memory_mb(),
    }


def _cpu_model() -> str | None:
    text = _read_text(Path("/proc/cpuinfo"))
    if text:
        for line in text.splitlines():
            if line.lower().startswith(("model name", "hardware", "processor\t: ")) and ":" in line:
                value = line.split(":", 1)[1].strip()
                if value and not value.isdigit():
                    return value
    if platform.system() == "Darwin":
        try:
            proc = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                  capture_output=True, text=True, timeout=5, check=False)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return platform.processor() or None


def _host_memory_mb() -> float | None:
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 * 1024), 1)
    except (ValueError, OSError, AttributeError):
        return None


def _package_version(name: str) -> str | None:
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _read_int(path: Path) -> int | None:
    text = _read_text(path)
    try:
        return None if text is None else int(text)
    except ValueError:
        return None


def _parse_params(items: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--param expects key=value, got '{item}'.")
        key, value = item.split("=", 1)
        params[key.strip()] = value
    return params


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write <run_id>.meta.json for one ROS2 run.")
    parser.add_argument("--output", required=True, help="Metadata JSON path (must not exist).")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--resource-profile", required=True, help="Label written to the run CSV.")
    parser.add_argument("--requested-cpus", default="", help="CPU list the wrapper requested, e.g. 0,1.")
    parser.add_argument("--requested-memory-max", default="", help="Memory limit requested, e.g. 2G.")
    parser.add_argument("--param", action="append", default=[], help="Experiment parameter key=value.")
    parser.add_argument("--require-applied", action="store_true",
                        help=f"Exit {EXIT_LIMITS_NOT_APPLIED} unless requested limits are verified in effect.")
    args = parser.parse_args(argv)

    output = Path(args.output)
    if output.exists():
        print(f"錯誤：{output} 已存在，拒絕覆寫 run metadata。", file=sys.stderr)
        return 1
    payload = collect_run_metadata(
        run_id=args.run_id,
        resource_profile=args.resource_profile,
        requested_cpus=args.requested_cpus,
        requested_memory_max=args.requested_memory_max,
        params=_parse_params(args.param),
    )
    write_json(output, payload)
    limits = payload["resource_limits"]
    print(f"run metadata: {output} measurement_class={limits['measurement_class']} applied={limits['applied']}")
    if args.require_applied and limits["measurement_class"] not in VALID_MEASUREMENT_CLASSES:
        print(
            f"錯誤：要求的資源限制未確認生效（measurement_class={limits['measurement_class']}，"
            f"effective={limits['effective']}）。不可標示為 constrained measurement。",
            file=sys.stderr,
        )
        return EXIT_LIMITS_NOT_APPLIED
    return 0


if __name__ == "__main__":
    sys.exit(main())
