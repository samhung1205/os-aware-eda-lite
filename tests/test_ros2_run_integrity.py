"""Regression tests for P0-2: ROS2 runtime runs must never be mixed silently.

Covers the detector logger helpers, the sweep scripts (with fake ``ros2`` and
``timeout`` executables, so no ROS2 install is needed), and the runtime analyzer.
"""

import ast
import csv
import importlib.util
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.ros2_runtime.analyze_runtime import (
    build_runtime_summary,
    load_runtime_rows,
    write_runtime_summary,
    write_runtime_svgs,
)
from src.ros2_runtime.build_os_profiles import build_os_profile_payload

REPO = Path(__file__).resolve().parents[1]
PIPELINE_DIR = REPO / "src/ros2_uav_pipeline/mobilevit_uav_pipeline"

HEADER = (
    "run_id,scenario,model_name,input_fps,qos_depth,fake_delay_ms,resource_profile,"
    "frame_id,latency_ms,inference_ms,deadline_miss,dropped,cpu_percent,memory_mb\n"
)
LEGACY_HEADER = HEADER.split(",", 1)[1]


def _row(frame_id, run_id="", fps="20.0", resource_profile="normal", latency="20"):
    prefix = f"{run_id}," if run_id is not None else ""
    return (
        f"{prefix}qos_sweep,mobilevit_xxs,{fps},5,0,{resource_profile},"
        f"{frame_id},{latency},10,0,0,50,300\n"
    )


def _legacy_rows(frame_ids):
    return "".join(_row(i, run_id=None) for i in frame_ids)


def _run_rows(run_id, frame_ids, **kwargs):
    return "".join(_row(i, run_id=run_id, **kwargs) for i in frame_ids)


def _summarise(files):
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, body in files.items():
            (Path(tmpdir) / name).write_text(body, encoding="utf-8")
        return build_runtime_summary(load_runtime_rows([tmpdir]))


def _load_run_log():
    spec = importlib.util.spec_from_file_location("run_log_under_test", PIPELINE_DIR / "run_log.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnalyzerRunSeparationTest(unittest.TestCase):
    def test_repeated_runs_with_run_ids_are_summarised_per_run(self):
        summary = _summarise(
            {
                "run_a.csv": HEADER + _run_rows("run_a", range(0, 100, 2)),
                "run_b.csv": HEADER + _run_rows("run_b", range(100)),
            }
        )

        self.assertEqual([row["run_id"] for row in summary], ["run_a", "run_b"])
        by_run = {row["run_id"]: row for row in summary}
        self.assertEqual(by_run["run_a"]["processed_frames"], "50")
        self.assertEqual(by_run["run_a"]["dropped_frames"], "49")
        self.assertEqual(by_run["run_a"]["drop_rate_pct"], "49.4949")
        self.assertEqual(by_run["run_b"]["processed_frames"], "100")
        self.assertEqual(by_run["run_b"]["dropped_frames"], "0")

    def test_two_run_ids_in_one_file_are_separated(self):
        summary = _summarise(
            {"merged.csv": HEADER + _run_rows("run_a", range(0, 10, 2)) + _run_rows("run_b", range(10))}
        )

        self.assertEqual(len(summary), 2)
        by_run = {row["run_id"]: row for row in summary}
        self.assertEqual(by_run["run_a"]["dropped_frames"], "4")
        self.assertEqual(by_run["run_b"]["dropped_frames"], "0")

    def test_duplicate_frame_id_within_one_run_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r"run_id 'run_a'.*duplicate frame_id 5"):
            _summarise({"run_a.csv": HEADER + _run_rows("run_a", [3, 4, 5, 5, 6])})

    def test_same_run_id_copied_into_two_files_is_rejected(self):
        body = HEADER + _run_rows("run_a", range(10))
        with self.assertRaises(ValueError) as context:
            _summarise({"run_a.csv": body, "run_a_copy.csv": body})

        message = str(context.exception)
        self.assertIn("duplicate frame_id", message)
        self.assertIn("run_a.csv", message)
        self.assertIn("run_a_copy.csv", message)

    def test_run_id_reused_for_different_configurations_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r"run_id 'run_a' is used by 2 configurations"):
            _summarise(
                {
                    "a.csv": HEADER + _run_rows("run_a", range(5), fps="10.0"),
                    "b.csv": HEADER + _run_rows("run_a", range(5), fps="20.0"),
                }
            )

    def test_rows_are_never_silently_deduplicated(self):
        """The P0-2 reproduction: two appended runs used to report 0% drops."""

        with self.assertRaisesRegex(ValueError, r"legacy CSV without run_id.*duplicate frame_id"):
            _summarise({"appended.csv": LEGACY_HEADER + _legacy_rows(range(0, 100, 2)) + _legacy_rows(range(100))})


