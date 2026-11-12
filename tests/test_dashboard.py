"""Phase 4: dashboard data pipeline, manifest, KPI consistency and failure behaviour.

Standard library only. Mutation tests run the builder against a temporary root whose
``results/csv`` is a copy (raw run directories are symlinked, never modified).
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from cli_support import run_cli  # noqa: E402
from src.dashboard import build_data as bd  # noqa: E402

DASH = REPO / "dashboard"
DATA_DIR = DASH / "data"


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TempRoot:
    """A repo-shaped root for the builder: copied results/csv, symlinked raw run dirs."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="dash_test_")
        self.root = Path(self._tmp.name)
        (self.root / "results/raw").mkdir(parents=True)
        shutil.copytree(REPO / "results/csv", self.root / "results/csv")
        for name in ("ros2", "ros2_phase3_formal"):
            (self.root / "results/raw" / name).symlink_to(REPO / "results/raw" / name, target_is_directory=True)
        (self.root / "results/figures").symlink_to(REPO / "results/figures", target_is_directory=True)

    def path(self, rel: str) -> Path:
        return self.root / rel

    def rehash(self, rel: str) -> None:
        """Update every manifest / sidecar under results/csv that records ``rel``,
        so a deliberate content change is not caught by the hash check first."""
        new = _sha(self.path(rel))
        for mf in (self.root / "results/csv").glob("*.json"):
            text = mf.read_text(encoding="utf-8")
            data = json.loads(text)
            changed = False
            for key in ("inputs", "outputs"):
                for rec in data.get(key) or []:
                    if rec.get("path") == rel:
                        rec["sha256"] = new
                        changed = True
            out = data.get("output")
            if isinstance(out, dict) and ("results/csv/" + str(out.get("path"))) == rel:
                out["sha256"] = new
                changed = True
            if changed:
                mf.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def build(self, *extra: str, expect: int | None = 0):
        return run_cli([sys.executable, "-m", "src.dashboard.build_data", "--root", self.root,
                        "--output-dir", self.root / "out", *extra], expect=expect)

    def cleanup(self):
        self._tmp.cleanup()


