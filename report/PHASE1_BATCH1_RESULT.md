# Phase 1 / Batch 1：ROS 2 Measurement Correctness

- 日期：2026-11-10
- Branch：`fix/pr-a1-ros2-data-integrity`
- 基準：PR-A1 checkpoint commit `a40816d`（本次開始前建立，不含使用者的 `plot_6lines.py`、`results/.DS_Store`、未追蹤 SVG 與 `~$*.pptx`）
- 本批次狀態：**未 commit、未 push、未 merge**
- 對應 audit：P1-4、P1-5、P1-6，以及 PR-A1 遺留的 launch reliability（`LAUNCH`）
- 結果：上述四個 audit case 由 `REPRODUCED` 變為 `FIXED`；測試共 71 個（原 44 + 新 27），全部通過。

## 1. 修改摘要

### P1-4 Deadline correctness
- Detector CSV 新增 `deadline_ms` 欄位，每列都記錄該 run 的 deadline。
- **唯一定義**：processed frame 在 `latency_ms > deadline_ms` 時算 miss。dropped frame 一律不算 deadline miss（只計入 drop）。只有 `deadline_ms` 未知時（legacy CSV）才採用 log 裡的 `deadline_miss` 旗標。
- **分母統一**：`deadline_miss_rate_pct` = misses / processed frames，因此 ≤ 100%。新增 `effective_miss_rate_pct` = (misses + dropped) / total frames，代表「沒有準時交付的比例」。processed 為 0 時 rate 留空，不寫 0。
- 同一 run 若出現多個 `deadline_ms` 值，直接報錯。
- EDA-Lite 的 `cost_model.deadline_ms`（33.3）與 cost/DP 邏輯**未修改**，留待下一批；文件已註明兩者是不同參數。

### P1-5 Frame-drop accounting
- **Publisher log**：publisher 為每個發布的 frame 寫一列到 `<run_id>.publisher.csv`（line-buffered，launch 結束時已發布的資料都已落盤）。Analyzer 以它作為 frame window，因此能計入開頭與結尾的掉幀。
- **去重複合併**：dropped = window 內從未被處理的 frame（集合差）＋沒有 frame_id 的 explicit drop。explicit drop 與 frame-ID gap 取聯集，每個 frame 最多算一次。
- **完整度標示** `frame_accounting`：
  - `publisher_log`：完整；
  - `frame_id_range`：沒有 publisher log，開頭/結尾未知，只是下限；
  - `explicit_only`：只有 explicit drop；
  - `unavailable`：無法推估，`dropped_frames`、`drop_rate_pct`、`total_rows`、`effective_miss_rate_pct` 一律留空，**不寫 0**。圖表顯示 `n/a`；`build_os_profiles` 遇到空的 `drop_rate_pct` 直接拒絕，不當成 0%（舊 summary 沒有這個欄位時，仍沿用文件既有的 0 預設）。
- **Grouping key 正規化**：`input_fps` 統一為 float 文字（`20` → `20.0`，與 detector 寫出的格式及既有 profile 名稱一致）；`qos_depth`、`fake_delay_ms` 是整數值時寫成整數。排序改用 `(是否數值, 值)`，數值與文字混合時不再出現 `TypeError`。
- Detector 不再自行編號無法解析的 `frame_id`（原本用 `last+1`，會掩蓋掉幀）。影像轉換失敗時記為 explicit dropped，不再拿 `torch.randn` 假輸入去跑推論。

### P1-6 Timing & profiling
- **時鐘語意**：跨程序時間戳記（`published/received/completed_at_ns`）一律用 host wall clock（`time.time_ns()`，等同 ROS `SYSTEM_TIME`，不受 `use_sim_time` 影響）；publisher 也改用同一來源打 header stamp。程序內各階段耗時用 monotonic 的 `time.perf_counter_ns()`。Detector 與 publisher 不再呼叫 `get_clock()`。
- **新增欄位**：
  - `transport_ms`（published → callback 開始，DDS 傳輸 + executor 排隊）
  - `preprocess_ms`
  - `artificial_delay_ms`（注入的 sleep）
  - `inference_ms`（**只含** model forward）
  - `latency_ms`（end-to-end）
