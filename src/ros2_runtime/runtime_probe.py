"""Runtime probe for one ROS2 run: verifies the DDS transport actually in use and
samples per-process / cgroup resource usage (Phase 2 / Batch 2).

Why: ``FASTRTPS_DEFAULT_PROFILES_FILE`` being set (recorded in ``meta.json``) does
not prove that Fast DDS parsed the XML. A malformed or ignored profile silently
falls back to the RMW default transports (UDPv4 + 512 KB SHM segment), which lose
most large best-effort frames on the Phase 2 server. This probe looks at what the
running publisher / detector processes really opened:

- UDP sockets: socket inodes from ``/proc/<pid>/fd`` matched against
  ``/proc/net/udp{,6}``. The SHM-only profile disables the builtin transports, so
  a correctly loaded profile opens **no** UDP socket.
- Fast DDS shared-memory segments: ``/dev/shm/fastrtps_*`` files mapped in
  ``/proc/<pid>/maps`` and their size. The profile sets ``segment_size`` 16 MiB;
  the default segment is 512 KB.

It also samples CPU time, RSS, CPU affinity and nice of each node, the cgroup
(scope) ``memory.current`` / ``memory.peak`` / ``memory.swap.current`` / ``cpu.stat``,
host load and per-CPU busy time of the allowed CPUs and their SMT siblings
(interference from other users of the shared server).

Standard library only, read-only: it never changes a system setting. Run it in
the same systemd scope as the launch (the sweep scripts do), in the background;
it stops on SIGTERM/SIGINT or after ``--max-seconds`` and writes one JSON file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import time
from pathlib import Path
from typing import Any

SCHEMA = "ros2_runtime_probe/v1"
NODE_PATTERNS = {
    "publisher": re.compile(r"image_stream_node(\.py)?$"),
    "detector": re.compile(r"mobilevit_detector_node(\.py)?$"),
}
FASTDDS_SHM_PREFIX = "fastrtps_"
CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def _read(path: str | Path) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def parse_cpu_list(text: str | None) -> list[int]:
    cpus: list[int] = []
    for part in (text or "").strip().split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            cpus.extend(range(int(lo), int(hi) + 1))
        else:
            cpus.append(int(part))
    return cpus


def udp_inodes(proc_net: str | Path = "/proc/net") -> set[int]:
    """Inodes of all UDP sockets in the probe's network namespace."""

    inodes: set[int] = set()
    for name in ("udp", "udp6"):
        text = _read(Path(proc_net) / name)
        if not text:
            continue
        for line in text.splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 10 and fields[9].isdigit():
                inodes.add(int(fields[9]))
    return inodes


def socket_inodes(pid: int) -> set[int]:
    inodes: set[int] = set()
    fd_dir = Path(f"/proc/{pid}/fd")
    try:
        entries = list(fd_dir.iterdir())
    except OSError:
        return inodes
    for entry in entries:
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        match = re.fullmatch(r"socket:\[(\d+)\]", target)
        if match:
            inodes.add(int(match.group(1)))
    return inodes


def shm_segments_from_maps(maps_text: str | None) -> set[str]:
    """``/dev/shm/fastrtps_*`` paths mapped by a process (lock / semaphore files excluded)."""

    found: set[str] = set()
    for line in (maps_text or "").splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        path = parts[5].strip().removesuffix(" (deleted)")
        name = os.path.basename(path)
        if path.startswith("/dev/shm/") and name.startswith(FASTDDS_SHM_PREFIX) and not name.endswith("_el"):
            found.add(path)
    return found


def parse_stat(text: str | None) -> dict[str, int] | None:
    """utime, stime (ticks), nice, num_threads from /proc/<pid>/stat."""

    if not text:
        return None
    rest = text[text.rfind(")") + 2:].split()
    # rest[0] is field 3 (state); utime=14, stime=15, nice=19, num_threads=20
    try:
        return {"utime": int(rest[11]), "stime": int(rest[12]), "nice": int(rest[16]),
                "num_threads": int(rest[17])}
    except (IndexError, ValueError):
        return None