class LegacyCsvCompatibilityTest(unittest.TestCase):
    def test_clean_legacy_csv_is_one_run_per_file(self):
        summary = _summarise(
            {
                "first.csv": LEGACY_HEADER + _legacy_rows(range(0, 10, 2)),
                "second.csv": LEGACY_HEADER + _legacy_rows(range(10)),
            }
        )

        self.assertEqual(len(summary), 2)
        by_file = {Path(row["run_id"]).name: row for row in summary}
        self.assertTrue(all(row["run_id"].startswith("legacy:") for row in summary))
        self.assertEqual(by_file["first.csv"]["dropped_frames"], "4")
        self.assertEqual(by_file["second.csv"]["dropped_frames"], "0")

    def test_legacy_file_with_frame_id_restart_is_rejected(self):
        # Two appended runs whose frame_ids do not overlap: no duplicate, but a reset.
        body = LEGACY_HEADER + _legacy_rows(range(50, 100)) + _legacy_rows(range(0, 30))
        with self.assertRaisesRegex(ValueError, r"frame_id goes back from 99 to 0"):
            _summarise({"appended.csv": body})

    def test_legacy_file_with_baseline_and_tuned_rows_stays_separable(self):
        # Old scripts wrote normal and tuned runs into the same file name.
        body = (
            LEGACY_HEADER
            + "".join(_row(i, run_id=None, resource_profile="normal") for i in range(10))
            + "".join(_row(i, run_id=None, resource_profile="tuned") for i in range(0, 10, 2))
        )
        summary = _summarise({"shared.csv": body})

        self.assertEqual([row["resource_profile"] for row in summary], ["normal", "tuned"])
        self.assertEqual([row["dropped_frames"] for row in summary], ["0", "4"])


