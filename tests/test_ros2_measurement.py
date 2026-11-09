"""Regression tests for Phase 1 / Batch 1: ROS2 measurement correctness.

P1-4 deadline accounting, P1-5 frame-drop accounting and grouping keys, P1-6
timing/warm-up, and launch reliability. No ROS2 install is needed: node logic
lives in run_log.py, and the launch file is exercised with stub launch modules.
"""

import csv
import importlib.util
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

from src.ros2_runtime.analyze_runtime import (
    SUMMARY_FIELDS,
    build_bar_chart_svg,
    build_runtime_summary,
    load_publisher_frames,
    load_runtime_rows,
)
from src.ros2_runtime.build_os_profiles import build_os_profile_payload

REPO = Path(__file__).resolve().parents[1]
PIPELINE_DIR = REPO / "src/ros2_uav_pipeline/mobilevit_uav_pipeline"
LAUNCH_FILE = REPO / "src/ros2_uav_pipeline/launch/mobilevit_uav_pipeline.launch.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_log = _load_module("run_log_measurement_test", PIPELINE_DIR / "run_log.py")

LEGACY_HEADER = (
    "scenario,model_name,input_fps,qos_depth,fake_delay_ms,resource_profile,"
    "frame_id,latency_ms,inference_ms,deadline_ms,deadline_miss,dropped,cpu_percent,memory_mb\n"
)


def _legacy(frame_id, latency="20", deadline="", miss=0, dropped=0, fps="20.0", qos="5"):
    return (
        f"qos_sweep,mobilevit_xxs,{fps},{qos},0,normal,{frame_id},{latency},10,"
        f"{deadline},{miss},{dropped},50,300\n"
    )


def _v2_csv(rows):
    """Detector CSV in the current schema; ``rows`` override per-row fields."""

    base = {
        "run_id": "run_v2", "scenario": "overload_sweep", "model_name": "mobilevit_xxs",
        "input_fps": "20.0", "qos_depth": "5", "fake_delay_ms": "80", "resource_profile": "normal",
        "deadline_ms": "100.0", "warmup": "0", "latency_ms": "95", "transport_ms": "2",
        "preprocess_ms": "3", "artificial_delay_ms": "80", "inference_ms": "10",
        "deadline_miss": "0", "dropped": "0", "cpu_percent": "50", "memory_mb": "300",
    }
    lines = [",".join(run_log.DETECTOR_CSV_HEADER)]
    for override in rows:
        values = {**base, **override}
        lines.append(",".join(str(values.get(column, "")) for column in run_log.DETECTOR_CSV_HEADER))
    return "\n".join(lines) + "\n"


def _publisher_csv(run_id, frame_ids):
    return "run_id,frame_id,published_at_ns\n" + "".join(f"{run_id},{i},{i}\n" for i in frame_ids)


def _summarise(files, warmup_frames=0):
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, body in files.items():
            (Path(tmpdir) / name).write_text(body, encoding="utf-8")
        return build_runtime_summary(
            load_runtime_rows([tmpdir]),
            publisher_frames=load_publisher_frames([tmpdir]),
            warmup_frames=warmup_frames,
        )


