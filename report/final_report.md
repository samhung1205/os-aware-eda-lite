# 輕量化 MobileViT 之 OS 層級效能解析與 EDA-Lite 模擬

## 摘要

本專題以 Vision Transformer 類模型在邊緣與 ROS2 場景中的部署瓶頸為主題，建立一個可重現、可解釋的 **OS-aware EDA-Lite** 模擬與分析流程。專題不嘗試完整重現 EDA compiler，也不主張量測真實硬體能耗；目前核心貢獻是用簡化 MobileViT block profile 比較 layer fusion scheduling、SRAM 限制、ROS2 runtime pressure 與 dropped-frame communication pressure 對估計成本的影響。

目前已完成的主要結果屬於 **EDA-Lite simulation estimates**。ROS2 MobileViT pipeline 已在 repo 中，但尚未從本 repo 執行過真實 ROS 2 benchmark；組員提供的 22 個 `measured_*` OS profiles 沒有 raw ROS2 CSV、run metadata 與 `ros2_runtime_summary.csv`，因此標示為 **UNVERIFIED**（`runtime_os_profiles.legacy_unverified.json`），不可作為 measured dataset。`scripts/check_runtime_provenance.py` 目前回報 `BLOCKED`。本專題也沒有 adaptive / runtime scheduler：OS profiles 只改變離線 EDA-Lite 成本模型的權重。

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
4. **ROS2 runtime analysis**：接收 ROS2 CSV，分析 latency、P95/P99、jitter、drop rate，並轉成 runtime-derived OS profiles。

目前 repo 中的主要實作：

- `src/eda_lite/`：EDA-Lite simulator。
- `src/ros2_runtime/`：ROS2 runtime CSV analyzer 與 OS profile builder。
- `data/model_profiles/mobilevit_xxs_simplified.json`
- `data/model_profiles/mobilevit_s_simplified.json`
- `experiments/eda_lite/mobilevit_profile_sweep.json`
- `experiments/eda_lite/mobilevit_runtime_aware_sweep.json`
- `src/ros2_uav_pipeline/`：組員新增的 ROS2 MobileViT image stream 與 detector pipeline。

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
- `dp`：找最低 OS-aware cost 的 contiguous partition。自 Phase 1 / Batch 2 起，`dp` 精確最小化 reported 的整個 schedule 成本（含 max peak SRAM 與總 latency 的 deadline 項），並以 exhaustive oracle 驗證；先前版本最小化的是 per-subgraph 加總的替代目標（audit P0-1）。

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

Runtime-derived profiles：

- `experiments/eda_lite/runtime_os_profiles.legacy_unverified.json` contains 22 teammate-provided `measured_*` profiles for MobileViT-XXS and MobileViT-S.

These profiles are **UNVERIFIED**: no raw ROS2 CSVs, publisher logs, run metadata or runtime summary exist for them, `scripts/check_runtime_provenance.py` reports `BLOCKED`, and they use the legacy cross-model calibration (MobileViT-S idle already shows a ≈3.3× latency multiplier only because it is slower than XXS). Any number or figure derived from them must be labelled UNVERIFIED (the six-line figures carry `[OS profile: UNVERIFIED]` in their titles). They must not be presented as measured results.

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
| 256KB | greedy=dp (tie) | 4.14% | 3.93% | 0.41% | 2 |
| 512KB | greedy=dp (tie) | 8.88% | 8.42% | 0.88% | 3 |
| 1024KB | greedy=dp (tie) | 8.88% | 8.42% | 0.88% | 3 |
| 2048KB | greedy=dp (tie) | 8.88% | 8.42% | 0.88% | 3 |

Note (Phase 1 / Batch 2): `greedy` and `dp` choose the same partition at the same cost in every row; the earlier label `greedy` was only `min()` picking the first tied row, not a greedy win. The numbers are unchanged.

Interpretation:

- Larger SRAM allows deeper fusion up to the model's `fusible` barriers.
- DRAM traffic reduction is more visible than latency reduction because this lightweight cost model includes compute latency and subgraph overhead.
- The scheduler stops improving after 512KB because the remaining barriers are structural, not only memory-limited.