class BundleTest(unittest.TestCase):
    """The committed bundle: current, deterministic, internally consistent."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = json.loads((DATA_DIR / bd.OUTPUT_JSON).read_text(encoding="utf-8"))

    def test_committed_bundle_is_current(self):
        proc = run_cli([sys.executable, "-m", "src.dashboard.build_data", "--check"])
        self.assertIn("CURRENT", proc.stdout)

    def test_build_is_deterministic(self):
        a, _ = bd.build_bundle(REPO)
        b, inputs = bd.build_bundle(REPO)
        self.assertEqual(bd.render(a, inputs), bd.render(b, inputs))
        text = (DATA_DIR / bd.OUTPUT_JSON).read_text(encoding="utf-8")
        self.assertNotRegex(text, r"20\d\d-\d\d-\d\dT\d\d:\d\d")  # no build timestamps

    def test_js_bundle_holds_the_same_object(self):
        js = (DATA_DIR / bd.OUTPUT_JS).read_text(encoding="utf-8")
        m = re.search(r"window\.DASHBOARD_DATA = (.*);\s*$", js, re.S)
        self.assertIsNotNone(m)
        self.assertEqual(json.loads(m.group(1)), self.bundle)

    def test_manifest_hashes_match_inputs_and_outputs(self):
        manifest = json.loads((DATA_DIR / bd.OUTPUT_MANIFEST).read_text(encoding="utf-8"))
        self.assertTrue(manifest["inputs"])
        for rec in manifest["inputs"] + manifest["outputs"]:
            with self.subTest(path=rec["path"]):
                self.assertEqual(_sha(REPO / rec["path"]), rec["sha256"])
        outs = {Path(o["path"]).name for o in manifest["outputs"]}
        self.assertEqual(outs, {bd.OUTPUT_JSON, bd.OUTPUT_JS})

    def test_only_formal_sources(self):
        for src in self.bundle["sources"]:
            for token in bd.FORBIDDEN_PATH_TOKENS:
                self.assertNotIn(token, src["path"].lower(), src["path"])
            self.assertTrue(src["path"].startswith(("results/csv/", "results/raw/ros2/", "results/raw/ros2_phase3_formal/")),
                            src["path"])
        for run in self.bundle["scheduling"]["runs"]:
            self.assertTrue(run["block"].startswith("p3b2_"), run["block"])
        for run in self.bundle["baseline"]["runs"]:
            self.assertRegex(run["run_id"], bd.P2_RUN_ID)

    def test_run_counts_match_raw_directories(self):
        p2 = len(list((REPO / "results/raw/ros2").glob("*.meta.json")))
        p3 = len(list((REPO / "results/raw/ros2_phase3_formal").glob("*.meta.json")))
        k = self.bundle["kpis"]["runs"]
        self.assertEqual((k["phase2"], k["phase3"], k["total"]), (p2, p3, p2 + p3))
        self.assertEqual(k["phase3_blocks"], sum(c["n_blocks"] for c in self.bundle["scheduling"]["conditions"]))


class KpiConsistencyTest(unittest.TestCase):
    """Every KPI equals the value in the verified CSV it was read from."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = json.loads((DATA_DIR / bd.OUTPUT_JSON).read_text(encoding="utf-8"))
        cls.paired = _csv(REPO / bd.P3_PAIRED)
        cls.arms = _csv(REPO / bd.P3_ARMS)

    def _paired_row(self, cid, arm, ref):
        for r in self.paired:
            c = bd._condition_id(r["model_name"], r["input_fps"], r["fake_delay_ms"], r.get("fps_schedule", ""))
            if c == cid and r["scheduler_arm"] == arm and r["reference_arm"] == ref:
                return r
        self.fail(f"no paired row {cid} {arm} {ref}")

    def test_headline_kpis_equal_paired_csv(self):
        k = self.bundle["kpis"]
        for key, (arm, ref) in {
            "guard_vs_latest_primary": ("guard_c5_q10", "latest_q10"),
            "adaptive_vs_latest_primary": ("adaptive_c5_q10", "latest_q10"),
            "adaptive_vs_guard_primary": ("adaptive_c5_q10", "guard_c5_q10"),
        }.items():
            row = self._paired_row(bd.PRIMARY_CONDITION, arm, ref)
            with self.subTest(kpi=key):
                for field, col in (("mean", "mean"), ("lo", "ci95_lo"), ("hi", "ci95_hi")):
                    self.assertAlmostEqual(k[key][field], float(row[f"d_effective_miss_rate_pct_{col}"]), places=3)
                self.assertEqual(k[key]["n_neg"], int(float(row["d_effective_miss_rate_pct_n_neg"])))
                self.assertEqual(k[key]["n_blocks"], int(row["n_blocks"]))

    def test_arm_table_equals_arms_csv(self):
        table = {(r["condition"], r["arm"]): r for r in self.bundle["scheduling"]["arms_table"]}
        self.assertEqual(len(table), len(self.arms))
        for r in self.arms:
            cid = bd._condition_id(r["model_name"], r["input_fps"], r["fake_delay_ms"], r.get("fps_schedule", ""))
            row = table[(cid, r["scheduler_arm"])]
            for metric in ("effective_miss_rate_pct", "on_time_fps", "p99_latency_ms", "drop_rate_pct"):
                self.assertAlmostEqual(row[metric]["mean"], float(r[f"{metric}_mean"]), places=3)

    def test_guard_and_adaptive_are_reported_side_by_side_everywhere(self):
        s = self.bundle["scheduling"]
        for c in s["conditions"]:
            arms = {r["arm"] for r in s["arms_table"] if r["condition"] == c["id"]}
            self.assertTrue({"guard_c5_q10", "adaptive_c5_q10"} <= arms, c["id"])
            self.assertTrue(any(p["condition"] == c["id"] and p["arm"] == "adaptive_c5_q10"
                                and p["reference"] == "guard_c5_q10" for p in s["paired"]), c["id"])
        f = {x["id"]: x for x in self.bundle["findings"]}
        self.assertIn("adaptive", f)
        self.assertIn("no measurable benefit", f["adaptive"]["title"])

    def test_findings_quote_the_kpis(self):
        k, f = self.bundle["kpis"], {x["id"]: x["text"] for x in self.bundle["findings"]}
        g = k["guard_vs_latest_primary"]
        self.assertIn(f"{-g['mean']:.1f} pp", f["guard"])
        self.assertIn(f"{g['n_neg']}/{g['n_blocks']} blocks", f["guard"])
        ag = k["adaptive_vs_guard_primary"]
        self.assertIn(f"{ag['mean']:+.2f} pp".replace("-", "−"), f["adaptive"])
        self.assertIn("Not an equivalence test", f["adaptive"])
        for text in f.values():  # no significance / generality / energy claims
            low = text.lower()
            for banned in ("significant", "all hardware", "energy saving", "energy improvement", "proves"):
                self.assertNotIn(banned, low)

    def test_chinese_text_quotes_the_same_numbers(self):
        """Language switch: every *_zh sibling exists and carries exactly the numbers of its English field."""
        num = re.compile(r"[−+]?\d+(?:\.\d+)?")
        pairs = [(f, "title") for f in self.bundle["findings"]] + [(f, "text") for f in self.bundle["findings"]]
        pairs += [(a, "summary") for a in self.bundle["arms"]] + [(e, "reason") for e in self.bundle["excluded"]]
        pairs += [(f, "regime") for f in self.bundle["mechanism"]["feasibility"]]
        pairs += [(self.bundle["mechanism"], "model_note"), (self.bundle["simulation"], "note")]
        pairs += [(s, "role") for s in self.bundle["sources"]]
        for obj, key in pairs:
            with self.subTest(key=key, en=obj[key][:60]):
                zh = obj.get(key + "_zh")
                self.assertTrue(zh, "missing Chinese text")
                if key != "role":
                    self.assertNotEqual(zh, obj[key])
                self.assertEqual(sorted(num.findall(zh)), sorted(num.findall(obj[key])))
        self.assertEqual({s["role"] for s in self.bundle["sources"]} - set(bd.ROLE_ZH), set())
        k, f = self.bundle["kpis"], {x["id"]: x["text_zh"] for x in self.bundle["findings"]}
        g = k["guard_vs_latest_primary"]
        self.assertIn(f"{-g['mean']:.1f} pp", f["guard"])
        self.assertIn("不是 equivalence test", f["adaptive"])
        for text in f.values():  # same claim limits as the English findings
            for banned in ("顯著", "所有硬體", "節能", "證明"):
                self.assertNotIn(banned, text)

    def test_cross_architecture_comparisons_are_flagged(self):
        for p in self.bundle["scheduling"]["paired"]:
            legacy = {p["arm"], p["reference"]} & {"legacy_q1", "legacy_q5"}
            app = {p["arm"], p["reference"]} - {"legacy_q1", "legacy_q5"}
            expected = "cross_architecture" if legacy and app else "same_architecture"
            self.assertEqual(p["comparison"], expected, (p["arm"], p["reference"]))

    def test_feasibility_view_is_derived_from_arms(self):
        for f in self.bundle["mechanism"]["feasibility"]:
            c = next(x for x in self.bundle["scheduling"]["conditions"] if x["id"] == f["condition"])
            self.assertAlmostEqual(f["inter_arrival_ms"], round(1000.0 / c["input_fps"], 2), places=2)
            self.assertAlmostEqual(f["age_bound_ms"], f["inter_arrival_ms"] + f["service_ms"], delta=0.02)
            self.assertEqual(f["overloaded"], f["utilization"] >= 1.0)

    def test_simulation_is_separate_and_builtin_only(self):
        sim = self.bundle["simulation"]
        self.assertEqual(sim["kind"], "simulation_estimate")
        self.assertIn("not hardware measurements", sim["note"])
        self.assertTrue(sim["rows"])
        self.assertNotIn("simulation", json.dumps(self.bundle["kpis"]))