class DeadlineAccountingTest(unittest.TestCase):
    """P1-4."""

    def test_dropped_frames_are_not_deadline_misses(self):
        # Audit repro: 2 on-time frames + 2 dropped rows flagged miss used to give 100%.
        body = LEGACY_HEADER + _legacy(0) + _legacy(1) + _legacy(2, "", miss=1, dropped=1) + _legacy(3, "", miss=1, dropped=1)
        summary = _summarise({"a.csv": body})[0]

        self.assertEqual(summary["processed_frames"], "2")
        self.assertEqual(summary["dropped_frames"], "2")
        self.assertEqual(summary["deadline_misses"], "0")
        self.assertEqual(summary["deadline_miss_rate_pct"], "0")
        self.assertEqual(summary["effective_miss_rate_pct"], "50")

    def test_deadline_ms_is_the_single_definition(self):
        body = (
            LEGACY_HEADER
            + _legacy(0, latency="120", deadline="100", miss=0)   # flag wrong: is a miss
            + _legacy(1, latency="80", deadline="100", miss=1)    # flag wrong: not a miss
            + _legacy(2, latency="100", deadline="100", miss=0)   # boundary: not a miss
        )
        summary = _summarise({"a.csv": body})[0]

        self.assertEqual(summary["deadline_misses"], "1")
        self.assertEqual(summary["deadline_ms"], "100")
        self.assertEqual(summary["deadline_miss_rate_pct"], "33.3333")

    def test_logged_flag_is_used_only_when_deadline_is_unknown(self):
        body = LEGACY_HEADER + _legacy(0, miss=1) + _legacy(1, miss=0)
        summary = _summarise({"a.csv": body})[0]

        self.assertEqual(summary["deadline_misses"], "1")
        self.assertEqual(summary["deadline_ms"], "")

    def test_miss_rate_never_exceeds_100_pct(self):
        rows = [{"frame_id": i, "latency_ms": "150"} for i in range(3)]
        rows += [{"frame_id": i, "dropped": "1", "deadline_miss": "1", "latency_ms": ""} for i in range(3, 9)]
        summary = _summarise({"run_v2.csv": _v2_csv(rows)})[0]

        self.assertEqual(summary["deadline_miss_rate_pct"], "100")
        self.assertEqual(summary["deadline_misses"], "3")
        self.assertEqual(summary["effective_miss_rate_pct"], "100")

    def test_no_processed_frames_gives_unknown_rate_not_zero(self):
        body = LEGACY_HEADER + _legacy(0, "", dropped=1) + _legacy(1, "", dropped=1)
        summary = _summarise({"a.csv": body})[0]

        self.assertEqual(summary["deadline_miss_rate_pct"], "")
        self.assertEqual(summary["drop_rate_pct"], "100")

    def test_one_run_must_use_one_deadline(self):
        body = _v2_csv([{"frame_id": 0}, {"frame_id": 1, "deadline_ms": "50"}])
        with self.assertRaisesRegex(ValueError, "several deadline_ms values"):
            _summarise({"run_v2.csv": body})