### 6.2 MobileViT-XXS Summary

For `mobilevit_xxs_simplified_profile_estimate` under `normal` OS profile:

| SRAM | Best scheduler | DRAM reduction | Energy reduction | Latency reduction | Max fusion depth |
|---:|---|---:|---:|---:|---:|
| 256KB | greedy=dp (tie) | 14.33% | 13.88% | 2.30% | 3 |
| 512KB | greedy=dp (tie) | 14.33% | 13.88% | 2.30% | 3 |
| 1024KB | greedy=dp (tie) | 14.33% | 13.88% | 2.30% | 3 |
| 2048KB | greedy=dp (tie) | 14.33% | 13.88% | 2.30% | 3 |

Interpretation:

- MobileViT-XXS benefits from early fusion even at 256KB SRAM in the simplified profile.
- Increasing SRAM does not further improve fusion depth because attention/head barriers dominate the partition.

### 6.3 SRAM Saturation Analysis

The SRAM sweep result saturates early because EDA-Lite does not execute MobileViT on image samples. The simulator uses the simplified JSON model profiles in `data/model_profiles/` and estimates memory traffic, energy, latency, and fusion feasibility from block-level fields such as `input_kb`, `output_kb`, `weight_kb`, `compute_macs`, and `fusible`.

Therefore, the plateau after 512KB is not caused by the COCO128 dataset. COCO128 is only the default image-folder input for the ROS2 runtime pipeline. It can affect measured ROS2 latency, drop rate, and deadline miss behavior after real runtime CSVs are collected, but it does not directly change the EDA-Lite SRAM sweep in Chapter 6.

In the current simplified profiles, the effective fusion thresholds are small:

| Model | Candidate fused region | Estimated peak SRAM | Effect |
|---|---|---:|---|
| MobileViT-XXS | `stem_conv + mv2_block_1 + mobilevit_block_1_local` | 192KB | Already feasible at 256KB |
| MobileViT-S | `stem_conv + mv2_block_1` | 248KB | Feasible at 256KB |
| MobileViT-S | `stem_conv + mv2_block_1 + mobilevit_block_1_local` | 268KB | Not feasible at 256KB, feasible from 512KB |

Once these regions are fused, larger SRAM budgets do not create additional improvements because the remaining MobileViT attention blocks and classifier head are marked `fusible=false`. The scheduler only fuses contiguous regions whose layers are all fusible, so structural barriers dominate after the small SRAM thresholds are crossed. This is why DRAM traffic, estimated energy, estimated latency, and max fusion depth remain flat at larger SRAM budgets.

This behavior should be interpreted as a limitation of the coarse EDA-Lite profile and fusion model, not as evidence that real hardware or real datasets stop benefiting from memory capacity above 512KB. A finer sensitivity study could add SRAM points around the thresholds, such as 128KB, 192KB, 224KB, 248KB, 256KB, 268KB, 320KB, and 512KB, instead of extending the sweep to GB-scale SRAM values.

### 6.4 Figures

Generated figures for MobileViT-S:

- `results/figures/mobilevit_s/dram_traffic_by_sram.svg`
- `results/figures/mobilevit_s/estimated_energy_by_sram.svg`
- `results/figures/mobilevit_s/estimated_latency_by_sram.svg`
- `results/figures/mobilevit_s/fusion_depth_by_sram.svg`

These figures are simulation outputs. They are not measured hardware energy or measured runtime latency.

## 7. ROS2 Runtime Measurement Status

本 repo 目前已包含 ROS2 MobileViT pipeline source code and launch file. It still does not include raw ROS2 runtime CSVs, so measured-result claims must reference the provenance limitation in `report/runtime_result_provenance.md`.

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

### 7.2 ROS2 Pipeline Inputs

組員已加入：

- `image_stream_node.py`
- `mobilevit_detector_node.py`
- launch file
- package name
- environment scripts

Still needed for full auditability:

- raw runtime CSVs or `results/csv/ros2_runtime_summary.csv`

Launch arguments:

```text
dataset_path, input_fps, qos_depth, model_name, fake_inference_delay_ms,
deadline_ms, resource_profile, scenario, output_csv, run_id, warmup_frames
```