class FailureBehaviourTest(unittest.TestCase):
    """Missing, tampered or excluded data stops the build and writes nothing."""

    def setUp(self):
        self.t = TempRoot()

    def tearDown(self):
        self.t.cleanup()

    def test_clean_temp_root_builds(self):
        self.t.build()
        built = json.loads((self.t.root / "out" / bd.OUTPUT_JSON).read_text(encoding="utf-8"))
        committed = json.loads((DATA_DIR / bd.OUTPUT_JSON).read_text(encoding="utf-8"))
        self.assertEqual(built["kpis"], committed["kpis"])

    def test_missing_input_is_blocked_and_writes_nothing(self):
        for rel in (bd.P3_PAIRED, bd.P2_CONDITIONS, bd.SIM_SIDECAR):
            with self.subTest(missing=rel):
                t = TempRoot()
                try:
                    t.path(rel).unlink()
                    proc = t.build(expect=bd.BLOCKED)
                    self.assertIn("BLOCKED", proc.stderr)
                    self.assertFalse((t.root / "out").exists())
                finally:
                    t.cleanup()

    def test_missing_raw_directory_is_blocked(self):
        (self.t.root / "results/raw/ros2_phase3_formal").unlink()
        proc = self.t.build(expect=bd.BLOCKED)
        self.assertIn("missing", proc.stderr)

    def test_tampered_table_is_broken(self):
        rows = _csv(self.t.path(bd.P3_ARMS))
        rows[0]["effective_miss_rate_pct_mean"] = "0"
        _write_csv(self.t.path(bd.P3_ARMS), rows)
        proc = self.t.build(expect=bd.BROKEN)
        self.assertIn("SHA-256", proc.stderr)
        self.assertFalse((self.t.root / "out").exists())

    def test_pilot_run_in_a_formal_table_is_rejected(self):
        rows = _csv(self.t.path(bd.P3_ARMS))
        rows[0]["run_ids"] += ";sched_sweep_mobilevit_s_normal_20fps_latest_q10_d0_p3b1_r1"
        _write_csv(self.t.path(bd.P3_ARMS), rows)
        self.t.rehash(bd.P3_ARMS)
        proc = self.t.build(expect=bd.BROKEN)
        self.assertIn("non-formal run", proc.stderr)

    def test_unconstrained_run_is_rejected(self):
        rows = _csv(self.t.path(bd.P2_RUNS))
        rows[0]["measurement_class"] = "unconstrained"
        _write_csv(self.t.path(bd.P2_RUNS), rows)
        self.t.rehash(bd.P2_RUNS)
        proc = self.t.build(expect=bd.BROKEN)
        self.assertIn("constrained", proc.stderr)

    def test_incomplete_condition_is_rejected(self):
        rows = [r for r in _csv(self.t.path(bd.P3_ARMS))
                if not (r["scheduler_arm"] == "adaptive_c5_q10" and r["input_fps"] == "20.0" and not r["fps_schedule"])]
        _write_csv(self.t.path(bd.P3_ARMS), rows)
        self.t.rehash(bd.P3_ARMS)
        proc = self.t.build(expect=bd.BROKEN)
        self.assertIn("arms, expected 6", proc.stderr)

    def test_non_builtin_simulation_rows_are_rejected(self):
        rows = _csv(self.t.path(bd.SIM_SWEEP))
        rows[0]["os_profile_provenance"] = "unverified"
        _write_csv(self.t.path(bd.SIM_SWEEP), rows)
        self.t.rehash(bd.SIM_SWEEP)
        proc = self.t.build(expect=bd.BROKEN)
        self.assertIn("built-in", proc.stderr)

    def test_excluded_paths_are_refused(self):
        src = bd.Sources(REPO)
        for rel in ("results/csv/ros2_phase3_pilot_arms.csv",
                    "experiments/eda_lite/runtime_os_profiles.legacy_unverified.json",
                    "experiments/eda_lite/runtime_os_profiles.example.json",
                    "results/csv/eda_lite_mobilevit_runtime_aware_sweep.csv"):
            with self.subTest(rel=rel):
                with self.assertRaises(bd.DashboardDataError) as ctx:
                    src.path(rel, "test")
                self.assertEqual(ctx.exception.status, bd.BROKEN)

    def test_check_reports_stale_bundle(self):
        self.t.build()
        out = self.t.root / "out" / bd.OUTPUT_JSON
        out.write_text(out.read_text(encoding="utf-8").replace('"schema"', '"schema_x"', 1), encoding="utf-8")
        proc = self.t.build("--check", expect=bd.STALE)
        self.assertIn("STALE", proc.stderr)
        (self.t.root / "out" / bd.OUTPUT_JS).unlink()
        self.t.build("--check", expect=bd.STALE)


