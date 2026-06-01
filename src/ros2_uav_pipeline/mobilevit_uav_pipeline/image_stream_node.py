#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import numpy as np
import cv2
import os
import glob

class ImageStreamNode(Node):
    def __init__(self):
        super().__init__('image_stream_node')
        
        # 宣告參數 (Parameters) 以便接受從 Launch 檔或命令列傳入的數值
        self.declare_parameter('dataset_path', 'data/raw/images/coco128/images/train2017')
        self.declare_parameter('input_fps', 30.0)
        
        dataset_path = self.get_parameter('dataset_path').value
        input_fps = float(self.get_parameter('input_fps').value)
        if input_fps <= 0:
            raise ValueError('input_fps must be positive.')
        
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
        self.get_logger().info(f'影像發布節點已啟動，目標發布頻率：{input_fps} FPS')

    def timer_callback(self):
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
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = str(self.seq_id)
        
        # 發布影像，將資料送入 OS 的網路堆疊 (Network Stack) 進行 DDS 傳輸
        self.publisher_.publish(msg)
        self.get_logger().debug(f'已發布幀 {self.seq_id}')
        self.seq_id += 1

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
