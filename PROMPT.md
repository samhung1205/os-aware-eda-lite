python 部分是成功啟動了
(eda_lite) emo@user317-System-Product-Name:~/work/OS_Final$ python3 src/ros2_uav_pipeline/src/image_stream_node.py
[INFO] [1779700412.890654551] [image_stream_node]: 影像發布節點已啟動，目標發布頻率：30 FPS

但是companion board卻...

(eda_lite) emo@user317-System-Product-Name:~/work/OS_Final$ ./scripts/run_baseline_experiments.sh
==========================================================
啟動 Baseline 實驗 (OS 未微調 + 嚴格硬體限制)
CPU 限制: Cores 0, 1 (透過 taskset)
記憶體限制: 2GB (透過 systemd-run MemoryMax)
==========================================================
Running as unit: run-r27405a7630f14633a3f3e1593cf1a0c2.scope; invocation ID: b0b977acc0d0450abd8935b89d216cb8
[INFO] [1779700439.351376963] [mobilevit_detector_node]: 正在載入 MobileViT-XXS 模型 (CPU)...
Traceback (most recent call last):
  File "/home/emo/work/OS_Final/src/ros2_uav_pipeline/src/mobilevit_detector_node.py", line 119, in <module>
    main()
  File "/home/emo/work/OS_Final/src/ros2_uav_pipeline/src/mobilevit_detector_node.py", line 109, in main
    node = MobileViTDetectorNode()
  File "/home/emo/work/OS_Final/src/ros2_uav_pipeline/src/mobilevit_detector_node.py", line 37, in __init__
    self.model = models.mobile_vit_xxs() 
AttributeError: module 'torchvision.models' has no attribute 'mobile_vit_xxs'