- **Warm-up**：detector 參數 `warmup_frames`（預設 10；腳本為 `WARMUP_FRAMES`）會把前 N 個 processed frame 標成 `warmup=1`。Analyzer 排除這些列，另有 `--warmup-frames N`（預設 0，legacy CSV 也適用），measurement window 從最後一個 warm-up frame_id 之後開始。
- **Summary 新增欄位**（附加在原有欄位之後，原有欄位順序不變）：`deadline_ms`、`effective_miss_rate_pct`、`published_frames`、`frame_accounting`、`warmup_frames_excluded`、`avg_transport_ms`、`avg_preprocess_ms`、`avg_artificial_delay_ms`、`p95_inference_ms`、`timing_schema`（`v2` / `legacy` / `mixed`；legacy 的 `inference_ms` 可能含 artificial delay）。

### ROS 2 launch reliability
- Launch 檔改用 `OpaqueFunction`：`run_id` 只解析一次，publisher 與 detector 共用；detector CSV 與 publisher log 的路徑都由同一個 run_id 推導。
- `OnProcessExit` → `EmitEvent(Shutdown)`：任一 node 結束（啟動失敗、例外、被停止）就結束整個 launch，不會再空轉到 timeout。
- 新增 `experiments/ros2/run_common.sh`（`run_prepare` / `run_finish`）。只有「被 timeout 停止（exit 124）**且** detector CSV 有資料列」才算成功；提早結束（exit 0/1 等）或沒有任何資料都算失敗：腳本中止，該 run 的 CSV 改名為 `*.failed`，analyzer 不會讀取。
- 修正一個實際踩到的 bug：macOS bash 3.2 在 C locale 下，會把 `$status）` 後面的全形括號當成變數名的一部分，導致 `unbound variable`。所有緊接中文字元的變數都改成 `${var}`。

## 2. 修改檔案

| 檔案 | 變更 |
|---|---|
| `src/ros2_uav_pipeline/mobilevit_uav_pipeline/run_log.py` | detector/publisher CSV schema、`frame_timing`、stamp 轉換、`parse_frame_id`、`publisher_csv_path` |
| `.../mobilevit_detector_node.py` | 新 timing/deadline/warm-up 欄位；只用 wall clock + perf_counter；不編造 frame_id 或輸入 |
| `.../image_stream_node.py` | wall-clock stamp；`run_id`/`output_csv` 參數；publisher log |
| `src/ros2_uav_pipeline/launch/mobilevit_uav_pipeline.launch.py` | `OpaqueFunction` 共用 run_id；任一 node 結束即 Shutdown；新增 `warmup_frames` 參數 |
| `experiments/ros2/run_common.sh`（新） | 執行前檢查 / 結果分類 / `*.failed` 隔離 |
| `experiments/ros2/run_{fps,qos,overload}_sweep.sh` | 使用 `run_common.sh`、傳遞 `WARMUP_FRAMES` |
| `src/ros2_runtime/analyze_runtime.py` | deadline 定義、window/drop 會計、key 正規化與排序、warm-up、stage timing、publisher log 載入、`--warmup-frames`、圖表 `n/a` |
| `src/ros2_runtime/build_os_profiles.py` | 拒絕未知的 drop rate |
| `tests/test_ros2_measurement.py`（新，27 tests） | 見第 3 節 |
| `tests/test_ros2_run_integrity.py` | fake `ros2`/`timeout` 改成模擬「到時結束」(99→124)，並新增 publisher log 與失敗模式；新增 2 個腳本測試；更新 header/launch 斷言以對應新結構（沒有放寬條件） |
| `scripts/audit_repro.py` | P1-5 改用 publisher log 驗證；新增 `P1-6`、`LAUNCH` case；與舊版 analyzer 相容 |
| `README.md`、`AGENTS.md`、`experiments/ros2/README.md`、`report/ros2_pipeline_integration.md` | CSV 契約、量測定義、publisher log、warm-up、launch 行為 |
| `report/audit_p0_p1_p2.md`、`report/ai_interaction_log.md` | P1-4/5/6 狀態與決策紀錄 |