class SummaryOutputTest(unittest.TestCase):
    def test_summary_csv_and_figures_carry_run_identity(self):
        summary = _summarise(
            {
                "run_a.csv": HEADER + _run_rows("run_a", range(5)),
                "run_b.csv": HEADER + _run_rows("run_b", range(5)),
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.csv"
            write_runtime_summary(summary_path, summary)
            with summary_path.open(encoding="utf-8", newline="") as file:
                written = list(csv.DictReader(file))
            write_runtime_svgs(summary, Path(tmpdir) / "figures")
            svg_text = (Path(tmpdir) / "figures/ros2_avg_latency.svg").read_text(encoding="utf-8")

        self.assertEqual([row["run_id"] for row in written], ["run_a", "run_b"])
        self.assertIn("d0 run1", svg_text)
        self.assertIn("d0 run2", svg_text)

    def test_os_profiles_keep_repeated_runs_distinct(self):
        summary = _summarise(
            {
                "run_a.csv": HEADER + _run_rows("run_a", range(5)),
                "run_b.csv": HEADER + _run_rows("run_b", range(5)),
            }
        )
        payload = build_os_profile_payload(summary, profile_prefix="measured")

        self.assertEqual(len(set(payload["os_profiles"])), 2)


class DetectorRunLogTest(unittest.TestCase):
    def setUp(self):
        self.run_log = _load_run_log()

    def test_auto_run_ids_are_unique_and_explicit_ids_are_kept(self):
        generated = {self.run_log.resolve_run_id("auto") for _ in range(20)}
        self.assertEqual(len(generated), 20)
        self.assertRegex(self.run_log.resolve_run_id(""), r"^\d{8}T\d{6}_\d+_[0-9a-f]{8}$")
        self.assertEqual(self.run_log.resolve_run_id(" run_a.1 "), "run_a.1")

    def test_invalid_run_id_is_rejected(self):
        for value in ("../escape", "a b", "-leading-dash", "a/b"):
            with self.assertRaises(ValueError, msg=value):
                self.run_log.resolve_run_id(value)

    def test_auto_output_csv_uses_run_id(self):
        self.assertEqual(
            self.run_log.resolve_output_csv("auto", "run_a"),
            os.path.join("results", "raw", "ros2", "run_a.csv"),
        )
        self.assertEqual(self.run_log.resolve_output_csv("custom/x.csv", "run_a"), "custom/x.csv")

    def test_existing_csv_is_never_appended_or_overwritten(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "nested", "run_a.csv")
            self.run_log.create_run_csv(path, ["run_id", "frame_id"])
            with open(path, "a", encoding="utf-8") as file:
                file.write("run_a,0\n")
            before = Path(path).read_text(encoding="utf-8")

            with self.assertRaisesRegex(FileExistsError, "Refusing to append to or overwrite"):
                self.run_log.create_run_csv(path, ["run_id", "frame_id"])

            self.assertEqual(Path(path).read_text(encoding="utf-8"), before)

    def test_detector_header_and_launch_file_include_run_id(self):
        node_source = (PIPELINE_DIR / "mobilevit_detector_node.py").read_text(encoding="utf-8")
        header = None
        for node in ast.parse(node_source).body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "CSV_HEADER":
                header = ast.literal_eval(node.value)
        self.assertIsNotNone(header)
        self.assertEqual(header[0], "run_id")
        self.assertIn("create_run_csv(self.log_file_path, CSV_HEADER)", node_source)
        self.assertIn("self.run_id, self.scenario", node_source)

        launch_source = (REPO / "src/ros2_uav_pipeline/launch/mobilevit_uav_pipeline.launch.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("DeclareLaunchArgument('run_id'", launch_source)
        self.assertIn("['run_id:=', LaunchConfiguration('run_id')]", launch_source)


FAKE_TIMEOUT = """#!/usr/bin/env bash
shift
exec "$@"
"""

# Emulates the detector: writes one CSV per launch and refuses to clobber it.
FAKE_ROS2 = """#!/usr/bin/env bash
set -euo pipefail
set -o noclobber
for arg in "$@"; do
  case "$arg" in
    output_csv:=*) out="${arg#output_csv:=}" ;;
    run_id:=*) run_id="${arg#run_id:=}" ;;
    scenario:=*) scenario="${arg#scenario:=}" ;;
    model_name:=*) model="${arg#model_name:=}" ;;
    input_fps:=*) fps="${arg#input_fps:=}" ;;
    qos_depth:=*) qos="${arg#qos_depth:=}" ;;
    fake_inference_delay_ms:=*) delay="${arg#fake_inference_delay_ms:=}" ;;
    resource_profile:=*) rp="${arg#resource_profile:=}" ;;
  esac
done
echo "$run_id" >> "$FAKE_ROS2_LOG"
{
  echo "run_id,scenario,model_name,input_fps,qos_depth,fake_delay_ms,resource_profile,frame_id,latency_ms,dropped"
  for i in 0 1 2 4; do echo "$run_id,$scenario,$model,$fps,$qos,$delay,$rp,$i,20,0"; done
} > "$out"
"""

SWEEPS = {
    "run_fps_sweep.sh": ("fps_sweep", {"FPS_VALUES": "5 10"}),
    "run_qos_sweep.sh": ("qos_sweep", {"QOS_VALUES": "1 5"}),
    "run_overload_sweep.sh": ("overload_sweep", {"DELAY_VALUES_MS": "0 30"}),
}


@unittest.skipIf(shutil.which("bash") is None, "bash is required for sweep script tests")
class SweepScriptRunIdTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.bin_dir = root / "bin"
        self.bin_dir.mkdir()
        for name, body in (("ros2", FAKE_ROS2), ("timeout", FAKE_TIMEOUT)):
            path = self.bin_dir / name
            path.write_text(body, encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.results_dir = root / "raw"
        self.log = root / "ros2_calls.log"

    def _run(self, script, extra_env, run_tag=None):
        env = {
            **os.environ,
            "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "RESULTS_DIR": str(self.results_dir),
            "RUN_SECONDS": "1",
            "ROS2_SETUP": "",
            "MODEL_NAME": "mobilevit_xxs",
            "RESOURCE_PROFILE": "normal",
            "FAKE_ROS2_LOG": str(self.log),
            **extra_env,
        }
        env.pop("RUN_TAG", None)
        if run_tag is not None:
            env["RUN_TAG"] = run_tag
        return subprocess.run(
            ["bash", str(REPO / "experiments/ros2" / script)],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_repeated_sweeps_write_separate_csvs_that_analyze_per_run(self):
        for script, (scenario, extra_env) in SWEEPS.items():
            with self.subTest(script=script):
                first = self._run(script, extra_env)
                second = self._run(script, extra_env)
                self.assertEqual(first.returncode, 0, first.stderr)
                self.assertEqual(second.returncode, 0, second.stderr)

                csvs = sorted(self.results_dir.glob(f"{scenario}_*.csv"))
                self.assertEqual(len(csvs), 4)
                for path in csvs:
                    self.assertIn("_normal_", path.name)
                    with path.open(encoding="utf-8", newline="") as file:
                        run_ids = {row["run_id"] for row in csv.DictReader(file)}
                    self.assertEqual(run_ids, {path.stem})

                summary = build_runtime_summary(load_runtime_rows(csvs))
                self.assertEqual(len(summary), 4)
                self.assertEqual(len({row["run_id"] for row in summary}), 4)
                self.assertTrue(all(row["dropped_frames"] == "1" for row in summary))

    def test_reused_run_tag_refuses_to_touch_existing_csv(self):
        for script, (scenario, extra_env) in SWEEPS.items():
            with self.subTest(script=script):
                first = self._run(script, extra_env, run_tag=f"fixed_{scenario}")
                self.assertEqual(first.returncode, 0, first.stderr)
                existing = sorted(self.results_dir.glob(f"{scenario}_*_fixed_{scenario}.csv"))
                self.assertEqual(len(existing), 2)
                before = {path: path.read_text(encoding="utf-8") for path in existing}
                calls_before = self.log.read_text(encoding="utf-8").count("\n")

                second = self._run(script, extra_env, run_tag=f"fixed_{scenario}")

                self.assertEqual(second.returncode, 1)
                self.assertIn("拒絕 append 或覆寫", second.stderr)
                self.assertEqual({path: path.read_text(encoding="utf-8") for path in existing}, before)
                self.assertEqual(self.log.read_text(encoding="utf-8").count("\n"), calls_before)

    def test_invalid_run_tag_is_rejected_before_launch(self):
        result = self._run("run_fps_sweep.sh", {"FPS_VALUES": "5"}, run_tag="bad tag/..")

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
