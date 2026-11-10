#!/usr/bin/env python3
import rclpy
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
        frame_timing, parse_frame_id, resolve_output_csv, resolve_run_id, stamp_to_ns,
    )
except ImportError:  # executed by file path from the checked-in launch file
    from run_log import (
        DETECTOR_CSV_HEADER, MODEL_WEIGHTS, create_model_strict, create_run_csv,
        frame_timing, parse_frame_id, resolve_output_csv, resolve_run_id, stamp_to_ns,
    )

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

        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT, 
            history=HistoryPolicy.KEEP_LAST,
            depth=self.qos_depth
        )
        
        self.bridge = CvBridge()
        
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

        # 模型與 CSV 都就緒後才建立 subscription：publisher 只在偵測到 subscriber 後才開始發布
        # （image_stream_node），因此 torch import / 模型載入期間不會有 frame 被發布後又算成掉幀。
        self.subscription = self.create_subscription(Image, 'image_raw', self.listener_callback, qos_profile)

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
        self._write_row(frame_id, published_at_ns, received_at_ns, warmup=warmup, dropped=0,
                        completed_at_ns=completed_at_ns, timing=timing)
        self.get_logger().debug(f'Frame {frame_id} 處理完畢 | 延遲 {timing["latency_ms"]:.2f} ms')

    def _write_row(self, frame_id, published_at_ns, received_at_ns, warmup, dropped,
                   completed_at_ns=None, timing=None):
        timing = timing or {}
        values = {
            'run_id': self.run_id, 'scenario': self.scenario, 'model_name': self.model_name,
            'input_fps': self.input_fps, 'qos_depth': self.qos_depth,
            'fake_delay_ms': self.fake_delay_ms, 'resource_profile': self.resource_profile,
            'deadline_ms': self.deadline_ms, 'frame_id': frame_id, 'warmup': warmup,
            'published_at_ns': published_at_ns, 'received_at_ns': received_at_ns,
            'completed_at_ns': completed_at_ns, 'dropped': dropped,
            'cpu_percent': self.process.cpu_percent(),
            'memory_mb': self.process.memory_info().rss / (1024 * 1024),
            **timing,
        }
        with open(self.log_file_path, 'a', newline='') as f:
            csv.writer(f).writerow(['' if values.get(k) is None else values.get(k, '') for k in DETECTOR_CSV_HEADER])

def main(args=None):
    rclpy.init(args=args)
    node = MobileViTDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