class FrontendTest(unittest.TestCase):
    """Static checks of the page: self-contained, five views, separate simulation entry."""

    def test_pages_load_no_external_resources(self):
        for f in [*DASH.glob("*.html"), *(DASH / "assets").glob("*.js"), *(DASH / "assets").glob("*.css"),
                  *(DASH / "assets").glob("*.svg")]:
            text = f.read_text(encoding="utf-8")
            with self.subTest(file=f.name):
                for m in re.finditer(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", text):
                    self.assertFalse(re.match(r"(https?:)?//", m.group(1)), f"{f.name}: external {m.group(1)}")
                self.assertNotIn("@import url(http", text)

    def test_referenced_local_files_exist(self):
        for page in DASH.glob("*.html"):
            for m in re.finditer(r"""(?:src|href)\s*=\s*["']([^"'#?]+)""", page.read_text(encoding="utf-8")):
                with self.subTest(page=page.name, ref=m.group(1)):
                    self.assertTrue((DASH / m.group(1)).is_file())

    def test_information_architecture(self):
        index = (DASH / "index.html").read_text(encoding="utf-8")
        for view in ("overview", "baseline", "scheduling", "mechanism", "evidence"):
            self.assertIn(f'href="#{view}"', index)
            self.assertIn(f'id="view-{view}"', index)
        self.assertIn('href="simulation.html"', index)
        sim = (DASH / "simulation.html").read_text(encoding="utf-8")
        self.assertIn("Simulation estimates", sim)
        self.assertIn("Estimates", index)

    def test_missing_data_has_an_empty_state(self):
        for js in ("app.js", "simulation.js"):
            self.assertIn("not found", (DASH / "assets" / js).read_text(encoding="utf-8"), js)

    def test_preview_server_is_localhost_only(self):
        script = (REPO / "scripts/serve_dashboard.sh").read_text(encoding="utf-8")
        self.assertIn("HOST=127.0.0.1", script)
        self.assertIn('--bind "$HOST"', script)
        self.assertNotIn("0.0.0.0", script.replace("never 0.0.0.0", ""))


if __name__ == "__main__":
    unittest.main()
