#!/usr/bin/env python3
import sys
import threading

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rcl_interfaces.msg import ParameterDescriptor
from sensor_msgs.msg import Image
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
import torch
import timm
import time
import csv
import os
import psutil
import cv2
from cv_bridge import CvBridge

try:  # installed package (ros2 run / ros2 launch <package>)
    from mobilevit_uav_pipeline.run_log import (
        DETECTOR_CSV_HEADER, MODEL_WEIGHTS, create_model_strict, create_run_csv,
        frame_timing, parse_frame_id, queue_timing, resolve_output_csv, resolve_run_id, stamp_to_ns,
    )
    from mobilevit_uav_pipeline.scheduling import (
        ALL_POLICIES, DROP_CONVERSION, DROP_SHUTDOWN, DROP_SHUTDOWN_INFLIGHT, POLICY_LEGACY,
        FrameItem, FrameScheduler, SchedulerConfig,
    )
except ImportError:  # executed by file path from the checked-in launch file
    from run_log import (
        DETECTOR_CSV_HEADER, MODEL_WEIGHTS, create_model_strict, create_run_csv,
        frame_timing, parse_frame_id, queue_timing, resolve_output_csv, resolve_run_id, stamp_to_ns,
    )
    from scheduling import (
        ALL_POLICIES, DROP_CONVERSION, DROP_SHUTDOWN, DROP_SHUTDOWN_INFLIGHT, POLICY_LEGACY,
        FrameItem, FrameScheduler, SchedulerConfig,
    )

# Seconds the shutdown path waits for the worker to finish the frame it is processing
# (launch escalates SIGINT -> SIGTERM after 5 s).
WORKER_JOIN_TIMEOUT_S = 3.0