class FrameDropAccountingTest(unittest.TestCase):
    """P1-5."""

    def test_explicit_drops_and_gaps_are_merged_without_double_counting(self):
        body = LEGACY_HEADER + _legacy(0) + _legacy(1, "", dropped=1) + _legacy(10)
        summary = _summarise({"a.csv": body})[0]

        self.assertEqual(summary["dropped_frames"], "9")  # 1 explicit + gaps 2..9
        self.assertEqual(summary["total_rows"], "11")

        body = LEGACY_HEADER + _legacy(0) + _legacy(1, "", dropped=1) + _legacy(2)
        self.assertEqual(_summarise({"a.csv": body})[0]["dropped_frames"], "1")

    def test_publisher_log_counts_leading_and_trailing_drops(self):
        rows = [{"frame_id": i, "run_id": "run_p"} for i in range(40, 90)]
        summary = _summarise(
            {"run_p.csv": _v2_csv(rows), "run_p.publisher.csv": _publisher_csv("run_p", range(100))}
        )[0]

        self.assertEqual(summary["frame_accounting"], "publisher_log")
        self.assertEqual(summary["published_frames"], "100")
        self.assertEqual(summary["processed_frames"], "50")
        self.assertEqual(summary["dropped_frames"], "50")
        self.assertEqual(summary["drop_rate_pct"], "50")

    def test_without_publisher_log_drops_are_flagged_as_lower_bound(self):
        rows = [{"frame_id": i} for i in range(40, 90)]
        summary = _summarise({"run_v2.csv": _v2_csv(rows)})[0]

        self.assertEqual(summary["frame_accounting"], "frame_id_range")
        self.assertEqual(summary["published_frames"], "")
        self.assertEqual(summary["dropped_frames"], "0")

    def test_unknown_drops_are_left_empty_not_zero(self):
        body = (
            "scenario,model_name,input_fps,qos_depth,latency_ms\n"
            "fps_sweep,mobilevit_xxs,20,5,20\nfps_sweep,mobilevit_xxs,20,5,25\n"
        )
        summary = _summarise({"a.csv": body})[0]

        self.assertEqual(summary["frame_accounting"], "unavailable")
        for column in ("dropped_frames", "drop_rate_pct", "total_rows", "effective_miss_rate_pct"):
            self.assertEqual(summary[column], "", column)
        svg = build_bar_chart_svg([summary], "drop_rate_pct", "Frame drop rate (%)")
        self.assertIn(">n/a<", svg)

    def test_explicit_drops_without_frame_id(self):
        body = LEGACY_HEADER + _legacy("", "20") + _legacy("", "", dropped=1)
        summary = _summarise({"a.csv": body})[0]

        self.assertEqual(summary["frame_accounting"], "explicit_only")
        self.assertEqual(summary["dropped_frames"], "1")

    def test_os_profiles_refuse_unknown_drop_rate(self):
        row = {"scenario": "s", "model_name": "m", "avg_latency_ms": "10", "drop_rate_pct": "",
               "frame_accounting": "unavailable", "run_id": "r"}
        with self.assertRaisesRegex(ValueError, "refusing to assume 0%"):
            build_os_profile_payload([row], baseline_latency_ms=10)

    def test_numeric_group_keys_are_normalised(self):
        body = LEGACY_HEADER + _legacy(0, fps="20") + _legacy(1, fps="20.0", qos="5.0")
        summary = _summarise({"a.csv": body})

        self.assertEqual(len(summary), 1)
        self.assertEqual((summary[0]["input_fps"], summary[0]["qos_depth"]), ("20.0", "5"))

    def test_mixed_numeric_and_text_keys_sort_without_error(self):
        summary = _summarise(
            {
                "a.csv": LEGACY_HEADER + _legacy(0, fps="10"),
                "b.csv": "scenario,model_name,frame_id,latency_ms\nqos_sweep,mobilevit_xxs,0,20\n",
                "c.csv": LEGACY_HEADER + _legacy(0, fps="5"),
            }
        )

        self.assertEqual([row["input_fps"] for row in summary], ["5.0", "10.0", "unknown"])

    def test_publisher_logs_are_loaded_separately(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "r.csv").write_text(_v2_csv([{"frame_id": 0, "run_id": "r"}]), encoding="utf-8")
            Path(tmpdir, "r.publisher.csv").write_text(_publisher_csv("r", [0, 1]), encoding="utf-8")
            Path(tmpdir, "old.csv.failed").write_text("garbage", encoding="utf-8")

            self.assertEqual(len(load_runtime_rows([tmpdir])), 1)
            self.assertEqual(load_publisher_frames([tmpdir]), {"r": [0, 1]})

            Path(tmpdir, "r.publisher.csv").write_text(_publisher_csv("r", [0, 0]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "repeats frame_id"):
                load_publisher_frames([tmpdir])


class TimingAndWarmupTest(unittest.TestCase):
    """P1-6."""

    def test_frame_timing_separates_stages(self):
        ms = 1_000_000
        timing = run_log.frame_timing(
            published_at_ns=1_000 * ms, received_at_ns=1_002 * ms, completed_at_ns=1_095 * ms,
            received_perf_ns=0, preprocessed_perf_ns=3 * ms, delayed_perf_ns=83 * ms,
            inferred_perf_ns=93 * ms, deadline_ms=90.0,
        )

        self.assertEqual(timing["transport_ms"], 2.0)
        self.assertEqual(timing["preprocess_ms"], 3.0)
        self.assertEqual(timing["artificial_delay_ms"], 80.0)
        self.assertEqual(timing["inference_ms"], 10.0)
        self.assertEqual(timing["latency_ms"], 95.0)
        self.assertEqual(timing["deadline_miss"], 1)

    def test_stamp_helpers_and_frame_id_parsing(self):
        ns = 1_731_200_000_123_456_789
        self.assertEqual(run_log.stamp_to_ns(*run_log.ns_to_stamp(ns)), ns)
        self.assertEqual(run_log.parse_frame_id("42"), 42)
        self.assertIsNone(run_log.parse_frame_id("camera_link"))
        self.assertEqual(run_log.publisher_csv_path("results/raw/ros2/r1.csv"), "results/raw/ros2/r1.publisher.csv")

    def test_detector_uses_one_clock_per_purpose(self):
        source = (PIPELINE_DIR / "mobilevit_detector_node.py").read_text(encoding="utf-8")
        publisher = (PIPELINE_DIR / "image_stream_node.py").read_text(encoding="utf-8")

        self.assertNotIn("get_clock()", source)
        self.assertNotIn("get_clock()", publisher)
        self.assertEqual(source.count("time.time_ns()"), 2)  # received + completed
        self.assertEqual(source.count("time.perf_counter_ns()"), 4)
        self.assertIn("published_at_ns = time.time_ns()", publisher)
        self.assertNotIn("last_seq_id + 1", source)
        self.assertNotIn("torch.randn", source)

    def test_v2_summary_reports_stage_timings(self):
        rows = [{"frame_id": i} for i in range(5)]
        summary = _summarise({"run_v2.csv": _v2_csv(rows)})[0]

        self.assertEqual(summary["timing_schema"], "v2")
        self.assertEqual(summary["avg_inference_ms"], "10")
        self.assertEqual(summary["avg_artificial_delay_ms"], "80")
        self.assertEqual(summary["avg_transport_ms"], "2")
        self.assertEqual(summary["avg_preprocess_ms"], "3")
        self.assertEqual(summary["p95_inference_ms"], "10")

    def test_legacy_timing_is_labelled(self):
        summary = _summarise({"a.csv": LEGACY_HEADER + _legacy(0)})[0]

        self.assertEqual(summary["timing_schema"], "legacy")
        self.assertEqual(summary["avg_artificial_delay_ms"], "")

    def test_warmup_rows_are_excluded_from_stats_and_window(self):
        rows = [{"frame_id": i, "run_id": "run_w", "warmup": "1", "latency_ms": "900"} for i in range(5, 8)]
        rows += [{"frame_id": i, "run_id": "run_w"} for i in range(8, 20)]
        summary = _summarise(
            {"run_w.csv": _v2_csv(rows), "run_w.publisher.csv": _publisher_csv("run_w", range(20))}
        )[0]

        self.assertEqual(summary["warmup_frames_excluded"], "3")
        self.assertEqual(summary["processed_frames"], "12")
        self.assertEqual(summary["published_frames"], "12")  # frames 8..19
        self.assertEqual(summary["dropped_frames"], "0")
        self.assertEqual(summary["p99_latency_ms"], "95")

    def test_cli_warmup_frames_applies_to_legacy_csv(self):
        body = LEGACY_HEADER + _legacy(0, latency="500") + _legacy(1) + _legacy(2) + _legacy(4)
        summary = _summarise({"a.csv": body}, warmup_frames=1)[0]

        self.assertEqual(summary["warmup_frames_excluded"], "1")
        self.assertEqual(summary["avg_latency_ms"], "20")
        self.assertEqual(summary["dropped_frames"], "1")  # frame 3


class CsvSchemaCompatibilityTest(unittest.TestCase):
    def test_all_detector_schema_generations_are_readable(self):
        pr_a1 = (
            "run_id,scenario,model_name,input_fps,qos_depth,fake_delay_ms,resource_profile,frame_id,"
            "published_at_ns,received_at_ns,completed_at_ns,latency_ms,inference_ms,deadline_miss,"
            "dropped,cpu_percent,memory_mb\n"
            "run_a1,fps_sweep,mobilevit_xxs,20.0,5,0,normal,0,0,0,0,20,10,0,0,50,300\n"
        )
        summary = _summarise(
            {"legacy.csv": LEGACY_HEADER + _legacy(0), "run_a1.csv": pr_a1, "run_v2.csv": _v2_csv([{"frame_id": 0}])}
        )

        self.assertEqual(len(summary), 3)
        self.assertEqual(sorted(row["timing_schema"] for row in summary), ["legacy", "legacy", "v2"])

    def test_cli_writes_extended_summary_columns_in_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw = Path(tmpdir, "raw")
            raw.mkdir()
            (raw / "r.csv").write_text(_v2_csv([{"run_id": "r", "frame_id": i} for i in range(4)]), encoding="utf-8")
            (raw / "r.publisher.csv").write_text(_publisher_csv("r", range(6)), encoding="utf-8")
            out = Path(tmpdir, "summary.csv")
            subprocess.run(
                [sys.executable, "-m", "src.ros2_runtime.analyze_runtime", "--input", str(raw),
                 "--summary-output", str(out), "--warmup-frames", "1"],
                cwd=REPO, check=True, capture_output=True, text=True,
            )
            with out.open(encoding="utf-8", newline="") as file:
                reader = csv.DictReader(file)
                header, rows = reader.fieldnames, list(reader)

        self.assertEqual(header, SUMMARY_FIELDS)
        self.assertEqual(header[:20], [
            "scenario", "model_name", "input_fps", "qos_depth", "fake_delay_ms", "resource_profile",
            "run_id", "total_rows", "processed_frames", "dropped_frames", "drop_rate_pct",
            "deadline_misses", "deadline_miss_rate_pct", "avg_latency_ms", "p95_latency_ms",
            "p99_latency_ms", "jitter_ms", "avg_inference_ms", "avg_cpu_percent", "avg_memory_mb",
        ])
        self.assertEqual((rows[0]["processed_frames"], rows[0]["dropped_frames"]), ("3", "2"))


class _Recorder:
    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs


class LaunchConfiguration:
    def __init__(self, name):
        self.name = name

    def perform(self, context):
        return context.launch_configurations[self.name]


def _stub_launch_modules():
    names = {
        "launch": ["LaunchDescription"],
        "launch.actions": ["DeclareLaunchArgument", "EmitEvent", "ExecuteProcess", "LogInfo",
                           "OpaqueFunction", "RegisterEventHandler"],
        "launch.event_handlers": ["OnProcessExit"],
        "launch.events": ["Shutdown"],
    }
    modules = {}
    for module_name, classes in names.items():
        module = types.ModuleType(module_name)
        for class_name in classes:
            setattr(module, class_name, type(class_name, (_Recorder,), {}))
        modules[module_name] = module
    substitutions = types.ModuleType("launch.substitutions")
    substitutions.LaunchConfiguration = LaunchConfiguration
    modules["launch.substitutions"] = substitutions
    return modules


class LaunchReliabilityTest(unittest.TestCase):
    def setUp(self):
        stubs = _stub_launch_modules()
        saved = {name: sys.modules.get(name) for name in stubs}
        sys.modules.update(stubs)
        self.addCleanup(lambda: [sys.modules.pop(n) if v is None else sys.modules.__setitem__(n, v) for n, v in saved.items()])
        self.launch = _load_module("launch_under_test", LAUNCH_FILE)

    def _actions(self, **overrides):
        description = self.launch.generate_launch_description()
        entities = description.args[0]
        defaults = {e.args[0]: e.kwargs["default_value"] for e in entities if type(e).__name__ == "DeclareLaunchArgument"}
        opaque = [e for e in entities if type(e).__name__ == "OpaqueFunction"][0]
        context = types.SimpleNamespace(launch_configurations={**defaults, **overrides})
        return opaque.kwargs["function"](context)

    @staticmethod
    def _params(process):
        cmd = process.kwargs["cmd"]
        return dict(cmd[i + 1].split(":=", 1) for i, part in enumerate(cmd) if part == "-p")

    def test_auto_run_id_is_resolved_once_and_shared(self):
        actions = self._actions()
        processes = [a for a in actions if type(a).__name__ == "ExecuteProcess"]
        publisher, detector = (self._params(p) for p in processes)

        self.assertNotEqual(detector["run_id"], "auto")
        self.assertEqual(publisher["run_id"], detector["run_id"])
        self.assertEqual(detector["output_csv"], f"results/raw/ros2/{detector['run_id']}.csv")
        self.assertEqual(publisher["output_csv"], f"results/raw/ros2/{detector['run_id']}.publisher.csv")
        self.assertEqual(detector["warmup_frames"], "10")

    def test_explicit_paths_are_passed_through(self):
        actions = self._actions(run_id="run_x", output_csv="out/run_x.csv", deadline_ms="50.0")
        publisher, detector = (self._params(a) for a in actions if type(a).__name__ == "ExecuteProcess")

        self.assertEqual(detector["output_csv"], "out/run_x.csv")
        self.assertEqual(publisher["output_csv"], "out/run_x.publisher.csv")
        self.assertEqual(detector["deadline_ms"], "50.0")

    def test_any_node_exit_shuts_down_the_launch(self):
        actions = self._actions(run_id="run_y")
        processes = [a for a in actions if type(a).__name__ == "ExecuteProcess"]
        handlers = [a for a in actions if type(a).__name__ == "RegisterEventHandler"]

        self.assertEqual(len(handlers), 2)
        targets = []
        for handler in handlers:
            on_exit = handler.args[0]
            self.assertEqual(type(on_exit).__name__, "OnProcessExit")
            targets.append(on_exit.kwargs["target_action"])
            events = [a for a in on_exit.kwargs["on_exit"] if type(a).__name__ == "EmitEvent"]
            self.assertEqual(type(events[0].kwargs["event"]).__name__, "Shutdown")
        self.assertCountEqual(targets, processes)


if __name__ == "__main__":
    unittest.main()
