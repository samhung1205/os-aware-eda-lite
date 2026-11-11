"""Phase 3 / Batch 2: deadline_guard ablation policy, dynamic input rate, formal A/B driver,
host load gate. Standard library only (no ROS 2)."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from collections import deque
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import test_phase3_scheduling as p3  # noqa: E402
from test_phase3_scheduling import MS, cfg, est, item, run_log, sched  # noqa: E402
from src.ros2_runtime import host_load_gate as gate  # noqa: E402

PIPELINE_DIR = REPO / "src/ros2_uav_pipeline/mobilevit_uav_pipeline"


class DeadlineGuardTest(unittest.TestCase):
    def test_guard_is_an_application_policy(self):
        self.assertIn("deadline_guard", sched.APP_POLICIES)
        self.assertEqual(sched.DEADLINE_AWARE_POLICIES, ("adaptive", "deadline_guard"))

    def test_guard_takes_newest_feasible_even_when_not_overloaded(self):
        # Same queue / estimates as test_adaptive_edf_takes_oldest_feasible_when_not_overloaded:
        # adaptive -> oldest feasible (edf); the guard has no utilisation switch.
        q_a, q_g = deque([item(0, 0), item(1, 10)]), deque([item(0, 0), item(1, 10)])
        e = est(30, 30, fps=10)  # rho 0.3
        a = sched.select(cfg("adaptive", deadline_ms=100), q_a, 20 * MS, e)
        g = sched.select(cfg("deadline_guard", deadline_ms=100), q_g, 20 * MS, e)
        self.assertEqual((a[0].frame_id, a[2]), (0, "edf"))
        self.assertEqual((g[0].frame_id, g[2]), (1, "newest_feasible"))
        self.assertEqual([(d.frame_id, r) for d, r in g[1]], [(0, "superseded")])
        self.assertEqual(list(q_g), [])

    def test_guard_equals_adaptive_when_overloaded(self):
        for now_ms, e in ((20, est(30, 60, fps=20)), (120, est(40, 60, fps=20)),
                          (80, est(60, 60, fps=20, ingest=1.0)), (10, est(150, 150, fps=20))):
            frames = [(0, 0), (1, 20), (2, 40)]
            qa = deque(item(f, p) for f, p in frames if p <= now_ms)
            qg = deque(item(f, p) for f, p in frames if p <= now_ms)
            a = sched.select(cfg("adaptive", deadline_ms=100), qa, now_ms * MS, e)
            g = sched.select(cfg("deadline_guard", deadline_ms=100), qg, now_ms * MS, e)
            with self.subTest(now_ms=now_ms):
                self.assertEqual(None if a[0] is None else a[0].frame_id,
                                 None if g[0] is None else g[0].frame_id)
                self.assertEqual(a[2], g[2])
                self.assertEqual([(d.frame_id, r) for d, r in a[1]], [(d.frame_id, r) for d, r in g[1]])
                self.assertEqual([f.frame_id for f in qa], [f.frame_id for f in qg])

    def test_guard_shares_no_estimate_wait_and_best_effort(self):
        c = cfg("deadline_guard", deadline_ms=100)
        chosen, _, decision = sched.select(c, deque([item(0, 0), item(1, 50)]), 500 * MS, est())
        self.assertEqual((chosen.frame_id, decision), (0, "no_estimate"))
        chosen, drops, decision = sched.select(c, deque([item(0, 0), item(1, 20)]), 80 * MS,
                                               est(60, 60, fps=5, ingest=1.0))
        self.assertEqual((chosen, decision), (None, "wait"))
        self.assertEqual({r for _, r in drops}, {"deadline_infeasible"})
        chosen, drops, decision = sched.select(c, deque([item(0, 0), item(1, 5)]), 10 * MS,
                                               est(150, 150, fps=5))
        self.assertEqual((chosen.frame_id, decision), (1, "best_effort"))

    def test_params_guard_has_no_switch_and_adaptive_text_is_unchanged(self):
        self.assertEqual(
            cfg("adaptive").params_text(),  # identical to the Batch 1 pilot rows
            "capacity=5;deadline_ms=100.0;margin_ms=0.0;overflow=evict_oldest;"
            "overload_threshold=1.0;quantile=0.9;window=32")
        self.assertEqual(
            cfg("deadline_guard").params_text(),
            "capacity=5;deadline_ms=100.0;margin_ms=0.0;overflow=evict_oldest;quantile=0.9;window=32")

    def test_guard_overflow_evicts_oldest_and_bounded(self):
        c, q = cfg("deadline_guard", queue_capacity=2), deque()
        drops = []
        for i in range(5):
            drops += sched.admit(c, q, item(i, i))
            self.assertLessEqual(len(q), 2)
        self.assertEqual([(d.frame_id, r) for d, r in drops],
                         [(0, "queue_full_evict_oldest"), (1, "queue_full_evict_oldest"),
                          (2, "queue_full_evict_oldest")])


class GuardThreadingTest(unittest.TestCase):
    def test_guard_overload_accounting_and_monotone(self):
        # Same producer/consumer harness as the Batch 1 policies (not subclassed: no re-run).
        rows, stats = p3.SchedulerThreadingTest._run(self, "deadline_guard", producer_gap_s=0.001, service_s=0.004, deadline_ms=20.0)
        self.assertGreater(stats["dropped"], 0)
        processed = [f for f, w in rows.items() if w == "processed"]
        self.assertEqual(processed, sorted(processed))


class FpsScheduleTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(run_log.parse_fps_schedule("10@20,20@20,10@20"),
                         [(10.0, 20.0), (20.0, 20.0), (10.0, 20.0)])
        for empty in ("", "  ", "none", None):
            self.assertEqual(run_log.parse_fps_schedule(empty), [])
        for bad in ("10:20", "10@0", "0@5", "10@x", "10@5@3"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                run_log.parse_fps_schedule(bad)

    def test_rate_and_phase_at_elapsed(self):
        s = run_log.parse_fps_schedule("10@20,20@20,10@20")
        for t, fps, phase in ((0, 10, 0), (19.99, 10, 0), (20, 20, 1), (39.9, 20, 1),
                              (40, 10, 2), (75, 10, 2)):
            self.assertEqual(run_log.scheduled_fps(s, t), fps, t)
            self.assertEqual(run_log.schedule_phase(s, t), phase, t)

    def test_publisher_and_launch_keep_fixed_mode_by_default(self):
        pub = (PIPELINE_DIR / "image_stream_node.py").read_text()
        self.assertIn("self.declare_parameter('fps_schedule', ''", pub)
        self.assertIn("if self.fps_schedule:\n            self._apply_fps_schedule()", pub)
        self.assertIn("timer_period_ns", pub)  # period change, no timer destroyed in its callback
        launch = (REPO / "src/ros2_uav_pipeline/launch/mobilevit_uav_pipeline.launch.py").read_text()
        self.assertIn("('fps_schedule', '')", launch)
        # an empty schedule is not forwarded: the publisher command line is unchanged
        self.assertIn("if value['fps_schedule'].strip() else []", launch)
        # the publisher log format is unchanged (the phase is derived from timestamps)
        self.assertEqual(run_log.PUBLISHER_CSV_HEADER, ["run_id", "frame_id", "published_at_ns"])


def _formal_plan(**env_extra):
    env = {**os.environ, "DRY_RUN": "1", **env_extra}
    proc = subprocess.run(["bash", "experiments/ros2/run_sched_formal.sh"], cwd=REPO, env=env,
                          capture_output=True, text=True)
    return proc, [line.strip().split("|") for line in proc.stdout.splitlines() if line.startswith("  ")
                  and "|" in line]


class FormalDriverTest(unittest.TestCase):
    ARMS = ["legacy_qos:1", "legacy_qos:5", "fifo", "latest_frame", "deadline_guard", "adaptive"]

    def test_default_plan(self):
        proc, plan = _formal_plan()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        blocks: dict[str, list] = {}
        for rnd, name, k, model, fps, delay, schedule, order in plan:
            self.assertEqual(sorted(order.split()), sorted(self.ARMS), "every arm exactly once per block")
            blocks.setdefault(name, []).append((int(rnd), int(k), order.split()))
        self.assertEqual({n: len(b) for n, b in blocks.items()},
                         {"s20": 5, "s10": 3, "s30": 3, "xxs30d25": 3, "sdyn": 3})
        for name, b in blocks.items():
            self.assertEqual([k for _, k, _ in b], list(range(1, len(b) + 1)), name)
            self.assertEqual(len({order[0] for _, _, order in b}), len(b), f"{name}: same first arm")
            if len(b) == 3:
                self.assertEqual([r for r, _, _ in b], [1, 3, 5], f"{name}: blocks spread over rounds")
        sdyn = [p for p in plan if p[1] == "sdyn"][0]
        self.assertEqual(sdyn[6], "10@20,20@20,10@20")
        self.assertIn("RUN_SECONDS=65", proc.stdout)

    def test_custom_conditions_and_bad_blocks(self):
        proc, plan = _formal_plan(FORMAL_CONDITIONS="a|mobilevit_s|20|0|-|2 b|mobilevit_xxs|20|0|-|1",
                                  SCHED_ARMS="fifo adaptive")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([(p[0], p[1], p[2]) for p in plan], [("1", "a", "1"), ("1", "b", "1"), ("2", "a", "2")])
        proc, _ = _formal_plan(FORMAL_CONDITIONS="a|mobilevit_s|20|0|-|0")
        self.assertEqual(proc.returncode, 2)

    def test_git_and_load_gate_before_every_block(self):
        text = (REPO / "experiments/ros2/run_sched_formal.sh").read_text()
        loop = text[text.index('for entry in "${plan[@]}"; do'):]
        run = loop.index("run_baseline_experiments.sh")
        self.assertLess(loop.index("git status --porcelain"), run)
        self.assertLess(loop.index("host_load_gate"), run)
        self.assertIn("exit 4", loop)

    def test_sweep_accepts_guard_and_labels_dynamic_runs(self):
        env = {**os.environ, "PATH": "/usr/bin:/bin", "SCHED_ARMS": "deadline_guard lifo"}
        proc = subprocess.run(["bash", "experiments/ros2/run_sched_sweep.sh"], cwd=REPO, env=env,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("'lifo'", proc.stderr)  # deadline_guard passed validation
        text = (REPO / "experiments/ros2/run_sched_sweep.sh").read_text()
        self.assertIn('arm_label="guard_c${QUEUE_CAPACITY}_q${arm_depth}"', text)
        self.assertIn('SCENARIO="sched_dynamic"', text)
        self.assertIn('fps_schedule="$FPS_SCHEDULE"', text)  # recorded in meta.json


class HostLoadGateTest(unittest.TestCase):
    def test_busy_pct(self):
        before = {12: (1000, 900), 13: (1000, 1000)}
        after = {12: (1100, 950), 13: (1100, 1100)}
        self.assertEqual(gate.busy_pct(before, after, [12, 13, 14]), {12: 50.0, 13: 0.0, 14: 100.0})

    def test_evaluate(self):
        self.assertEqual(gate.evaluate({12: 3.0, 13: 0.0}, 1.5, 15, 6), (True, []))
        quiet, reasons = gate.evaluate({12: 30.0, 13: 0.0}, 7.0, 15, 6)
        self.assertFalse(quiet)
        self.assertEqual(len(reasons), 2)


if __name__ == "__main__":
    unittest.main()