class MobileViTDetectorNode(Node):
    def __init__(self):
        super().__init__('mobilevit_detector_node')
        
        # 宣告動態參數 (Parameters)
        self.declare_parameter('model_name', 'mobilevit_xxs')
        # 浮點參數允許整數字面值（`input_fps:=5`、`deadline_ms:=100` 會被解析成 INTEGER），以 float() 轉換。
        float_param = ParameterDescriptor(dynamic_typing=True)
        self.declare_parameter('input_fps', 30.0, float_param)
        self.declare_parameter('qos_depth', 10)
        self.declare_parameter('fake_inference_delay_ms', 0)
        self.declare_parameter('deadline_ms', 100.0, float_param)
        self.declare_parameter('scenario', 'fps_sweep')
        self.declare_parameter('resource_profile', 'normal')
        self.declare_parameter('output_csv', 'auto')
        self.declare_parameter('run_id', 'auto')
        # 前 N 個處理完成的 frame 標記為 warmup=1（模型 lazy init 等），analyzer 不納入正式統計。
        self.declare_parameter('warmup_frames', 10)
        # Phase 3 / Batch 1: application scheduling. legacy_qos (default) = unchanged Phase 2
        # behaviour: inference inside the subscription callback, the DDS KEEP_LAST(qos_depth)
        # queue is the only queue. fifo / latest_frame / adaptive = ingestion callback ->
        # bounded application queue -> one inference worker thread (scheduling.py).
        self.declare_parameter('scheduler_policy', POLICY_LEGACY)
        self.declare_parameter('queue_capacity', 5)
        self.declare_parameter('fifo_overflow', 'reject_newest')
        self.declare_parameter('adaptive_window', 32)
        self.declare_parameter('adaptive_quantile', 0.9, float_param)
        self.declare_parameter('adaptive_margin_ms', 0.0, float_param)
        self.declare_parameter('adaptive_overload_threshold', 1.0, float_param)
        # Intra-op threads of torch AND OpenCV (both OpenMP). 0 = library defaults (Phase 2
        # behaviour). Phase 3 sets 1 for every arm: with this node's imports, OpenMP work on the
        # main thread (legacy_qos callback) runs on ~1 core even with 2 threads, while a worker
        # thread gets 2 (torch ~35% faster) and an OpenCV helper thread that busy-spins (~20%
        # CPU). Without the control the arms would differ in compute, not only in scheduling
        # (report/PHASE3_BATCH1_RESULT.md §2).
        self.declare_parameter('intra_op_threads', 0)

        self.model_name = str(self.get_parameter('model_name').value)
        self.input_fps = float(self.get_parameter('input_fps').value)
        self.qos_depth = int(self.get_parameter('qos_depth').value)
        self.fake_delay_ms = int(self.get_parameter('fake_inference_delay_ms').value)
        self.deadline_ms = float(self.get_parameter('deadline_ms').value)
        self.scenario = str(self.get_parameter('scenario').value)
        self.resource_profile = str(self.get_parameter('resource_profile').value)
        self.warmup_frames = int(self.get_parameter('warmup_frames').value)
        # 每次啟動都是一個獨立 run：唯一 run_id + 只能新建的 CSV，避免重跑時 append 混用資料。
        self.run_id = resolve_run_id(self.get_parameter('run_id').value)
        self.log_file_path = resolve_output_csv(self.get_parameter('output_csv').value, self.run_id)
        if self.input_fps <= 0:
            raise ValueError('input_fps must be positive.')
        if self.qos_depth <= 0:
            raise ValueError('qos_depth must be positive.')
        if self.deadline_ms <= 0:
            raise ValueError('deadline_ms must be positive.')
        if self.fake_delay_ms < 0:
            raise ValueError('fake_inference_delay_ms must be non-negative.')
        if self.warmup_frames < 0:
            raise ValueError('warmup_frames must be non-negative.')
        self.scheduler_policy = str(self.get_parameter('scheduler_policy').value).strip()
        if self.scheduler_policy not in ALL_POLICIES:
            raise ValueError(f'scheduler_policy must be one of {", ".join(ALL_POLICIES)}.')
        self.scheduler_config = None
        if self.scheduler_policy != POLICY_LEGACY:
            # Validated here (before the model loads) so a bad parameter ends the run at once.
            self.scheduler_config = SchedulerConfig(
                policy=self.scheduler_policy,
                queue_capacity=int(self.get_parameter('queue_capacity').value),
                deadline_ms=self.deadline_ms,
                fifo_overflow=str(self.get_parameter('fifo_overflow').value).strip(),
                adaptive_window=int(self.get_parameter('adaptive_window').value),
                adaptive_quantile=float(self.get_parameter('adaptive_quantile').value),
                adaptive_margin_ms=float(self.get_parameter('adaptive_margin_ms').value),
                adaptive_overload_threshold=float(self.get_parameter('adaptive_overload_threshold').value),
            )
        # CSV rows come from two threads in the application modes (ingestion: drop rows,
        # worker: processed rows); one re-entrant lock serialises every write.
        self._csv_lock = threading.RLock()
        self._csv_closed = False
        self._inflight = None
        self.scheduler = None
        self._worker = None
        self.worker_error = None
        self.worker_failed = threading.Event()

        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT, 
            history=HistoryPolicy.KEEP_LAST,
            depth=self.qos_depth
        )
        
        self.bridge = CvBridge()
        
        requested_threads = int(self.get_parameter('intra_op_threads').value)
        if requested_threads < 0:
            raise ValueError('intra_op_threads must be >= 0.')
        if requested_threads > 0:
            torch.set_num_threads(requested_threads)
            cv2.setNumThreads(requested_threads)
        self.intra_op_threads = f'torch={torch.get_num_threads()};cv2={cv2.getNumThreads()}'
        self.get_logger().info(f'intra-op threads: {self.intra_op_threads}（要求 {requested_threads or "default"}）')

        self.get_logger().info(f'正在載入模型: {self.model_name} (CPU)...')
        self.device = torch.device('cpu')
        
        # 依 model_name 建立 timm 模型（mobilevit_xxs、mobilevit_s 等）。
        # 隨機初始化權重（pretrained=False，不載入權重檔）：只量測延遲，不量測準確率。
        # 載入失敗直接結束 node（launch 隨之結束、sweep 標為 failed），絕不改用其他模型。
        self.model = create_model_strict(self.model_name, timm.create_model)
        self.get_logger().info(f'模型權重：{MODEL_WEIGHTS}（timm pretrained=False，僅供延遲量測）')

        self.model.to(self.device)
        self.model.eval()
        self.get_logger().info('模型載入完成！開始等待影像輸入...')

        self.processed_count = 0
        self.process = psutil.Process(os.getpid())
        
        # 檔案已存在時直接失敗（不 append、不覆蓋）。
        create_run_csv(self.log_file_path, DETECTOR_CSV_HEADER)
        self.get_logger().info(f'run_id={self.run_id}，量測資料寫入 {self.log_file_path}')

        callback = self.listener_callback
        if self.scheduler_config is not None:
            self.scheduler = FrameScheduler(self.scheduler_config)
            self._queue_capacity = self.scheduler_config.effective_capacity
            self._scheduler_params = self.scheduler_config.params_text()
            # Exactly one worker. stop_scheduler() joins it (bounded wait) so its last row is
            # written; daemon=True only guarantees a stuck forward pass cannot block process exit.
            self._worker = threading.Thread(target=self._worker_main, name='inference_worker', daemon=True)
            self._worker.start()
            callback = self.ingest_callback
            self.get_logger().info(
                f'scheduler_policy={self.scheduler_policy} ({self._scheduler_params})，'
                f'DDS KEEP_LAST depth={self.qos_depth}，單一 inference worker')
        else:
            self._queue_capacity = None
            self._scheduler_params = ''
            self.get_logger().info(f'scheduler_policy={POLICY_LEGACY}（推論在 subscription callback 內）')

        # 模型與 CSV 都就緒後才建立 subscription：publisher 只在偵測到 subscriber 後才開始發布
        # （image_stream_node），因此 torch import / 模型載入期間不會有 frame 被發布後又算成掉幀。
        self.subscription = self.create_subscription(Image, 'image_raw', callback, qos_profile)

    def listener_callback(self, msg):
        # 跨程序時間戳記一律用 host wall clock（與 publisher 相同，不受 use_sim_time 影響）；
        # 程序內各階段耗時用 monotonic perf_counter。
        received_at_ns = time.time_ns()
        received_perf_ns = time.perf_counter_ns()
        published_at_ns = stamp_to_ns(msg.header.stamp.sec, msg.header.stamp.nanosec)
        # 無法解析的 frame_id 留空，不自行編號（避免掩蓋掉幀）。
        frame_id = parse_frame_id(msg.header.frame_id)

        # 轉換影像 (cv_bridge) 並預處理為 Tensor (1, 3, 256, 256)
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='rgb8')
            resized = cv2.resize(cv_image, (256, 256))
            tensor_input = torch.from_numpy(resized).permute(2, 0, 1).unsqueeze(0).float() / 255.0
            tensor_input = tensor_input.to(self.device)
        except Exception as e:
            # 不以假資料推論：記為 explicit dropped frame。
            self.get_logger().error(f'影像轉換失敗，frame {frame_id} 記為 dropped: {e}')
            self._write_row(frame_id, published_at_ns, received_at_ns, warmup=0, dropped=1)
            return
        preprocessed_perf_ns = time.perf_counter_ns()

        # 假延遲注入 (Overload 實驗)：單獨計時，不算進 inference_ms
        if self.fake_delay_ms > 0:
            time.sleep(self.fake_delay_ms / 1000.0)
        delayed_perf_ns = time.perf_counter_ns()

        with torch.no_grad():
            _ = self.model(tensor_input)
        inferred_perf_ns = time.perf_counter_ns()
        completed_at_ns = time.time_ns()

        timing = frame_timing(
            published_at_ns, received_at_ns, completed_at_ns,
            received_perf_ns, preprocessed_perf_ns, delayed_perf_ns, inferred_perf_ns,
            self.deadline_ms,
        )
        warmup = 1 if self.processed_count < self.warmup_frames else 0
        self.processed_count += 1
        # legacy_qos: no application queue; processing starts in the callback (received_at_ns).
        self._write_row(frame_id, published_at_ns, received_at_ns, warmup=warmup, dropped=0,
                        completed_at_ns=completed_at_ns, timing=timing,
                        extra={'started_at_ns': received_at_ns,
                               **queue_timing(published_at_ns, None, None, received_at_ns)})
        self.get_logger().debug(f'Frame {frame_id} 處理完畢 | 延遲 {timing["latency_ms"]:.2f} ms')

    # ------------------------------------------------------------ application scheduling
    def ingest_callback(self, msg):
        """Lightweight ingestion: timestamp the message and hand it to the scheduler."""
        received_at_ns = time.time_ns()
        received_perf_ns = time.perf_counter_ns()
        item = FrameItem(
            frame_id=parse_frame_id(msg.header.frame_id),
            published_at_ns=stamp_to_ns(msg.header.stamp.sec, msg.header.stamp.nanosec),
            received_at_ns=received_at_ns, received_perf_ns=received_perf_ns, payload=msg,
        )
        for dropped, reason in self.scheduler.submit(item):
            self._write_drop_row(dropped, reason)

    def _worker_main(self):
        try:
            while True:
                item, drops = self.scheduler.next_frame()
                for dropped, reason in drops:
                    self._write_drop_row(dropped, reason)
                if item is None:
                    if self.scheduler.closed:
                        return
                    continue
                with self._csv_lock:
                    self._inflight = item
                self._process_item(item)
        except BaseException as exc:  # noqa: BLE001 - any worker failure must end the run
            self.worker_error = exc
            self.worker_failed.set()
            try:
                self.get_logger().error(f'inference worker 失敗，結束 run：{exc!r}')
            except Exception:
                pass

    def _process_item(self, item):
        started_at_ns = time.time_ns()
        started_perf_ns = time.perf_counter_ns()
        msg, item.payload = item.payload, None
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='rgb8')
            resized = cv2.resize(cv_image, (256, 256))
            tensor_input = torch.from_numpy(resized).permute(2, 0, 1).unsqueeze(0).float() / 255.0
            tensor_input = tensor_input.to(self.device)
        except Exception as e:
            self.get_logger().error(f'影像轉換失敗，frame {item.frame_id} 記為 dropped: {e}')
            item.dropped_at_ns = started_at_ns
            self._write_drop_row(item, DROP_CONVERSION, started_at_ns=started_at_ns)
            return
        preprocessed_perf_ns = time.perf_counter_ns()
        if self.fake_delay_ms > 0:
            time.sleep(self.fake_delay_ms / 1000.0)
        delayed_perf_ns = time.perf_counter_ns()
        with torch.no_grad():
            _ = self.model(tensor_input)
        inferred_perf_ns = time.perf_counter_ns()
        completed_at_ns = time.time_ns()

        # preprocess_ms starts at processing start (not at ingestion): service time keeps the
        # Phase 2 meaning (preprocess + artificial delay + inference of one frame).
        timing = frame_timing(
            item.published_at_ns, item.received_at_ns, completed_at_ns,
            started_perf_ns, preprocessed_perf_ns, delayed_perf_ns, inferred_perf_ns,
            self.deadline_ms,
        )
        warmup = 1 if self.processed_count < self.warmup_frames else 0
        self.processed_count += 1
        self.scheduler.record_service(
            timing['preprocess_ms'] + timing['artificial_delay_ms'] + timing['inference_ms'], bool(warmup))
        self._write_row(
            item.frame_id, item.published_at_ns, item.received_at_ns, warmup=warmup, dropped=0,
            completed_at_ns=completed_at_ns, timing=timing,
            extra={**self._item_fields(item), 'started_at_ns': started_at_ns,
                   **queue_timing(item.published_at_ns, item.enqueued_at_ns, item.dequeued_at_ns,
                                  started_at_ns)},
            finished=item,
        )

    def _item_fields(self, item):
        return {
            'enqueued_at_ns': item.enqueued_at_ns, 'dequeued_at_ns': item.dequeued_at_ns,
            'queue_len_at_enqueue': item.queue_len_at_enqueue,
            'queue_len_at_dequeue': item.queue_len_at_dequeue,
            'scheduler_decision': item.decision, 'est_service_ms': item.est_service_ms,
            'est_utilization': item.est_utilization, 'predicted_latency_ms': item.predicted_latency_ms,
        }

    def _write_drop_row(self, item, reason, started_at_ns=None):
        # Drop rows sample no CPU / RSS (the analyzer averages those over processed rows).
        item.payload = None
        self._write_row(
            item.frame_id, item.published_at_ns, item.received_at_ns, warmup=0, dropped=1,
            extra={**self._item_fields(item), 'drop_reason': reason,
                   'dropped_at_ns': item.dropped_at_ns,
                   'started_at_ns': started_at_ns},
            sample_resources=False, finished=item,
        )

    def stop_scheduler(self):
        """Shutdown: stop the queue, let the worker finish its frame, log what is left.

        Every frame that reached the application queue ends with exactly one row:
        processed, policy drop, ``shutdown_pending`` (still queued) or
        ``shutdown_inflight`` (worker did not finish within WORKER_JOIN_TIMEOUT_S).
        """
        if self.scheduler is None:
            return
        drained = self.scheduler.close()
        if self._worker is not None:
            self._worker.join(WORKER_JOIN_TIMEOUT_S)
        with self._csv_lock:
            for item in drained:
                self._write_drop_row(item, DROP_SHUTDOWN)
            if self._inflight is not None:
                self._write_drop_row(self._inflight, DROP_SHUTDOWN_INFLIGHT)
            self._csv_closed = True  # a worker that finishes later writes nothing
        # The ROS logger may already be shut down (SIGINT): print to stderr instead.
        print(f'[{self.run_id}] scheduler stats: {self.scheduler.stats()}', file=sys.stderr, flush=True)

    def _write_row(self, frame_id, published_at_ns, received_at_ns, warmup, dropped,
                   completed_at_ns=None, timing=None, extra=None, sample_resources=True,
                   finished=None):
        timing = timing or {}
        values = {
            'run_id': self.run_id, 'scenario': self.scenario, 'model_name': self.model_name,
            'input_fps': self.input_fps, 'qos_depth': self.qos_depth,
            'fake_delay_ms': self.fake_delay_ms, 'resource_profile': self.resource_profile,
            'deadline_ms': self.deadline_ms, 'frame_id': frame_id, 'warmup': warmup,
            'published_at_ns': published_at_ns, 'received_at_ns': received_at_ns,
            'completed_at_ns': completed_at_ns, 'dropped': dropped,
            'scheduler_policy': self.scheduler_policy, 'queue_capacity': self._queue_capacity,
            'scheduler_params': self._scheduler_params, 'intra_op_threads': self.intra_op_threads,
            **timing,
            **(extra or {}),
        }
        with self._csv_lock:
            if self._csv_closed:
                return
            if sample_resources:
                values['cpu_percent'] = self.process.cpu_percent()
                values['memory_mb'] = self.process.memory_info().rss / (1024 * 1024)
            with open(self.log_file_path, 'a', newline='') as f:
                csv.writer(f).writerow(['' if values.get(k) is None else values.get(k, '') for k in DETECTOR_CSV_HEADER])
            # The frame has its row: it is no longer in flight (same lock as stop_scheduler).
            if finished is not None and self._inflight is finished:
                self._inflight = None

def main(args=None):
    rclpy.init(args=args)
    node = MobileViTDetectorNode()
    try:
        if node.scheduler is None:
            rclpy.spin(node)  # legacy_qos: unchanged single-threaded spin
        else:
            # The executor thread only runs the ingestion callback; inference runs in the
            # worker thread. Stop when the context shuts down (SIGINT) or the worker fails.
            executor = SingleThreadedExecutor()
            executor.add_node(node)
            while rclpy.ok() and not node.worker_failed.is_set():
                executor.spin_once(timeout_sec=0.1)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.stop_scheduler()
        node.destroy_node()
        rclpy.try_shutdown()
    if node.worker_error is not None:
        sys.exit(1)  # the launch shuts down early -> the sweep marks the run failed

if __name__ == '__main__':
    main()
