# ROS2 MobileViT Pipeline Integration Checklist

This checklist defines what is needed before ROS2 runtime results can be reported as measured data.

## Required Files From Teammate

- `image_stream_node.py`
- `mobilevit_detector_node.py`
- ROS2 `launch.py` file
- ROS2 package name and workspace layout
- Python/package requirements
- One short sample runtime CSV produced by the pipeline
- Any model-loading notes, including whether the node uses real MobileViT, a substitute model, or dummy tensors

## Required Launch Arguments

The existing experiment scripts expect the launch file to accept:

```text
dataset_path
input_fps
qos_depth
model_path
model_name
fake_inference_delay_ms
deadline_ms
resource_profile
scenario
output_csv
```

If the teammate launch file uses different names, update the shell scripts instead of changing the analyzer contract.

## Required Runtime CSV Columns

Recommended CSV columns:

```text
scenario,model_name,input_fps,qos_depth,fake_delay_ms,resource_profile,
frame_id,published_at_ns,received_at_ns,completed_at_ns,
latency_ms,inference_ms,deadline_miss,dropped,cpu_percent,memory_mb
```

Minimum acceptable columns:

- Grouping: `scenario`, `model_name`, `input_fps`, `qos_depth`, `resource_profile`
- Latency: either `latency_ms` or both `published_at_ns` and `completed_at_ns`
- Drop accounting: either explicit `dropped` rows or monotonic `frame_id` values so gaps can be inferred

## Dataset Path

Default small image-folder input:

```text
data/raw/images/coco128/images/train2017
```

Prepare it with:

```bash
bash experiments/ros2/prepare_coco128.sh
```

The dataset directory is intentionally ignored by git. COCO128 is used only as compact image stream input for ROS2 runtime pressure testing, not as a YOLO experiment.

Reference:

```text
https://docs.ultralytics.com/datasets/detect/coco128/
```

## Measured-Data Rule

Do not call ROS2 numbers measured unless:

1. The CSV was produced by a real ROS2 run.
2. The exact script command and environment variables are recorded.
3. The CSV is analyzed with `src.ros2_runtime.analyze_runtime`.
4. Any runtime-derived OS profile is generated from that analyzed summary.
