"""Regression tests for the fixes found by the Phase 2 / Batch 1 real ROS 2 smoke test.

Standard library only (no ROS 2): the node checks are source-level, like the other
pipeline tests, because rclpy is not installed in CI.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from src.provenance import sha256_file
from src.ros2_runtime.run_metadata import collect_run_metadata, dds_profile_info, read_effective_limits

REPO = Path(__file__).resolve().parents[1]
PIPELINE_DIR = REPO / "src/ros2_uav_pipeline/mobilevit_uav_pipeline"
FASTDDS_PROFILE = REPO / "experiments/ros2/fastdds_shm_large.xml"
WRAPPERS = (REPO / "scripts/run_baseline_experiments.sh", REPO / "scripts/run_os_tuned_experiments.sh")


class FloatParameterTypingTest(unittest.TestCase):
    """`ros2 launch ... input_fps:=5` arrives as INTEGER; DOUBLE-typed declarations rejected it."""

    def test_float_parameters_accept_integer_literals(self):
        for node, names in (("image_stream_node.py", ("input_fps",)),
                            ("mobilevit_detector_node.py", ("input_fps", "deadline_ms"))):
            source = (PIPELINE_DIR / node).read_text(encoding="utf-8")
            self.assertIn("ParameterDescriptor(dynamic_typing=True)", source, node)
            for name in names:
                match = re.search(rf"declare_parameter\('{name}', ([^\n]*)\)\n", source)
                self.assertIsNotNone(match, (node, name))
                self.assertTrue(
                    "dynamic_typing=True" in match.group(1) or "float_param" in match.group(1),
                    f"{node}: {name} must be declared with dynamic typing ({match.group(0).strip()})",
                )
                self.assertIn(f"float(self.get_parameter('{name}').value)", source, (node, name))


class StartupOrderingTest(unittest.TestCase):
    """Frames must not be published (and logged) before the detector is ready to receive them."""

    def test_detector_subscribes_only_after_model_and_csv_are_ready(self):
        source = (PIPELINE_DIR / "mobilevit_detector_node.py").read_text(encoding="utf-8")
        subscribe = source.index("self.create_subscription(Image, 'image_raw'")
        self.assertGreater(subscribe, source.index("create_model_strict(self.model_name"))
        self.assertGreater(subscribe, source.index("create_run_csv(self.log_file_path, DETECTOR_CSV_HEADER)"))
        self.assertEqual(source.count("create_subscription("), 1)

    def test_publisher_waits_for_a_subscriber_before_frame_zero(self):
        source = (PIPELINE_DIR / "image_stream_node.py").read_text(encoding="utf-8")
        callback = source[source.index("def timer_callback(self):"):]
        gate = callback.index("get_subscription_count() == 0")
        self.assertLess(gate, callback.index("self.publisher_.publish(msg)"))
        self.assertLess(gate, callback.index("self.publish_writer.writerow"))
        self.assertLess(gate, callback.index("self.seq_id += 1"))
        self.assertIn("self.streaming = False", source)
        self.assertIn("self.streaming = True", callback)


class DdsProfileTest(unittest.TestCase):
    def test_checked_in_profile_is_shm_only_with_large_segment(self):
        ns = {"f": "http://www.eprosima.com/xml/schemas/fastdds-profiles"}
        root = ET.parse(FASTDDS_PROFILE).getroot()
        descriptor = root.find("f:transport_descriptors/f:transport_descriptor", ns)
        self.assertEqual(descriptor.find("f:type", ns).text, "SHM")
        self.assertGreaterEqual(int(descriptor.find("f:segment_size", ns).text), 2 * 1024 * 1024)
        participant = root.find("f:participant", ns)
        self.assertEqual(participant.get("is_default_profile"), "true")
        self.assertEqual(participant.find("f:rtps/f:useBuiltinTransports", ns).text, "false")
        self.assertEqual(participant.find("f:rtps/f:userTransports/f:transport_id", ns).text,
                         descriptor.find("f:transport_id", ns).text)

    def test_metadata_records_profile_path_and_hash(self):
        info = dds_profile_info({"FASTRTPS_DEFAULT_PROFILES_FILE": str(FASTDDS_PROFILE)})
        self.assertEqual(info["path"], str(FASTDDS_PROFILE))
        self.assertEqual(info["sha256"], sha256_file(FASTDDS_PROFILE))
        self.assertTrue(info["parsed"]["shm_only"])
        self.assertEqual(info["parsed"]["shm_segment_size"], 16 * 1024 * 1024)
        self.assertIsNone(dds_profile_info({})["path"])
        missing = dds_profile_info({"FASTRTPS_DEFAULT_PROFILES_FILE": "/nonexistent/profile.xml"})
        self.assertIsNone(missing["sha256"])
        self.assertIn("not readable", missing["note"])
        meta = collect_run_metadata("r", "normal", effective={"cpus_allowed": [0], "memory_max_bytes": "max"})
        self.assertIn("dds_profile", meta)


class SwapLimitTest(unittest.TestCase):
    def test_swap_limit_is_recorded_but_does_not_change_the_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc, cg = Path(tmp) / "proc", Path(tmp) / "cg"
            (proc / "self").mkdir(parents=True)
            (proc / "self/cgroup").write_text("0::/user.slice/run-1.scope\n", encoding="utf-8")
            scope = cg / "user.slice/run-1.scope"
            scope.mkdir(parents=True)
            (scope / "memory.max").write_text("4294967296\n", encoding="utf-8")
            (scope / "memory.swap.max").write_text("0\n", encoding="utf-8")
            (cg / "user.slice/memory.swap.max").write_text("max\n", encoding="utf-8")
            limits = read_effective_limits(proc, cg, affinity=lambda: {12, 14})
            (scope / "memory.swap.max").write_text("max\n", encoding="utf-8")
            unlimited = read_effective_limits(proc, cg, affinity=lambda: {12, 14})
        self.assertEqual(limits["memory_swap_max_bytes"], 0)
        self.assertEqual(limits["memory_max_bytes"], 4 * 1024**3)
        self.assertEqual(unlimited["memory_swap_max_bytes"], "max")
        meta = collect_run_metadata("r", "normal", "12,14", "4G", effective=limits)
        self.assertEqual(meta["resource_limits"]["measurement_class"], "constrained")


class WrapperOptionsTest(unittest.TestCase):
    def test_wrappers_disable_swap_and_allow_narrow_smoke_runs(self):
        for path in WRAPPERS:
            text = path.read_text(encoding="utf-8")
            self.assertIn('MEMORY_SWAP_MAX="${MEMORY_SWAP_MAX-0}"', text, path)
            self.assertIn('${MEMORY_SWAP_MAX:+-p MemorySwapMax="$MEMORY_SWAP_MAX"}', text, path)
            self.assertIn('MODELS="${MODELS:-mobilevit_xxs mobilevit_s}"', text, path)
            self.assertIn('SWEEPS="${SWEEPS:-fps qos overload}"', text, path)
            for sweep in ("run_fps_sweep.sh", "run_qos_sweep.sh", "run_overload_sweep.sh"):
                self.assertIn(sweep, text, path)
            subprocess.run(["bash", "-n", str(path)], check=True)

    def test_unknown_sweep_name_is_rejected(self):
        # The tuned wrapper exits earlier on rmem_max; the baseline wrapper reaches the sweep loop,
        # whose `case` rejects the name before run_sweep (no taskset / systemd-run / ros2 is started).
        proc = subprocess.run(
            ["bash", str(WRAPPERS[0])], cwd=REPO, capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "MODELS": "mobilevit_xxs", "SWEEPS": "bogus",
                 "HOME": tempfile.gettempdir()},
        )
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("未知的 SWEEPS", proc.stderr)


if __name__ == "__main__":
    unittest.main()
