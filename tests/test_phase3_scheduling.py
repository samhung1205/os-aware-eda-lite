"""Phase 3 / Batch 1: scheduling policies, bounded queue, concurrency, shutdown,
frame accounting and CSV compatibility. Standard library only (no ROS 2)."""

from __future__ import annotations

import ast
import csv
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections import deque
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
PIPELINE_DIR = REPO / "src/ros2_uav_pipeline/mobilevit_uav_pipeline"

from src.ros2_runtime import analyze_runtime as ar  # noqa: E402
from src.ros2_runtime.aggregate_scheduling import build_paired, derive  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


sched = _load("scheduling_under_test", PIPELINE_DIR / "scheduling.py")
run_log = _load("run_log_phase3_test", PIPELINE_DIR / "run_log.py")

MS = 1_000_000


def cfg(policy, **kw):
    return sched.SchedulerConfig(policy=policy, **kw)


def item(fid, pub_ms, recv_ms=None):
    recv = pub_ms if recv_ms is None else recv_ms
    return sched.FrameItem(frame_id=fid, published_at_ns=pub_ms * MS, received_at_ns=recv * MS)


def est(service_q=None, mean_=None, fps=None, ingest=0.0):
    return sched.Estimates(service_q_ms=service_q, service_mean_ms=mean_, arrival_fps=fps,
                           ingest_delay_ms=ingest)


class FakeClock:
    def __init__(self, ms=0):
        self.ns = ms * MS

    def __call__(self):
        return self.ns


