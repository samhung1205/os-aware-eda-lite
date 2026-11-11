#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import ParameterDescriptor
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import numpy as np
import cv2
import os
import glob
import csv
import time

try:  # installed package (ros2 run / ros2 launch <package>)
    from mobilevit_uav_pipeline.run_log import (
        DISABLED, PUBLISHER_CSV_HEADER, create_run_csv, ns_to_stamp, parse_fps_schedule,
        resolve_run_id, scheduled_fps,
    )
except ImportError:  # executed by file path from the checked-in launch file
    from run_log import (
        DISABLED, PUBLISHER_CSV_HEADER, create_run_csv, ns_to_stamp, parse_fps_schedule,
        resolve_run_id, scheduled_fps,
    )

class ImageStreamNode(Node):
    def __init__(self):
        super().__init__('image_stream_node')
        
        # 宣告參數 (Parameters) 以便接受從 Launch 檔或命令列傳入的數值
        self.declare_parameter('dataset_path', 'data/raw/images/coco128/images/train2017')
        # dynamic_typing：launch 傳入 `input_fps:=5` 會被 ROS 2 解析成 INTEGER，而預設值 30.0 是 DOUBLE；
        # 不開 dynamic_typing 時 rclpy 會丟 InvalidParameterTypeException。數值一律以 float() 轉換。
        self.declare_parameter('input_fps', 30.0, ParameterDescriptor(dynamic_typing=True))
        # 每個發布的 frame 記錄到 <run_id>.publisher.csv，讓 analyzer 可計算開頭/結尾掉幀。
        # 'none' = 不記錄（單獨執行時）。
        self.declare_parameter('run_id', 'auto')
        self.declare_parameter('output_csv', DISABLED)
        # Phase 3 / Batch 2: optional piecewise-constant input rate "<fps>@<s>,<fps>@<s>,..."
        # measured from frame 0. Empty (default) = the fixed input_fps (unchanged behaviour).
        self.declare_parameter('fps_schedule', '', ParameterDescriptor(dynamic_typing=True))
        
        dataset_path = self.get_parameter('dataset_path').value
        input_fps = float(self.get_parameter('input_fps').value)
        if input_fps <= 0:
            raise ValueError('input_fps must be positive.')
        self.fps_schedule = parse_fps_schedule(str(self.get_parameter('fps_schedule').value))
        self.stream_start_perf = None
        if self.fps_schedule:
            input_fps = self.fps_schedule[0][0]  # the timer starts at the first segment's rate
        self.current_fps = input_fps
        
        # 開啟資料夾中的第一張圖片作為預設圖片建立 Publisher，模擬網路堆疊中傳送端 (Sender)
        self.publisher_ = self.create_publisher(Image, 'image_raw', 10)
        
        # 讀取 COCO 資料夾下所有的 .jpg 圖片路徑
        self.image_paths = sorted(glob.glob(os.path.join(dataset_path, '*.jpg')))
        if not self.image_paths:
            self.get_logger().error(f'在 {dataset_path} 找不到任何圖片！請確認路徑。')
        else:
            self.get_logger().info(f'成功載入 {len(self.image_paths)} 張真實圖片。')
            
        self.current_img_idx = 0
        
        # 根據參數設定計時器頻率
        timer_period = 1.0 / input_fps
        self.timer = self.create_timer(timer_period, self.timer_callback)
        self.bridge = CvBridge()
        self.seq_id = 0
        # 在偵測到至少一個 subscriber（detector 已載入模型並訂閱）之前不發布、不編號、不寫 publisher log，
        # 避免 detector 啟動期間發布的 frame 被 publisher_log accounting 算成掉幀。
        # 開始後即使 subscriber 消失也持續發布：之後未被處理的 frame 是真正的掉幀。
        self.streaming = False
        self.run_id = resolve_run_id(self.get_parameter('run_id').value)
        self.publish_log = None
        log_path = str(self.get_parameter('output_csv').value).strip()
        if log_path and log_path != DISABLED:
            create_run_csv(log_path, PUBLISHER_CSV_HEADER)  # 已存在則失敗，不 append
            # line buffering：被 launch 結束時已發布的每一筆都已寫入
            self.publish_log = open(log_path, 'a', newline='', buffering=1)
            self.publish_writer = csv.writer(self.publish_log)
            self.get_logger().info(f'run_id={self.run_id}，發布紀錄寫入 {log_path}')
        self.get_logger().info(f'影像發布節點已啟動，目標發布頻率：{input_fps} FPS'
                               + (f'，動態排程 {self.fps_schedule}' if self.fps_schedule else ''))

    def timer_callback(self):
        if not self.streaming:
            if self.publisher_.get_subscription_count() == 0:
                self.get_logger().info('等待 subscriber（detector）就緒後才開始發布...', throttle_duration_sec=5.0)
                return
            self.streaming = True
            self.stream_start_perf = time.perf_counter()
            self.get_logger().info('偵測到 subscriber，開始發布 frame 0。')
        if not self.image_paths:
            # 如果沒有圖片，產生一個黑畫面作為 Fallback，避免程式崩潰
            img_array = np.zeros((1080, 1920, 3), dtype=np.uint8)
        else:
            # 讀取真實 OpenCV 影像
            img_path = self.image_paths[self.current_img_idx]
            img_array = cv2.imread(img_path)
            
            if img_array is None:
                self.get_logger().warning(f'無法讀取圖片: {img_path}')
                img_array = np.zeros((1080, 1920, 3), dtype=np.uint8)
                
            # 準備讀取下一張，若到盡頭則從頭開始 (Loop)
            self.current_img_idx = (self.current_img_idx + 1) % len(self.image_paths)
        
        # 將 numpy array (OpenCV BGR) 轉換為 ROS 2 的 sensor_msgs/Image 訊息
        msg = self.bridge.cv2_to_imgmsg(img_array, encoding="bgr8")
        
        # 打上精確的時間戳記與自定義的序號 (Sequence ID)。
        # 在 ROS 2 中 Header 已經移除了 seq 欄位，所以我們透過 frame_id 來傳遞序號，
        # 以便 Subscriber 端可以用來計算 OS 網路緩衝區 (UDP Buffer) 造成的掉幀 (Frame Drop)。
        # 用 host wall clock（與 detector 相同的時間來源）打時間戳記。
        published_at_ns = time.time_ns()
        msg.header.stamp.sec, msg.header.stamp.nanosec = ns_to_stamp(published_at_ns)
        msg.header.frame_id = str(self.seq_id)
        
        # 發布影像，將資料送入 OS 的網路堆疊 (Network Stack) 進行 DDS 傳輸
        self.publisher_.publish(msg)
        if self.publish_log is not None:
            self.publish_writer.writerow([self.run_id, self.seq_id, published_at_ns])
        self.get_logger().debug(f'已發布幀 {self.seq_id}')
        self.seq_id += 1
        if self.fps_schedule:
            self._apply_fps_schedule()

    def _apply_fps_schedule(self):
        """Switch the timer period when the schedule enters a new segment (dynamic mode only)."""
        target = scheduled_fps(self.fps_schedule, time.perf_counter() - self.stream_start_perf)
        if target != self.current_fps:
            # rclpy Timer.timer_period_ns setter (rcl_timer_exchange_period): same timer,
            # new period from the next call on; no timer is destroyed inside its own callback.
            self.timer.timer_period_ns = int(round(1e9 / target))
            self.get_logger().info(f'fps_schedule: {self.current_fps} -> {target} FPS at frame {self.seq_id}')
            self.current_fps = target

def main(args=None):
    rclpy.init(args=args)
    node = ImageStreamNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