未動到：EDA-Lite（`src/eda_lite/`，包括使用者的 `plot_6lines.py`）、所有 `results/` 與 `experiments/eda_lite/` 資料、PR-B～PR-F 範圍。

## 3. 測試結果

```bash
python3 -m unittest discover -s tests        # Ran 71 tests ... OK
```

| 檢查 | 結果 |
|---|---|
| Unit / integration tests | **71/71 通過**（Python 3.11.4，macOS，bash 3.2） |
| 新測試對照 PR-A1 checkpoint（`a40816d`） | `test_ros2_measurement.py` 的 27 個測試在舊行為下**全部失敗**。舊 analyzer 缺少 `load_publisher_frames`，比對時只在暫存副本加了 API 名稱 shim，行為仍是舊的 |
| `python3 scripts/audit_repro.py` | 在 `a40816d` 上 P1-4、P1-5、P1-6、LAUNCH 為 **REPRODUCED**；現在為 **FIXED**。P0-2 維持 FIXED。P0-1、P0-3、P1-1/2/3/7 仍為 REPRODUCED（不在本批範圍） |
| Shell syntax（`bash -n`，11 個 `.sh`） | 全部通過 |
| Python syntax（`ast.parse` src/scripts/tests，26 個檔案） | 全部通過 |
| CSV schema 相容性 | legacy（無 run_id）、PR-A1（有 run_id、無新欄位）、v2 三代 detector CSV 都能分析（`test_all_detector_schema_generations_are_readable`）；summary 前 20 欄順序不變（`test_cli_writes_extended_summary_columns_in_order`）；舊 summary 沒有 `drop_rate_pct` 欄位時 `build_os_profiles` 仍相容 |
| `check_runtime_provenance.py` | 仍 exit 1（P0-3，不在本批） |

新增測試分類（`tests/test_ros2_measurement.py`）：
- **Deadline**（6）：dropped 不算 miss（audit 原例）、`deadline_ms` 為唯一定義（含邊界 `=`）、只有 deadline 未知時才採用 flag、miss rate ≤100%、processed=0 時留空、同一 run 多個 deadline 時報錯。
- **Drop accounting**（9）：explicit + gap 不重複計算、publisher log 計入開頭/結尾掉幀、無 log 時標成下限、unknown 時留空與 `n/a`、explicit_only、OS profile 拒絕未知 drop rate、數值 key 正規化、混合型別排序、publisher log 分開載入並略過 `*.failed`。
- **Timing / warm-up**（7）：stage 分離、stamp 往返與 frame_id 解析、時鐘來源（靜態檢查）、v2 stage 平均、legacy 標示、warm-up 排除與 window 邊界、CLI `--warmup-frames`。
- **Schema**（2）與 **Launch**（3，用 stub 的 `launch` 模組實際執行 launch 檔）：run_id 只解析一次且兩個 node 共用、明確路徑推導 publisher log、兩個 node 都掛上 `OnProcessExit → Shutdown`。

`tests/test_ros2_run_integrity.py` 新增的腳本測試：
- `test_launch_failures_are_reported_and_quarantined`：涵蓋 early_exit / crash / no_frames 三種情況，確認 exit 1、第一個失敗點就中止、沒有殘留可分析的 `*.csv`。
- `test_timed_runs_succeed_and_pass_warmup_frames`。

## 4. 尚需實機驗證（本機沒有 ROS 2，**未做實機測試**）

1. 在 Linux/RoboStack 跑一次短 sweep（例如 `FPS_VALUES=5 RUN_SECONDS=15 bash experiments/ros2/run_fps_sweep.sh`），確認以下各點：
   - 兩個 node 都能匯入 `run_log`；
   - `<run_id>.csv` 與 `<run_id>.publisher.csv` 都有產生，欄位順序正確；
   - `msg.header.stamp.sec/nanosec` 的 tuple 指派在 rclpy 下可行；
   - publisher log 的 line buffering 在 SIGINT/SIGTERM 下沒有遺失資料。
