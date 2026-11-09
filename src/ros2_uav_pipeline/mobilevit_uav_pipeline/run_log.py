"""Run identity and CSV creation helpers for the MobileViT detector logger.

Standard library only, so the run-integrity rules can be unit-tested without
ROS 2. Each detector process is one run: it gets a unique ``run_id`` and
writes to a CSV file that it creates exclusively. An existing file is never
appended to or overwritten.
"""

from __future__ import annotations

import csv
import os
import re
import time
import uuid

AUTO = "auto"
DEFAULT_RESULTS_DIR = os.path.join("results", "raw", "ros2")
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def resolve_run_id(value: str | None) -> str:
    """Return the given run_id, or generate a unique one for empty/``auto``."""

    text = "" if value is None else str(value).strip()
    if not text or text == AUTO:
        return f"{time.strftime('%Y%m%dT%H%M%S')}_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    if not _RUN_ID_PATTERN.match(text):
        raise ValueError(
            f"run_id '{text}' is invalid: use only letters, digits, '.', '_' or '-', "
            "starting with a letter or digit."
        )
    return text


def resolve_output_csv(value: str | None, run_id: str) -> str:
    """Return the CSV path; empty/``auto`` means results/raw/ros2/<run_id>.csv."""

    text = "" if value is None else str(value).strip()
    if not text or text == AUTO:
        return os.path.join(DEFAULT_RESULTS_DIR, f"{run_id}.csv")
    return text


def create_run_csv(path: str, header: list[str]) -> None:
    """Create ``path`` with ``header``; fail if the file already exists."""

    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    try:
        with open(path, "x", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow(header)
    except FileExistsError as exc:
        raise FileExistsError(
            f"Runtime CSV '{path}' already exists. Refusing to append to or overwrite it, "
            "because rows from different runs would be mixed. Use a new output_csv "
            "(or output_csv:=auto) and a new run_id."
        ) from exc