class PolicySemanticsTest(unittest.TestCase):
    def test_fifo_serves_in_arrival_order(self):
        c, q = cfg("fifo", queue_capacity=3), deque()
        for i in range(3):
            self.assertEqual(sched.admit(c, q, item(i, i)), [])
        got = [sched.select(c, q, 0, est())[0].frame_id for _ in range(3)]
        self.assertEqual(got, [0, 1, 2])

    def test_fifo_overflow_reject_newest_is_tail_drop(self):
        c, q = cfg("fifo", queue_capacity=2), deque()
        sched.admit(c, q, item(0, 0))
        sched.admit(c, q, item(1, 1))
        drops = sched.admit(c, q, item(2, 2))
        self.assertEqual([(d.frame_id, r) for d, r in drops], [(2, "queue_full_reject_newest")])
        self.assertEqual([f.frame_id for f in q], [0, 1])

    def test_fifo_overflow_evict_oldest_is_head_drop(self):
        c, q = cfg("fifo", queue_capacity=2, fifo_overflow="evict_oldest"), deque()
        for i in range(3):
            drops = sched.admit(c, q, item(i, i))
        self.assertEqual([(d.frame_id, r) for d, r in drops], [(0, "queue_full_evict_oldest")])
        self.assertEqual([f.frame_id for f in q], [1, 2])

    def test_latest_frame_keeps_only_newest(self):
        c, q = cfg("latest_frame", queue_capacity=5), deque()
        self.assertEqual(c.effective_capacity, 1)
        sched.admit(c, q, item(0, 0))
        drops = sched.admit(c, q, item(1, 1))
        self.assertEqual([(d.frame_id, r) for d, r in drops], [(0, "superseded")])
        chosen, drops, decision = sched.select(c, q, 0, est())
        self.assertEqual((chosen.frame_id, drops, decision), (1, [], "latest"))

    def test_adaptive_without_estimate_serves_oldest(self):
        c, q = cfg("adaptive"), deque([item(0, 0), item(1, 50)])
        chosen, drops, decision = sched.select(c, q, 500 * MS, est())
        self.assertEqual((chosen.frame_id, drops, decision), (0, [], "no_estimate"))

    def test_adaptive_edf_drops_infeasible_older_and_keeps_newer(self):
        c = cfg("adaptive", deadline_ms=100)
        q = deque([item(0, 0), item(1, 50), item(2, 100)])
        # now=120 ms, S_q=40: predicted 160 / 110 / 60 -> only frame 2 feasible; not overloaded
        chosen, drops, decision = sched.select(c, q, 120 * MS, est(40, 40, fps=10))
        self.assertEqual(chosen.frame_id, 2)
        self.assertEqual(decision, "edf")
        self.assertEqual([(d.frame_id, r) for d, r in drops],
                         [(0, "deadline_infeasible"), (1, "deadline_infeasible")])
        self.assertEqual(list(q), [])

    def test_adaptive_edf_takes_oldest_feasible_when_not_overloaded(self):
        c = cfg("adaptive", deadline_ms=100)
        q = deque([item(0, 0), item(1, 10)])
        chosen, drops, decision = sched.select(c, q, 20 * MS, est(30, 30, fps=10))  # rho 0.3
        self.assertEqual((chosen.frame_id, drops, decision), (0, [], "edf"))
        self.assertEqual([f.frame_id for f in q], [1])  # still queued, not dropped

    def test_adaptive_overloaded_takes_newest_feasible(self):
        c = cfg("adaptive", deadline_ms=100)
        q = deque([item(0, 0), item(1, 10)])
        chosen, drops, decision = sched.select(c, q, 20 * MS, est(30, 60, fps=20))  # rho 1.2
        self.assertEqual((chosen.frame_id, decision), (1, "newest_feasible"))
        self.assertEqual([(d.frame_id, r) for d, r in drops], [(0, "superseded")])

    def test_adaptive_waits_when_nothing_feasible_but_fresh_frame_could_be(self):
        c = cfg("adaptive", deadline_ms=100)
        q = deque([item(0, 0), item(1, 20)])
        chosen, drops, decision = sched.select(c, q, 80 * MS, est(60, 60, fps=20, ingest=1.0))
        self.assertIsNone(chosen)
        self.assertEqual(decision, "wait")
        self.assertEqual({r for _, r in drops}, {"deadline_infeasible"})
        self.assertEqual(len(q), 0)

    def test_adaptive_best_effort_when_deadline_unattainable(self):
        c = cfg("adaptive", deadline_ms=100)
        q = deque([item(0, 0), item(1, 20)])
        chosen, drops, decision = sched.select(c, q, 30 * MS, est(150, 150, fps=20))
        self.assertEqual((chosen.frame_id, decision), (1, "best_effort"))
        self.assertEqual([(d.frame_id, r) for d, r in drops], [(0, "superseded")])

    def test_adaptive_margin_tightens_budget(self):
        q = deque([item(0, 0)])
        c = cfg("adaptive", deadline_ms=100, adaptive_margin_ms=10)
        chosen, _, decision = sched.select(c, q, 55 * MS, est(40, 40, fps=5))  # 95 > 90
        self.assertIsNone(chosen)
        self.assertEqual(decision, "wait")

    def test_adaptive_overflow_evicts_oldest(self):
        c, q = cfg("adaptive", queue_capacity=2), deque()
        for i in range(3):
            drops = sched.admit(c, q, item(i, i))
        self.assertEqual([(d.frame_id, r) for d, r in drops], [(0, "queue_full_evict_oldest")])

    def test_queue_never_exceeds_capacity_random(self):
        rng = random.Random(7)
        for policy, extra in (("fifo", {}), ("fifo", {"fifo_overflow": "evict_oldest"}),
                              ("latest_frame", {}), ("adaptive", {})):
            c, q, fid = cfg(policy, queue_capacity=3, **extra), deque(), 0
            for _ in range(2000):
                if rng.random() < 0.7:
                    sched.admit(c, q, item(fid, fid))
                    fid += 1
                else:
                    sched.select(c, q, fid * MS, est(rng.choice([None, 5.0, 500.0]), 5.0, fps=30))
                self.assertLessEqual(len(q), c.effective_capacity, policy)

    def test_config_validation_and_params(self):
        for bad in ({"policy": "legacy_qos"}, {"policy": "lifo"},
                    {"policy": "fifo", "queue_capacity": 0},
                    {"policy": "fifo", "fifo_overflow": "x"},
                    {"policy": "adaptive", "adaptive_quantile": 0},
                    {"policy": "adaptive", "adaptive_margin_ms": -1},
                    {"policy": "adaptive", "deadline_ms": 0}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                sched.SchedulerConfig(**bad)
        self.assertEqual(cfg("fifo").params_text(), "capacity=5;overflow=reject_newest")
        self.assertEqual(cfg("latest_frame", queue_capacity=9).params_text(), "capacity=1")
        self.assertIn("quantile=0.9", cfg("adaptive").params_text())


class EstimatorTest(unittest.TestCase):
    def test_window_quantile_is_nearest_rank_and_bounded(self):
        w = sched.WindowEstimator(4)
        self.assertIsNone(w.quantile(0.9))
        for v in (10, 20, 30, 40, 1000):
            w.add(v)
        self.assertEqual(len(w), 4)  # oldest (10) fell out
        self.assertEqual(w.quantile(0.9), 1000)
        self.assertEqual(w.quantile(0.5), 30)

    def test_arrival_rate(self):
        a = sched.ArrivalRateEstimator(5)
        self.assertIsNone(a.rate_fps())
        for i in range(10):
            a.add(i * 50 * MS)
        self.assertAlmostEqual(a.rate_fps(), 20.0)

    def test_estimate_uses_only_completed_non_warmup_service(self):
        s = sched.FrameScheduler(cfg("adaptive"), clock_ns=FakeClock())
        self.assertIsNone(s.estimates().service_q_ms)
        s.record_service(999.0, warmup=True)
        self.assertIsNone(s.estimates().service_q_ms)
        s.record_service(50.0, warmup=False)
        self.assertEqual(s.estimates().service_q_ms, 50.0)


class SchedulerThreadingTest(unittest.TestCase):
    def _run(self, policy, producer_gap_s, service_s, n=300, **kw):
        s = sched.FrameScheduler(cfg(policy, queue_capacity=4, **kw))
        rows: dict[int, str] = {}
        lock = threading.Lock()

        def record(fid, what):
            with lock:
                self.assertNotIn(fid, rows, f"frame {fid} logged twice")
                rows[fid] = what

        def consumer():
            while True:
                it, drops = s.next_frame(timeout=1.0)
                for d, reason in drops:
                    record(d.frame_id, reason)
                if it is None:
                    if s.closed:
                        return
                    continue
                time.sleep(service_s)
                s.record_service(service_s * 1000, warmup=False)
                record(it.frame_id, "processed")

        worker = threading.Thread(target=consumer)
        worker.start()
        for i in range(n):
            now = time.time_ns()
            for d, reason in s.submit(sched.FrameItem(i, now, now)):
                record(d.frame_id, reason)
            time.sleep(producer_gap_s)
        for d in s.close():
            record(d.frame_id, "shutdown_pending")
        worker.join(5)
        self.assertFalse(worker.is_alive(), "worker did not stop after close()")
        stats = s.stats()
        self.assertEqual(stats["submitted"], n)
        self.assertEqual(stats["submitted"],
                         stats["dequeued"] + stats["dropped"] + stats["drained"] + stats["pending"])
        self.assertEqual(sorted(rows), list(range(n)), "every frame exactly one terminal state")
        self.assertLessEqual(stats["max_queue_len"], s.config.effective_capacity)
        return rows, stats

    def test_overload_accounting_all_policies(self):
        for policy in ("fifo", "latest_frame", "adaptive"):
            with self.subTest(policy=policy):
                rows, stats = self._run(policy, producer_gap_s=0.001, service_s=0.004,
                                        **({"deadline_ms": 20.0} if policy == "adaptive" else {}))
                self.assertGreater(stats["dropped"], 0)
                processed = [f for f, w in rows.items() if w == "processed"]
                if policy != "fifo":  # newest-first policies never go back in time
                    self.assertEqual(processed, sorted(processed))

    def test_fifo_underload_drops_nothing(self):
        rows, stats = self._run("fifo", producer_gap_s=0.003, service_s=0.0005, n=100)
        self.assertEqual(stats["dropped"], 0)

    def test_blocked_worker_wakes_on_close(self):
        s = sched.FrameScheduler(cfg("fifo"))
        result = []
        t = threading.Thread(target=lambda: result.append(s.next_frame()))
        t.start()
        time.sleep(0.05)
        self.assertEqual(s.close(), [])
        t.join(2)
        self.assertFalse(t.is_alive())
        self.assertEqual(result, [(None, [])])
        self.assertTrue(s.closed)

    def test_submit_after_close_is_shutdown_drop(self):
        s = sched.FrameScheduler(cfg("fifo"))
        s.close()
        drops = s.submit(item(5, 0))
        self.assertEqual([(d.frame_id, r) for d, r in drops], [(5, "shutdown_pending")])
        self.assertEqual(s.stats()["dropped"], 1)


# ---------------------------------------------------------------- analyzer accounting

def _row(fid, *, dropped=False, reason="", latency=50.0, warmup=False, policy="fifo", cap="5",
         params="capacity=5;overflow=reject_newest", run_id="r1", wait=None, age=None):
    return ar.RuntimeRow(
        scenario="sched_sweep", model_name="mobilevit_s", input_fps="20.0", qos_depth="10",
        fake_delay_ms="0", resource_profile="normal", frame_id=fid,
        latency_ms=None if dropped else latency, inference_ms=None if dropped else 40.0,
        deadline_miss=False if dropped else latency > 100, dropped=dropped, cpu_percent=None,
        memory_mb=None, run_id=run_id, deadline_ms=100.0, warmup=warmup,
        scheduler_policy=policy, queue_capacity=cap, scheduler_params=params, drop_reason=reason,
        queue_wait_ms=wait, frame_age_at_start_ms=age,
        published_at_ns=fid * 50 * MS, completed_at_ns=None if dropped else fid * 50 * MS + int(latency * MS),
    )


class AnalyzerAccountingTest(unittest.TestCase):
    def test_breakdown_is_disjoint_and_sums_to_dropped(self):
        rows = [_row(i, warmup=True) for i in range(3)]  # warm-up 0..2
        rows += [_row(1 + 2, dropped=True, reason="superseded")]  # id 3
        rows += [_row(4, wait=10.0, age=12.0), _row(5, dropped=True, reason="queue_full_reject_newest"),
                 _row(7, latency=150.0, wait=30.0, age=40.0), _row(8, dropped=True, reason="deadline_infeasible"),
                 _row(9, dropped=True, reason="conversion_error"), _row(10, dropped=True, reason="shutdown_pending")]
        published = {"r1": list(range(13))}  # 6 never seen (interior), 11 and 12 after last seen (tail)
        (s,) = ar.build_runtime_summary(rows, publisher_frames=published)
        self.assertEqual(s["published_frames"], "10")  # ids 3..12
        self.assertEqual(s["processed_frames"], "2")
        self.assertEqual(s["dropped_frames"], "8")
        parts = {k: int(s[k]) for k in ("app_policy_dropped_frames", "shutdown_unfinished_frames",
                                         "dds_unreceived_frames", "tail_unobserved_frames",
                                         "other_dropped_frames")}
        self.assertEqual(parts, {"app_policy_dropped_frames": 3, "shutdown_unfinished_frames": 1,
                                 "dds_unreceived_frames": 1, "tail_unobserved_frames": 2,
                                 "other_dropped_frames": 1})
        self.assertEqual(sum(parts.values()), int(s["dropped_frames"]))
        self.assertEqual(s["policy_drop_reasons"],
                         "deadline_infeasible:1;queue_full_reject_newest:1;superseded:1")
        self.assertEqual(s["scheduler_policy"], "fifo")
        self.assertEqual(s["p50_queue_wait_ms"], "10")
        self.assertEqual(s["p95_frame_age_at_start_ms"], "40")
        self.assertAlmostEqual(float(s["app_policy_drop_rate_pct"]), 30.0)
        self.assertAlmostEqual(float(s["effective_miss_rate_pct"]), 90.0)  # (1 miss + 8 drops) / 10

    def test_warmup_period_policy_drops_are_excluded(self):
        rows = [_row(0, warmup=True), _row(1, dropped=True, reason="superseded"), _row(2, warmup=True),
                _row(3), _row(4)]
        (s,) = ar.build_runtime_summary(rows, publisher_frames={"r1": list(range(5))})
        self.assertEqual((s["processed_frames"], s["dropped_frames"], s["app_policy_dropped_frames"]),
                         ("2", "0", "0"))

    def test_frame_processed_and_dropped_is_rejected_not_double_counted(self):
        rows = [_row(0), _row(1), _row(1, dropped=True, reason="superseded")]
        with self.assertRaisesRegex(ValueError, "duplicate frame_id 1"):
            ar.build_runtime_summary(rows)

    def test_one_run_one_torch_thread_setting(self):
        rows = [_row(0), ar.RuntimeRow(**{**_row(1).__dict__, "intra_op_threads": "2"})]
        with self.assertRaisesRegex(ValueError, "several scheduler configurations"):
            ar.build_runtime_summary(rows)

    def test_one_run_one_scheduler(self):
        rows = [_row(0), _row(1, policy="adaptive")]
        with self.assertRaisesRegex(ValueError, "several scheduler configurations"):
            ar.build_runtime_summary(rows)

    def test_metadata_policy_must_match_detector(self):
        meta = {"r1": (Path("r1.meta.json"), {"experiment": {"scheduler_policy": "adaptive"}})}
        with self.assertRaisesRegex(ValueError, "requested scheduler_policy 'adaptive'"):
            ar.build_runtime_summary([_row(0), _row(1)], run_metadata=meta)

    def test_legacy_rows_default_to_legacy_qos(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r1.csv"
            header = run_log.DETECTOR_CSV_HEADER[:run_log.DETECTOR_CSV_HEADER.index("scheduler_policy")]
            with path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(header)
                for fid in range(3):
                    w.writerow(["r1" if h == "run_id" else fid if h == "frame_id" else
                                "20" if h == "latency_ms" else "" for h in header])
            (s,) = ar.build_runtime_summary(ar.load_runtime_rows([path]))
        self.assertEqual((s["scheduler_policy"], s["queue_capacity"]), ("legacy_qos", ""))
        self.assertEqual(s["dds_unreceived_frames"], "0")

    def test_reason_constants_match_scheduler(self):
        self.assertEqual(ar.POLICY_DROP_REASONS, sched.POLICY_DROP_REASONS)
        self.assertEqual(ar.SHUTDOWN_DROP_REASONS, sched.SHUTDOWN_DROP_REASONS)
        self.assertEqual(ar.LEGACY_POLICY, sched.POLICY_LEGACY)


class CsvCompatibilityTest(unittest.TestCase):
    BATCH2_SUMMARY = REPO / "results/csv/ros2_runtime_summary.csv"

    def test_detector_header_only_appends(self):
        legacy = ["run_id", "scenario", "model_name", "input_fps", "qos_depth", "fake_delay_ms",
                  "resource_profile", "deadline_ms", "frame_id", "warmup", "published_at_ns",
                  "received_at_ns", "completed_at_ns", "latency_ms", "transport_ms", "preprocess_ms",
                  "artificial_delay_ms", "inference_ms", "deadline_miss", "dropped", "cpu_percent",
                  "memory_mb"]
        self.assertEqual(run_log.DETECTOR_CSV_HEADER[:len(legacy)], legacy)
        self.assertEqual(run_log.SCHEDULING_CSV_COLUMNS[0], "scheduler_policy")
        self.assertEqual(len(set(run_log.DETECTOR_CSV_HEADER)), len(run_log.DETECTOR_CSV_HEADER))

    def test_summary_fields_only_append(self):
        with self.BATCH2_SUMMARY.open(newline="") as f:
            old = next(csv.reader(f))
        self.assertEqual(ar.SUMMARY_FIELDS[:len(old)], old)
        self.assertEqual(ar.SUMMARY_FIELDS[len(old)], "scheduler_policy")

    def test_batch2_raw_data_reproduces_committed_summary(self):
        raw = REPO / "results/raw/ros2"
        if not any(raw.glob("*.csv")):
            self.skipTest("no Phase 2 raw data in this checkout")
        with self.BATCH2_SUMMARY.open(newline="") as f:
            committed = list(csv.DictReader(f))
        old_fields = list(committed[0].keys())
        inputs = [raw]
        rows = ar.build_runtime_summary(
            ar.load_runtime_rows(inputs), publisher_frames=ar.load_publisher_frames(inputs),
            warmup_frames=10, run_metadata=ar.load_run_metadata(inputs),
            publisher_times=ar.load_publisher_times(inputs))
        self.assertEqual(len(rows), len(committed))
        for new, old in zip(rows, committed):
            self.assertEqual({k: new[k] for k in old_fields}, old, old["run_id"])
            self.assertEqual(new["scheduler_policy"], "legacy_qos")
            parts = sum(int(new[k]) for k in ("app_policy_dropped_frames", "shutdown_unfinished_frames",
                                              "dds_unreceived_frames", "tail_unobserved_frames",
                                              "other_dropped_frames"))
            self.assertEqual(parts, int(new["dropped_frames"]), old["run_id"])

    def test_queue_timing_helper(self):
        t = run_log.queue_timing(0, 2 * MS, 12 * MS, 13 * MS)
        self.assertEqual((t["queue_wait_ms"], t["frame_age_at_start_ms"]), (10.0, 13.0))
        self.assertIsNone(run_log.queue_timing(0, None, None, 5 * MS)["queue_wait_ms"])


# ---------------------------------------------------------------- node / launch / scripts

class NodeStructureTest(unittest.TestCase):
    SOURCE = (PIPELINE_DIR / "mobilevit_detector_node.py").read_text(encoding="utf-8")

    def _method(self, name):
        tree = ast.parse(self.SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return ast.get_source_segment(self.SOURCE, node)
        self.fail(f"{name} not found")

    def test_exactly_one_worker_thread(self):
        self.assertEqual(self.SOURCE.count("threading.Thread("), 1)
        self.assertEqual(self.SOURCE.count("._worker.start()"), 1)

    def test_ingestion_is_lightweight(self):
        body = self._method("ingest_callback")
        for heavy in ("self.model", "imgmsg_to_cv2", "cv2.resize", "torch.", "time.sleep"):
            self.assertNotIn(heavy, body)
        self.assertIn("self.scheduler.submit(item)", body)

    def test_legacy_path_unchanged_inference_in_callback(self):
        body = self._method("listener_callback")
        self.assertIn("self.model(tensor_input)", body)
        self.assertNotIn("scheduler", body.replace("scheduler_policy", ""))
        main = self._method("main")
        self.assertIn("rclpy.spin(node)", main)

    def test_shutdown_path(self):
        main = self._method("main")
        self.assertIn("ExternalShutdownException", main)
        self.assertLess(main.index("finally:"), main.index("node.stop_scheduler()"))
        stop = self._method("stop_scheduler")
        for needle in ("self.scheduler.close()", "self._worker.join(WORKER_JOIN_TIMEOUT_S)",
                       "DROP_SHUTDOWN", "DROP_SHUTDOWN_INFLIGHT", "self._csv_closed = True"):
            self.assertIn(needle, stop)
        self.assertIn("with self._csv_lock:", self._method("_write_row"))

    def test_launch_forwards_scheduler_arguments(self):
        launch = (REPO / "src/ros2_uav_pipeline/launch/mobilevit_uav_pipeline.launch.py").read_text()
        for name in ("scheduler_policy", "queue_capacity", "fifo_overflow", "adaptive_window",
                     "adaptive_quantile", "adaptive_margin_ms", "adaptive_overload_threshold",
                     "intra_op_threads"):
            self.assertIn(f"'{name}'", launch)
            self.assertIn(f"self.declare_parameter('{name}'", self.SOURCE)
        self.assertIn("('scheduler_policy', 'legacy_qos')", launch)


class ScriptTest(unittest.TestCase):
    def test_sweep_rejects_unknown_arm_before_ros(self):
        env = {**os.environ, "PATH": "/usr/bin:/bin", "SCHED_ARMS": "fifo legacy_qos:5 lifo"}
        proc = subprocess.run(["bash", "experiments/ros2/run_sched_sweep.sh"], cwd=REPO, env=env,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("lifo", proc.stderr)

    def test_pilot_plan_interleaves_every_arm_once_per_block(self):
        env = {**os.environ, "DRY_RUN": "1", "REPEATS": "3"}
        proc = subprocess.run(["bash", "experiments/ros2/run_sched_pilot.sh"], cwd=REPO, env=env,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        plan = [line.strip().split("|") for line in proc.stdout.splitlines() if line.startswith("  ")]
        self.assertEqual(len(plan), 12)
        arms = {"legacy_qos:1", "legacy_qos:5", "fifo", "latest_frame", "adaptive"}
        firsts = {}
        for r, model, fps, order in plan:
            self.assertEqual(sorted(order.split()), sorted(arms))
            firsts.setdefault((model, fps), []).append(order.split()[0])
        for cond, first in firsts.items():
            self.assertEqual(len(set(first)), 3, cond)  # a different arm starts each repeat

    def test_pilot_rechecks_clean_tree_before_every_block(self):
        text = (REPO / "experiments/ros2/run_sched_pilot.sh").read_text()
        loop = text[text.index('for entry in "${plan[@]}"; do'):]
        self.assertLess(loop.index("git status --porcelain"), loop.index("run_baseline_experiments.sh"))

    def test_wrapper_knows_sched_sweep(self):
        text = (REPO / "scripts/run_baseline_experiments.sh").read_text()
        self.assertIn("sched) ", text)
        self.assertIn("experiments/ros2/run_sched_sweep.sh", text)


class AggregateSchedulingTest(unittest.TestCase):
    def test_derive_and_paired_differences(self):
        self.assertEqual(derive({"offered_fps": "20", "avg_service_ms": "60",
                                 "effective_miss_rate_pct": "25"}),
                         {"utilization": "1.2", "on_time_fps": "15"})
        base = {"model_name": "mobilevit_s", "input_fps": "20.0", "fake_delay_ms": "0"}
        rows = []
        for tag, (ref, new) in {"b1": (40, 30), "b2": (50, 30)}.items():
            rows.append({**base, "run_tag": tag, "scheduler_arm": "legacy_q1", "effective_miss_rate_pct": str(ref)})
            rows.append({**base, "run_tag": tag, "scheduler_arm": "adaptive_c5_q10", "effective_miss_rate_pct": str(new)})
        (rec,) = build_paired(rows, "legacy_q1")
        self.assertEqual(rec["n_blocks"], 2)
        self.assertEqual((rec["d_effective_miss_rate_pct_mean"], rec["d_effective_miss_rate_pct_min"],
                          rec["d_effective_miss_rate_pct_max"]), ("-15", "-20", "-10"))
        with self.assertRaisesRegex(ValueError, "two runs of arm"):
            build_paired(rows + [rows[0]], "legacy_q1")


if __name__ == "__main__":
    unittest.main()