def status_fields(text: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            out[key.strip()] = value.strip()
    return out


def cpu_times(stat_text: str | None) -> dict[int, tuple[int, int]]:
    """{cpu: (total_ticks, idle_ticks)} from /proc/stat."""

    out: dict[int, tuple[int, int]] = {}
    for line in (stat_text or "").splitlines():
        if line.startswith("cpu") and len(line) > 3 and line[3].isdigit():
            parts = line.split()
            values = [int(v) for v in parts[1:]]
            out[int(parts[0][3:])] = (sum(values[:8]), values[3] + values[4])
    return out


def smt_siblings(cpu: int) -> list[int]:
    text = _read(f"/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list")
    return parse_cpu_list(text) if text else [cpu]


def own_cgroup_dir() -> Path | None:
    text = _read("/proc/self/cgroup")
    for line in (text or "").splitlines():
        if line.startswith("0::"):
            return Path("/sys/fs/cgroup") / line[3:].strip().lstrip("/")
    return None


def cgroup_pids(cgroup: Path | None) -> list[int]:
    if cgroup is None:
        return []
    text = _read(cgroup / "cgroup.procs")
    return [int(x) for x in (text or "").split() if x.isdigit()]


def classify_pid(pid: int) -> str | None:
    raw = _read(f"/proc/{pid}/cmdline")
    if not raw:
        return None
    for arg in raw.split("\0")[:3]:
        for role, pattern in NODE_PATTERNS.items():
            if pattern.search(arg):
                return role
    return None


def _int_or_none(text: str | None) -> int | None:
    text = (text or "").strip()
    return int(text) if text.isdigit() else None


def _cgroup_cpu_usage_usec(cgroup: Path | None) -> int | None:
    if cgroup is None:
        return None
    for line in (_read(cgroup / "cpu.stat") or "").splitlines():
        if line.startswith("usage_usec "):
            return int(line.split()[1])
    return None


def udp_snmp() -> dict[str, int]:
    text = _read("/proc/net/snmp") or ""
    lines = [line for line in text.splitlines() if line.startswith("Udp:")]
    if len(lines) < 2:
        return {}
    keys, values = lines[0].split()[1:], lines[1].split()[1:]
    return {k: int(v) for k, v in zip(keys, values) if k in ("InErrors", "RcvbufErrors", "InDatagrams")}


def evaluate_dds(nodes: dict[str, dict[str, Any]], expected_segment_bytes: int | None,
                 expect_shm_only: bool) -> dict[str, Any]:
    """Decide whether the observed transport matches the requested SHM-only profile."""

    reasons: list[str] = []
    for role in NODE_PATTERNS:
        if role not in nodes or not nodes[role].get("samples"):
            reasons.append(f"{role} process never observed")
    udp_by_role = {role: nodes.get(role, {}).get("max_udp_sockets") for role in NODE_PATTERNS}
    seg_sizes = sorted({size for node in nodes.values() for size in node.get("shm_segment_sizes", [])})
    if expect_shm_only:
        for role, count in udp_by_role.items():
            if count is None:
                continue
            if count > 0:
                reasons.append(f"{role} opened {count} UDP socket(s): builtin transports active, "
                               "XML profile not applied")
        if expected_segment_bytes is not None:
            if not seg_sizes:
                reasons.append("no Fast DDS /dev/shm segment mapped")
            elif max(seg_sizes) < expected_segment_bytes:
                reasons.append(f"largest SHM segment {max(seg_sizes)} B < expected {expected_segment_bytes} B "
                               "(default 512 KB segment: XML segment_size not applied)")
    return {
        "expect_shm_only": expect_shm_only,
        "expected_segment_bytes": expected_segment_bytes,
        "max_udp_sockets": udp_by_role,
        "shm_segment_sizes": seg_sizes,
        "verified": expect_shm_only and not reasons,
        "reasons": reasons,
    }


class Probe:
    def __init__(self, interval: float):
        self.interval = interval
        self.cgroup = own_cgroup_dir()
        self.self_pid = os.getpid()
        self.nodes: dict[str, dict[str, Any]] = {}
        self.cg_samples: list[dict[str, Any]] = []
        self.allowed = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else []
        watch: set[int] = set()
        for cpu in self.allowed:
            watch.update(smt_siblings(cpu))
        self.watch_cpus = sorted(watch)
        self.cpu_start = cpu_times(_read("/proc/stat"))
        self.snmp_start = udp_snmp()
        self.load_samples: list[float] = []
        self.started = time.time()

    def sample(self) -> None:
        udp = udp_inodes()
        now = time.time()
        for pid in cgroup_pids(self.cgroup):
            if pid == self.self_pid:
                continue
            role = classify_pid(pid)
            if role is None:
                continue
            stat = parse_stat(_read(f"/proc/{pid}/stat"))
            if stat is None:
                continue
            status = status_fields(_read(f"/proc/{pid}/status"))
            segs = shm_segments_from_maps(_read(f"/proc/{pid}/maps"))
            sizes = []
            for seg in segs:
                try:
                    sizes.append(os.stat(seg).st_size)
                except OSError:
                    pass
            n_udp = len(socket_inodes(pid) & udp)
            node = self.nodes.setdefault(role, {
                "pid": pid, "samples": 0, "max_udp_sockets": 0, "shm_segments": set(),
                "shm_segment_sizes": set(), "cpus_allowed": set(), "nice": set(),
                "first": None, "last": None, "max_rss_mb": 0.0, "max_threads": 0,
            })
            if node["pid"] != pid:
                # A different process (e.g. the previous run's node still exiting when this
                # probe started): CPU accounting restarts on the newest pid.
                node.setdefault("pid_changes", []).append(pid)
                node["pid"] = pid
                node["first"] = None
            ticks = stat["utime"] + stat["stime"]
            node["samples"] += 1
            node["max_udp_sockets"] = max(node["max_udp_sockets"], n_udp)
            node["shm_segments"].update(segs)
            node["shm_segment_sizes"].update(sizes)
            node["cpus_allowed"].add(status.get("Cpus_allowed_list", ""))
            node["nice"].add(stat["nice"])
            rss_kb = int((status.get("VmRSS", "0 kB").split() or ["0"])[0])
            node["max_rss_mb"] = max(node["max_rss_mb"], rss_kb / 1024)
            node["max_threads"] = max(node["max_threads"], stat["num_threads"])
            if node["first"] is None:
                node["first"] = (now, ticks)
            node["last"] = (now, ticks)
        if self.cgroup is not None:
            self.cg_samples.append({
                "t": now,
                "memory_current": _int_or_none(_read(self.cgroup / "memory.current")),
                "swap_current": _int_or_none(_read(self.cgroup / "memory.swap.current")),
            })
        load = (_read("/proc/loadavg") or "0").split()[0]
        self.load_samples.append(float(load))

    def finish(self, expected_segment_bytes: int | None, expect_shm_only: bool) -> dict[str, Any]:
        cpu_end = cpu_times(_read("/proc/stat"))
        per_cpu = {}
        for cpu in self.watch_cpus:
            if cpu in self.cpu_start and cpu in cpu_end:
                total = cpu_end[cpu][0] - self.cpu_start[cpu][0]
                idle = cpu_end[cpu][1] - self.cpu_start[cpu][1]
                per_cpu[str(cpu)] = round(100 * (1 - idle / total), 2) if total > 0 else None
        nodes_out: dict[str, dict[str, Any]] = {}
        for role, node in self.nodes.items():
            cpu_pct = None
            if node["first"] and node["last"] and node["last"][0] > node["first"][0]:
                dt = node["last"][0] - node["first"][0]
                cpu_pct = round(100 * (node["last"][1] - node["first"][1]) / CLK_TCK / dt, 2)
            nodes_out[role] = {
                "pid": node["pid"], "samples": node["samples"],
                "max_udp_sockets": node["max_udp_sockets"],
                "shm_segments": sorted(node["shm_segments"]),
                "shm_segment_sizes": sorted(node["shm_segment_sizes"]),
                "cpus_allowed": sorted(node["cpus_allowed"]),
                "nice": sorted(node["nice"]),
                "avg_cpu_percent_sampled": cpu_pct,
                "max_rss_mb": round(node["max_rss_mb"], 1),
                "max_threads": node["max_threads"],
                **({"pid_changes": node["pid_changes"]} if "pid_changes" in node else {}),
            }
        mem = [s["memory_current"] for s in self.cg_samples if s["memory_current"] is not None]
        swap = [s["swap_current"] for s in self.cg_samples if s["swap_current"] is not None]
        snmp_end = udp_snmp()
        return {
            "schema": SCHEMA,
            "started_at": self.started,
            "ended_at": time.time(),
            "interval_s": self.interval,
            "cgroup": None if self.cgroup is None else str(self.cgroup),
            "probe_cpus_allowed": self.allowed,
            "dds": evaluate_dds(nodes_out, expected_segment_bytes, expect_shm_only),
            "nodes": nodes_out,
            "cgroup_usage": {
                "max_memory_current_mb": round(max(mem) / 1048576, 1) if mem else None,
                "memory_peak_mb": (lambda v: None if v is None else round(v / 1048576, 1))(
                    _int_or_none(_read(self.cgroup / "memory.peak")) if self.cgroup else None),
                "max_swap_current_bytes": max(swap) if swap else None,
                "cpu_usage_usec_at_end": _cgroup_cpu_usage_usec(self.cgroup),
            },
            "host": {
                "loadavg_1m_min": min(self.load_samples) if self.load_samples else None,
                "loadavg_1m_max": max(self.load_samples) if self.load_samples else None,
                "watched_cpus_busy_pct": per_cpu,
                "udp_snmp_delta": {k: snmp_end.get(k, 0) - v for k, v in self.snmp_start.items()},
            },
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe DDS transport and resource usage of one ROS2 run.")
    parser.add_argument("--output", required=True, help="Probe JSON path (must not exist).")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--max-seconds", type=float, default=3600.0)
    parser.add_argument("--expect-shm-only", action="store_true",
                        help="Profile disables builtin transports: any UDP socket fails verification.")
    parser.add_argument("--expected-segment-bytes", type=int, default=None)
    parser.add_argument("--dds-profile", default="",
                        help="Fast DDS XML in use; an SHM-only profile sets --expect-shm-only and the "
                             "expected segment size from the file.")
    args = parser.parse_args(argv)
    if args.dds_profile:
        from src.ros2_runtime.run_metadata import parse_fastdds_profile

        parsed = parse_fastdds_profile(args.dds_profile)
        if parsed.get("shm_only"):
            args.expect_shm_only = True
            if args.expected_segment_bytes is None:
                args.expected_segment_bytes = parsed.get("shm_segment_size")

    out = Path(args.output)
    if out.exists():
        parser.error(f"{out} already exists")
    stop = {"flag": False}

    def _stop(*_: Any) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    probe = Probe(args.interval)
    deadline = time.time() + args.max_seconds
    while not stop["flag"] and time.time() < deadline:
        probe.sample()
        end = time.time() + args.interval
        while not stop["flag"] and time.time() < end:
            time.sleep(min(0.1, args.interval))
    result = probe.finish(args.expected_segment_bytes, args.expect_shm_only)
    result["run_id"] = args.run_id
    with out.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
