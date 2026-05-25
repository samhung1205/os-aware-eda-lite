# 輕量化 MobileViT 之 OS 層級效能解析與 EDA-Lite 模擬

## 摘要

本專題以 Vision Transformer 類模型在邊緣與 ROS2 場景中的部署瓶頸為主題，建立一個可重現、可解釋的 **OS-aware EDA-Lite** 模擬與分析流程。專題不嘗試完整重現 EDA compiler，也不主張量測真實硬體能耗；目前核心貢獻是用簡化 MobileViT block profile 比較 layer fusion scheduling、SRAM 限制、ROS2 runtime pressure 與 dropped-frame communication pressure 對估計成本的影響。

目前已完成的結果屬於 **EDA-Lite simulation estimates**。ROS2 runtime analysis pipeline 已具備，但本 repo 尚未包含可執行的 ROS2 workspace、launch file、rosbag 或 measured CSV，因此 runtime-aware 結果若使用 `runtime_os_profiles.example.json`，只能視為 example profile 示範，不能稱為實測結果。

## 1. 背景與動機

Vision Transformer 與輕量化 Transformer 架構逐漸被部署到邊緣裝置與機器人系統。這類部署的瓶頸不只在 FLOPS，也會受到作業系統層級因素影響，例如：

- 記憶體階層與 SRAM/DRAM traffic。
- ROS2/DDS 通訊、serialization、UDP buffer 與 dropped frames。
- CPU scheduling、deadline miss、latency jitter。
- 邊緣裝置上的有限 memory budget 與 runtime pressure。

因此，本專題選擇以 MobileViT 作為 ViT 類 lightweight vision model 代表，將 compiler-inspired layer fusion 模擬與 OS runtime pressure analysis 串接起來。

## 2. 為什麼不做 YOLO 主線

YOLO 相關檔案存在於本 repo 中，是早期方向的 legacy work。由於目前題目聚焦在 Vision Transformer (ViT)，如果把 YOLO 放入主要實驗，會讓專題主軸變成 CNN/object detection framework comparison，而不是 ViT/Transformer 在 OS 層級下的效能解析。

本專題因此採取以下做法：

- 主線只討論 MobileViT simplified profiles。
- YOLO 檔案保留為 legacy，不放入主要圖表、結果分析與結論。
- COCO128 若被使用，只作為小型 image-folder input，不作 YOLO training 或 YOLO evaluation。

## 3. 系統架構

整體 workflow 分成四層：

1. **MobileViT simplified model profiles**：用 coarse block JSON 描述 MobileViT-XXS 與 MobileViT-S。
2. **EDA-Lite scheduler simulation**：比較 `layerwise`、`greedy`、`dp` 在不同 SRAM budget 下的 fusion 結果。
3. **OS-aware cost model**：把 energy/latency estimates 與 deadline miss、memory pressure、drop pressure 合併成 total cost。
4. **ROS2 runtime analysis**：未來可接收真實 ROS2 CSV，分析 latency、P95/P99、jitter、drop rate，並轉成 runtime-derived OS profiles。

目前 repo 中的主要實作：

- `src/eda_lite/`：EDA-Lite simulator。
- `src/ros2_runtime/`：ROS2 runtime CSV analyzer 與 OS profile builder。
- `data/model_profiles/mobilevit_xxs_simplified.json`
- `data/model_profiles/mobilevit_s_simplified.json`
- `experiments/eda_lite/mobilevit_profile_sweep.json`
- `experiments/eda_lite/mobilevit_runtime_aware_sweep.json`

## 4. EDA-Lite 方法

### 4.1 Simplified MobileViT Profile

MobileViT profiles 使用簡化 sequential block 格式：

```text
model_name
layers[]
  name
  op_type
  input_kb
  output_kb
  weight_kb
  compute_macs
  fusible
```

此格式不代表完整 ONNX graph，也不保證 operator-level accuracy。它的用途是讓 OS/EDA-inspired simulator 可以比較 memory traffic、fusion depth 與 coarse latency/energy trend。

### 4.2 Scheduling Strategies

本專題比較三種 scheduling 策略：

