"""Phase 1 / Batch 2 regression tests: scheduling and cost-model correctness.

Covers audit items P0-1 (DP objective), P1-1 (greedy pruning), P1-2 (sweep
robustness), P1-3 (pure profile, ties, profile selection, sensitivity) and the
EDA-Lite side of P1-4 (deadline uses the effective latency).
"""

import csv
import itertools
import json
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.eda_lite.analyze_results import (
    build_summary_rows,
    load_result_rows,
    write_metric_svgs,
)
from src.eda_lite.cost_model import (
    OS_PROFILES,
    CostConfig,
    estimate_schedule_metrics,
    make_cost_config,
    make_os_profiles,
)
from src.eda_lite.model_loader import LayerProfile, load_model_profile
from src.eda_lite.run_profile_sweep import run_profile_sweep
from src.eda_lite.run_simulation import (
    CSV_FIELDS,
    run_simulation_with_config,
    write_simulation_csv,
)
from src.eda_lite.schedulers import (
    EXHAUSTIVE_MAX_LAYERS,
    InfeasibleScheduleError,
    costs_tie,
    dp_schedule,
    exhaustive_schedule,
    greedy_schedule,
    is_feasible_subgraph,
    layerwise_schedule,
    serialize_subgraphs,
)

REPO = Path(__file__).resolve().parents[1]
XXS = REPO / "data/model_profiles/mobilevit_xxs_simplified.json"
SMALL = REPO / "data/model_profiles/mobilevit_s_simplified.json"
SRAM_CFG = REPO / "experiments/eda_lite/mobilevit_sram_sweep.json"


def _cost(schedule, sram, profile="normal", config=None, profiles=None):
    return estimate_schedule_metrics(
        schedule.subgraphs, sram, profile, config, profiles
    ).os_aware_total_cost


def _brute_force_min(layers, sram, profile, config, profiles):
    """Independent oracle: score every partition with estimate_schedule_metrics."""

    n = len(layers)
    best = None
    for cuts in itertools.product((False, True), repeat=n - 1):
        bounds = [0] + [i for i, cut in enumerate(cuts, 1) if cut] + [n]
        parts = [tuple(layers[a:b]) for a, b in zip(bounds, bounds[1:])]
        if all(is_feasible_subgraph(p, sram, config) for p in parts):
            cost = estimate_schedule_metrics(parts, sram, profile, config, profiles).os_aware_total_cost
            best = cost if best is None else min(best, cost)
    return best


def _random_case(rng):
    n = rng.randint(1, 8)
    layers = tuple(
        LayerProfile(
            f"l{i}",
            "Conv",
            rng.choice([8, 16, 32, 64, 128, 150]),
            rng.choice([8, 16, 32, 64, 128, 150]),
            rng.choice([1, 16, 64, 128]),
            rng.choice([1e6, 5e7, 3e8, 1e9]),
            rng.random() > 0.15,
        )
        for i in range(n)
    )
    profiles = make_os_profiles(
        {
            "x": {
                "latency_multiplier": rng.choice([0.0, 1.0, 1.5, 3.0]),
                "deadline_miss_rate": rng.choice([0.0, 0.3, 1.0]),
                "memory_pressure": rng.choice([0.0, 0.5, 1.0]),
                "drop_rate": rng.choice([0.0, 0.2]),
            }
        }
    )
    config = make_cost_config(
        {
            "deadline_ms": rng.choice([0.0, 2.0, 5.0, 10.0, 30.0]),
            "beta": rng.choice([0.0, 100.0, 1000.0]),
            "gamma": rng.choice([0.0, 50.0, 5000.0]),
            "subgraph_overhead_ms": rng.choice([0.0, 0.02, 2.0]),
        }
    )
    sram = rng.choice([100, 200, 300, 500, 10_000])
    return layers, sram, config, profiles


