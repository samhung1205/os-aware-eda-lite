import tempfile
import unittest
from pathlib import Path

from src.ros2_runtime.analyze_runtime import (
    build_runtime_summary,
    load_runtime_rows,
    write_runtime_svgs,
)
from src.ros2_runtime.build_os_profiles import build_os_profile_payload


class Ros2RuntimeAnalysisTest(unittest.TestCase):
    def test_runtime_summary_uses_latency_and_deadline_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "runtime.csv"
            input_path.write_text(_sample_runtime_csv_with_latency(), encoding="utf-8")

            rows = load_runtime_rows([input_path])
            summary_rows = build_runtime_summary(rows)

        self.assertEqual(len(summary_rows), 1)
        summary = summary_rows[0]
        self.assertEqual(summary["processed_frames"], "3")
        self.assertEqual(summary["dropped_frames"], "1")
        self.assertEqual(summary["total_rows"], "4")
        self.assertEqual(summary["drop_rate_pct"], "25")
        self.assertEqual(summary["deadline_misses"], "1")
        self.assertEqual(summary["deadline_miss_rate_pct"], "33.3333")
        self.assertEqual(summary["avg_latency_ms"], "50")
        self.assertEqual(summary["p95_latency_ms"], "80")
        self.assertEqual(summary["p99_latency_ms"], "80")

    def test_runtime_summary_can_derive_latency_from_timestamps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "runtime.csv"
            input_path.write_text(_sample_runtime_csv_with_timestamps(), encoding="utf-8")

            rows = load_runtime_rows([input_path])
            summary_rows = build_runtime_summary(rows)

        self.assertEqual(summary_rows[0]["processed_frames"], "2")
        self.assertEqual(summary_rows[0]["avg_latency_ms"], "20")
        self.assertEqual(summary_rows[0]["deadline_misses"], "1")

    def test_runtime_summary_can_infer_drops_from_frame_id_gaps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "runtime.csv"
            input_path.write_text(_sample_runtime_csv_with_frame_gap(), encoding="utf-8")

            rows = load_runtime_rows([input_path])
            summary_rows = build_runtime_summary(rows)

        summary = summary_rows[0]
        self.assertEqual(summary["processed_frames"], "3")
        self.assertEqual(summary["dropped_frames"], "2")
        self.assertEqual(summary["total_rows"], "5")
        self.assertEqual(summary["drop_rate_pct"], "40")

    def test_runtime_analysis_writes_svg_figures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "runtime.csv"
            figures_dir = tmp_path / "figures"
            input_path.write_text(_sample_runtime_csv_with_latency(), encoding="utf-8")

            rows = load_runtime_rows([input_path])
            summary_rows = build_runtime_summary(rows)
            figure_paths = write_runtime_svgs(summary_rows, figures_dir)

            self.assertEqual(len(figure_paths), 4)
            svg_text = (figures_dir / "ros2_avg_latency.svg").read_text(encoding="utf-8")

        self.assertIn("<svg", svg_text)
        self.assertIn("Average latency", svg_text)

    def test_build_os_profiles_from_runtime_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "runtime.csv"
            input_path.write_text(_sample_runtime_csv_with_latency(), encoding="utf-8")
            rows = load_runtime_rows([input_path])
            summary_rows = build_runtime_summary(rows)

        payload = build_os_profile_payload(
            summary_rows,
            baseline_latency_ms=25,
            memory_reference_mb=1000,
            profile_prefix="measured",
        )

        self.assertEqual(len(payload["os_profiles"]), 1)
        profile_name = payload["os_profiles"][0]
        profile = payload["os_profile_definitions"][profile_name]
        self.assertTrue(profile_name.startswith("measured_fps_sweep"))
        self.assertEqual(profile["latency_multiplier"], 2.0)
        self.assertEqual(profile["deadline_miss_rate"], 0.333333)
        self.assertEqual(profile["memory_pressure"], 0.5225)
        self.assertEqual(profile["drop_rate"], 0.25)

    def test_build_os_profiles_defaults_missing_drop_rate_to_zero(self):
        payload = build_os_profile_payload(
            [
                {
                    "scenario": "compat",
                    "model_name": "mobilevit_xxs",
                    "input_fps": "20",
                    "qos_depth": "5",
                    "fake_delay_ms": "0",
                    "resource_profile": "normal",
                    "avg_latency_ms": "10",
                    "deadline_miss_rate_pct": "0",
                    "avg_memory_mb": "128",
                }
            ],
            baseline_latency_ms=10,
            memory_reference_mb=256,
            profile_prefix="runtime",
        )

        profile_name = payload["os_profiles"][0]
        profile = payload["os_profile_definitions"][profile_name]
        self.assertEqual(profile["drop_rate"], 0.0)


def _sample_runtime_csv_with_latency():
    return (
        "scenario,model_name,input_fps,qos_depth,fake_delay_ms,resource_profile,"
        "frame_id,latency_ms,inference_ms,deadline_ms,deadline_miss,dropped,"
        "cpu_percent,memory_mb\n"
        "fps_sweep,mobilevit_xxs,20,5,0,normal,1,30,20,70,0,0,40,512\n"
        "fps_sweep,mobilevit_xxs,20,5,0,normal,2,40,25,70,0,0,45,520\n"
        "fps_sweep,mobilevit_xxs,20,5,0,normal,3,80,55,70,1,0,50,530\n"
        "fps_sweep,mobilevit_xxs,20,5,0,normal,4,,0,70,0,1,48,528\n"
    )


def _sample_runtime_csv_with_timestamps():
    return (
        "scenario,model_name,input_fps,qos_depth,fake_delay_ms,resource_profile,"
        "frame_id,published_at_ns,completed_at_ns,inference_ms,deadline_ms,"
        "deadline_miss,dropped,cpu_percent,memory_mb\n"
        "qos_sweep,mobilevit_xxs,20,1,0,normal,1,1000000000,1010000000,8,25,0,0,40,512\n"
        "qos_sweep,mobilevit_xxs,20,1,0,normal,2,2000000000,2030000000,20,25,0,0,42,516\n"
    )


def _sample_runtime_csv_with_frame_gap():
    return (
        "scenario,model_name,input_fps,qos_depth,fake_delay_ms,resource_profile,"
        "frame_id,latency_ms,inference_ms,deadline_ms,deadline_miss,dropped,"
        "cpu_percent,memory_mb\n"
        "fps_sweep,mobilevit_xxs,30,5,0,normal,1,15,10,33.3,0,0,40,512\n"
        "fps_sweep,mobilevit_xxs,30,5,0,normal,2,16,11,33.3,0,0,42,514\n"
        "fps_sweep,mobilevit_xxs,30,5,0,normal,5,18,12,33.3,0,0,44,516\n"
    )


if __name__ == "__main__":
    unittest.main()
