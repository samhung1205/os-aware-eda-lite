"""Phase 1 / Batch 3: provenance (P0-3), OS profile calibration (P1-7), run metadata (P1-8).

All "measured" data in this file is synthetic and lives only in temporary
directories: it exercises the provenance and calibration code paths and is
never written into the repository or reported as a measurement.
"""

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.eda_lite.cost_model import make_cost_config, make_os_profiles
from src.eda_lite.run_simulation import (
    run_simulation_with_config,
    select_profiles_for_model,
    write_simulation_csv,
    write_simulation_provenance,
)
from src.provenance import (
    CLASS_CONSTRAINED,
    CLASS_CONSTRAINT_FAILED,
    CLASS_CONSTRAINT_UNVERIFIED,
    CLASS_UNCONSTRAINED,
    assess_os_profile_payload,
    read_json,
    simulation_provenance_path,
    summary_manifest_path,
)
from src.ros2_runtime.analyze_runtime import (
    build_runtime_summary,
    load_run_metadata,
    load_runtime_rows,
)
from src.ros2_runtime.build_os_profiles import build_os_profile_payload
from src.ros2_runtime.run_metadata import (
    NODE_QOS,
    classify_limits,
    collect_run_metadata,
    parse_cpu_list,
    parse_size_bytes,
    read_effective_limits,
)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_runtime_provenance  # noqa: E402

XXS = REPO / "data/model_profiles/mobilevit_xxs_simplified.json"
S = REPO / "data/model_profiles/mobilevit_s_simplified.json"
EDA = REPO / "experiments/eda_lite"
LEGACY_FILE = EDA / "runtime_os_profiles.legacy_unverified.json"
LEGACY_CFG = EDA / "mobilevit_runtime_aware_sweep_legacy_unverified.json"
DEFAULT_CFG = EDA / "mobilevit_runtime_aware_sweep.json"

DETECTOR_HEADER = [
    "run_id", "scenario", "model_name", "input_fps", "qos_depth", "fake_delay_ms",
    "resource_profile", "deadline_ms", "frame_id", "warmup", "published_at_ns", "received_at_ns",
    "completed_at_ns", "latency_ms", "transport_ms", "preprocess_ms", "artificial_delay_ms",
    "inference_ms", "deadline_miss", "dropped", "cpu_percent", "memory_mb",
]
# (run_id, scenario, model, fps, delay_ms, latency_ms, memory_mb) -- synthetic.
SYNTHETIC_RUNS = (
    ("xxs_idle", "fps_sweep", "mobilevit_xxs", "5.0", "0", 40.0, 300.0),
    ("xxs_overload", "overload_sweep", "mobilevit_xxs", "20.0", "80", 160.0, 310.0),
    ("s_idle", "fps_sweep", "mobilevit_s", "5.0", "0", 120.0, 600.0),
)
UNCONSTRAINED = {"cpus_allowed": None, "memory_max_bytes": None}