class DpObjectiveTest(unittest.TestCase):
    """P0-1: dp minimises exactly the reported os_aware_total_cost."""

    def test_dp_matches_exhaustive_oracle_on_random_models(self):
        rng = random.Random(20261110)
        checked = 0
        for _ in range(600):
            layers, sram, config, profiles = _random_case(rng)
            try:
                oracle = exhaustive_schedule(layers, sram, "x", config, profiles)
            except InfeasibleScheduleError:
                with self.assertRaises(InfeasibleScheduleError):
                    dp_schedule(layers, sram, "x", config, profiles)
                continue
            dp = dp_schedule(layers, sram, "x", config, profiles)
            self.assertEqual(dp.subgraphs, oracle.subgraphs)
            self.assertEqual(
                _cost(dp, sram, "x", config, profiles),
                _cost(oracle, sram, "x", config, profiles),
            )
            self.assertTrue(
                costs_tie(
                    _cost(dp, sram, "x", config, profiles),
                    _brute_force_min(layers, sram, "x", config, profiles),
                )
            )
            checked += 1
        self.assertGreater(checked, 300)

    def test_dp_matches_exhaustive_on_mobilevit_profiles(self):
        config = make_cost_config(json.loads(SRAM_CFG.read_text())["cost_model"])
        for path in (XXS, SMALL):
            layers = load_model_profile(path).layers
            for sram, deadline, profile in itertools.product(
                (256, 384, 1024), (5.0, 20.0, 33.3), sorted(OS_PROFILES)
            ):
                cfg = replace(config, deadline_ms=deadline)
                dp = dp_schedule(layers, sram, profile, cfg)
                oracle = exhaustive_schedule(layers, sram, profile, cfg)
                self.assertEqual(dp.subgraphs, oracle.subgraphs, (path.name, sram, deadline, profile))

    def test_audit_toy_deadline_hinge_is_on_total_latency(self):
        # Two 3 ms layers, 5 ms deadline. Each subgraph alone meets the deadline,
        # the schedule does not: the old per-subgraph DP saw no deadline excess
        # and lost to greedy (audit P0-1: 186.28 vs 162.24).
        config = make_cost_config({"deadline_ms": 5.0})
        profiles = make_os_profiles(
            {"p": {"latency_multiplier": 1.0, "deadline_miss_rate": 1.0, "memory_pressure": 0.0}}
        )
        toy = (
            LayerProfile("a", "Conv", 10, 10, 1, 300e6, True),
            LayerProfile("b", "Conv", 10, 10, 1, 300e6, True),
        )
        dp = dp_schedule(toy, 1024, "p", config, profiles)
        greedy = greedy_schedule(toy, 1024, config)
        self.assertLessEqual(
            _cost(dp, 1024, "p", config, profiles), _cost(greedy, 1024, "p", config, profiles)
        )
        self.assertEqual(serialize_subgraphs(dp.subgraphs), "a+b")

    def test_memory_term_uses_schedule_peak_not_sum(self):
        # Splitting lowers the peak (201 vs 301 KB) at the price of DRAM traffic.
        # With the max-peak term the split wins; a sum-of-peaks surrogate would
        # charge the split 402 KB and wrongly prefer fusion.
        toy = _memory_toy()
        config = make_cost_config({"gamma": 5000.0})
        profiles = make_os_profiles(
            {"mem": {"latency_multiplier": 1.0, "deadline_miss_rate": 0.0, "memory_pressure": 1.0}}
        )
        dp = dp_schedule(toy, 1000, "mem", config, profiles)
        self.assertEqual(serialize_subgraphs(dp.subgraphs), "a | b")
        self.assertEqual(dp.subgraphs, exhaustive_schedule(toy, 1000, "mem", config, profiles).subgraphs)

    def test_tie_break_prefers_fewer_subgraphs(self):
        # Zero-cost layers: every partition costs the same.
        free = make_cost_config(
            {
                "dram_energy_per_kb": 0.0,
                "compute_energy_per_mmac": 0.0,
                "dram_latency_per_kb_ms": 0.0,
                "compute_latency_per_mmac_ms": 0.0,
                "subgraph_overhead_ms": 0.0,
            }
        )
        layers = tuple(LayerProfile(f"l{i}", "Conv", 1, 1, 1, 1, True) for i in range(4))
        for scheduler in (dp_schedule, exhaustive_schedule):
            result = scheduler(layers, 1024, "pure", free)
            self.assertEqual(len(result.subgraphs), 1)

    def test_exhaustive_refuses_large_models(self):
        layers = tuple(
            LayerProfile(f"l{i}", "Conv", 1, 1, 1, 1, True) for i in range(EXHAUSTIVE_MAX_LAYERS + 1)
        )
        with self.assertRaisesRegex(ValueError, "at most"):
            exhaustive_schedule(layers, 1024)

    def test_negative_cost_weights_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-negative"):
            make_cost_config({"gamma": -1.0})


