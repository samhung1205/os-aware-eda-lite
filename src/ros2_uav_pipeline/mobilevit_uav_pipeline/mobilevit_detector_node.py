#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
import torch
import timm
import time
import csv
import os
import psutil
from cv_bridge import CvBridge

class MobileViTDetectorNode(Node):
    def __init__(self):
        super().__init__('mobilevit_detector_node')
        
        # 宣告動態參數 (Parameters)
        self.declare_parameter('model_name', 'mobilevit_xxs')
        self.declare_parameter('input_fps', 30.0)
        self.declare_parameter('qos_depth', 10)
        self.declare_parameter('fake_inference_delay_ms', 0)
        self.declare_parameter('deadline_ms', 100.0)
        self.declare_parameter('scenario', 'fps_sweep')
        self.declare_parameter('resource_profile', 'normal')
        self.declare_parameter('output_csv', 'results/raw/ros2/latency_log.csv')

        self.model_name = str(self.get_parameter('model_name').value)
        self.input_fps = float(self.get_parameter('input_fps').value)
        self.qos_depth = int(self.get_parameter('qos_depth').value)
        self.fake_delay_ms = int(self.get_parameter('fake_inference_delay_ms').value)
        self.deadline_ms = float(self.get_parameter('deadline_ms').value)
        self.scenario = str(self.get_parameter('scenario').value)
        self.resource_profile = str(self.get_parameter('resource_profile').value)
        self.log_file_path = str(self.get_parameter('output_csv').value)
        if self.input_fps <= 0:
            raise ValueError('input_fps must be positive.')
        if self.qos_depth <= 0:
            raise ValueError('qos_depth must be positive.')
        if self.deadline_ms <= 0:
            raise ValueError('deadline_ms must be positive.')
        if self.fake_delay_ms < 0:
            raise ValueError('fake_inference_delay_ms must be non-negative.')

        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT, 
            history=HistoryPolicy.KEEP_LAST,
            depth=self.qos_depth
        )
        
        self.subscription = self.create_subscription(Image, 'image_raw', self.listener_callback, qos_profile)
        self.bridge = CvBridge()
        
        self.get_logger().info(f'正在載入模型: {self.model_name} (CPU)...')
        self.device = torch.device('cpu')
        
        # 動態切換模型 (timm 支援 mobilevit_xxs, mobilevit_s)
        try:
            self.model = timm.create_model(self.model_name, pretrained=False)
        except Exception as e:
            self.get_logger().error(f'載入模型失敗，預設回退至 mobilevit_xxs: {e}')
            self.model_name = 'mobilevit_xxs'
            self.model = timm.create_model(self.model_name, pretrained=False)
            
        self.model.to(self.device)
        self.model.eval()
        self.get_logger().info('模型載入完成！開始等待影像輸入...')

        self.last_seq_id = -1
        self.process = psutil.Process(os.getpid())
        
        os.makedirs(os.path.dirname(self.log_file_path), exist_ok=True)
        if not os.path.exists(self.log_file_path):
            with open(self.log_file_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'scenario', 'model_name', 'input_fps', 'qos_depth', 'fake_delay_ms', 'resource_profile',
                    'frame_id', 'published_at_ns', 'received_at_ns', 'completed_at_ns',
                    'latency_ms', 'inference_ms', 'deadline_miss', 'dropped', 'cpu_percent', 'memory_mb'
                ])

    def listener_callback(self, msg):
        received_at_ns = self.get_clock().now().nanoseconds
        published_at_ns = msg.header.stamp.sec * int(1e9) + msg.header.stamp.nanosec
        
        try:
            current_seq_id = int(msg.header.frame_id)
        except ValueError:
            current_seq_id = self.last_seq_id + 1

        self.last_seq_id = current_seq_id

        # 轉換影像 (cv_bridge) 並預處理為 Tensor (1, 3, 256, 256)
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='rgb8')
            import cv2
            resized = cv2.resize(cv_image, (256, 256))
            tensor_input = torch.from_numpy(resized).permute(2, 0, 1).unsqueeze(0).float() / 255.0
            tensor_input = tensor_input.to(self.device)
        except Exception as e:
            self.get_logger().error(f'影像轉換失敗: {e}')
            tensor_input = torch.randn(1, 3, 256, 256, device=self.device)

        inf_start_ns = time.time_ns()
        
        # 假延遲注入 (Overload 實驗)
        if self.fake_delay_ms > 0:
            time.sleep(self.fake_delay_ms / 1000.0)
            
        with torch.no_grad():
            _ = self.model(tensor_input)
            
        completed_at_ns = self.get_clock().now().nanoseconds
        inf_end_ns = time.time_ns()
        
        inference_ms = (inf_end_ns - inf_start_ns) / 1e6
        latency_ms = (completed_at_ns - published_at_ns) / 1e6
        deadline_miss = 1 if latency_ms > self.deadline_ms else 0
        
        cpu_percent = self.process.cpu_percent()
        memory_mb = self.process.memory_info().rss / (1024 * 1024)

        with open(self.log_file_path, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                self.scenario, self.model_name, self.input_fps, self.qos_depth, self.fake_delay_ms, self.resource_profile,
                current_seq_id, published_at_ns, received_at_ns, completed_at_ns,
                latency_ms, inference_ms, deadline_miss, 0, cpu_percent, memory_mb
            ])
            
        self.get_logger().debug(f'Frame {current_seq_id} 處理完畢 | 延遲 {latency_ms:.2f} ms')

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