- `layerwise`：每個 block 單獨執行，作為 baseline。
- `greedy`：由左至右盡可能融合符合 SRAM 限制的 contiguous blocks。
- `dp`：用 dynamic programming 找最低 OS-aware cost 的 contiguous partition。

### 4.3 Cost Model

EDA-Lite 使用估計式 cost model：

```text
os_aware_total_cost =
    estimated_energy
  + alpha * estimated_latency
  + beta  * deadline_miss_penalty
  + gamma * memory_pressure_penalty
  + delta * communication_drop_penalty
```

其中：

- `estimated_energy` 與 `estimated_latency` 是 simulator estimates，不是真實硬體量測。
- `deadline_miss_rate` 反映 deadline pressure。
- `memory_pressure` 反映 OS memory pressure。
- `drop_rate` 反映 ROS2/DDS/UDP 或接收端處理不及造成的 communication pressure。

## 5. 實驗設定

### 5.1 Simulation Profiles

本報告使用：

- `mobilevit_xxs_simplified_profile_estimate`
- `mobilevit_s_simplified_profile_estimate`

### 5.2 SRAM Budgets

```text
256KB, 512KB, 1024KB, 2048KB
```

### 5.3 OS Profiles

內建 OS profiles：

- `normal`
- `high_latency`
- `high_memory_pressure`

Example runtime profiles：

- `runtime_normal_20fps_q5_d0`
- `runtime_overload_20fps_q5_d80`

Example runtime profiles 只用於示範 runtime-aware workflow，不是 measured ROS2 data。

### 5.4 Reproduction Commands

```bash
python3 -m src.eda_lite.run_profile_sweep \
  --config experiments/eda_lite/mobilevit_profile_sweep.json \
  --output results/csv/eda_lite_mobilevit_profile_sweep.csv
```

```bash
python3 -m src.eda_lite.analyze_results \
  --input results/csv/eda_lite_mobilevit_profile_sweep.csv \
  --summary-output results/csv/eda_lite_mobilevit_profile_summary.csv \
  --figures-dir results/figures/mobilevit_s \
  --plot-os-profile normal \
  --plot-model mobilevit_s_simplified_profile_estimate
```

```bash
python3 -m src.eda_lite.run_simulation \
  --profile data/model_profiles/mobilevit_xxs_simplified.json \
  --config experiments/eda_lite/mobilevit_runtime_aware_sweep.json \
  --output results/csv/eda_lite_mobilevit_runtime_aware_sweep.csv
```

## 6. Simulation Results

### 6.1 MobileViT-S Summary

For `mobilevit_s_simplified_profile_estimate` under `normal` OS profile:

| SRAM | Best scheduler | DRAM reduction | Energy reduction | Latency reduction | Max fusion depth |
|---:|---|---:|---:|---:|---:|
| 256KB | greedy | 4.14% | 3.93% | 0.41% | 2 |
| 512KB | greedy | 8.88% | 8.42% | 0.88% | 3 |
| 1024KB | greedy | 8.88% | 8.42% | 0.88% | 3 |
| 2048KB | greedy | 8.88% | 8.42% | 0.88% | 3 |

Interpretation:

- Larger SRAM allows deeper fusion up to the model's `fusible` barriers.
- DRAM traffic reduction is more visible than latency reduction because this lightweight cost model includes compute latency and subgraph overhead.
- The scheduler stops improving after 512KB because the remaining barriers are structural, not only memory-limited.

### 6.2 MobileViT-XXS Summary

For `mobilevit_xxs_simplified_profile_estimate` under `normal` OS profile:

| SRAM | Best scheduler | DRAM reduction | Energy reduction | Latency reduction | Max fusion depth |
|---:|---|---:|---:|---:|---:|
| 256KB | greedy | 14.33% | 13.88% | 2.30% | 3 |
| 512KB | greedy | 14.33% | 13.88% | 2.30% | 3 |
| 1024KB | greedy | 14.33% | 13.88% | 2.30% | 3 |
| 2048KB | greedy | 14.33% | 13.88% | 2.30% | 3 |

Interpretation:

- MobileViT-XXS benefits from early fusion even at 256KB SRAM in the simplified profile.
- Increasing SRAM does not further improve fusion depth because attention/head barriers dominate the partition.

### 6.3 Figures

Generated figures for MobileViT-S:

- `results/figures/mobilevit_s/dram_traffic_by_sram.svg`
- `results/figures/mobilevit_s/estimated_energy_by_sram.svg`
- `results/figures/mobilevit_s/estimated_latency_by_sram.svg`
- `results/figures/mobilevit_s/fusion_depth_by_sram.svg`

These figures are simulation outputs. They are not measured hardware energy or measured runtime latency.

## 7. ROS2 Runtime Measurement Plan

本 repo 目前尚未包含可執行 ROS2 workspace，因此本節是待組員 pipeline 接入後執行的 measurement plan。

### 7.1 Dataset

Default input path:

```text
data/raw/images/coco128/images/train2017
```

Prepare command:

```bash
bash experiments/ros2/prepare_coco128.sh
```

COCO128 is a compact image subset used as ROS2 image stream input. It is not used here as a YOLO experiment.

### 7.2 Required ROS2 Pipeline Inputs

Need from teammate:

- `image_stream_node.py`
- `mobilevit_detector_node.py`
- launch file
- package name
- requirements/environment notes
- one sample CSV

Expected launch arguments:

```text
dataset_path, input_fps, qos_depth, model_path, model_name,
fake_inference_delay_ms, deadline_ms, resource_profile, scenario, output_csv
```

### 7.3 Runtime CSV Contract

Recommended columns:

```text
scenario,model_name,input_fps,qos_depth,fake_delay_ms,resource_profile,
frame_id,published_at_ns,received_at_ns,completed_at_ns,
latency_ms,inference_ms,deadline_miss,dropped,cpu_percent,memory_mb
```

The analyzer can infer latency from timestamps and dropped frames from `frame_id` gaps.

### 7.4 Runtime Commands

```bash
bash experiments/ros2/run_fps_sweep.sh
bash experiments/ros2/run_qos_sweep.sh
bash experiments/ros2/run_overload_sweep.sh
```

Then:

```bash
python3 -m src.ros2_runtime.analyze_runtime \
  --input results/raw/ros2 \
  --summary-output results/csv/ros2_runtime_summary.csv \
  --figures-dir results/figures/ros2
```

```bash
python3 -m src.ros2_runtime.build_os_profiles \
  --input results/csv/ros2_runtime_summary.csv \
  --output experiments/eda_lite/runtime_os_profiles.json \
  --profile-prefix measured
```

Only after these steps may the report call the runtime profiles measured.

## 8. Limitations

- MobileViT profiles are simplified coarse estimates, not exact ONNX-derived model graphs.
- Energy and latency are simulator estimates, not hardware measurements.
- The simulator does not implement full EDA tensor splitting, memory planning, NPU scheduling, or code generation.
- The current repo has no measured ROS2 runtime CSV yet.
- `runtime_os_profiles.example.json` is example data only.
- COCO128 is used only as a small image input source, not as YOLO training/evaluation.
- LLM/long-context KV-cache analysis remains background motivation, not implemented functionality.

## 9. Conclusion

本專題已建立一條可重現的 MobileViT + ROS2 OS-aware analysis workflow。Simulation results show that inter-layer fusion can reduce estimated DRAM traffic and energy under SRAM constraints, while ROS2 runtime pressure can later be converted into OS profiles to influence scheduler cost. The next key step is to connect the teammate's ROS2 MobileViT pipeline, generate real runtime CSVs, and replace example OS profiles with measured runtime-derived profiles.

## References

- EDA paper: `EDA: Energy-Efficient Inter-Layer Model Compilation for Edge DNN Inference Acceleration`.
- Project background document: `跨平台輕量化模型效能分析與模擬.pdf`.
- COCO128 dataset documentation: https://docs.ultralytics.com/datasets/detect/coco128/
- COCO128 download URL used by `prepare_coco128.sh`: https://github.com/ultralytics/assets/releases/download/v0.0.0/coco128.zip