class GreedyAndSweepTest(unittest.TestCase):
    """P1-1 and P1-2."""

    def test_greedy_scans_past_infeasible_extension(self):
        layers = (
            LayerProfile("l0", "Conv", 10, 100, 1, 1e6, True),
            LayerProfile("l1", "Conv", 100, 150, 1, 1e6, True),
            LayerProfile("l2", "Conv", 150, 10, 1, 1e6, True),
        )
        # SRAM(l0)=111, SRAM(l0+l1)=261, SRAM(l0+l1+l2)=171: not monotone.
        result = greedy_schedule(layers, 255)
        self.assertEqual(serialize_subgraphs(result.subgraphs), "l0+l1+l2")

    def test_greedy_no_longer_falsely_infeasible(self):
        layers = (
            LayerProfile("l0", "Conv", 10, 150, 1, 1e6, True),
            LayerProfile("l1", "Conv", 150, 150, 1, 1e6, True),
            LayerProfile("l2", "Conv", 150, 10, 1, 1e6, True),
        )
        # l1 alone needs 301 KB, but l0+l1+l2 fits in 200 KB.
        result = greedy_schedule(layers, 200)
        self.assertEqual(serialize_subgraphs(result.subgraphs), "l0+l1+l2")

    def test_greedy_reports_infeasibility_explicitly(self):
        layers = (LayerProfile("big", "Conv", 100, 100, 64, 1e6, False),)
        with self.assertRaises(InfeasibleScheduleError):
            greedy_schedule(layers, 100)
        with self.assertRaises(InfeasibleScheduleError):
            layerwise_schedule(layers, 100)
        with self.assertRaises(InfeasibleScheduleError):
            dp_schedule(layers, 100)

    def test_sweep_marks_infeasible_rows_instead_of_aborting(self):
        config = json.loads(SRAM_CFG.read_text())
        config["sram_kb"] = [128, 256]
        rows = run_simulation_with_config(SMALL, config)
        self.assertEqual(len(rows), 2 * 4 * 3)
        small = [row for row in rows if row["sram_kb"] == "128"]
        self.assertTrue(all(row["feasible"] == "false" for row in small))
        self.assertTrue(all(row["os_aware_total_cost"] == "" for row in small))
        self.assertIn("requires", small[0]["infeasible_reason"])
        self.assertTrue(all(row["feasible"] == "true" for row in rows if row["sram_kb"] == "256"))

    def test_configuration_errors_still_abort(self):
        config = json.loads(SRAM_CFG.read_text())
        config["os_profiles"] = ["no_such_profile"]
        with self.assertRaisesRegex(ValueError, "Unknown OS profile"):
            run_simulation_with_config(XXS, config)
        config = json.loads(SRAM_CFG.read_text())
        config["schedulers"] = ["nope"]
        with self.assertRaisesRegex(ValueError, "Unknown scheduler"):
            run_simulation_with_config(XXS, config)


