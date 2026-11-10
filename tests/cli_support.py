"""Shared helper for tests that run project CLIs or shell scripts in a subprocess.

``subprocess.run(..., check=True)`` turns a failing child into a bare
``CalledProcessError`` that hides the child's stdout/stderr, which made one
intermittent error in Phase 1 / Batch 3 impossible to diagnose afterwards.
``run_cli`` instead fails with the command, working directory, exit code and
the complete output of the child.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Sequence

REPO = Path(__file__).resolve().parents[1]


def run_cli(args: Sequence[Any], *, expect: int | None = 0, cwd: Path | str = REPO,
            **kwargs: Any) -> subprocess.CompletedProcess:
    """Run ``args``; raise AssertionError with full diagnostics on an unexpected exit code.

    ``expect=None`` accepts any exit code (the caller asserts on it).
    """

    proc = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, text=True, **kwargs)
    if expect is not None and proc.returncode != expect:
        raise AssertionError(describe_failure(proc, expect, cwd))
    return proc


def describe_failure(proc: subprocess.CompletedProcess, expect: int | None = None,
                     cwd: Path | str = REPO) -> str:
    """Multi-line description of a finished subprocess for assertion messages."""

    cmd = proc.args if isinstance(proc.args, str) else " ".join(map(str, proc.args))
    wanted = "" if expect is None else f", expected {expect}"
    return (
        f"command exited {proc.returncode}{wanted}\n"
        f"  cmd: {cmd}\n  cwd: {cwd}\n"
        f"--- stdout ---\n{proc.stdout or ''}\n--- stderr ---\n{proc.stderr or ''}"
    )
