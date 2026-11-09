"""Run identity, CSV schema and timing helpers for the MobileViT ROS2 nodes.

Standard library only, so the run-integrity and measurement rules can be
unit-tested without ROS 2. Each launch is one run: it gets a unique ``run_id``
and writes CSV files that it creates exclusively. An existing file is never
appended to or overwritten.

Clock semantics (see README "ROS2 Runtime CSV Contract"):

- Cross-process timestamps (``published_at_ns``, ``received_at_ns``,
  ``completed_at_ns``) use the host wall clock (``time.time_ns()``, the same
  clock as ROS ``SYSTEM_TIME``). Publisher and detector must run on one host.
- In-process durations (``preprocess_ms``, ``artificial_delay_ms``,
  ``inference_ms``) use the monotonic ``time.perf_counter_ns()``.
"""

from __future__ import annotations

import csv
import os
import re
import time
import uuid

AUTO = "auto"
DISABLED = "none"
DEFAULT_RESULTS_DIR = os.path.join("results", "raw", "ros2")
PUBLISHER_SUFFIX = ".publisher.csv"
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Detector CSV (one row per received frame). Columns are read by name, so
# older CSVs without the newer columns stay readable by the analyzer.
DETECTOR_CSV_HEADER = [
    "run_id", "scenario", "model_name", "input_fps", "qos_depth", "fake_delay_ms",
    "resource_profile", "deadline_ms", "frame_id", "warmup",
    "published_at_ns", "received_at_ns", "completed_at_ns",
    "latency_ms", "transport_ms", "preprocess_ms", "artificial_delay_ms", "inference_ms",
    "deadline_miss", "dropped", "cpu_percent", "memory_mb",
]

# Publisher CSV (one row per published frame): <run_id>.publisher.csv
PUBLISHER_CSV_HEADER = ["run_id", "frame_id", "published_at_ns"]


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
    """Return the detector CSV path; empty/``auto`` means results/raw/ros2/<run_id>.csv."""

    text = "" if value is None else str(value).strip()
    if not text or text == AUTO:
        return os.path.join(DEFAULT_RESULTS_DIR, f"{run_id}.csv")
    return text


def publisher_csv_path(detector_csv: str) -> str:
    """Return the publisher log path that belongs to a detector CSV."""

    base = detector_csv[:-4] if detector_csv.endswith(".csv") else detector_csv
    return base + PUBLISHER_SUFFIX


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


def ns_to_stamp(ns: int) -> tuple[int, int]:
    """Split wall-clock nanoseconds into ROS ``(sec, nanosec)``."""

    return ns // 1_000_000_000, ns % 1_000_000_000


def stamp_to_ns(sec: int, nanosec: int) -> int:
    return int(sec) * 1_000_000_000 + int(nanosec)


def parse_frame_id(text: str) -> int | None:
    """Return the integer frame id, or None. Never invents a frame id."""

    try:
        return int(str(text).strip())
    except ValueError:
        return None


def frame_timing(
    published_at_ns: int,
    received_at_ns: int,
    completed_at_ns: int,
    received_perf_ns: int,
    preprocessed_perf_ns: int,
    delayed_perf_ns: int,
    inferred_perf_ns: int,
    deadline_ms: float,
) -> dict[str, float | int]:
    """Derive per-frame timing fields.

    Wall-clock stamps give the cross-process values; monotonic perf-counter
    stamps give the in-process stage durations:

    - ``transport_ms``: published -> callback start (DDS transport + executor queue)
    - ``preprocess_ms``: cv_bridge conversion, resize, tensor creation
    - ``artificial_delay_ms``: injected ``fake_inference_delay_ms`` sleep
    - ``inference_ms``: model forward pass only
    - ``latency_ms``: end-to-end, published -> inference completed
    - ``deadline_miss``: 1 iff ``latency_ms > deadline_ms``
    """

    latency_ms = (completed_at_ns - published_at_ns) / 1e6
    return {
        "latency_ms": latency_ms,
        "transport_ms": (received_at_ns - published_at_ns) / 1e6,
        "preprocess_ms": (preprocessed_perf_ns - received_perf_ns) / 1e6,
        "artificial_delay_ms": (delayed_perf_ns - preprocessed_perf_ns) / 1e6,
        "inference_ms": (inferred_perf_ns - delayed_perf_ns) / 1e6,
        "deadline_miss": 1 if latency_ms > deadline_ms else 0,
    }
