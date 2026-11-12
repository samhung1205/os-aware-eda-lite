"""Phase 1 / Batch 4 (audit P2-1 .. P2-6): CI, dependencies, repo hygiene, pipeline contracts.

Standard library only. ROS 2 is not needed: the launch file runs against stub
launch modules (shared with test_ros2_measurement) and node sources are
inspected statically.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cli_support import describe_failure, run_cli  # noqa: E402

from src.eda_lite.model_loader import load_model_profile  # noqa: E402

PIPELINE_DIR = REPO / "src/ros2_uav_pipeline/mobilevit_uav_pipeline"
LAUNCH_FILE = REPO / "src/ros2_uav_pipeline/launch/mobilevit_uav_pipeline.launch.py"
SWEEPS = ("run_fps_sweep.sh", "run_qos_sweep.sh", "run_overload_sweep.sh")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git_ls_files():
    if shutil.which("git") is None:
        return None
    proc = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=False)
    return proc.stdout.splitlines() if proc.returncode == 0 else None


def _layer(name, inp, out, **extra):
    return {"name": name, "op_type": "Conv", "input_kb": inp, "output_kb": out,
            "weight_kb": 1, "compute_macs": 1, "fusible": True, **extra}


class StrictModelLoadingTest(unittest.TestCase):
    """P2-6: a failed model load must end the run, never substitute another model."""

    def setUp(self):
        self.run_log = _load("run_log_quality_test", PIPELINE_DIR / "run_log.py")

    def test_creates_exactly_the_requested_model_with_random_weights(self):
        calls = []
        model = self.run_log.create_model_strict(
            " mobilevit_s ", lambda name, pretrained: calls.append((name, pretrained)) or "model")
        self.assertEqual(model, "model")
        self.assertEqual(calls, [("mobilevit_s", False)])
        self.assertEqual(self.run_log.MODEL_WEIGHTS, "random_init")

    def test_unknown_model_raises_without_fallback(self):
        calls = []

        def create(name, pretrained):
            calls.append(name)
            raise RuntimeError(f"Unknown model ({name})")

        with self.assertRaisesRegex(RuntimeError, "Refusing to fall back.*mobilevit_typo|mobilevit_typo.*Refusing"):
            self.run_log.create_model_strict("mobilevit_typo", create)
        self.assertEqual(calls, ["mobilevit_typo"])  # no second attempt with another model

    def test_empty_model_name_is_rejected(self):
        for value in ("", "  ", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_log.create_model_strict(value, lambda name, pretrained: "model")

    def test_detector_source_has_no_fallback(self):
        source = (PIPELINE_DIR / "mobilevit_detector_node.py").read_text(encoding="utf-8")
        self.assertIn("create_model_strict(self.model_name, timm.create_model)", source)
        self.assertNotIn("self.model_name = 'mobilevit_xxs'", source)
        self.assertNotIn("pretrained=True", source)
        # The run CSV is created only after the model loaded, so a failed load leaves no CSV.
        self.assertLess(source.index("create_model_strict("), source.index("create_run_csv("))


class ModelPathRemovedTest(unittest.TestCase):
    """P2-6: model_path was declared and forwarded but never used by any node."""

    def setUp(self):
        from test_ros2_measurement import _stub_launch_modules  # shared launch stubs

        stubs = _stub_launch_modules()
        saved = {name: sys.modules.get(name) for name in stubs}
        sys.modules.update(stubs)
        self.addCleanup(lambda: [sys.modules.pop(n) if v is None else sys.modules.__setitem__(n, v)
                                 for n, v in saved.items()])
        self.launch = _load("launch_quality_test", LAUNCH_FILE)

    def _run(self, **overrides):
        entities = self.launch.generate_launch_description().args[0]
        defaults = {e.args[0]: e.kwargs["default_value"] for e in entities
                    if type(e).__name__ == "DeclareLaunchArgument"}
        opaque = [e for e in entities if type(e).__name__ == "OpaqueFunction"][0]
        context = types.SimpleNamespace(launch_configurations={**defaults, **overrides})
        return defaults, opaque.kwargs["function"](context)

    def test_launch_does_not_declare_or_forward_model_path(self):
        defaults, actions = self._run()
        self.assertNotIn("model_path", defaults)
        for process in (a for a in actions if type(a).__name__ == "ExecuteProcess"):
            self.assertFalse(any("model_path" in str(part) for part in process.kwargs["cmd"]))

    def test_passing_model_path_fails_instead_of_being_ignored(self):
        with self.assertRaisesRegex(RuntimeError, "model_path is not supported"):
            self._run(model_path="weights.pt")

    def test_sweep_scripts_do_not_forward_model_path(self):
        for name in SWEEPS:
            text = (REPO / "experiments/ros2" / name).read_text(encoding="utf-8")
            self.assertNotIn("model_path", text, name)
            self.assertNotIn("MODEL_PATH", text, name)
            self.assertIn("model_weights=random_init", text, name)

    @unittest.skipIf(shutil.which("bash") is None, "bash required")
    def test_sweep_refuses_model_path_environment_variable(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "MODEL_PATH": "weights.pt", "RESULTS_DIR": tmp, "PATH": "/usr/bin:/bin"}
            proc = run_cli(["bash", REPO / "experiments/ros2/run_fps_sweep.sh"], expect=2, env=env)
            self.assertIn("MODEL_PATH", proc.stderr)
            self.assertEqual(list(Path(tmp).iterdir()), [])


class ModelProfileValidationTest(unittest.TestCase):
    """P2-6: structural checks on simplified model profiles."""

    def _load(self, layers):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            # allow_nan: json.dump writes NaN/Infinity tokens, which json.load accepts.
            path.write_text(json.dumps({"model_name": "m", "layers": layers}), encoding="utf-8")
            return load_model_profile(path)

    def test_all_repository_profiles_pass_validation(self):
        for path in sorted((REPO / "data/model_profiles").glob("*.json")):
            with self.subTest(profile=path.name):
                self.assertGreater(len(load_model_profile(path).layers), 0)

    def test_broken_tensor_chain_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r"layers\[0\]\.output_kb \(20\) != layers\[1\]\.input_kb \(30\)"):
            self._load([_layer("a", 10, 20), _layer("b", 30, 30)])

    def test_chain_tolerates_float_rounding(self):
        profile = self._load([_layer("a", 10, 0.1 + 0.2), _layer("b", 0.3, 5)])
        self.assertEqual(len(profile.layers), 2)

    def test_duplicate_layer_names_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicates"):
            self._load([_layer("a", 10, 10), _layer("a", 10, 10)])

    def test_non_finite_numbers_are_rejected(self):
        for value in (math.nan, math.inf):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite"):
                self._load([_layer("a", 10, value)])


class DependencySplitTest(unittest.TestCase):
    """P2-2: stdlib simulator vs pinned ROS 2 node dependencies."""

    def _requirements(self, name):
        return [ln.strip() for ln in (REPO / name).read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")]

    def test_simulator_needs_no_packages(self):
        self.assertEqual(self._requirements("requirements-sim.txt"), [])

    def test_ros2_node_requirements_are_pinned_and_exclude_ros_packages(self):
        pins = [p for p in self._requirements("requirements-ros2.txt") if not p.startswith("-")]
        self.assertTrue(pins)
        for pin in pins:
            self.assertRegex(pin, r"^[A-Za-z0-9_.-]+==[0-9][0-9A-Za-z.+]*$")
        names = {p.split("==")[0].lower() for p in pins}
        self.assertTrue({"torch", "timm", "numpy", "psutil"} <= names)
        # cv2 must come from conda's opencv (cv_bridge), rclpy etc. from ROS 2.
        self.assertFalse(names & {"opencv-python", "opencv-contrib-python", "rclpy", "cv_bridge"})
        self.assertTrue(next(p for p in pins if p.startswith("numpy==")).startswith("numpy==1."))

    def test_environment_pins_python_and_ros_distro(self):
        text = (REPO / "environment.yml").read_text(encoding="utf-8")
        self.assertIn("- python=3.10", text)
        self.assertIn("ros-humble-ros-base", text)
        self.assertIn("ros-humble-cv-bridge", text)
        self.assertIn("-r requirements-ros2.txt", text)
        self.assertEqual(self._requirements("requirements.txt"), ["-r requirements-ros2.txt"])

    def test_simulator_and_analysis_modules_import_only_the_standard_library(self):
        stdlib = set(sys.stdlib_module_names)
        roots = [REPO / "src/eda_lite", REPO / "src/ros2_runtime", REPO / "src/dashboard", REPO / "src/provenance.py",
                 *sorted((REPO / "scripts").glob("*.py"))]
        files = [p for r in roots for p in (r.rglob("*.py") if r.is_dir() else [r])]
        for path in files:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                for name in names:
                    top = name.split(".")[0]
                    with self.subTest(file=str(path.relative_to(REPO)), module=name):
                        self.assertTrue(top in stdlib or top in {"src", "__future__"},
                                        f"{path.relative_to(REPO)} imports non-stdlib '{name}'")


class RepositoryHygieneTest(unittest.TestCase):
    """P2-3: no tracked caches; results tracking policy matches .gitignore."""

    def test_no_tracked_caches_or_os_files(self):
        files = _git_ls_files()
        if files is None:
            self.skipTest("not a git checkout")
        junk = [f for f in files if "__pycache__/" in f or f.endswith((".pyc", ".DS_Store"))
                or Path(f).name.startswith("~$")]
        self.assertEqual(junk, [])

    def test_results_policy_in_gitignore(self):
        if shutil.which("git") is None:
            self.skipTest("git required")

        def ignored(path):
            return subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=REPO,
                                  check=False).returncode == 0

        if subprocess.run(["git", "rev-parse"], cwd=REPO, capture_output=True, check=False).returncode:
            self.skipTest("not a git checkout")
        for path in ("results/raw/ros2/r1.csv", "results/raw/ros2/r1.publisher.csv",
                     "results/raw/ros2/r1.meta.json", "results/csv/ros2_runtime_summary.csv",
                     "results/csv/ros2_runtime_summary.manifest.json",
                     "results/csv/eda_lite_x.provenance.json", "experiments/eda_lite/runtime_os_profiles.json"):
            with self.subTest(tracked=path):
                self.assertFalse(ignored(path), f"{path} must be trackable")
        for path in ("results/raw/ros2/r1.csv.failed", "stray.csv", "src/__pycache__/m.cpython-311.pyc",
                     "results/.DS_Store", "~$deck.pptx", "ci-logs/tests.log"):
            with self.subTest(ignored=path):
                self.assertTrue(ignored(path), f"{path} must be ignored")

    def test_tracked_simulation_csvs_have_sidecars(self):
        files = _git_ls_files()
        if files is None:
            self.skipTest("not a git checkout")
        tracked = set(files)
        for csv_path in ("results/csv/eda_lite_mobilevit_profile_sweep.csv",
                         "results/csv/eda_lite_mobilevit_runtime_aware_sweep.csv"):
            self.assertIn(csv_path, tracked)
            self.assertIn(csv_path[:-4] + ".provenance.json", tracked)


class ContinuousIntegrationTest(unittest.TestCase):
    """P2-1 / P2-5: the workflow runs the checks, and the checks themselves behave."""

    def test_workflow_runs_every_check_without_ros2(self):
        text = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        for step in ("tests", "shell", "audit", "provenance", "repeat 5"):
            self.assertIn(f"bash scripts/ci_checks.sh {step}", text)
        for version in ("3.10", "3.11", "3.12", "3.13"):
            self.assertIn(f'"{version}"', text)
        commands = [ln.split("run:", 1)[1] for ln in text.splitlines() if ln.strip().startswith("run:")]
        self.assertTrue(commands)
        for command in commands:  # CI installs nothing: stdlib only, no ROS 2
            self.assertNotIn("pip", command)
            self.assertNotIn("conda", command)
            self.assertNotIn("apt", command)
        self.assertNotIn("continue-on-error", text)
        # The Phase 3 gate needs the measurement commit in history: the job that runs it must not
        # use the default shallow checkout (it would report BROKEN on GitHub but pass locally).
        jobs = re.split(r"\n  (?=[a-z][\w-]*:\n)", text.split("\njobs:\n", 1)[1])
        gate_jobs = [j for j in jobs if "ci_checks.sh provenance" in j]
        self.assertEqual(len(gate_jobs), 1)
        self.assertIn("fetch-depth: 0", gate_jobs[0])

    def test_pages_workflow_verifies_before_publishing_dashboard_only(self):
        """Release v1.0.0: Pages deploys dashboard/ from main only after every evidence check."""

        text = (REPO / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        self.assertIn("branches: [main]", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("if: github.ref == 'refs/heads/main'", text)
        self.assertIn("fetch-depth: 0", text)  # Phase 3 gate needs the measurement commit
        self.assertNotIn("continue-on-error", text)
        commands = [ln.split("run:", 1)[1].strip() for ln in text.splitlines() if ln.strip().startswith("run:")]
        for command in commands:  # nothing installed: stdlib only, no ROS 2
            for tool in ("pip", "conda", "apt", "npm"):
                self.assertNotIn(tool, command)
        checks = ["python3 scripts/check_runtime_provenance.py",
                  "python3 scripts/check_phase3_provenance.py --expect-runs 102",
                  "python3 scripts/check_table_regeneration.py",
                  "python3 -m src.dashboard.build_data --check"]
        self.assertEqual(commands, checks)
        upload = text.index("actions/upload-pages-artifact@")
        for check in checks:  # every check runs before the artifact is uploaded
            self.assertLess(text.index(check), upload)
        self.assertRegex(text[upload:], r"with:\n\s+path: dashboard\n")
        self.assertEqual(len(re.findall(r"^\s+path:", text, re.M)), 1)
        self.assertIn("actions/deploy-pages@", text)
        self.assertIn("needs: build", text)
        # ci.yml is kept alongside it
        self.assertTrue((REPO / ".github/workflows/ci.yml").is_file())

    def test_dashboard_uses_only_relative_paths_inside_dashboard(self):
        """The site must work under a repository subpath (https://<user>.github.io/<repo>/)."""

        site = REPO / "dashboard"
        refs = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+)["']|url\(\s*["']?([^"')]+)""")
        files = [*site.glob("*.html"), *site.glob("assets/*.js"), *site.glob("assets/*.css")]
        self.assertTrue(files)
        for path in files:
            text = path.read_text(encoding="utf-8")
            for match in refs.finditer(text):
                ref = match.group(1) or match.group(2)
                if ref.startswith(("#", "data:")) or "${" in ref:
                    continue
                with self.subTest(file=path.name, ref=ref):
                    self.assertFalse(ref.startswith(("/", "http:", "https:", "//")), "absolute or external")
                    self.assertNotIn("..", ref, "points outside dashboard/")
                    # CSS url() resolves against the stylesheet; HTML and links built in JS
                    # resolve against the page, which is always in dashboard/.
                    base = path.parent if path.suffix == ".css" else site
                    target = (base / ref.split("#", 1)[0].split("?", 1)[0]).resolve()
                    self.assertTrue(target.is_file(), f"missing {target}")
                    self.assertTrue(target.is_relative_to(site.resolve()))

    def test_license_is_mit(self):
        text = (REPO / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("MIT License\n"))
        self.assertRegex(text, r"Copyright \(c\) \d{4} \S")

    @unittest.skipIf(shutil.which("bash") is None, "bash required")
    def test_ci_script_syntax_and_usage(self):
        run_cli(["bash", "-n", REPO / "scripts/ci_checks.sh"])
        proc = run_cli(["bash", REPO / "scripts/ci_checks.sh", "bogus"], expect=2)
        self.assertIn("usage", proc.stderr)

    @unittest.skipIf(shutil.which("bash") is None, "bash required")
    def test_provenance_gate_keeps_blocked_and_rejects_fake_verified(self):
        """BLOCKED passes as BLOCKED; VERIFIED without raw data fails; BROKEN fails."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            shutil.copy(REPO / "scripts/ci_checks.sh", root / "scripts/ci_checks.sh")
            (root / "results/raw/ros2").mkdir(parents=True)
            checker = root / "scripts/check_runtime_provenance.py"
            for exit_code, expect, needle in ((1, 0, "BLOCKED"), (0, 1, "reported VERIFIED but"),
                                              (2, 2, "BROKEN")):
                with self.subTest(checker_exit=exit_code):
                    checker.write_text(f"import sys; print('fake checker'); sys.exit({exit_code})\n",
                                       encoding="utf-8")
                    proc = run_cli(["bash", root / "scripts/ci_checks.sh", "provenance"], expect=expect,
                                   cwd=root, env={**os.environ, "PYTHON": sys.executable})
                    self.assertIn(needle, proc.stdout + proc.stderr, describe_failure(proc, expect))

    def test_audit_strict_passes_on_current_tree(self):
        proc = run_cli([sys.executable, REPO / "scripts/audit_repro.py", "--strict",
                        "P2-1", "P2-2", "P2-3", "P2-6"], expect=None)
        # P2-3 reports BLOCKED (not a failure) outside a git checkout.
        self.assertEqual(proc.returncode, 0, describe_failure(proc, 0))
        self.assertNotIn("REPRODUCED", proc.stdout)


if __name__ == "__main__":
    unittest.main()
