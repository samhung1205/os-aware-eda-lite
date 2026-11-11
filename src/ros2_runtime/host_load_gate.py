"""Low-load gate for a shared server (Phase 3 / Batch 2).

    python3 -m src.ros2_runtime.host_load_gate --cpus 12,14 [--max-busy-pct 15] \
        [--max-loadavg 6] [--sample-s 3] [--max-wait-s 1800] [--log results/.../load_gate.jsonl] [--label X]

Before a measurement block, waits until (a) every CPU of ``--cpus`` **and its SMT
siblings** is less than ``--max-busy-pct`` busy over a ``--sample-s`` window and
(b) the 1-minute load average is below ``--max-loadavg``. Re-samples every 30 s.
Exit 0 when the host is quiet (or immediately with ``--check-only`` and a quiet
host), exit 4 when it stayed busy for ``--max-wait-s`` (the caller stops the
batch instead of measuring under load). Every sample is appended as one JSON line
to ``--log`` (if given) so the gate decisions are kept next to the raw data.

Read-only (``/proc/stat``, ``/proc/loadavg``, sysfs topology); never changes system
settings. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from src.ros2_runtime.runtime_probe import parse_cpu_list, cpu_times, smt_siblings

GATE_PASS, GATE_BUSY = 0, 4


def busy_pct(before: dict[int, tuple[int, int]], after: dict[int, tuple[int, int]],
             cpus: list[int]) -> dict[int, float]:
    """Per-CPU busy % between two /proc/stat snapshots (missing CPU -> 100, i.e. not quiet)."""

    out = {}
    for cpu in cpus:
        if cpu not in before or cpu not in after:
            out[cpu] = 100.0
            continue
        total = after[cpu][0] - before[cpu][0]
        idle = after[cpu][1] - before[cpu][1]
        out[cpu] = 0.0 if total <= 0 else round(100.0 * (total - idle) / total, 2)
    return out


def evaluate(per_cpu: dict[int, float], loadavg_1m: float, max_busy_pct: float,
             max_loadavg: float) -> tuple[bool, list[str]]:
    reasons = [f"cpu{cpu} {pct}% busy >= {max_busy_pct}%" for cpu, pct in sorted(per_cpu.items())
               if pct >= max_busy_pct]
    if loadavg_1m >= max_loadavg:
        reasons.append(f"loadavg_1m {loadavg_1m} >= {max_loadavg}")
    return not reasons, reasons


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def sample(cpus: list[int], sample_s: float) -> tuple[dict[int, float], float]:
    before = cpu_times(_read("/proc/stat"))
    time.sleep(sample_s)
    after = cpu_times(_read("/proc/stat"))
    return busy_pct(before, after, cpus), float(_read("/proc/loadavg").split()[0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cpus", required=True, help="CPU list of the measurement scope, e.g. 12,14")
    parser.add_argument("--max-busy-pct", type=float, default=15.0)
    parser.add_argument("--max-loadavg", type=float, default=6.0)
    parser.add_argument("--sample-s", type=float, default=3.0)
    parser.add_argument("--max-wait-s", type=float, default=1800.0)
    parser.add_argument("--retry-s", type=float, default=30.0)
    parser.add_argument("--log", default="")
    parser.add_argument("--label", default="")
    args = parser.parse_args(argv)

    base = parse_cpu_list(args.cpus)
    if not base:
        parser.error("--cpus is empty")
    watched = sorted({sib for cpu in base for sib in smt_siblings(cpu)} | set(base))
    deadline = time.monotonic() + args.max_wait_s
    while True:
        per_cpu, load1 = sample(watched, args.sample_s)
        quiet, reasons = evaluate(per_cpu, load1, args.max_busy_pct, args.max_loadavg)
        record = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "label": args.label, "quiet": quiet,
            "watched_cpus_busy_pct": {str(k): v for k, v in per_cpu.items()},
            "loadavg_1m": load1, "max_busy_pct": args.max_busy_pct,
            "max_loadavg": args.max_loadavg, "reasons": reasons, "pid": os.getpid(),
        }
        if args.log:
            with open(args.log, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, sort_keys=True) + "\n")
        print(("QUIET " if quiet else "BUSY  ") + json.dumps(record, sort_keys=True), flush=True)
        if quiet:
            return GATE_PASS
        if time.monotonic() + args.retry_s > deadline:
            return GATE_BUSY
        time.sleep(args.retry_s)


if __name__ == "__main__":
    sys.exit(main())