2. 確認真實 `ros2 launch` 的行為：
   - detector 故意失敗（例如輸出檔已存在）時，launch 會立即結束、腳本回報失敗並產生 `*.failed`；
   - 正常到時結束時 `timeout` 回傳 124；
   - `ros2 launch` 在 SIGTERM 下能在合理時間內結束（目前 `timeout` 沒有加 `-k`）。
3. **既有疑慮，非本批引入**：腳本以 `deadline_ms:=100`、`input_fps:=5` 這類整數字串傳給宣告為 double 的參數。Humble 的靜態型別檢查可能拒絕。過去的 measured 資料顯示可以運作，但仍建議實機確認。
4. 驗證 `transport_ms` 與 `latency_ms` 的數值合理性：同機時應為非負且量級正確；跨機器時兩邊時鐘不同步，這兩個欄位會無效，目前不支援跨機。

## 5. 剩餘限制

- `frame_id_range` 模式（沒有 publisher log，例如舊資料）的掉幀數只是下限；已用 `frame_accounting` 標示，但數值本身無法補正。
- 結尾 in-flight frame（publisher 已送出、detector 尚未處理就被停止）會被算成 dropped。對 60 秒 run 來說只是少數幾個 frame，但仍會讓 drop rate 略為偏高。
- Warm-up 預設 10 frame 是經驗值，而且設了 warm-up 之後，啟動期（subscriber 尚未就緒）的掉幀會被排除在 window 外；若要研究啟動期掉幀，請設 `WARMUP_FRAMES=0`。
- legacy CSV 的 `inference_ms` 可能含 artificial delay，只能用 `timing_schema=legacy` 標示，無法回溯修正。
- `cpu_percent` 的第一個樣本仍是 0（psutil 的語意），多核時可能 > 100%；warm-up 能排除第一個樣本，但沒有做正規化。
- 不在本批範圍：EDA-Lite deadline / `latency_multiplier`（P1-4 第 1、2 點）、P1-7 正規化、P1-8 run metadata、P0-1、P0-3、P1-1/2/3、P2。

## 6. Git diff 概況

- 已提交：`a40816d` PR-A1 checkpoint。
- 本批未提交，排除使用者既有變更後共 **17 個已追蹤檔案，+815 / −226**，另有 2 個新檔：`experiments/ros2/run_common.sh`（49 行）、`tests/test_ros2_measurement.py`（439 行）。主要變更：

```text
src/ros2_runtime/analyze_runtime.py                 | 318 +++++++++++++++++----
src/ros2_uav_pipeline/launch/...launch.py           | 132 ++++++---
src/ros2_uav_pipeline/.../mobilevit_detector_node.py | 103 ++++---
src/ros2_uav_pipeline/.../run_log.py                |  93 +++++-
tests/test_ros2_run_integrity.py                    |  93 ++++--
scripts/audit_repro.py                              |  80 +++++-
README.md                                           |  42 ++-
src/ros2_uav_pipeline/.../image_stream_node.py      |  28 +-
src/ros2_runtime/build_os_profiles.py               |  22 +-
experiments/ros2/run_{fps,qos,overload}_sweep.sh    |  21 +- (each)
其餘文件                                             | 小幅更新
```

- 仍未提交、刻意保留的使用者變更：`src/eda_lite/plot_6lines.py`、`results/.DS_Store`、`results/figures/eda_lite/{s,xxs}/os_aware_total_cost_by_sram.svg`、`~$os-aware-eda-lite-final-presentation.pptx`。
- 提交本批時請排除被追蹤的 `__pycache__/*.pyc`（執行測試會改寫，audit P2-3）；交付前已還原。

## 7. 下一步建議

1. 依第 4 節在 ROS 2 環境做 smoke run；通過後再提交本批。
2. 下一批：EDA-Lite 端的 deadline 與 cost 一致性，包括 P1-4 第 1、2 點（`latency_multiplier` 套用到 deadline、runtime deadline 與 simulation deadline 的對應），並與 P0-1（DP objective）、P1-3 一起處理。
3. P0-3：用新 schema 重新產生 raw CSV / publisher log / summary，再重建 `runtime_os_profiles.json`（屆時再一併處理 P1-7 的依模型正規化）。