(`model_path` was removed in Phase 1 / Batch 4: the detector never read it.)

### 7.3 Runtime CSV Contract

Detector CSV columns (one file per run, `<run_id>.csv`; plus `<run_id>.publisher.csv` and `<run_id>.meta.json`):

```text
run_id,scenario,model_name,input_fps,qos_depth,fake_delay_ms,resource_profile,
deadline_ms,frame_id,warmup,published_at_ns,received_at_ns,completed_at_ns,
latency_ms,transport_ms,preprocess_ms,artificial_delay_ms,inference_ms,
deadline_miss,dropped,cpu_percent,memory_mb
```

The analyzer can infer latency from timestamps and dropped frames from `frame_id` gaps and the publisher log.

### 7.3.1 Measurement semantics (must be stated with any ROS 2 number)

- **Model weights.** The detector runs `timm.create_model(model_name, pretrained=False)`: random initial weights, no checkpoint. Forward-pass latency is meaningful; detection accuracy is not measured. A model that cannot be created ends the run; there is no fallback to another model.
- **QoS.** Publisher RELIABLE / KEEP_LAST 10 (fixed); detector subscription BEST_EFFORT / KEEP_LAST `qos_depth`. The QoS sweep varies only the subscriber queue depth.
- **Latency statistics.** End-to-end latency = publish → inference done (host wall clock; publisher and detector on one host). P95/P99 use nearest-rank percentiles; `jitter_ms` is the population standard deviation of per-frame latency, not inter-arrival jitter.
- **Deadline / drops.** A processed frame misses iff `latency_ms > deadline_ms`; dropped frames are counted separately (never as misses); warm-up frames are excluded.
- **Resource limits.** A run is "constrained" only if its `meta.json` says `measurement_class=constrained` (limits read back from affinity / cgroup v2).

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

Only after these steps, with `build_os_profiles --require-verified` succeeding and `scripts/check_runtime_provenance.py` reporting `VERIFIED`, may the report call the runtime profiles measured.

## 8. Limitations

- MobileViT profiles are simplified coarse estimates, not exact ONNX-derived model graphs.
- Energy and latency are simulator estimates, not hardware measurements.
- The simulator does not implement full EDA tensor splitting, memory planning, NPU scheduling, or code generation.
- The current repo has no measured ROS2 runtime CSV yet; the teammate-provided runtime-derived profiles and ROS2 figures are UNVERIFIED (provenance check: BLOCKED).
- `runtime_os_profiles.example.json` is example data only.
- ROS 2 inference uses random-initialised weights (latency only, no accuracy); jitter is the latency standard deviation; the QoS sweep only varies the subscriber depth.
- The pinned ROS 2 environment (`environment.yml`, `requirements-ros2.txt`) has not yet been exercised on the target Linux machine.
- There is no adaptive / runtime scheduling; on the coarse MobileViT profiles the OS profiles change the reported cost but not the chosen partition.
- COCO128 is used only as a small image input source, not as YOLO training/evaluation.
- LLM/long-context KV-cache analysis remains background motivation, not implemented functionality.

## 9. Conclusion

本專題已建立一條 MobileViT + ROS2 OS-aware analysis workflow：模擬部分可完整重現（CI 驗證），runtime 部分的程式與 provenance 檢查已就緒，但真實量測尚待 Phase 2。Simulation results show that inter-layer fusion can reduce estimated DRAM traffic and energy under SRAM constraints, while ROS2 runtime pressure can later be converted into OS profiles to influence scheduler cost. The next key step is to connect the teammate's ROS2 MobileViT pipeline, generate real runtime CSVs, and replace example OS profiles with measured runtime-derived profiles.

## References

- EDA paper: `EDA: Energy-Efficient Inter-Layer Model Compilation for Edge DNN Inference Acceleration`.
- Project background document: `跨平台輕量化模型效能分析與模擬.pdf`.
- COCO128 dataset documentation: https://docs.ultralytics.com/datasets/detect/coco128/
- COCO128 download URL used by `prepare_coco128.sh`: https://github.com/ultralytics/assets/releases/download/v0.0.0/coco128.zip
