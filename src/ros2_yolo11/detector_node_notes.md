# YOLO11 Detector Node Integration Notes

These notes define the intended ROS2 integration path for the OS-aware EDA-Lite project. They do not download weights or modify the TA sample repository.

## Baseline Pipeline

Expected ROS2 data flow:

```text
image_stream_node
  -> /image_raw
  -> detector_node
  -> /detections
  -> decision_node
  -> /system_state
  -> logger_node
  -> CSV runtime metrics
```

## YOLO11 Detector Parameters

The detector node should expose these launch parameters when adapting the TA sample:

- `model_path`: path to YOLO weights, such as `yolo11n.pt`, `yolo11s.pt`, or a custom model.
- `model_name`: human-readable model label written to CSV.
- `device`: `cpu`, `cuda:0`, or platform-specific device string.
- `input_topic`: default `/image_raw`.
- `detections_topic`: default `/detections`.
- `confidence_threshold`: detector confidence threshold.
- `fake_inference_delay_ms`: optional artificial delay for overload experiments.
- `deadline_ms`: soft real-time deadline used by logger metrics.
- `qos_depth`: ROS2 QoS queue depth.

## CSV Logging Contract

The logger should write one row per input frame or detection result. The runtime analyzer supports `latency_ms` directly or derives latency from timestamps.

Recommended columns:

```text
scenario,model_name,input_fps,qos_depth,fake_delay_ms,resource_profile,
frame_id,published_at_ns,received_at_ns,completed_at_ns,
latency_ms,inference_ms,deadline_miss,dropped,cpu_percent,memory_mb
```

Column notes:

- `scenario`: experiment group, for example `fps_sweep`, `qos_sweep`, `overload_sweep`, or `yolo11_comparison`.
- `model_name`: model label such as `yolov8n`, `yolo11n`, `yolo11s`, or `custom_yolo11`.
- `input_fps`: image stream target FPS.
- `qos_depth`: subscriber or publisher queue depth used in the run.
- `fake_delay_ms`: artificial delay injected inside detector node.
- `resource_profile`: label such as `normal`, `cpu_stress`, or `memory_stress`.
- `published_at_ns`: timestamp at image publication.
- `received_at_ns`: timestamp when detector receives the image.
- `completed_at_ns`: timestamp after detection completes.
- `latency_ms`: end-to-end latency. If omitted, analyzer uses `(completed_at_ns - published_at_ns) / 1e6`.
- `inference_ms`: detector-only model execution time.
- `deadline_miss`: boolean or `0/1`.
- `dropped`: boolean or `0/1`; useful when logger emits missing-frame records.
- `cpu_percent`: process or system CPU usage sample.
- `memory_mb`: process memory usage sample.

## Detector Change Sketch

When modifying the TA detector node, keep the change small:

1. Replace YOLOv8 weight loading with a parameterized model path.
2. Preserve the same input and output topics so the rest of the pipeline keeps working.
3. Add per-frame timestamps around receive, inference start, inference end, and publish.
4. Write `model_name`, `input_fps`, `qos_depth`, `fake_delay_ms`, and `deadline_ms` into the logger output.
5. Keep detection accuracy secondary; the OS experiment focuses on latency, jitter, drops, and deadline misses.

## Reporting Rules

- Report ROS2 latency and resource metrics as runtime measurements.
- Report EDA-Lite energy and latency as simulation estimates.
- Do not claim the simplified YOLO11 EDA-Lite profile is an exact compiler representation of YOLO11.
- For overload experiments, clearly state whether delay is real model time or artificial delay.