class AnalyzerTest(unittest.TestCase):
    """P1-2 / P1-3: infeasible rows, missing baselines and ties in the summary."""

    def _summary(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.csv"
            path.write_text(_HEADER + body, encoding="utf-8")
            return build_summary_rows(load_result_rows(path))

    def test_tie_is_reported_not_attributed_to_greedy(self):
        summary = self._summary(
            "toy,layerwise,256,normal,3,1,120,400,410,10,450,a | b | c,true,,33.3\n"
            "toy,greedy,256,normal,2,2,160,300,310,8,340,a+b | c,true,,33.3\n"
            "toy,dp,256,normal,2,2,160,300,310,8,340,a+b | c,true,,33.3\n"
        )[0]
        self.assertEqual(summary["best_scheduler"], "greedy=dp")
        self.assertEqual(summary["num_tied_schedulers"], "2")
        self.assertEqual(summary["tied_same_partition"], "true")

    def test_infeasible_rows_never_win_and_baseline_status(self):
        summary = self._summary(
            "toy,layerwise,128,normal,,,,,,,,,false,too small,33.3\n"
            "toy,greedy,128,normal,2,2,120,300,310,8,350,a+b | c,true,,33.3\n"
            "toy,dp,128,normal,2,2,110,290,300,8,340,a | b+c,true,,33.3\n"
        )[0]
        self.assertEqual(summary["best_scheduler"], "dp")
        self.assertEqual(summary["baseline_status"], "infeasible")
        self.assertEqual(summary["dram_reduction_pct"], "")
        self.assertEqual(summary["layerwise_estimated_energy"], "")
        self.assertEqual(summary["infeasible_schedulers"], "layerwise")

    def test_missing_baseline_and_no_feasible_group(self):
        rows = self._summary(
            "toy,dp,256,normal,2,2,110,290,300,8,340,a | b+c,true,,33.3\n"
            "toy,dp,64,normal,,,,,,,,,false,too small,33.3\n"
        )
        by_sram = {row["sram_kb"]: row for row in rows}
        self.assertEqual(by_sram["256"]["baseline_status"], "missing")
        self.assertEqual(by_sram["256"]["best_scheduler"], "dp")
        self.assertEqual(by_sram["64"]["best_scheduler"], "")
        self.assertEqual(by_sram["64"]["num_tied_schedulers"], "0")

    def test_plots_skip_infeasible_rows_and_need_one_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.csv"
            path.write_text(
                _HEADER
                + "toy,layerwise,128,normal,,,,,,,,,false,too small,10\n"
                + "toy,layerwise,256,normal,3,1,120,400,410,10,450,a | b | c,true,,10\n"
                + "toy,layerwise,256,normal,3,1,120,400,410,10,450,a | b | c,true,,20\n",
                encoding="utf-8",
            )
            rows = load_result_rows(path)
            with self.assertRaisesRegex(ValueError, "one deadline"):
                write_metric_svgs(rows, Path(tmp) / "f", os_profile="normal")
            written = write_metric_svgs(rows, Path(tmp) / "f", os_profile="normal", deadline_ms="10")
            self.assertEqual(len(written), 4)

    def test_simulation_csv_round_trips_through_analyzer(self):
        config = json.loads(SRAM_CFG.read_text())
        config["sram_kb"] = [128, 256]
        rows = run_simulation_with_config(SMALL, config)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.csv"
            write_simulation_csv(path, rows)
            with path.open(encoding="utf-8") as f:
                self.assertEqual(next(csv.reader(f)), CSV_FIELDS)
            summary = build_summary_rows(load_result_rows(path))
        self.assertEqual(len(summary), 2 * 4)
        for row in summary:
            if row["sram_kb"] == "128":
                self.assertEqual(row["best_scheduler"], "")
            else:
                self.assertEqual(row["best_scheduler"], "greedy=dp")


class OsAwareSemanticsTest(unittest.TestCase):
    """P1-3 and P1-4 (EDA-Lite side)."""

    def test_pure_profile_keeps_latency_and_drops_os_pressure(self):
        pure = OS_PROFILES["pure"]
        self.assertEqual(pure.latency_multiplier, 1.0)
        self.assertEqual(
            (pure.deadline_miss_rate, pure.memory_pressure, pure.drop_rate), (0.0, 0.0, 0.0)
        )
        layers = load_model_profile(SMALL).layers
        schedule = layerwise_schedule(layers, 512)
        config = make_cost_config({"deadline_ms": 1.0})  # deadline far exceeded
        metrics = estimate_schedule_metrics(schedule.subgraphs, 512, "pure", config)
        self.assertAlmostEqual(
            metrics.os_aware_total_cost,
            metrics.estimated_energy + config.alpha * metrics.estimated_latency_ms,
        )
        self.assertGreater(metrics.breakdown.latency_cost, 0.0)
        self.assertEqual(metrics.breakdown.deadline_cost, 0.0)
        self.assertEqual(metrics.breakdown.memory_pressure_cost, 0.0)

    def test_deadline_penalty_uses_effective_latency(self):
        layers = (LayerProfile("a", "Conv", 10, 10, 1, 2e9, True),)  # ~20 ms
        config = CostConfig(deadline_ms=33.3)
        profiles = make_os_profiles(
            {
                "m1": {"latency_multiplier": 1.0, "deadline_miss_rate": 0.5, "memory_pressure": 0.0},
                "m2": {"latency_multiplier": 2.0, "deadline_miss_rate": 0.5, "memory_pressure": 0.0},
            }
        )
        m1 = estimate_schedule_metrics([layers], 1024, "m1", config, profiles)
        m2 = estimate_schedule_metrics([layers], 1024, "m2", config, profiles)
        self.assertLess(m1.estimated_latency_ms, 33.3)
        self.assertEqual(m1.breakdown.deadline_cost, 0.0)
        self.assertAlmostEqual(m2.breakdown.effective_latency_ms, 2 * m2.estimated_latency_ms)
        self.assertAlmostEqual(
            m2.breakdown.deadline_cost,
            config.beta * 0.5 * (2 * m2.estimated_latency_ms - 33.3),
        )
        self.assertEqual(m1.estimated_latency_ms, m2.estimated_latency_ms)

    def test_when_each_term_changes_the_schedule(self):
        """Memory pressure can make dp split; a tight deadline can undo it."""

        toy = _memory_toy()
        config = make_cost_config({"gamma": 5000.0, "beta": 10000.0, "deadline_ms": 20.3})
        profiles = make_os_profiles(
            {
                "mem_only": {"latency_multiplier": 1.0, "deadline_miss_rate": 0.0, "memory_pressure": 1.0},
                "mem_and_deadline": {
                    "latency_multiplier": 1.0,
                    "deadline_miss_rate": 1.0,
                    "memory_pressure": 1.0,
                },
            }
        )

        def plan(profile, cfg=config):
            schedule = dp_schedule(toy, 1000, profile, cfg, profiles)
            self.assertEqual(
                schedule.subgraphs, exhaustive_schedule(toy, 1000, profile, cfg, profiles).subgraphs
            )
            return serialize_subgraphs(schedule.subgraphs)

        self.assertEqual(plan("pure"), "a+b")  # fusion saves DRAM energy and latency
        self.assertEqual(plan("mem_only"), "a | b")  # lower peak SRAM wins
        self.assertEqual(plan("mem_and_deadline"), "a+b")  # split misses the deadline
        self.assertEqual(plan("mem_and_deadline", replace(config, deadline_ms=100.0)), "a | b")

    def test_sram_sensitivity_on_mobilevit_profiles(self):
        config = make_cost_config(json.loads(SRAM_CFG.read_text())["cost_model"])
        s_layers = load_model_profile(SMALL).layers
        xxs_layers = load_model_profile(XXS).layers
        # MobileViT-S: block_2 attention alone needs 240 KB and is non-fusible.
        with self.assertRaises(InfeasibleScheduleError):
            dp_schedule(s_layers, 192, "pure", config)
        self.assertEqual(dp_schedule(s_layers, 256, "pure", config).max_fusion_depth, 2)
        self.assertEqual(dp_schedule(s_layers, 384, "pure", config).max_fusion_depth, 3)
        # MobileViT-XXS: everything fits at 192 KB and the 3-layer stem chain fuses.
        self.assertEqual(dp_schedule(xxs_layers, 192, "pure", config).max_fusion_depth, 3)

    def test_repository_sensitivity_sweep_is_consistent(self):
        rows = run_profile_sweep(REPO / "experiments/eda_lite/mobilevit_sensitivity_sweep.json")
        self.assertEqual(len(rows), 2 * 7 * 6 * 4 * 4)
        groups = {}
        for row in rows:
            key = (row["model_name"], row["sram_kb"], row["deadline_ms"], row["os_profile"])
            groups.setdefault(key, {})[row["scheduler"]] = row
        for key, group in groups.items():
            self.assertEqual(group["dp"]["feasible"], group["exhaustive"]["feasible"], key)
            self.assertEqual(group["dp"]["subgraphs"], group["exhaustive"]["subgraphs"], key)
            self.assertEqual(
                group["dp"]["os_aware_total_cost"], group["exhaustive"]["os_aware_total_cost"], key
            )
        self.assertEqual({row["deadline_ms"] for row in rows}, {"5", "10", "20", "33.3", "50", "100"})

    def test_six_line_plot_profiles_come_from_arguments(self):
        from src.eda_lite.plot_6lines import generate_6line_charts

        source = (REPO / "src/eda_lite/plot_6lines.py").read_text(encoding="utf-8")
        self.assertNotIn("d150", source)
        self.assertNotIn('== "normal"', source)
        config = json.loads(SRAM_CFG.read_text())
        rows = run_simulation_with_config(XXS, config)
        model = rows[0]["model_name"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.csv"
            write_simulation_csv(path, rows)
            generate_6line_charts(model, path, path, "high_latency", Path(tmp) / "f")
            svg = (Path(tmp) / "f" / "dram_traffic_by_sram.svg").read_text(encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "No rows"):
                generate_6line_charts(model, path, path, "missing_profile", Path(tmp) / "g")
        self.assertIn("(Pure)", svg)
        self.assertIn("(OS-Aware)", svg)


_HEADER = (
    "model_name,scheduler,sram_kb,os_profile,num_subgraphs,max_fusion_depth,"
    "peak_sram_kb,dram_traffic_kb,estimated_energy,estimated_latency_ms,"
    "os_aware_total_cost,subgraphs,feasible,infeasible_reason,deadline_ms\n"
)


def _memory_toy():
    # Alone: 100+100+0+1 = 201 KB each; fused: 100+100+100+1 = 301 KB.
    return (
        LayerProfile("a", "Conv", 100, 100, 1, 1e9, True),
        LayerProfile("b", "Conv", 100, 100, 1, 1e9, True),
    )


if __name__ == "__main__":
    unittest.main()
