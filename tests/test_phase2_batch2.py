"""Phase 2 / Batch 2: runtime DDS probe, Fast DDS XML parsing, new summary columns.

Standard library only (no ROS 2); the probe logic is tested on fixed /proc-style text.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ros2_runtime.analyze_runtime import RuntimeRow, SUMMARY_FIELDS, build_runtime_summary
from src.ros2_runtime.run_metadata import parse_fastdds_profile
from src.ros2_runtime.runtime_probe import (
    cpu_times,
    evaluate_dds,
    parse_cpu_list,
    parse_stat,
    shm_segments_from_maps,
)

REPO = Path(__file__).resolve().parents[1]
FASTDDS_PROFILE = REPO / "experiments/ros2/fastdds_shm_large.xml"
SWEEPS = [REPO / f"experiments/ros2/run_{name}_sweep.sh" for name in ("fps", "qos", "overload")]


class FastDdsProfileParseTest(unittest.TestCase):
    def test_checked_in_profile_is_shm_only_16mib(self):
        parsed = parse_fastdds_profile(str(FASTDDS_PROFILE))
        self.assertTrue(parsed["valid_xml"])
        self.assertTrue(parsed["shm_only"])
        self.assertEqual(parsed["shm_segment_size"], 16 * 1024 * 1024)
        self.assertFalse(parsed["default_participant"]["use_builtin_transports"])

    def test_invalid_xml_and_udp_profile_are_not_shm_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp, "bad.xml")
            bad.write_text("<profiles><participant", encoding="utf-8")
            self.assertFalse(parse_fastdds_profile(str(bad))["valid_xml"])
            udp = Path(tmp, "udp.xml")
            udp.write_text(FASTDDS_PROFILE.read_text(encoding="utf-8").replace(
                "<type>SHM</type>", "<type>UDPv4</type>"), encoding="utf-8")
            self.assertFalse(parse_fastdds_profile(str(udp))["shm_only"])


class ProbeParsingTest(unittest.TestCase):
    def test_shm_segments_exclude_lock_files(self):
        maps = "\n".join([
            "7f00-7f10 rw-s 00000000 00:1a 11 /dev/shm/fastrtps_9428a9bd69c7b119",
            "7f10-7f20 rw-s 00000000 00:1a 12 /dev/shm/fastrtps_9428a9bd69c7b119_el",
            "7f20-7f30 rw-s 00000000 00:1a 13 /dev/shm/fastrtps_port29150",
            "7f30-7f40 r-xp 00000000 08:01 14 /usr/lib/libc.so.6",
            "7f40-7f50 rw-s 00000000 00:1a 15 /dev/shm/other_segment",
        ])
        self.assertEqual(shm_segments_from_maps(maps),
                         {"/dev/shm/fastrtps_9428a9bd69c7b119", "/dev/shm/fastrtps_port29150"})

    def test_parse_stat_handles_spaces_in_comm(self):
        text = "123 (python3 x) S 1 1 1 0 -1 0 0 0 0 0 250 50 0 0 30 10 12 0 100 0 0"
        self.assertEqual(parse_stat(text), {"utime": 250, "stime": 50, "nice": 10, "num_threads": 12})

    def test_cpu_list_and_times(self):
        self.assertEqual(parse_cpu_list("12,14-15"), [12, 14, 15])
        times = cpu_times("cpu  1 1 1 1 1 0 0 0\ncpu12 10 0 5 80 5 0 0 0 0 0\n")
        self.assertEqual(times, {12: (100, 85)})


class EvaluateDdsTest(unittest.TestCase):
    SEG = 16 * 1024 * 1024

    def _nodes(self, udp=0, sizes=(52400, 16802336)):
        return {role: {"samples": 5, "max_udp_sockets": udp, "shm_segment_sizes": list(sizes)}
                for role in ("publisher", "detector")}

    def test_verified_when_no_udp_and_large_segment(self):
        result = evaluate_dds(self._nodes(), self.SEG, True)
        self.assertTrue(result["verified"], result["reasons"])

    def test_udp_socket_or_default_segment_fails(self):
        self.assertFalse(evaluate_dds(self._nodes(udp=7), self.SEG, True)["verified"])
        result = evaluate_dds(self._nodes(sizes=(52400, 549408)), self.SEG, True)
        self.assertFalse(result["verified"])
        self.assertIn("512 KB", " ".join(result["reasons"]))

    def test_missing_process_fails_and_non_shm_profile_never_verifies(self):
        nodes = self._nodes()
        del nodes["detector"]
        self.assertFalse(evaluate_dds(nodes, self.SEG, True)["verified"])
        self.assertFalse(evaluate_dds(self._nodes(), None, False)["verified"])


class SweepScriptProbeWiringTest(unittest.TestCase):
    def test_every_sweep_starts_and_stops_the_probe_around_launch(self):
        for script in SWEEPS:
            text = script.read_text(encoding="utf-8")
            start = text.index('run_start_probe "$run_id" "$output_csv"')
            launch = text.index('"${timeout_cmd[@]}" ros2 launch')
            stop = text.index("run_stop_probe")
            finish = text.index("run_finish")
            self.assertLess(start, launch, script.name)
            self.assertLess(launch, stop, script.name)
            self.assertLess(stop, finish, script.name)

    def test_failed_runs_rename_probe_and_unverified_profile_fails(self):
        common = (REPO / "experiments/ros2/run_common.sh").read_text(encoding="utf-8")
        self.assertIn('"${output_csv%.csv}.probe.json"; do\n    if [[ -e "$path" ]]; then\n      mv', common)
        self.assertIn('reason="$(_probe_check "$output_csv")"', common)
        self.assertIn("無法於執行期驗證", common)
        wrapper = (REPO / "scripts/run_baseline_experiments.sh").read_text(encoding="utf-8")
        self.assertIn('nice -n "$NICE_LEVEL" bash "$script_path"', wrapper)
        self.assertIn("export RMW_IMPLEMENTATION=rmw_fastrtps_cpp", wrapper)


class SummaryRateColumnsTest(unittest.TestCase):
    def _row(self, frame_id, published_ns, completed_ns, dropped=False):
        return RuntimeRow(
            scenario="fps_sweep", model_name="m", input_fps="10.0", qos_depth="5", fake_delay_ms="0",
            resource_profile="normal", frame_id=frame_id,
            latency_ms=None if dropped else (completed_ns - published_ns) / 1e6,
            inference_ms=None if dropped else 20.0, deadline_miss=False, dropped=dropped,
            cpu_percent=10.0, memory_mb=100.0 + frame_id, run_id="r1", deadline_ms=100.0,
            transport_ms=None if dropped else 1.0, preprocess_ms=None if dropped else 0.5,
            artificial_delay_ms=None if dropped else 30.0, timing_schema="v2",
            published_at_ns=published_ns, completed_at_ns=None if dropped else completed_ns,
        )

    def test_offered_and_processed_fps_and_p50(self):
        period = 100_000_000  # 10 FPS offered
        rows = [self._row(i, i * period, i * period + 50_000_000) for i in range(0, 11, 2)]
        publisher = {"r1": list(range(11))}
        times = {"r1": {i: i * period for i in range(11)}}
        (summary,) = build_runtime_summary(rows, publisher_frames=publisher, publisher_times=times)
        self.assertAlmostEqual(float(summary["offered_fps"]), 10.0, places=6)
        self.assertAlmostEqual(float(summary["processed_fps"]), 5.0, places=6)
        self.assertAlmostEqual(float(summary["p50_latency_ms"]), 50.0)
        self.assertAlmostEqual(float(summary["avg_service_ms"]), 50.5)
        self.assertEqual(summary["max_memory_mb"], "110")
        self.assertEqual(summary["dropped_frames"], "5")
        start = SUMMARY_FIELDS.index("p50_latency_ms")  # Batch 2 block, later batches append after it
        self.assertEqual(SUMMARY_FIELDS[start:start + 8], [
            "p50_latency_ms", "p50_transport_ms", "p95_transport_ms", "p50_inference_ms",
            "avg_service_ms", "offered_fps", "processed_fps", "max_memory_mb"])

    def test_rates_empty_without_timestamps(self):
        rows = [self._row(0, 0, 1), self._row(1, 1, 2)]
        rows = [RuntimeRow(**{**r.__dict__, "completed_at_ns": None}) for r in rows]
        (summary,) = build_runtime_summary(rows)
        self.assertEqual(summary["processed_fps"], "")
        self.assertEqual(summary["offered_fps"], "")


if __name__ == "__main__":
    unittest.main()


class AggregateBaselineTest(unittest.TestCase):
    def test_derive_separates_overload_from_below_capacity_loss(self):
        from src.ros2_runtime.aggregate_baseline import derive

        over = derive({"avg_service_ms": "64", "offered_fps": "30", "drop_rate_pct": "48"})
        self.assertEqual(over["drop_cause"], "overload")
        self.assertAlmostEqual(float(over["utilization"]), 1.92)
        self.assertAlmostEqual(float(over["expected_overload_drop_pct"]), 100 * (1 - 1 / 1.92), places=2)
        self.assertEqual(derive({"avg_service_ms": "19", "offered_fps": "30", "drop_rate_pct": "2"})["drop_cause"],
                         "below_capacity")
        self.assertEqual(derive({"avg_service_ms": "19", "offered_fps": "30", "drop_rate_pct": "0"})["drop_cause"], "none")
        self.assertEqual(derive({"avg_service_ms": "", "offered_fps": "30", "drop_rate_pct": "0"})["drop_cause"], "unknown")

    def test_conditions_use_runs_as_replicates(self):
        from src.ros2_runtime.aggregate_baseline import build_conditions

        base = {"scenario": "fps_sweep", "model_name": "m", "input_fps": "5.0", "qos_depth": "5",
                "fake_delay_ms": "0", "dds_verified": "true", "measurement_class": "constrained",
                "drop_cause": "none"}
        runs = [dict(base, run_id=f"r{i}", p50_latency_ms=str(v)) for i, v in enumerate((10, 12, 14))]
        (cond,) = build_conditions(runs)
        self.assertEqual(cond["n_runs"], 3)
        self.assertEqual(cond["p50_latency_ms_mean"], "12")
        self.assertEqual(cond["p50_latency_ms_sd"], "2")
        self.assertEqual((cond["p50_latency_ms_min"], cond["p50_latency_ms_max"]), ("10", "14"))
        self.assertEqual(cond["all_dds_verified"], "true")


class NodeExitWaitTest(unittest.TestCase):
    def test_stop_probe_waits_for_nodes_and_probe_resets_cpu_on_pid_change(self):
        common = (REPO / "experiments/ros2/run_common.sh").read_text(encoding="utf-8")
        body = common[common.index("run_stop_probe() {"):]
        self.assertLess(body.index("_wait_nodes_exit"), body.index("kill -TERM"))
        probe = (REPO / "src/ros2_runtime/runtime_probe.py").read_text(encoding="utf-8")
        change = probe[probe.index('if node["pid"] != pid:'):probe.index("ticks = stat")]
        self.assertIn('node["first"] = None', change)
