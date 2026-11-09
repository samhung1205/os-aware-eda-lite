import json
import tempfile
import unittest
from pathlib import Path

from src.eda_lite.analyze_results import (
    build_summary_rows,
    load_result_rows,
    write_metric_svgs,
)
from src.eda_lite.cost_model import estimate_schedule_metrics, make_os_profiles
from src.eda_lite.model_loader import LayerProfile, load_model_profile
from src.eda_lite.run_profile_sweep import run_profile_sweep
from src.eda_lite.run_simulation import run_simulation
from src.eda_lite.schedulers import (
    dp_schedule,
    greedy_schedule,
    layerwise_schedule,
)


class EdaLiteTest(unittest.TestCase):
    def test_load_model_profile_from_json(self):
        profile = {
            "model_name": "unit_test_model",
            "layers": [
                {
                    "name": "conv1",
                    "op_type": "Conv",
                    "input_kb": 32,
                    "output_kb": 32,
                    "weight_kb": 16,
                    "compute_macs": 1000,
                    "fusible": True,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile.json"
            path.write_text(json.dumps(profile), encoding="utf-8")
            loaded = load_model_profile(path)

        self.assertEqual(loaded.model_name, "unit_test_model")
        self.assertEqual(len(loaded.layers), 1)
        self.assertEqual(loaded.layers[0].name, "conv1")

    def test_layerwise_uses_one_subgraph_per_layer(self):
        layers = _small_layers()
        result = layerwise_schedule(layers, sram_kb=256)

        self.assertEqual(len(result.subgraphs), len(layers))
        self.assertEqual(result.max_fusion_depth, 1)

    def test_greedy_schedule_respects_sram_limit(self):
        layers = _small_layers()
        result = greedy_schedule(layers, sram_kb=160)
        metrics = estimate_schedule_metrics(result.subgraphs, sram_kb=160)

        self.assertLessEqual(metrics.peak_sram_kb, 160)

    def test_dp_cost_is_not_worse_than_layerwise(self):
        layers = _small_layers()
        layerwise = layerwise_schedule(layers, sram_kb=256)
        dp = dp_schedule(layers, sram_kb=256)

        layerwise_cost = estimate_schedule_metrics(
            layerwise.subgraphs,
            sram_kb=256,
        ).os_aware_total_cost
        dp_cost = estimate_schedule_metrics(dp.subgraphs, sram_kb=256).os_aware_total_cost

        self.assertLessEqual(dp_cost, layerwise_cost)

    def test_non_fusible_layer_breaks_fusion(self):
        layers = (
            LayerProfile("a", "Conv", 32, 32, 16, 1000, True),
            LayerProfile("barrier", "Output", 32, 32, 16, 1000, False),
            LayerProfile("c", "Conv", 32, 32, 16, 1000, True),
        )

        result = greedy_schedule(layers, sram_kb=1024)

        self.assertEqual(result.max_fusion_depth, 1)
        self.assertEqual(len(result.subgraphs), 3)

    def test_dp_fusion_depth_does_not_decrease_with_more_sram(self):
        layers = _small_layers()
        small = dp_schedule(layers, sram_kb=128)
        large = dp_schedule(layers, sram_kb=512)

        self.assertLessEqual(small.max_fusion_depth, large.max_fusion_depth)

    def test_analysis_summary_selects_lowest_cost_scheduler(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "results.csv"
            input_path.write_text(_sample_results_csv(), encoding="utf-8")

            rows = load_result_rows(input_path)
            summary_rows = build_summary_rows(rows)

        self.assertEqual(len(summary_rows), 1)
        self.assertEqual(summary_rows[0]["best_scheduler"], "dp")
        self.assertEqual(summary_rows[0]["dram_reduction_pct"], "25")

    def test_analysis_writes_svg_figures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "results.csv"
            output_dir = Path(tmpdir) / "figures"
            input_path.write_text(_sample_results_csv(), encoding="utf-8")

            rows = load_result_rows(input_path)
            figure_paths = write_metric_svgs(rows, output_dir, os_profile="normal")

            self.assertEqual(len(figure_paths), 4)
            self.assertTrue((output_dir / "dram_traffic_by_sram.svg").exists())
            svg_text = (output_dir / "dram_traffic_by_sram.svg").read_text(encoding="utf-8")

        self.assertIn("<svg", svg_text)
        self.assertIn("DRAM traffic", svg_text)

    def test_analysis_requires_model_filter_for_multi_model_plots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "results.csv"
            output_dir = Path(tmpdir) / "figures"
            input_path.write_text(_sample_multi_model_results_csv(), encoding="utf-8")
            rows = load_result_rows(input_path)

            with self.assertRaisesRegex(ValueError, "one model at a time"):
                write_metric_svgs(rows, output_dir, os_profile="normal")

            figure_paths = write_metric_svgs(
                rows,
                output_dir,
                os_profile="normal",
                model_name="toy_b",
            )

            svg_text = figure_paths[0].read_text(encoding="utf-8")

        self.assertIn("toy_b", svg_text)
        self.assertNotIn("toy_a -", svg_text)

    def test_profile_sweep_runs_multiple_profiles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            _write_minimal_profile(tmp_path / "model_a.json", "model_a")
            _write_minimal_profile(tmp_path / "model_b.json", "model_b")
            config_path = tmp_path / "profile_sweep.json"
            config_path.write_text(
                json.dumps(
                    {
                        "profiles": ["model_a.json", "model_b.json"],
                        "simulation": {
                            "sram_kb": [128],
                            "schedulers": ["layerwise"],
                            "os_profiles": ["normal"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            rows = run_profile_sweep(config_path)

        self.assertEqual(len(rows), 2)
        self.assertEqual({row["model_name"] for row in rows}, {"model_a", "model_b"})

    def test_repository_edge_profile_sweep_config_runs(self):
        repo_root = Path(__file__).resolve().parents[1]
        rows = run_profile_sweep(repo_root / "experiments/eda_lite/edge_profile_sweep.json")

        self.assertEqual(len(rows), 72)
        self.assertEqual(
            {row["model_name"] for row in rows},
            {
                "edge_cnn_simplified_profile_estimate",
                "edge_cnn_large_simplified_profile_estimate",
            },
        )

    def test_repository_mobilevit_profiles_load(self):
        repo_root = Path(__file__).resolve().parents[1]
        xxs = load_model_profile(repo_root / "data/model_profiles/mobilevit_xxs_simplified.json")
        small = load_model_profile(repo_root / "data/model_profiles/mobilevit_s_simplified.json")

        self.assertEqual(xxs.model_name, "mobilevit_xxs_simplified_profile_estimate")
        self.assertEqual(small.model_name, "mobilevit_s_simplified_profile_estimate")
        self.assertTrue(any(not layer.fusible for layer in xxs.layers))
        self.assertTrue(any(layer.op_type == "TransformerAttention" for layer in small.layers))

    def test_repository_mobilevit_profile_sweep_config_runs(self):
        repo_root = Path(__file__).resolve().parents[1]
        rows = run_profile_sweep(repo_root / "experiments/eda_lite/mobilevit_profile_sweep.json")

        # 2 models x 4 SRAM sizes x 4 OS profiles (pure + 3 built-ins) x 3 schedulers.
        self.assertEqual(len(rows), 96)
        self.assertEqual(
            {row["model_name"] for row in rows},
            {
                "mobilevit_xxs_simplified_profile_estimate",
                "mobilevit_s_simplified_profile_estimate",
            },
        )

    def test_custom_os_profile_changes_schedule_cost(self):
        layers = _small_layers()
        schedule = layerwise_schedule(layers, sram_kb=256)
        os_profiles = make_os_profiles(
            {
                "runtime_pressure": {
                    "latency_multiplier": 2.0,
                    "deadline_miss_rate": 0.5,
                    "memory_pressure": 0.9,
                }
            }
        )

        normal_cost = estimate_schedule_metrics(
            schedule.subgraphs,
            sram_kb=256,
            os_profile_name="normal",
            os_profiles=os_profiles,
        ).os_aware_total_cost
        runtime_cost = estimate_schedule_metrics(
            schedule.subgraphs,
            sram_kb=256,
            os_profile_name="runtime_pressure",
            os_profiles=os_profiles,
        ).os_aware_total_cost

        self.assertGreater(runtime_cost, normal_cost)

    def test_custom_os_profile_drop_rate_changes_schedule_cost(self):
        layers = _small_layers()
        schedule = layerwise_schedule(layers, sram_kb=256)
        os_profiles = make_os_profiles(
            {
                "no_drop": {
                    "latency_multiplier": 1.0,
                    "deadline_miss_rate": 0.0,
                    "memory_pressure": 0.0,
                },
                "high_drop": {
                    "latency_multiplier": 1.0,
                    "deadline_miss_rate": 0.0,
                    "memory_pressure": 0.0,
                    "drop_rate": 0.5,
                },
            }
        )

        no_drop_cost = estimate_schedule_metrics(
            schedule.subgraphs,
            sram_kb=256,
            os_profile_name="no_drop",
            os_profiles=os_profiles,
        ).os_aware_total_cost
        high_drop_cost = estimate_schedule_metrics(
            schedule.subgraphs,
            sram_kb=256,
            os_profile_name="high_drop",
            os_profiles=os_profiles,
        ).os_aware_total_cost

        self.assertGreater(high_drop_cost, no_drop_cost)

    def test_runtime_aware_sweep_config_uses_os_profile_file(self):
        repo_root = Path(__file__).resolve().parents[1]
        rows = run_simulation(
            repo_root / "data/model_profiles/edge_cnn_simplified.json",
            repo_root / "experiments/eda_lite/edge_cnn_runtime_aware_sweep.json",
        )

        self.assertEqual(len(rows), 24)
        self.assertEqual(
            {row["os_profile"] for row in rows},
            {"runtime_normal_20fps_q5_d0", "runtime_overload_20fps_q5_d80"},
        )

    def test_mobilevit_runtime_aware_sweep_config_uses_os_profile_file(self):
        repo_root = Path(__file__).resolve().parents[1]
        os_profile_path = repo_root / "experiments/eda_lite/runtime_os_profiles.json"
        os_profile_payload = json.loads(os_profile_path.read_text(encoding="utf-8"))
        os_profile_names = os_profile_payload["os_profiles"]

        rows = run_simulation(
            repo_root / "data/model_profiles/mobilevit_xxs_simplified.json",
            repo_root / "experiments/eda_lite/mobilevit_runtime_aware_sweep.json",
        )

        self.assertEqual(len(rows), 4 * 3 * len(os_profile_names))
        self.assertEqual({row["os_profile"] for row in rows}, set(os_profile_names))
        self.assertTrue(all(name.startswith("measured_") for name in os_profile_names))


def _small_layers():
    return (
        LayerProfile("conv1", "Conv", 32, 32, 16, 12000000, True),
        LayerProfile("conv2", "Conv", 32, 48, 24, 18000000, True),
        LayerProfile("conv3", "Conv", 48, 32, 24, 16000000, True),
        LayerProfile("head", "Detect", 32, 16, 16, 8000000, False),
    )


def _sample_results_csv():
    return (
        "model_name,scheduler,sram_kb,os_profile,num_subgraphs,max_fusion_depth,"
        "peak_sram_kb,dram_traffic_kb,estimated_energy,estimated_latency_ms,"
        "os_aware_total_cost,subgraphs\n"
        "toy,layerwise,256,normal,3,1,120,400,410,10,450,a | b | c\n"
        "toy,greedy,256,normal,2,2,160,320,330,9,360,a+b | c\n"
        "toy,dp,256,normal,2,2,150,300,310,8,340,a | b+c\n"
    )


def _sample_multi_model_results_csv():
    header = (
        "model_name,scheduler,sram_kb,os_profile,num_subgraphs,max_fusion_depth,"
        "peak_sram_kb,dram_traffic_kb,estimated_energy,estimated_latency_ms,"
        "os_aware_total_cost,subgraphs\n"
    )
    return (
        header
        + "toy_a,layerwise,256,normal,1,1,120,400,410,10,450,a\n"
        + "toy_b,layerwise,256,normal,1,1,140,500,510,11,560,b\n"
    )


def _write_minimal_profile(path: Path, model_name: str) -> None:
    profile = {
        "model_name": model_name,
        "layers": [
            {
                "name": "conv",
                "op_type": "Conv",
                "input_kb": 16,
                "output_kb": 16,
                "weight_kb": 8,
                "compute_macs": 1000,
                "fusible": True,
            }
        ],
    }
    path.write_text(json.dumps(profile), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