def _cfg(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    cfg["__config_dir"] = str(Path(path).parent)
    return cfg


def _write_run(raw_dir, run_id, scenario, model, fps, delay, latency, memory, meta=True,
               effective=None, requested=("", "")):
    with (raw_dir / f"{run_id}.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=DETECTOR_HEADER)
        writer.writeheader()
        for frame in range(10):
            writer.writerow({
                "run_id": run_id, "scenario": scenario, "model_name": model, "input_fps": fps,
                "qos_depth": "5", "fake_delay_ms": delay, "resource_profile": "normal",
                "deadline_ms": "1000", "frame_id": frame, "warmup": 0, "published_at_ns": frame,
                "received_at_ns": frame, "completed_at_ns": frame, "latency_ms": latency,
                "transport_ms": 1, "preprocess_ms": 1, "artificial_delay_ms": delay,
                "inference_ms": latency / 2, "deadline_miss": 0, "dropped": 0,
                "cpu_percent": 50, "memory_mb": memory,
            })
    (raw_dir / f"{run_id}.publisher.csv").write_text(
        "run_id,frame_id,published_at_ns\n" + "".join(f"{run_id},{i},{i}\n" for i in range(10)),
        encoding="utf-8",
    )
    if meta:
        payload = collect_run_metadata(run_id, "normal", requested[0], requested[1],
                                       effective=effective or dict(UNCONSTRAINED))
        payload["host"]["memory_total_mb"] = 8192.0  # deterministic reference for the test
        (raw_dir / f"{run_id}.meta.json").write_text(json.dumps(payload), encoding="utf-8")


def _build_chain(root, meta=True, **run_kwargs):
    """Synthetic raw -> summary -> profiles under ``root`` using the real CLIs."""

    raw = root / "results/raw/ros2"
    raw.mkdir(parents=True)
    for run in SYNTHETIC_RUNS:
        _write_run(raw, *run, meta=meta, **run_kwargs)
    summary = root / "results/csv/ros2_runtime_summary.csv"
    profiles = root / "experiments/eda_lite/runtime_os_profiles.json"
    subprocess.run([sys.executable, "-m", "src.ros2_runtime.analyze_runtime", "--input", str(raw),
                    "--summary-output", str(summary)], cwd=REPO, check=True, capture_output=True)
    build = subprocess.run([sys.executable, "-m", "src.ros2_runtime.build_os_profiles", "--input",
                            str(summary), "--output", str(profiles), "--profile-prefix", "measured"],
                           cwd=REPO, check=True, capture_output=True, text=True)
    return raw, summary, profiles, build.stdout


def _idle(model, latency, **extra):
    row = dict(scenario="fps_sweep", model_name=model, input_fps="5.0", qos_depth="5",
               fake_delay_ms="0", resource_profile="normal", avg_latency_ms=str(latency),
               deadline_miss_rate_pct="0", drop_rate_pct="0", avg_memory_mb="300",
               memory_limit_mb="2048", run_id=f"{model}_{latency}")
    row.update(extra)
    return row


class ProvenanceChainTest(unittest.TestCase):
    def test_full_chain_verifies_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, summary, profiles, out = _build_chain(root)
            self.assertIn("provenance_status=verified", out)
            self.assertTrue(summary_manifest_path(summary).is_file())
            payload = read_json(profiles)
            self.assertEqual(assess_os_profile_payload(payload, profiles), ("verified", []))
            code, lines = check_runtime_provenance.check(root)
            self.assertEqual(code, check_runtime_provenance.VERIFIED, "\n".join(lines))

            # Simulation from verified profiles: no opt-in needed, rows labelled verified,
            # and each model only gets its own profiles.
            cfg = _cfg(DEFAULT_CFG)
            cfg["os_profile_file"] = str(profiles)
            rows = run_simulation_with_config(S, cfg)
            self.assertEqual({r["os_profile_provenance"] for r in rows}, {"verified"})
            self.assertEqual({r["os_profile"] for r in rows}, {"measured_fps_sweep_mobilevit_s_5_0fps_q5_d0_normal"})

    def test_tampered_raw_csv_breaks_the_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, _, profiles, _ = _build_chain(root)
            with (raw / "xxs_idle.csv").open("a", encoding="utf-8") as file:
                file.write("xxs_idle,fps_sweep,mobilevit_xxs,5.0,5,0,normal,1000,99,0,,,,1,,,,,0,0,50,300\n")
            status, reasons = assess_os_profile_payload(read_json(profiles), profiles)
            self.assertEqual(status, "unverified")
            self.assertTrue(any("xxs_idle.csv changed" in r for r in reasons), reasons)
            code, _ = check_runtime_provenance.check(root)
            self.assertEqual(code, check_runtime_provenance.BROKEN)
            cfg = _cfg(DEFAULT_CFG)
            cfg["os_profile_file"] = str(profiles)
            with self.assertRaisesRegex(ValueError, "UNVERIFIED"):
                run_simulation_with_config(XXS, cfg)

    def test_runs_without_metadata_are_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw"
            raw.mkdir()
            for run in SYNTHETIC_RUNS:
                _write_run(raw, *run, meta=False)
            summary = root / "summary.csv"
            subprocess.run([sys.executable, "-m", "src.ros2_runtime.analyze_runtime", "--input", str(raw),
                            "--summary-output", str(summary)], cwd=REPO, check=True, capture_output=True)
            # Without run metadata there is no verifiable memory reference either.
            proc = subprocess.run([sys.executable, "-m", "src.ros2_runtime.build_os_profiles", "--input",
                                   str(summary), "--output", str(root / "p.json"), "--require-verified",
                                   "--memory-reference-mb", "2048"],
                                  cwd=REPO, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("no run metadata", proc.stderr)
            self.assertFalse((root / "p.json").exists())

    def test_unapplied_resource_limits_are_never_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, summary, profiles, _ = _build_chain(
                root, effective={"cpus_allowed": [0, 1, 2, 3], "memory_max_bytes": "max"},
                requested=("0,1", "2G"),
            )
            with summary.open(encoding="utf-8", newline="") as file:
                classes = {row["measurement_class"] for row in csv.DictReader(file)}
            self.assertEqual(classes, {CLASS_CONSTRAINT_FAILED})
            payload = read_json(profiles)
            self.assertEqual(payload["metadata"]["provenance_status"], "unverified")
            self.assertEqual(check_runtime_provenance.check(root)[0], check_runtime_provenance.BROKEN)

    def test_stale_simulation_sidecar_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_chain(root)
            cfg_path = root / "experiments/eda_lite/sweep.json"
            cfg = json.loads(DEFAULT_CFG.read_text(encoding="utf-8"))
            cfg["os_profile_file"] = "runtime_os_profiles.json"
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            loaded = _cfg(cfg_path)
            rows = run_simulation_with_config(XXS, loaded)
            out = root / "results/csv/sim.csv"
            write_simulation_csv(out, rows)
            sidecar = write_simulation_provenance(out, rows, cfg_path, loaded, [XXS], "test")
            self.assertEqual(sidecar, simulation_provenance_path(out))
            record = read_json(sidecar)
            self.assertEqual(record["os_profile_file"]["provenance_status"], "verified")
            self.assertEqual(record["rows_by_os_profile_provenance"], {"verified": len(rows)})
            self.assertEqual(check_runtime_provenance.check(root)[0], check_runtime_provenance.VERIFIED)
            cfg["sram_kb"] = [256]
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            code, lines = check_runtime_provenance.check(root)
            self.assertEqual(code, check_runtime_provenance.BROKEN)
            self.assertTrue(any(line.startswith("STALE") for line in lines))

    def test_run_metadata_must_match_its_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            _write_run(raw, *SYNTHETIC_RUNS[0])
            meta = json.loads((raw / "xxs_idle.meta.json").read_text(encoding="utf-8"))
            meta["run_id"] = "other_run"
            (raw / "xxs_idle.meta.json").write_text(json.dumps(meta), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "other_run"):
                load_run_metadata([raw])

    def test_summary_carries_run_conditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            _write_run(raw, *SYNTHETIC_RUNS[0], effective={"cpus_allowed": [0, 1],
                       "memory_max_bytes": 2 * 1024**3}, requested=("0,1", "2G"))
            summary = build_runtime_summary(load_runtime_rows([raw]), run_metadata=load_run_metadata([raw]))
        self.assertEqual(summary[0]["measurement_class"], CLASS_CONSTRAINED)
        self.assertEqual(summary[0]["memory_limit_mb"], "2048")
        self.assertEqual(summary[0]["run_metadata"], "xxs_idle.meta.json")


class RepositoryProvenanceTest(unittest.TestCase):
    def test_repository_chain_is_blocked_not_passed(self):
        code, lines = check_runtime_provenance.check(REPO)
        if any((REPO / "results/raw/ros2").glob("*.csv")):
            self.skipTest("raw ROS2 data present; repository chain is checked by the script itself")
        self.assertEqual(code, check_runtime_provenance.BLOCKED, "\n".join(lines))

    def test_legacy_profiles_are_unverified_and_need_opt_in(self):
        payload = read_json(LEGACY_FILE)
        status, reasons = assess_os_profile_payload(payload, LEGACY_FILE)
        self.assertEqual(status, "unverified")
        self.assertTrue(reasons)
        strict = _cfg(LEGACY_CFG)
        del strict["allow_unverified_os_profiles"]
        with self.assertRaisesRegex(ValueError, "UNVERIFIED"):
            run_simulation_with_config(XXS, strict)

    def test_legacy_profiles_are_labelled_and_never_mixed_across_models(self):
        for model_path, own, other in ((XXS, "_mobilevit_xxs_", "_mobilevit_s_"),
                                       (S, "_mobilevit_s_", "_mobilevit_xxs_")):
            rows = run_simulation_with_config(model_path, _cfg(LEGACY_CFG))
            names = {r["os_profile"] for r in rows}
            self.assertEqual(len(names), 11)
            self.assertTrue(all(own in name for name in names))
            self.assertFalse(any(other in name for name in names))
            self.assertEqual({r["os_profile_provenance"] for r in rows}, {"unverified"})

    def test_explicit_profile_of_another_model_is_rejected(self):
        cfg = _cfg(LEGACY_CFG)
        cfg["os_profiles"] = ["measured_fps_sweep_mobilevit_s_5_0fps_q5_d0_normal"]
        with self.assertRaisesRegex(ValueError, "must not mix models"):
            run_simulation_with_config(XXS, cfg)

    def test_model_without_runtime_name_cannot_use_model_specific_profiles(self):
        with self.assertRaisesRegex(ValueError, "runtime_model_name"):
            select_profiles_for_model(["a"], {"a": "mobilevit_s"}, "m", None, explicit=False)
        self.assertEqual(select_profiles_for_model(["pure", "a"], {"a": None}, "m", None, False),
                         ["pure", "a"])

    def test_default_config_uses_example_profiles(self):
        rows = run_simulation_with_config(XXS, _cfg(DEFAULT_CFG))
        self.assertEqual({r["os_profile_provenance"] for r in rows}, {"example"})
        self.assertEqual(assess_os_profile_payload(read_json(EDA / "runtime_os_profiles.example.json"),
                                                   EDA / "runtime_os_profiles.example.json")[0], "example")

    def test_tracked_runtime_aware_csv_matches_regeneration(self):
        tracked = REPO / "results/csv/eda_lite_mobilevit_runtime_aware_sweep.csv"
        with tracked.open(encoding="utf-8", newline="") as file:
            tracked_rows = list(csv.DictReader(file))
        regen = run_simulation_with_config(XXS, _cfg(DEFAULT_CFG))
        self.assertEqual(len(tracked_rows), len(regen))
        for old, new in zip(tracked_rows, regen):
            for field in ("os_profile", "scheduler", "sram_kb", "subgraphs", "os_aware_total_cost",
                          "os_profile_provenance"):
                self.assertEqual(old[field], str(new[field]), field)


class CalibrationTest(unittest.TestCase):
    def test_each_model_uses_its_own_idle_baseline(self):
        payload = build_os_profile_payload([_idle("mobilevit_xxs", 40), _idle("mobilevit_s", 120)],
                                           profile_prefix="m")
        multipliers = {name: d["latency_multiplier"] for name, d in payload["os_profile_definitions"].items()}
        self.assertEqual(set(multipliers.values()), {1.0})
        baselines = {b["model_name"]: b for b in payload["metadata"]["baselines"]}
        self.assertEqual(baselines["mobilevit_s"]["latency_ms"], 120)
        self.assertEqual(baselines["mobilevit_s"]["run_ids"], ["mobilevit_s_120"])
        self.assertEqual(baselines["mobilevit_s"]["source"], "idle_run")

    def test_baseline_is_the_comparable_idle_condition_not_the_minimum(self):
        rows = [
            _idle("mobilevit_xxs", 42),
            _idle("mobilevit_xxs", 40, input_fps="30.0", run_id="fps30"),
            _idle("mobilevit_xxs", 38, scenario="overload_sweep", input_fps="1.0", run_id="ov_d0"),
            _idle("mobilevit_xxs", 44, run_id="repeat"),  # repeated idle run is averaged
        ]
        payload = build_os_profile_payload(rows, profile_prefix="m")
        baseline = payload["metadata"]["baselines"][0]
        self.assertEqual(baseline["latency_ms"], 43)
        self.assertEqual(baseline["condition"]["scenario"], "fps_sweep")
        self.assertEqual(baseline["condition"]["input_fps"], "5.0")
        profiles = payload["metadata"]["profiles"]
        fps30 = next(n for n, m in profiles.items() if m["run_id"] == "fps30")
        self.assertAlmostEqual(payload["os_profile_definitions"][fps30]["latency_multiplier"], 40 / 43, 5)

    def test_resource_profiles_are_normalised_separately_unless_requested(self):
        rows = [_idle("mobilevit_xxs", 40), _idle("mobilevit_xxs", 50, resource_profile="tuned", run_id="t")]
        own = build_os_profile_payload(rows, profile_prefix="m")["os_profile_definitions"]
        self.assertEqual({d["latency_multiplier"] for d in own.values()}, {1.0})
        shared = build_os_profile_payload(rows, profile_prefix="m", baseline_resource_profile="normal")
        tuned = shared["os_profile_definitions"]["m_fps_sweep_mobilevit_xxs_5_0fps_q5_d0_tuned"]
        self.assertEqual(tuned["latency_multiplier"], 1.25)

    def test_missing_idle_run_is_an_error_not_a_cross_model_baseline(self):
        rows = [_idle("mobilevit_xxs", 40), _idle("mobilevit_s", 300, fake_delay_ms="80")]
        with self.assertRaisesRegex(ValueError, "mobilevit_s"):
            build_os_profile_payload(rows, profile_prefix="m")
        payload = build_os_profile_payload(rows, profile_prefix="m",
                                           baseline_latency_ms={"mobilevit_xxs": 40, "mobilevit_s": 120})
        self.assertEqual(payload["os_profile_definitions"]["m_fps_sweep_mobilevit_s_5_0fps_q5_d80_normal"]
                         ["latency_multiplier"], 2.5)

    def test_memory_pressure_uses_a_verifiable_limit(self):
        rows = [_idle("mobilevit_xxs", 40, avg_memory_mb="300"),
                _idle("mobilevit_s", 120, avg_memory_mb="600")]
        defs = build_os_profile_payload(rows, profile_prefix="m")["os_profile_definitions"]
        self.assertEqual(sorted(d["memory_pressure"] for d in defs.values()), [0.146484, 0.292969])
        host = [dict(r, memory_limit_mb="", host_memory_mb="8192") for r in rows]
        meta = build_os_profile_payload(host, profile_prefix="m")["metadata"]["profiles"]
        self.assertEqual({m["memory_reference_source"] for m in meta.values()}, {"host_total_ram"})
        cli = build_os_profile_payload(rows, profile_prefix="m", memory_reference_mb=1200)
        self.assertEqual(sorted(d["memory_pressure"] for d in cli["os_profile_definitions"].values()),
                         [0.25, 0.5])
        with self.assertRaisesRegex(ValueError, "no verifiable memory reference"):
            build_os_profile_payload([dict(r, memory_limit_mb="") for r in rows], profile_prefix="m")

    def test_calibrated_costs_reflect_os_pressure_not_model_speed(self):
        rows = [
            _idle("mobilevit_xxs", 40),
            _idle("mobilevit_xxs", 160, scenario="overload_sweep", input_fps="20.0", fake_delay_ms="80",
                  deadline_miss_rate_pct="100", drop_rate_pct="40", run_id="xo"),
            _idle("mobilevit_s", 120, avg_memory_mb="600"),
            _idle("mobilevit_s", 480, scenario="overload_sweep", input_fps="20.0", fake_delay_ms="80",
                  deadline_miss_rate_pct="100", drop_rate_pct="40", avg_memory_mb="600", run_id="so"),
        ]
        payload = build_os_profile_payload(rows, profile_prefix="m")
        # In-memory synthetic rows: mark as example so the simulator accepts them,
        # keeping metadata.profiles (the per-model mapping) intact.
        payload["metadata"]["provenance_status"] = "example"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            cfg = _cfg(DEFAULT_CFG)
            cfg["os_profile_file"] = str(path)
            cfg["sram_kb"] = [512]
            cfg["schedulers"] = ["dp"]
            cfg["os_profiles"] = ["pure", *payload["os_profiles"]]
            costs = {}
            for model_path in (XXS, S):
                with self.assertRaisesRegex(ValueError, "must not mix models"):
                    run_simulation_with_config(model_path, cfg)
                own = dict(cfg)
                own["os_profiles"] = ["pure", *[n for n in payload["os_profiles"]
                                                if Path(model_path).stem.split("_simplified")[0] + "_" in n]]
                for row in run_simulation_with_config(model_path, own):
                    costs[(model_path.stem, row["os_profile"])] = row
        for stem, model in (("mobilevit_xxs_simplified", "mobilevit_xxs"), ("mobilevit_s_simplified", "mobilevit_s")):
            pure = costs[(stem, "pure")]
            idle = costs[(stem, f"m_fps_sweep_{model}_5_0fps_q5_d0_normal")]
            over = costs[(stem, f"m_overload_sweep_{model}_20_0fps_q5_d80_normal")]
            # Idle has multiplier 1.0 on both models: same latency term as pure, no deadline excess.
            self.assertEqual(idle["effective_latency_ms"], pure["effective_latency_ms"])
            self.assertEqual(float(idle["deadline_cost"]), 0.0)
            self.assertGreater(float(over["os_aware_total_cost"]), float(idle["os_aware_total_cost"]))
            self.assertGreater(float(over["deadline_cost"]), 0.0)
            self.assertEqual(idle["subgraphs"], pure["subgraphs"])

    def test_legacy_calibration_inflated_idle_mobilevit_s(self):
        # Documents the defect the recalibration removes: under the legacy global
        # baseline, idle MobileViT-S already pays a deadline penalty.
        legacy = read_json(LEGACY_FILE)["os_profile_definitions"]
        idle_s = legacy["measured_fps_sweep_mobilevit_s_5_0fps_q5_d0_normal"]["latency_multiplier"]
        self.assertGreater(idle_s, 3.0)
        cfg = _cfg(LEGACY_CFG)
        cfg["os_profiles"] = ["measured_fps_sweep_mobilevit_s_5_0fps_q5_d0_normal"]
        cfg["sram_kb"] = [512]
        cfg["schedulers"] = ["dp"]
        row = run_simulation_with_config(S, cfg)[0]
        self.assertGreater(float(row["deadline_cost"]), 0.0)
        self.assertEqual(row["os_profile_provenance"], "unverified")

    def test_os_profile_values_stay_valid_fractions(self):
        payload = build_os_profile_payload([_idle("mobilevit_xxs", 40, avg_memory_mb="5000")],
                                           profile_prefix="m")
        make_os_profiles(payload["os_profile_definitions"])  # raises on invalid fractions
        self.assertEqual(next(iter(payload["os_profile_definitions"].values()))["memory_pressure"], 1.0)
        make_cost_config(None)


class RunMetadataTest(unittest.TestCase):
    def test_parsers(self):
        self.assertEqual(parse_size_bytes("2G"), 2 * 1024**3)
        self.assertEqual(parse_size_bytes("512M"), 512 * 1024**2)
        self.assertEqual(parse_size_bytes("1048576"), 1048576)
        self.assertIsNone(parse_size_bytes("max"))
        self.assertIsNone(parse_size_bytes(""))
        self.assertEqual(parse_cpu_list("0,1,4-6"), [0, 1, 4, 5, 6])
        self.assertIsNone(parse_cpu_list(""))

    def test_requested_limits_are_constrained_only_when_read_back(self):
        req = {"cpus": [0, 1], "memory_max_bytes": 2 * 1024**3}
        cases = [
            ({"cpus_allowed": [0, 1], "memory_max_bytes": 2 * 1024**3}, CLASS_CONSTRAINED),
            ({"cpus_allowed": None, "memory_max_bytes": None}, CLASS_CONSTRAINT_UNVERIFIED),
            ({"cpus_allowed": [0, 1], "memory_max_bytes": None}, CLASS_CONSTRAINT_UNVERIFIED),
            ({"cpus_allowed": [0, 1, 2, 3], "memory_max_bytes": 2 * 1024**3}, CLASS_CONSTRAINT_FAILED),
            ({"cpus_allowed": [0, 1], "memory_max_bytes": "max"}, CLASS_CONSTRAINT_FAILED),
        ]
        for effective, expected in cases:
            self.assertEqual(classify_limits(req, effective)[1], expected, effective)
        self.assertEqual(classify_limits({"cpus": None, "memory_max_bytes": None},
                                         {"cpus_allowed": [0]})[1], CLASS_UNCONSTRAINED)

    def test_effective_limits_read_from_cgroup_v2(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc, cg = Path(tmp) / "proc", Path(tmp) / "cg"
            (proc / "self").mkdir(parents=True)
            (proc / "self/cgroup").write_text("0::/user.slice/run-1.scope\n", encoding="utf-8")
            scope = cg / "user.slice/run-1.scope"
            scope.mkdir(parents=True)
            (scope / "memory.max").write_text("2147483648\n", encoding="utf-8")
            (scope / "cpu.max").write_text("max 100000\n", encoding="utf-8")
            (cg / "user.slice/memory.max").write_text("max\n", encoding="utf-8")
            limits = read_effective_limits(proc, cg, affinity=lambda: {0, 1})
            no_delegation = Path(tmp) / "cg2"
            (no_delegation / "user.slice/run-1.scope").mkdir(parents=True)
            missing = read_effective_limits(proc, no_delegation, affinity=lambda: {0, 1})
        self.assertEqual(limits["cpus_allowed"], [0, 1])
        self.assertEqual(limits["memory_max_bytes"], 2147483648)
        self.assertEqual(limits["cpu_max"], "max 100000")
        self.assertIsNone(missing["memory_max_bytes"])

    def test_metadata_records_requested_effective_and_environment(self):
        meta = collect_run_metadata("r", "normal", "0,1", "2G", params={"qos_depth": "5"},
                                    effective={"cpus_allowed": [0, 1], "memory_max_bytes": 2 * 1024**3})
        for section in ("git", "host", "python", "packages", "ros2", "qos", "network_sysctl", "experiment"):
            self.assertIn(section, meta)
        self.assertIn("RMW_IMPLEMENTATION", meta["ros2"])
        self.assertIn("net.core.rmem_default", meta["network_sysctl"])
        self.assertIn("kernel_release", meta["host"])
        self.assertIn("torch", meta["packages"])
        limits = meta["resource_limits"]
        self.assertEqual(limits["requested"]["memory_max_bytes"], 2 * 1024**3)
        self.assertEqual(limits["measurement_class"], CLASS_CONSTRAINED)
        self.assertEqual(meta["experiment"], {"qos_depth": "5"})

    def test_cli_fails_when_requested_limits_are_not_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.meta.json"
            args = [sys.executable, "-m", "src.ros2_runtime.run_metadata", "--output", str(out),
                    "--run-id", "r", "--resource-profile", "normal", "--requested-cpus", "0",
                    "--requested-memory-max", "1K", "--require-applied"]
            proc = subprocess.run(args, cwd=REPO, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 3, proc.stderr)
            self.assertNotEqual(read_json(out)["resource_limits"]["measurement_class"], CLASS_CONSTRAINED)
            again = subprocess.run(args, cwd=REPO, capture_output=True, text=True)
            self.assertEqual(again.returncode, 1)  # never overwrites existing metadata

    def test_node_qos_description_matches_sources(self):
        pipeline = REPO / "src/ros2_uav_pipeline/mobilevit_uav_pipeline"
        publisher = (pipeline / "image_stream_node.py").read_text(encoding="utf-8")
        detector = (pipeline / "mobilevit_detector_node.py").read_text(encoding="utf-8")
        self.assertIn("create_publisher(Image, 'image_raw', 10)", publisher)
        self.assertIn("ReliabilityPolicy.BEST_EFFORT", detector)
        self.assertIn("HistoryPolicy.KEEP_LAST", detector)
        self.assertEqual(NODE_QOS["publisher"]["depth"], 10)

    def test_scripts_record_runs_and_never_run_sudo(self):
        scripts = {p: p.read_text(encoding="utf-8") for p in [
            *sorted((REPO / "experiments/ros2").glob("run_*_sweep.sh")),
            REPO / "scripts/run_baseline_experiments.sh",
            REPO / "scripts/run_os_tuned_experiments.sh",
        ]}
        for path, text in scripts.items():
            self.assertFalse(any(line.strip().startswith("sudo ") for line in text.splitlines()), path)
            subprocess.run(["bash", "-n", str(path)], check=True)
        for name in ("run_fps_sweep.sh", "run_qos_sweep.sh", "run_overload_sweep.sh"):
            self.assertIn("run_capture_metadata", scripts[REPO / "experiments/ros2" / name])
        for name in ("run_baseline_experiments.sh", "run_os_tuned_experiments.sh"):
            text = scripts[REPO / "scripts" / name]
            self.assertIn('RESOURCE_PROFILE="$UNCONSTRAINED_PROFILE"', text)
            self.assertIn('REQUESTED_MEMORY_MAX="$MEMORY_MAX"', text)
        common = (REPO / "experiments/ros2/run_common.sh").read_text(encoding="utf-8")
        self.assertIn('"${output_csv%.csv}.meta.json"', common)

    @unittest.skipUnless(shutil.which("bash"), "bash required")
    def test_capture_helper_fails_run_on_unverified_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r1.csv"
            script = (
                f'source "{REPO}/experiments/ros2/run_common.sh"; '
                f'REQUESTED_CPUS=0 REQUESTED_MEMORY_MAX=1K run_capture_metadata r1 "{out}" normal scenario=x'
            )
            proc = subprocess.run(["bash", "-c", script], cwd=REPO, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 3, proc.stderr)
            self.assertTrue((Path(tmp) / "r1.meta.json.failed").exists())
            ok = subprocess.run(["bash", "-c", script.replace("REQUESTED_CPUS=0 REQUESTED_MEMORY_MAX=1K ", "")
                                 .replace("r1", "r2")], cwd=REPO, capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            meta = read_json(Path(tmp) / "r2.meta.json")
            self.assertEqual(meta["resource_limits"]["measurement_class"], CLASS_UNCONSTRAINED)
            self.assertEqual(meta["experiment"], {"scenario": "x"})


if __name__ == "__main__":
    unittest.main()
