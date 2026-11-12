# Phase 3 / Batch 1：Runtime Scheduling & Queue Management

- 日期：2026-11-11（pilot 量測 03:36–04:17 +08:00）
- 分支：`phase3/scheduling-policies`，從 Phase 2 / Batch 2 最新 commit `fe3f2dc` 建立（建立前 working tree clean）；**未 push、未 merge、未修改 `main`**
- Commits：`33c9bf5`（排程實作 + 測試 + 腳本；pilot 所執行的程式碼）、本批次的 data + docs + report commit
- 一句話結論：三種應用層排程策略（FIFO / Latest-Frame / Deadline-Aware Adaptive）已在同一套「輕量 ingestion → bounded application queue → 單一 inference worker」架構下實作並通過測試；legacy QoS depth 1 / 5 保留為 baseline。60 個交錯排程的短時間 pilot run 全部成功（constrained、DDS 驗證通過）。
  - **過載（MobileViT-S 20 FPS，ρ ≈ 1.13–1.18）**：Adaptive 的 effective miss 為 14.0%（三個 run 13.8–14.2%）。對照組：Latest-Frame 24.2%、legacy depth 1 29.4%（21.2–35.0%）、FIFO 與 legacy depth 5 都是 100%。Adaptive 的 P99 是 98.8 ms，**低於 100 ms deadline**。代價是 drop rate 較高（13.8% vs Latest 11.8%）。
  - **接近容量（XXS 60 FPS，ρ ≈ 0.93–1.00）與未過載（S 10、XXS 20）**：各策略的 effective miss 差距都在 2 個百分點以內；FIFO 是例外，在 XXS 60 FPS 為 8.8%。**在這些條件下，Adaptive 沒有優勢。**
  - 實作過程中發現並修正一個會**混淆比較**的因素：在本 node 的 import 順序下，主執行緒（legacy callback）與 worker 執行緒的 OpenMP 有效平行度不同（§2）。所有 arm 因此固定 `intra_op_threads=1`。

## 1. 前置確認

| 項目 | 狀態 |
|---|---|
| 必讀文件 | `AGENTS.md`、`report/PHASE2_BATCH2_RESULT.md`、`src/ros2_uav_pipeline/`（publisher、detector、launch、`run_log.py`）、`src/ros2_runtime/analyze_runtime.py` / `aggregate_baseline.py`、`experiments/ros2/*.sh`、現有 171 個測試 |
| Phase 2 是否已 commit | 是。`phase2/batch2-ros2-baseline` @ `fe3f2dc`，`git status` 為 clean；從該處建立 `phase3/scheduling-policies` |
| 控制變數（與 Batch 2 相同） | Host `ctwlab`、`taskset -c 12,14` + `systemd-run --user --scope -p MemoryMax=4G -p MemorySwapMax=0`、`nice -n 10`、`ROS_DOMAIN_ID=87`、`RMW_IMPLEMENTATION=rmw_fastrtps_cpp` + `experiments/ros2/fastdds_shm_large.xml`（probe 執行期驗證）、COCO128、random-init timm 權重、preprocess 不變、warm-up 10、deadline 100 ms |
| 沒有改動的部分 | 模型、權重、前處理、輸入資料、publisher；EDA-Lite cost model；Dashboard（未新增）；Phase 2 的 75 個 raw runs、`ros2_runtime_summary.csv`、`runtime_os_profiles.json` 與 baseline 表格（`check_runtime_provenance.py` 仍為 **VERIFIED**） |

## 2. 架構設計

```text
publisher (RELIABLE depth 10, 不變)
   │  DDS（Fast DDS SHM）
   ▼
[DDS queue] subscriber BEST_EFFORT KEEP_LAST(qos_depth)          ← middleware 的佇列
   │
   ├─ legacy_qos：subscription callback 內做 preprocess + inference（Phase 2 原路徑，未改）
   │
   └─ fifo / latest_frame / adaptive：
        ingestion callback（executor 執行緒）：只記 received_at_ns、建 FrameItem、submit()
           ▼
        [application queue] FrameScheduler：bounded、Lock + Condition   ← 應用層佇列
           ▼
        單一 inference worker thread：next_frame() → preprocess → (delay) → inference → 寫 CSV
```

- **兩種佇列分開。**
  - Legacy 模式只有 DDS 佇列。丟棄由 KEEP_LAST 覆寫造成，應用層看不到，在 analyzer 中記為 `dds_unreceived_frames`。
  - 應用模式的 DDS depth 為 `SCHED_DDS_DEPTH=10`，由 ingestion 持續清空。pilot 中 36 個應用模式 run 的 `dds_unreceived_frames` 全部為 0，因此所有丟棄都由 policy 決定，並記錄 `drop_reason`（`app_policy_dropped_frames`）。
  - 改變 QoS depth 只是 legacy 的一個參數，不被當作新演算法。
- **所有新策略共用同一套執行架構**：同一個 ingestion callback、同一個 `FrameScheduler`、同一個 worker loop。唯一的差異是 `scheduling.py` 中純函式 `admit()` / `select()` 的 policy 分支。Worker 只有一個（測試檢查 `threading.Thread(` 只出現一次）。
- **Thread safety**：
  - queue 的所有操作都在 `FrameScheduler` 的 lock 內。
  - CSV 由兩個執行緒寫入：ingestion 寫 drop row，worker 寫 processed / drop row。兩者用同一把 `RLock` 串行化。
  - 「in-flight frame」的設定與清除，和寫 row 在同一把 lock 下完成，避免 shutdown 時同一個 frame 被寫兩次。
- **Shutdown**（`stop_scheduler()`，在 `main` 的 `finally` 中執行）：
  1. `close()`：停止接收，取出仍在 queue 的 frame。
  2. `join(3 s)`：讓 worker 完成正在處理的那個 frame。launch 從 SIGINT 升級到 SIGTERM 需要 5 s。
  3. queue 中剩下的 frame 記為 `shutdown_pending`；若 worker 逾時，in-flight frame 記為 `shutdown_inflight`。
  4. 設定 `_csv_closed`，之後 worker 的任何寫入都會被忽略。
  - Worker 是 daemon thread：卡住的 forward pass 不會阻止 process 退出。
  - Worker 發生例外時，main loop 會結束，process 以 exit 1 結束；launch 隨之提前結束，sweep 把該 run 標成 `*.failed`。
- **Bounded memory**：
  - queue 長度永遠不超過 capacity（隨機測試涵蓋 2000 步 × 4 種設定；pilot 中觀察到的最大長度：FIFO 5、Adaptive 2、Latest 1）。
  - Drop 時立即釋放 message payload。
  - cgroup `memory.peak`：S 約 402–410 MB、XXS 約 354–368 MB（上限 4 GiB），與 Batch 2 相近。

### 2.1 發現的混淆因素：OpenMP 有效平行度（`intra_op_threads`）

第一次真實 smoke test（XXS 60 FPS，程式碼尚未修正，資料在 repo 外 `~/phase3_smoke/b1/`）中：

- worker 模式的 inference 是 **11.6 ms，CPU 175%**；
- 緊接著執行的 legacy run 是 **17.3 ms，CPU 100%**。

在 ROS 之外重現（同樣 `taskset -c 12,14`）：

| 測試（XXS forward） | Main thread | Worker thread |
|---|---|---|
| 只 import torch / timm | 10.8 ms，CPU 200% | 11.0 ms，169% |
| 加上 rclpy timer callback | 10.9 ms，200% | 10.8 ms，200% |
| **與 detector node 相同的 import 順序**（rclpy → torch → timm → psutil → cv2 → cv_bridge） | **15.8 ms，100%** | **9.5 ms，200%** |
| 同上 + `torch.set_num_threads(2)` | 15.9 ms，100% | 9.6 ms，200% |
| 同上 + `torch.set_num_threads(1)` | 14.3 ms，100% | 14.2 ms，100% |
| cv2 前處理 + 1 thread torch，20 FPS pacing | CPU 34% | **CPU 56%**（OpenCV 的 OpenMP helper busy-spin）；`cv2.setNumThreads(1)` 後降為 33% |

判讀：

1. 在這組 import 下，主執行緒上的 OpenMP 工作只用到約 1 個核心。這也是 Batch 2 中 detector 總是「100% = 一顆核心」的原因。
2. 換到新的執行緒後，torch 會用到 2 個核心，OpenCV 也會多出一個會 spin 的 helper thread。
3. 若不處理，應用模式的 arm 會因為 **計算變快約 35%**（而不是排程）而勝出。

處理方式：

- 新增 detector 參數 `intra_op_threads`，同時設定 torch 與 OpenCV。預設 0 = 不改動，Phase 2 腳本的行為不變。
- `run_sched_sweep.sh` 對 **所有 arm（包含 legacy）** 設為 1，等於 Batch 2 legacy 的實際有效平行度。
- 實際值寫入每一列 CSV（`intra_op_threads=torch=1;cv2=1`）與 meta.json。

修正後，所有 arm 的 detector CPU 都是約 100%（見表 B）。這是執行環境的控制，不改模型、權重或前處理。完整根因（哪一個 import 設定了主執行緒的 OpenMP ICV）沒有追到底，只確定了現象與控制方式。

## 3. 各策略的精確語意（`src/ros2_uav_pipeline/mobilevit_uav_pipeline/scheduling.py`）

| Policy | Queue | Arrival 時 queue 已滿 | Worker 選擇 | Drop reason |
|---|---|---|---|---|
| `legacy_qos:<d>` | 只有 DDS KEEP_LAST(d) | DDS 覆寫最舊的 sample | executor 取 DDS 佇列中最舊的 sample | 不可見 → `dds_unreceived_frames` |
| `fifo` | capacity C（預設 5），依到達順序 | `fifo_overflow=reject_newest`（預設，tail drop：丟棄剛到的 frame）或 `evict_oldest`（head drop） | 最舊的 frame | `queue_full_reject_newest` / `queue_full_evict_oldest` |
| `latest_frame` | 最多 1 個 pending（capacity 參數被忽略） | 新 frame 取代 pending frame | 最新的 frame | `superseded` |
| `adaptive` | capacity C，滿了丟最舊 | `queue_full_evict_oldest` | 見下方 | `deadline_infeasible` / `superseded` |

Adaptive（deadline-aware）在 worker 空閒時做決策：

1. 對每個 pending frame 預測 `L̂ = (now − published) + S_q`。
   - `S_q` = 最近 `adaptive_window=32` 個**已完成、非 warm-up** frame 的 service time（preprocess + delay + inference）的 nearest-rank `adaptive_quantile=0.9` 分位數。
   - 可行條件：`L̂ ≤ deadline − adaptive_margin_ms (0)`。
2. 依狀況決策：
   - **還沒有估計值**（啟動期）→ 取最舊的 frame（`no_estimate`）。
   - **有可行的 frame**：
     - 若 `ρ̂ = λ̂ · S_mean < 1.0`（λ̂ = ingestion 端最近 32 個到達的速率）→ 取**最舊的可行 frame**（EDF，`edf`）。不會丟掉任何還來得及處理的 frame。
     - 否則 → 取**最新的可行 frame**（`newest_feasible`，主動卸載）。
     - 比所選 frame 更舊的 frame 一律丟棄：預測會超時者記 `deadline_infeasible`，其餘記 `superseded`。比所選 frame 更新的 frame 留在 queue 中。
   - **全部不可行，但新到的 frame 來得及**（ingest delay 中位數 + `S_q` ≤ budget）→ 全部記 `deadline_infeasible` 丟棄，等待下一個 frame（`wait`）。
   - **連新 frame 都來不及**（service 本身已超過 deadline）→ best effort：取最新的 frame，其餘記 `superseded`（`best_effort`）。
3. 只使用決策當下以前觀察到的資訊。參數（0.9 / 32 / 0 / 1.0）在任何 pilot 資料出現前就已固定在程式碼預設值中，看到結果後**沒有再調整**。

## 4. Logging、metadata 與 analyzer

- **Detector CSV**：在 Batch 2 欄位**之後**新增 17 欄，舊欄位位置不變：
  - `scheduler_policy`、`queue_capacity`、`scheduler_params`、`drop_reason`
  - `enqueued_at_ns`、`dequeued_at_ns`、`started_at_ns`、`dropped_at_ns`
  - `queue_wait_ms`、`frame_age_at_start_ms`、`queue_len_at_enqueue/at_dequeue`
  - `scheduler_decision`、`est_service_ms`、`est_utilization`、`predicted_latency_ms`、`intra_op_threads`

  其他說明：

  - Drop row 不取樣 CPU / RSS，以免影響平均值。
  - 跨執行緒的時間戳記一律使用 wall clock；各階段的持續時間使用 `perf_counter`。
  - 應用模式下 `preprocess_ms` 從 worker 開始處理時起算，所以 service time 的定義與 Phase 2 相同。
- **Summary**：同樣只在尾端新增 20 欄。`dropped_frames` 的定義不變，但拆成互斥且加總相等的五類：

  | 欄位 | 意義 |
  |---|---|
  | `app_policy_dropped_frames` | policy drop |
  | `shutdown_unfinished_frames` | run 結束時仍在 queue / in-flight |
  | `dds_unreceived_frames` | 有發布、但沒有進到 callback（DDS 覆寫或遺失） |
  | `tail_unobserved_frames` | 在 detector 看到的最後一個 frame 之後才發布（結束截斷） |
  | `other_dropped_frames` | conversion error、legacy explicit row |

  另外新增：`policy_drop_reasons`、`app_policy_drop_rate_pct`、queue wait 的 avg / P50 / P95 / P99、frame age at start 的 avg / P50 / P95、`max_queue_len`、`scheduler_decisions`、`intra_op_threads`。
- **防止重複計算**：
  - 同一個 frame_id 若同時有 processed row 與 drop row，analyzer 直接報錯（沿用 duplicate frame_id 檢查），不會 de-duplicate。
  - 同一個 run 若出現兩種排程設定（包含 `intra_op_threads`）→ 報錯。
  - meta.json 中要求的 `scheduler_policy` 與 detector 實際記錄的不同 → 報錯。
- **Warm-up**：只有 processed row 帶 warm-up 旗標。窗口從最後一個 warm-up frame_id 之後開始，所以 warm-up 期間的 policy drop 不會進入統計。Adaptive 的 service 估計也排除 warm-up frame。
- **Metadata / provenance**：
  - `meta.json` 的 `experiment` 記錄 `scheduler_policy`、`scheduler_arm`、`arm_position`、`sched_arms`、`run_tag`、`queue_capacity`、`fifo_overflow`、各個 `adaptive_*`、`intra_op_threads`。
  - summary manifest 的 `runs[]` 記錄 policy / capacity / params。
  - `aggregate_scheduling` 的 manifest 對 summary、其 manifest、120 個 meta / probe 檔與所有輸出計算 SHA-256。

## 5. 測試與 CI

| 項目 | 結果 |
|---|---|
| 新測試 `tests/test_phase3_scheduling.py` | 43 tests，涵蓋：policy 語意（FIFO 順序、tail / head drop、latest 取代、adaptive 的 no_estimate / EDF / newest_feasible / wait / best_effort / margin）、capacity 永不超過（隨機）、參數驗證、estimator（nearest-rank、window、只用已完成的非 warm-up 樣本）、**並行**（producer / consumer 執行緒、每個 frame 恰好一個終止狀態、counters 不變式、newest-first 不倒退）、**shutdown**（阻塞的 worker 會被 `close()` 喚醒、close 後 submit 記為 shutdown drop）、**frame accounting**（五類互斥且加總 = dropped、warm-up 期間的 drop 排除、processed + dropped 同一 frame 報錯、單一 run 單一設定、meta 一致性）、**CSV 相容**（detector header 與 summary 欄位只在尾端新增；**以現行 analyzer 重算 Batch 2 的 75 個 raw run，舊欄位逐字等於已 commit 的 summary**）、node 結構（單一 worker、ingestion 不做重工作、legacy 路徑不變、shutdown 路徑）、launch 參數、sweep / pilot 腳本 |
| 修改的既有測試（2 個，意圖不變） | `test_detector_uses_one_clock_per_purpose`：wall-clock 呼叫次數改為逐路徑檢查（legacy 2/4 不變；新增 ingestion 1/1、worker 2/4）。`test_phase2_batch2` 的 `SUMMARY_FIELDS[-8:]`：改為以欄位位置檢查，因為後面新增了欄位 |
| `bash scripts/ci_checks.sh all`（`33c9bf5`，eda_lite env） | exit 0：**213 tests OK**（1 skipped）、`bash -n` 全部通過、audit `0/17 reproduced`、provenance **VERIFIED**（75 raw） |
| 新增測試的穩定性 | 並行測試獨立重複 5 次，全部通過 |
| 最終 CI | 見 §9 |

## 6. Linux 實測（pilot）

### 6.1 設計

- 條件：S 10 / 20 FPS、XXS 20 / 60 FPS。
- Arm（共 5 個）：`legacy_q1`、`legacy_q5`、`fifo_c5_q10`、`latest_q10`、`adaptive_c5_q10`。
- 每個條件 3 個 repeat，每個 run 40 s（timeout 包含約 1–2 s 的啟動時間）→ 共 60 runs。
- 驅動程式 `experiments/ros2/run_sched_pilot.sh`（`DRY_RUN=1` 會印出計畫）：
  - 偶數 repeat 時條件順序反轉。
  - 每個（repeat, 條件）block 中 arm 的順序輪轉 `(r−1+條件序號) mod 5`。每個條件 3 個 repeat 的第一個 arm 都不同（有測試）。
  - 每個 block 是一次 `run_baseline_experiments.sh SWEEPS=sched`，與 Batch 2 相同的 scope / limits / DDS gate。
- 結果：
  - 60/60 到時正常結束，0 個 `*.failed`。
  - 60/60 `measurement_class=constrained`，`dds.verified=true`。
  - 所有 run `intra_op_threads=torch=1;cv2=1`，kernel UDP `RcvbufErrors` 增量 0。
- Raw 資料：`results/raw/ros2_phase3_pilot/`（31 MB）。衍生資料：`results/csv/ros2_phase3_pilot_{summary,runs,arms,paired}.csv` + manifests。
- 統計單位是 run；± 是 3 個 run 之間的樣本 SD；frame 不合併。

### 6.2 A. 主要指標（mean ± SD across runs）

定義：

- ρ = offered × service / 1000。
- On-time FPS = offered × (1 − effective miss)。
- Effective miss = (deadline miss + drops) / total frames。
- Frame age at start = publish → 開始處理。
- Queue wait 只適用於應用模式的 queue。

| Model | FPS | Arm | n | ρ | Processed FPS | On-time FPS | Drop % | Policy drop % | Deadline miss % | Effective miss % (min–max) | P50 | P95 | P99 latency (ms) | P50 frame age at start | P95 queue wait |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S | 10 | `legacy_q1` | 3 | 0.59 | 10.0 ± 0.0 | 10.0 ± 0.0 | 0.0 ± 0.0 | 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 (0.0–0.0) | 59.6 | 62.9 | 64.1 ± 1.3 | 0.5 | — |
| S | 10 | `legacy_q5` | 3 | 0.60 | 10.0 ± 0.0 | 10.0 ± 0.0 | 0.0 ± 0.0 | 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 (0.0–0.0) | 60.4 | 63.4 | 64.6 ± 0.9 | 0.5 | — |
| S | 10 | `fifo_c5_q10` | 3 | 0.57 | 10.0 ± 0.0 | 10.0 ± 0.0 | 0.0 ± 0.0 | 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 (0.0–0.0) | 58.3 | 60.0 | 61.8 ± 1.0 | 0.7 | 0.2 |
| S | 10 | `latest_q10` | 3 | 0.57 | 10.0 ± 0.0 | 10.0 ± 0.0 | 0.0 ± 0.0 | 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 (0.0–0.0) | 58.3 | 60.1 | 61.5 ± 0.4 | 0.7 | 0.2 |
| S | 10 | `adaptive_c5_q10` | 3 | 0.56 | 10.0 ± 0.0 | 10.0 ± 0.0 | 0.0 ± 0.0 | 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 (0.0–0.0) | 56.7 | 59.8 | 60.5 ± 0.1 | 0.7 | 0.2 |
| S | 20 | `legacy_q1` | 3 | 1.16 | 17.1 ± 0.7 | 14.1 ± 1.5 | 14.6 ± 3.5 | 0.0 | 17.5 ± 5.1 | 29.4 ± 7.3 (21.2–35.0) | 83.3 | 106.0 | 109.7 ± 1.8 | 24.9 | — |
| S | 20 | `legacy_q5` | 3 | 1.18 | 16.9 ± 0.4 | 0.0 ± 0.0 | 15.8 ± 1.9 | 0.0 | 100.0 ± 0.0 | 100.0 ± 0.0 (100.0–100.0) | 283.4 | 307.2 | 310.2 ± 1.1 | 224.6 | — |
| S | 20 | `fifo_c5_q10` | 3 | 1.13 | 17.6 ± 0.2 | 0.0 ± 0.0 | 12.0 ± 0.7 | 11.3 | 100.0 ± 0.0 | 100.0 ± 0.0 (100.0–100.0) | 314.4 | 339.4 | 345.3 ± 3.3 | 258.1 | 281.8 |
| S | 20 | `latest_q10` | 3 | 1.13 | 17.6 ± 0.0 | 15.2 ± 0.1 | 11.8 ± 0.1 | 11.8 | 14.1 ± 0.5 | 24.2 ± 0.3 (24.0–24.6) | 82.4 | 105.0 | 108.2 ± 0.5 | 25.7 | 47.6 |
| S | 20 | `adaptive_c5_q10` | 3 | 1.14 | 17.3 ± 0.0 | 17.2 ± 0.0 | 13.8 ± 0.1 | 13.7 | 0.3 ± 0.2 | 14.0 ± 0.2 (13.8–14.2) | 75.8 | 95.8 | 98.8 ± 0.3 | 19.1 | 38.0 |
| XXS | 20 | `legacy_q1` | 3 | 0.34 | 20.0 ± 0.0 | 20.0 ± 0.0 | 0.0 ± 0.0 | 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 (0.0–0.0) | 17.7 | 19.0 | 19.4 ± 0.2 | 0.5 | — |
| XXS | 20 | `legacy_q5` | 3 | 0.35 | 20.0 ± 0.0 | 20.0 ± 0.0 | 0.0 ± 0.0 | 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 (0.0–0.0) | 17.8 | 18.9 | 19.4 ± 0.4 | 0.5 | — |
| XXS | 20 | `fifo_c5_q10` | 3 | 0.34 | 20.0 ± 0.0 | 20.0 ± 0.0 | 0.0 ± 0.0 | 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 (0.0–0.0) | 17.4 | 18.8 | 19.3 ± 0.1 | 0.6 | 0.1 |
| XXS | 20 | `latest_q10` | 3 | 0.34 | 20.0 ± 0.0 | 20.0 ± 0.0 | 0.0 ± 0.1 | 0.0 | 0.0 ± 0.0 | 0.0 ± 0.1 (0.0–0.1) | 17.4 | 18.8 | 19.2 ± 0.1 | 0.7 | 0.1 |
| XXS | 20 | `adaptive_c5_q10` | 3 | 0.34 | 20.0 ± 0.0 | 20.0 ± 0.0 | 0.0 ± 0.0 | 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 (0.0–0.0) | 17.4 | 19.1 | 19.6 ± 0.0 | 0.7 | 0.2 |
| XXS | 60 | `legacy_q1` | 3 | 0.97 | 59.0 ± 1.7 | 59.0 ± 1.7 | 1.7 ± 2.9 | 0.0 | 0.0 ± 0.0 | 1.7 ± 2.9 (0.0–5.0) | 19.6 | 24.3 | 25.9 ± 7.5 | 3.2 | — |
| XXS | 60 | `legacy_q5` | 3 | 0.93 | 60.0 ± 0.0 | 60.0 ± 0.0 | 0.0 ± 0.0 | 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 (0.0–0.1) | 16.2 | 45.6 | 70.2 ± 21.0 | 0.6 | — |
| XXS | 60 | `fifo_c5_q10` | 3 | 1.00 | 59.2 ± 0.2 | 54.7 ± 1.6 | 1.4 ± 0.4 | 1.2 | 7.5 ± 2.4 | 8.8 ± 2.7 (7.0–11.9) | 91.6 | 101.1 | 104.5 ± 1.9 | 75.0 | 83.3 |
| XXS | 60 | `latest_q10` | 3 | 1.00 | 59.1 ± 0.2 | 59.1 ± 0.2 | 1.4 ± 0.3 | 1.4 | 0.0 ± 0.0 | 1.4 ± 0.3 (1.3–1.8) | 25.7 | 32.4 | 34.0 ± 0.2 | 9.2 | 15.0 |
| XXS | 60 | `adaptive_c5_q10` | 3 | 1.00 | 59.2 ± 0.1 | 59.2 ± 0.1 | 1.3 ± 0.1 | 1.3 | 0.0 ± 0.0 | 1.3 ± 0.1 (1.2–1.4) | 25.1 | 32.9 | 35.7 ± 0.6 | 8.3 | 15.5 |

### 6.3 B. Service time、CPU 與 drop 來源

| Model | FPS | Arm | Inference avg (ms) | Service avg (ms) | Detector CPU % (psutil) | intra_op_threads | DDS-unreceived | Tail | Shutdown | Max app queue | all DDS verified |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S | 10 | `legacy_q1` | 58.6 ± 0.5 | 59.0 ± 0.5 | 60 | torch=1;cv2=1 | 0.0 | 0.0 | 0.0 | — | true |
| S | 10 | `legacy_q5` | 59.5 ± 0.6 | 59.8 ± 0.6 | 61 | torch=1;cv2=1 | 0.0 | 0.0 | 0.0 | — | true |
| S | 10 | `fifo_c5_q10` | 56.2 ± 0.2 | 56.6 ± 0.2 | 57 | torch=1;cv2=1 | 0.0 | 0.0 | 0.0 | 1 | true |
| S | 10 | `latest_q10` | 56.5 ± 0.2 | 56.9 ± 0.2 | 58 | torch=1;cv2=1 | 0.0 | 0.0 | 0.0 | 1 | true |
| S | 10 | `adaptive_c5_q10` | 56.0 ± 0.3 | 56.4 ± 0.3 | 57 | torch=1;cv2=1 | 0.0 | 0.0 | 0.0 | 1 | true |
| S | 20 | `legacy_q1` | 57.8 ± 2.3 | 58.1 ± 2.3 | 100 | torch=1;cv2=1 | 110.7 | 0.0 | 0.0 | — | true |
| S | 20 | `legacy_q5` | 58.4 ± 1.3 | 58.8 ± 1.3 | 100 | torch=1;cv2=1 | 115.7 | 4.7 | 0.0 | — | true |
| S | 20 | `fifo_c5_q10` | 56.2 ± 0.5 | 56.5 ± 0.5 | 101 | torch=1;cv2=1 | 0.0 | 0.0 | 4.7 | 5 | true |
| S | 20 | `latest_q10` | 56.2 ± 0.1 | 56.5 ± 0.0 | 101 | torch=1;cv2=1 | 0.0 | 0.0 | 0.0 | 1 | true |
| S | 20 | `adaptive_c5_q10` | 56.4 ± 0.1 | 56.8 ± 0.1 | 99 | torch=1;cv2=1 | 0.0 | 0.0 | 0.3 | 2 | true |
| XXS | 20 | `legacy_q1` | 16.9 ± 0.4 | 17.2 ± 0.4 | 36 | torch=1;cv2=1 | 0.0 | 0.0 | 0.0 | — | true |
| XXS | 20 | `legacy_q5` | 16.9 ± 0.5 | 17.3 ± 0.5 | 36 | torch=1;cv2=1 | 0.0 | 0.0 | 0.0 | — | true |
| XXS | 20 | `fifo_c5_q10` | 16.5 ± 0.1 | 16.9 ± 0.1 | 35 | torch=1;cv2=1 | 0.0 | 0.0 | 0.0 | 1 | true |
| XXS | 20 | `latest_q10` | 16.4 ± 0.0 | 16.8 ± 0.0 | 35 | torch=1;cv2=1 | 0.0 | 0.3 | 0.0 | 1 | true |
| XXS | 20 | `adaptive_c5_q10` | 16.5 ± 0.0 | 16.9 ± 0.1 | 35 | torch=1;cv2=1 | 0.0 | 0.0 | 0.0 | 1 | true |
| XXS | 60 | `legacy_q1` | 15.8 ± 0.8 | 16.1 ± 0.8 | 98 | torch=1;cv2=1 | 38.7 | 0.0 | 0.0 | — | true |
| XXS | 60 | `legacy_q5` | 15.2 ± 0.3 | 15.5 ± 0.3 | 97 | torch=1;cv2=1 | 0.7 | 0.0 | 0.0 | — | true |
| XXS | 60 | `fifo_c5_q10` | 16.4 ± 0.1 | 16.7 ± 0.1 | 102 | torch=1;cv2=1 | 0.0 | 0.0 | 4.3 | 5 | true |
| XXS | 60 | `latest_q10` | 16.4 ± 0.0 | 16.7 ± 0.1 | 101 | torch=1;cv2=1 | 0.0 | 0.0 | 0.0 | 1 | true |
| XXS | 60 | `adaptive_c5_q10` | 16.4 ± 0.0 | 16.7 ± 0.0 | 101 | torch=1;cv2=1 | 0.0 | 0.3 | 0.3 | 2 | true |

### 6.4 C. 同一個 block 內的成對差異（arm − `legacy_q1`；mean (min…max) over 3 blocks）

| Model | FPS | Arm − `legacy_q1` | blocks | Δ processed FPS | Δ on-time FPS | Δ effective miss pp (min…max) | Δ deadline miss pp | Δ P50 ms | Δ P99 ms (min…max) | Δ service ms |
|---|---|---|---|---|---|---|---|---|---|---|
| S | 10 | `legacy_q5` | 3 | 0.00 | 0.00 | 0.0 (0.0…0.0) | 0.0 | 0.8 | 0.6 (-1.4…2.5) | 0.86 |
| S | 10 | `fifo_c5_q10` | 3 | -0.00 | 0.00 | 0.0 (0.0…0.0) | 0.0 | -1.3 | -2.2 (-2.6…-1.9) | -2.38 |
| S | 10 | `latest_q10` | 3 | -0.00 | 0.00 | 0.0 (0.0…0.0) | 0.0 | -1.3 | -2.6 (-4.0…-0.9) | -2.07 |
| S | 10 | `adaptive_c5_q10` | 3 | 0.00 | 0.00 | 0.0 (0.0…0.0) | 0.0 | -2.8 | -3.5 (-4.3…-2.2) | -2.58 |
| S | 20 | `legacy_q5` | 3 | -0.22 | -14.12 | 70.6 (65.0…78.8) | 82.5 | 200.1 | 200.5 (198.6…202.9) | 0.69 |
| S | 20 | `fifo_c5_q10` | 3 | 0.55 | -14.12 | 70.6 (65.0…78.8) | 82.5 | 231.1 | 235.6 (234.1…237.5) | -1.56 |
| S | 20 | `latest_q10` | 3 | 0.55 | 1.04 | -5.2 (-11.1…3.4) | -3.4 | -0.8 | -1.5 (-2.8…0.8) | -1.55 |
| S | 20 | `adaptive_c5_q10` | 3 | 0.18 | 3.08 | -15.4 (-20.8…-7.2) | -17.2 | -7.5 | -10.9 (-12.0…-8.8) | -1.31 |
| XXS | 20 | `legacy_q5` | 3 | -0.00 | 0.00 | 0.0 (0.0…0.0) | 0.0 | 0.2 | 0.0 (-0.3…0.6) | 0.04 |
| XXS | 20 | `fifo_c5_q10` | 3 | -0.00 | 0.00 | 0.0 (0.0…0.0) | 0.0 | -0.3 | -0.1 (-0.3…0.2) | -0.36 |
| XXS | 20 | `latest_q10` | 3 | -0.00 | -0.01 | 0.0 (0.0…0.1) | 0.0 | -0.3 | -0.2 (-0.5…-0.0) | -0.39 |
| XXS | 20 | `adaptive_c5_q10` | 3 | -0.00 | 0.00 | 0.0 (0.0…0.0) | 0.0 | -0.2 | 0.1 (-0.1…0.3) | -0.31 |
| XXS | 60 | `legacy_q5` | 3 | 1.00 | 0.98 | -1.6 (-5.0…0.0) | 0.0 | -3.4 | 44.2 (25.0…63.7) | -0.62 |
| XXS | 60 | `fifo_c5_q10` | 3 | 0.16 | -4.27 | 7.1 (6.9…7.4) | 7.5 | 72.1 | 78.6 (72.1…82.0) | 0.59 |
| XXS | 60 | `latest_q10` | 3 | 0.14 | 0.15 | -0.2 (-3.3…1.3) | 0.0 | 6.2 | 8.1 (-0.5…12.5) | 0.60 |
| XXS | 60 | `adaptive_c5_q10` | 3 | 0.25 | 0.23 | -0.4 (-3.8…1.4) | 0.0 | 5.6 | 9.8 (1.7…14.4) | 0.56 |

## 7. 取捨分析

1. **真實過載（S 20 FPS，ρ ≈ 1.13–1.18）**
   - **處理量相同**：processed FPS 都約 17 FPS。在過載下，總 drop 由 ρ 決定，幾乎與策略無關：11.8–15.8%；依 1−1/ρ 的預測是 12–15%。
   - **策略決定的是「哪些 frame 被處理、延遲多少」**：
     - **FIFO（tail drop, C=5）**：queue 一直是滿的。等待時間約 5 × service（P95 queue wait 282 ms）。P50 314 ms，比 legacy depth 5 的 283 ms 還差，因為 legacy 是 head drop，佇列中保留的是較新的 frame。Effective miss 100%。**FIFO 是在過載下最不適合即時推論的策略**，但它的行為完全符合定義。
     - **Latest-Frame** 與 legacy depth 1 的行為本質相同：最多保留 1 張，等待時間 < 一個到達間隔。兩者的 effective miss 為 24.2% vs 29.4%。成對差異 −5.2 pp，但三個 block 中有一個為正（−11.1…+3.4），**不能宣稱兩者有差異**。legacy_q1 的 run 間變異也大得多（21–35%）。
     - **Adaptive**：
       - effective miss 14.0%，三個 block 都低於 legacy_q1（−7.2…−20.8 pp），也都低於 Latest（13.8–14.2 vs 24.0–24.6，範圍不重疊）。
       - deadline miss 從 14% 降到 0.3%，P99 98.8 ms < deadline，on-time FPS 17.2 vs 15.2。
       - 代價：drop rate 多約 2 pp（13.8 vs 11.8%），因為它在預測來不及時主動丟掉 frame（每個 run 約 104 個 `deadline_infeasible`），並短暫等待下一張（worker 空閒）。processed FPS 因此低 0.3 FPS。
       - 運作機制：worker 空閒時，最新 frame 的年齡若超過約 100 − S_q ≈ 41 ms，處理它必定超時；Adaptive 改為等待下一張（≤ 9 ms 後到達）。
2. **接近容量（XXS 60 FPS）**
   - 應用模式的 service 比 legacy **慢 0.6 ms**（16.7 vs 15.5–16.1 ms，成對差異 +0.56–0.60 ms，每個 block 都是正值）。這把 ρ 從 0.93–0.97 推到 1.00，所以 legacy arm 幾乎不過載，應用模式則剛好達到臨界。在這個 ρ 附近的比較會受到這 4% 架構開銷左右，**不能把差異歸因於策略**。
   - 實際觀察：
     - legacy_q5：0% drop，但 P99 70 ms，變異大。
     - legacy_q1：effective miss 0–5%。
     - Latest / Adaptive：約 1.3% drop，0 miss，P99 34–36 ms。
     - FIFO：deadline miss 7.5%，effective 8.8%，P50 92 ms。
   - Adaptive 的決策在 `edf` 與 `newest_feasible` 之間約各半切換（ρ̂ 在門檻 1.0 附近擺動），結果與 Latest 沒有可分辨的差異。
3. **未過載（S 10、XXS 20）**：五個 arm 都是 0 drop、0 miss。延遲差異在 ±3 ms 以內，主要來自 service time 的差異（S：應用模式反而快約 2 ms；XXS 20：快約 0.3 ms）。Adaptive 在未過載時不會丟掉任何 frame（EDF 分支），滿足「不會無謂丟幀」的要求。
4. **Adaptive 不一定勝出**：它只在「service < deadline 但等待會讓 frame 過期」的過載區間有明確優勢。在臨界或未過載時，它與 Latest 相同。若 service ≥ deadline（例如 Batch 2 的 overload delay ≥ 80 ms），它會退化為 best effort，也就是 Latest（本批次未測）。

## 8. Git diff

`fe3f2dc..33c9bf5`（程式碼；pilot 執行的版本）：

```text
 .gitignore                                         |   4 +
 experiments/ros2/run_sched_pilot.sh                |  62 +++
 experiments/ros2/run_sched_sweep.sh                | 131 ++++++
 scripts/run_baseline_experiments.sh                |   4 +-
 src/ros2_runtime/aggregate_scheduling.py           | 211 +++++++++
 src/ros2_runtime/analyze_runtime.py                | 151 ++++++
 .../launch/mobilevit_uav_pipeline.launch.py        |  14 +
 .../mobilevit_detector_node.py                     | 253 +++++++++-
 .../mobilevit_uav_pipeline/run_log.py              |  34 ++
 .../mobilevit_uav_pipeline/scheduling.py           | 449 ++++++++++++++++++
 tests/test_phase2_batch2.py                        |   3 +-
 tests/test_phase3_scheduling.py                    | 519 +++++++++++++++++++++
 tests/test_ros2_measurement.py                     |  17 +-
 13 files changed, 1836 insertions(+), 16 deletions(-)
```

第二個 commit（data + docs + report）：

- `results/raw/ros2_phase3_pilot/`：240 個檔案 = 60 runs × csv / publisher.csv / meta.json / probe.json。
- `results/csv/ros2_phase3_pilot_*`：summary / runs / arms / paired + 2 個 manifest。
- 文件：`AGENTS.md`、`README.md`、`experiments/ros2/README.md`、`results/README.md`、`report/ai_interaction_log.md`、本報告。
- `run_sched_pilot.sh`：在每個 block 前重新檢查 git tree（見 §10.1），並加上對應測試。

Smoke / 診斷資料與獨立的 benchmark 腳本放在 repo 外的 `~/phase3_smoke/b1/`。Git identity 沿用 Batch 1/2 的做法，以 `git -c` 指定。

## 9. 驗證摘要

| 檢查 | 結果 |
|---|---|
| Pilot 完成度 | 60/60 exit 124、0 failed、60/60 constrained、60/60 DDS verified |
| 執行的程式碼 | 60/60 `git.commit=33c9bf5` |
| Frame accounting（真實資料） | 60/60 五類 drop 加總 = `dropped_frames`；36 個應用模式 run 的 interior `dds_unreceived` = 0、tail ≤ 1，所以**每個進到 detector 的 frame 都恰好有一個終止 row**；29 個 `shutdown_pending`、0 個 `shutdown_inflight`；Latest / Adaptive 處理的 frame_id 嚴格遞增；最大 queue 長度 ≤ capacity |
| Phase 2 artifacts | 沒有改動；`check_runtime_provenance.py` 仍為 VERIFIED（75 raw）；Batch 2 summary 可以由現行 analyzer 逐字重現（測試） |
| 最終 CI | 本報告 commit 前執行 `bash scripts/ci_checks.sh all`：exit 0、**214 tests OK**（1 skipped）、shell OK、audit 0/17、provenance VERIFIED |

## 10. 限制

### 10.1 本批次的執行瑕疵（如實揭露）

- **59/60 個 run 的 `meta.json` 記錄 `git.dirty=true`。**
  - 原因：pilot 執行期間，我修改了文件（`AGENTS.md`、`README.md`、`experiments/ros2/README.md`、`results/README.md`、`report/ai_interaction_log.md`）。pilot 只在開始時檢查 working tree。
  - 已查證：當時與 `33c9bf5` 的差異**只有這 5 個 .md 檔**（`git diff --name-only 33c9bf5` 中沒有任何非 Markdown 的 tracked 檔案）。node、scheduler、launch、腳本、analyzer 都與 `33c9bf5` 完全相同。
  - 量測本身不受影響，但 metadata 層級不是 clean，因此這批資料**只能作為 pilot**。
  - 已修正：`run_sched_pilot.sh` 現在在每個 block 前重新檢查 working tree，並有測試。
- **Shutdown 時印出的 scheduler 統計沒有出現在 log 中。**
  - 原因：`timeout` 送出 SIGTERM 後，`ros2 launch` 不再轉送子程序的輸出。
  - shutdown 路徑確實有執行：只在那裡寫入的 `shutdown_pending` row 存在。accounting 也已經用 publisher log 證明（§9）。
  - 若需要 detector 內部計數，下一批應改寫成 sidecar 檔。

### 10.2 方法與環境

- **架構開銷**：在 60 FPS 時，應用模式的 service 比 legacy 慢約 0.6 ms（約 4%）。推測是 ingestion 執行緒在 60 msg/s 下處理約 1 MB 訊息時與 worker 競爭 GIL / CPU。**沒有直接量測確認。** 在 S（20 msg/s）時，應用模式反而快約 2 ms。這兩種差異都會影響接近 ρ = 1 的比較。
- **`intra_op_threads=1` 是刻意的控制**：對齊 Batch 2 legacy 的實際行為，代表「單核推論」。2 執行緒的應用模式 arm 會快約 35%，但 legacy 路徑無法得到相同的平行度（主執行緒的 OpenMP 限制），所以沒有納入比較。根因只追到 import 順序 / OpenMP 的 per-thread 狀態。
- **主機狀態與 Batch 2 不同**：今天 XXS 的 service 約 15.5–16.7 ms，Batch 2 是 18.4 ms。因此 XXS 60 FPS 的 ρ ≈ 0.93–1.00，**不是 Batch 2 的 1.10**。原因是共用主機 + `powersave` governor。這也是**不能**把本批次的數字和 Batch 2 的表格直接相減的原因。
- **Pilot 規模**：40 s run（扣掉啟動與 warm-up 後約 35 s：S 20 FPS 約 690 frames、XXS 60 約 2300 frames），n = 3，沒有做顯著性檢定。只有 S 20 FPS 的 Adaptive 優勢在三個 block 中方向一致、範圍不重疊。
- **未測試**：artificial-delay 過載（service ≥ deadline 時的 best-effort 分支）、`fifo_overflow=evict_oldest`、其他 capacity / margin / quantile、`legacy_qos:10`。Adaptive 參數沒有做敏感度分析（依要求不事後調參）。
- 權重是 random-init，只量延遲。主機共用，沒有 cpuset 獨占。

## 11. 結論：是否具備正式 A/B Benchmark 的條件？

**大致具備，但要先完成三件事。**

已具備：

- 五個 arm 共用同一套控制變數與執行架構，只切換 policy。
- 交錯排程的驅動程式。
- 逐 run 的 metadata / probe / provenance。
- 完整且互斥的 drop accounting。
- 同一 block 內的成對分析工具。
- CI 全綠，Phase 2 artifacts 沒有被碰到。
- Pilot 已顯示在過載時有可量測、方向一致的差異。

正式比較前建議：

1. **固定 git 狀態**：正式執行時以 per-block 檢查（已實作）確保 60/60 `dirty=false`。
2. **處理 60 FPS 的架構開銷**：二選一：
   - (a) 量測並降低 ingestion 成本（例如確認是否為 GIL 競爭；把 ingestion callback 的工作減到最少；或改用 MultiThreadedExecutor 與 callback group 做比較）；
   - (b) 正式比較只使用 ρ 明確大於 1 的條件（S 20/30 FPS、XXS + artificial delay 30/80 ms、XXS ≥ 70 FPS），避開 ρ ≈ 1 的區間，並在報告中把 legacy vs 應用模式的 service 差異列為已知偏差。
3. **規模**：每個條件 ≥ 3（建議 5）個 60 s run，以 block 為單位做成對分析，並預先寫好主要指標（effective miss、on-time FPS、P99 latency）與判定規則，避免事後挑選指標。

## 附錄 D. 每個 pilot run（60 個；`pos` = 在 block 中的執行順序）

欄位定義同 §6。完整欄位見 `results/csv/ros2_phase3_pilot_runs.csv`。

| run_id | pos | ρ | Proc FPS | Drop % | Miss % | Eff miss % | P50 | P99 | Service | Policy drops (reasons) | DDS-unrecv | Tail | Shutdown | Decisions |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `mobilevit_s_10fps_legacy_q1_d0_p3b1_r1` | 1 | 0.59 | 10.00 | 0.0 | 0.0 | 0.0 | 59.6 | 64.7 | 58.8 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_s_10fps_legacy_q1_d0_p3b1_r2` | 5 | 0.59 | 10.00 | 0.0 | 0.0 | 0.0 | 60.1 | 65.0 | 59.5 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_s_10fps_legacy_q1_d0_p3b1_r3` | 4 | 0.59 | 10.00 | 0.0 | 0.0 | 0.0 | 59.1 | 62.6 | 58.6 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_s_10fps_legacy_q5_d0_p3b1_r1` | 2 | 0.60 | 10.00 | 0.0 | 0.0 | 0.0 | 60.9 | 65.2 | 60.3 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_s_10fps_legacy_q5_d0_p3b1_r2` | 1 | 0.59 | 10.00 | 0.0 | 0.0 | 0.0 | 59.9 | 63.6 | 59.2 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_s_10fps_legacy_q5_d0_p3b1_r3` | 5 | 0.60 | 10.00 | 0.0 | 0.0 | 0.0 | 60.5 | 65.1 | 60.0 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_s_10fps_fifo_c5_q10_d0_p3b1_r1` | 3 | 0.57 | 10.00 | 0.0 | 0.0 | 0.0 | 58.3 | 62.4 | 56.6 | 0 (-) | 0 | 0 | 0 | fifo:377 |
| `mobilevit_s_10fps_fifo_c5_q10_d0_p3b1_r2` | 2 | 0.57 | 10.00 | 0.0 | 0.0 | 0.0 | 58.4 | 62.4 | 56.7 | 0 (-) | 0 | 0 | 0 | fifo:376 |
| `mobilevit_s_10fps_fifo_c5_q10_d0_p3b1_r3` | 1 | 0.56 | 10.00 | 0.0 | 0.0 | 0.0 | 58.2 | 60.7 | 56.4 | 0 (-) | 0 | 0 | 0 | fifo:376 |
| `mobilevit_s_10fps_latest_q10_d0_p3b1_r1` | 4 | 0.57 | 10.00 | 0.0 | 0.0 | 0.0 | 58.4 | 61.8 | 56.8 | 0 (-) | 0 | 0 | 0 | latest:375 |
| `mobilevit_s_10fps_latest_q10_d0_p3b1_r2` | 3 | 0.57 | 10.00 | 0.0 | 0.0 | 0.0 | 58.3 | 61.0 | 56.7 | 0 (-) | 0 | 0 | 0 | latest:375 |
| `mobilevit_s_10fps_latest_q10_d0_p3b1_r3` | 2 | 0.57 | 10.00 | 0.0 | 0.0 | 0.0 | 58.3 | 61.7 | 57.1 | 0 (-) | 0 | 0 | 0 | latest:376 |
| `mobilevit_s_10fps_adaptive_c5_q10_d0_p3b1_r1` | 5 | 0.57 | 10.00 | 0.0 | 0.0 | 0.0 | 56.2 | 60.6 | 56.6 | 0 (-) | 0 | 0 | 0 | edf:374;no_estimate:1 |
| `mobilevit_s_10fps_adaptive_c5_q10_d0_p3b1_r2` | 4 | 0.56 | 10.00 | 0.0 | 0.0 | 0.0 | 55.9 | 60.6 | 56.1 | 0 (-) | 0 | 0 | 0 | edf:375;no_estimate:1 |
| `mobilevit_s_10fps_adaptive_c5_q10_d0_p3b1_r3` | 3 | 0.56 | 10.00 | 0.0 | 0.0 | 0.0 | 58.1 | 60.4 | 56.4 | 0 (-) | 0 | 0 | 0 | edf:375;no_estimate:1 |
| `mobilevit_s_20fps_legacy_q1_d0_p3b1_r1` | 5 | 1.18 | 16.83 | 15.8 | 19.1 | 31.9 | 84.3 | 110.4 | 58.9 | 0 (-) | 120 | 0 | 0 | - |
| `mobilevit_s_20fps_legacy_q1_d0_p3b1_r2` | 4 | 1.11 | 17.88 | 10.7 | 11.8 | 21.2 | 80.6 | 107.8 | 55.4 | 0 (-) | 81 | 0 | 0 | - |
| `mobilevit_s_20fps_legacy_q1_d0_p3b1_r3` | 3 | 1.20 | 16.56 | 17.3 | 21.5 | 35.0 | 84.9 | 111.1 | 59.9 | 0 (-) | 131 | 0 | 0 | - |
| `mobilevit_s_20fps_legacy_q5_d0_p3b1_r1` | 1 | 1.15 | 17.30 | 13.6 | 100.0 | 100.0 | 281.5 | 309.0 | 57.3 | 0 (-) | 100 | 4 | 0 | - |
| `mobilevit_s_20fps_legacy_q5_d0_p3b1_r2` | 5 | 1.20 | 16.59 | 17.2 | 100.0 | 100.0 | 284.3 | 310.6 | 59.7 | 0 (-) | 126 | 5 | 0 | - |
| `mobilevit_s_20fps_legacy_q5_d0_p3b1_r3` | 4 | 1.19 | 16.73 | 16.6 | 100.0 | 100.0 | 284.4 | 311.1 | 59.2 | 0 (-) | 121 | 5 | 0 | - |
| `mobilevit_s_20fps_fifo_c5_q10_d0_p3b1_r1` | 2 | 1.13 | 17.67 | 11.8 | 100.0 | 100.0 | 313.5 | 345.4 | 56.4 | 85 (queue_full_reject_newest:85) | 0 | 0 | 5 | fifo:671 |
| `mobilevit_s_20fps_fifo_c5_q10_d0_p3b1_r2` | 1 | 1.12 | 17.78 | 11.3 | 100.0 | 100.0 | 311.4 | 341.9 | 56.1 | 81 (queue_full_reject_newest:81) | 0 | 0 | 5 | fifo:674 |
| `mobilevit_s_20fps_fifo_c5_q10_d0_p3b1_r3` | 5 | 1.14 | 17.46 | 12.8 | 100.0 | 100.0 | 318.2 | 348.6 | 57.1 | 93 (queue_full_reject_newest:93) | 0 | 0 | 4 | fifo:663 |
| `mobilevit_s_20fps_latest_q10_d0_p3b1_r1` | 3 | 1.13 | 17.63 | 11.9 | 13.9 | 24.1 | 82.5 | 107.6 | 56.5 | 90 (superseded:90) | 0 | 0 | 0 | latest:669 |
| `mobilevit_s_20fps_latest_q10_d0_p3b1_r2` | 2 | 1.13 | 17.65 | 11.7 | 14.6 | 24.6 | 82.3 | 108.6 | 56.5 | 89 (superseded:89) | 0 | 0 | 0 | latest:671 |
| `mobilevit_s_20fps_latest_q10_d0_p3b1_r3` | 1 | 1.13 | 17.62 | 11.9 | 13.8 | 24.0 | 82.4 | 108.5 | 56.6 | 90 (superseded:90) | 0 | 0 | 0 | latest:669 |
| `mobilevit_s_20fps_adaptive_c5_q10_d0_p3b1_r1` | 4 | 1.13 | 17.29 | 13.7 | 0.2 | 13.8 | 76.0 | 98.5 | 56.7 | 104 (deadline_infeasible:104) | 0 | 0 | 0 | newest_feasible:655;no_estimate:1 |
| `mobilevit_s_20fps_adaptive_c5_q10_d0_p3b1_r2` | 3 | 1.14 | 17.26 | 13.8 | 0.2 | 13.9 | 75.7 | 99.0 | 56.8 | 105 (deadline_infeasible:105) | 0 | 0 | 0 | newest_feasible:654;no_estimate:1 |
| `mobilevit_s_20fps_adaptive_c5_q10_d0_p3b1_r3` | 2 | 1.14 | 17.27 | 13.8 | 0.5 | 14.2 | 75.6 | 99.0 | 56.7 | 104 (deadline_infeasible:104) | 0 | 0 | 1 | newest_feasible:654;no_estimate:1 |
| `mobilevit_xxs_20fps_legacy_q1_d0_p3b1_r1` | 4 | 0.35 | 20.00 | 0.0 | 0.0 | 0.0 | 18.2 | 19.4 | 17.6 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_xxs_20fps_legacy_q1_d0_p3b1_r2` | 3 | 0.34 | 20.00 | 0.0 | 0.0 | 0.0 | 17.3 | 19.2 | 17.0 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_xxs_20fps_legacy_q1_d0_p3b1_r3` | 2 | 0.34 | 20.00 | 0.0 | 0.0 | 0.0 | 17.5 | 19.7 | 17.1 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_xxs_20fps_legacy_q5_d0_p3b1_r1` | 5 | 0.33 | 20.00 | 0.0 | 0.0 | 0.0 | 17.1 | 19.0 | 16.7 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_xxs_20fps_legacy_q5_d0_p3b1_r2` | 4 | 0.35 | 20.00 | 0.0 | 0.0 | 0.0 | 18.1 | 19.8 | 17.5 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_xxs_20fps_legacy_q5_d0_p3b1_r3` | 3 | 0.35 | 20.00 | 0.0 | 0.0 | 0.0 | 18.3 | 19.6 | 17.6 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_xxs_20fps_fifo_c5_q10_d0_p3b1_r1` | 1 | 0.34 | 20.00 | 0.0 | 0.0 | 0.0 | 17.3 | 19.2 | 16.8 | 0 (-) | 0 | 0 | 0 | fifo:762 |
| `mobilevit_xxs_20fps_fifo_c5_q10_d0_p3b1_r2` | 5 | 0.34 | 20.00 | 0.0 | 0.0 | 0.0 | 17.4 | 19.4 | 16.9 | 0 (-) | 0 | 0 | 0 | fifo:762 |
| `mobilevit_xxs_20fps_fifo_c5_q10_d0_p3b1_r3` | 4 | 0.34 | 20.00 | 0.0 | 0.0 | 0.0 | 17.4 | 19.3 | 16.9 | 0 (-) | 0 | 0 | 0 | fifo:762 |
| `mobilevit_xxs_20fps_latest_q10_d0_p3b1_r1` | 2 | 0.34 | 20.00 | 0.1 | 0.0 | 0.1 | 17.4 | 19.3 | 16.8 | 0 (-) | 0 | 1 | 0 | latest:761 |
| `mobilevit_xxs_20fps_latest_q10_d0_p3b1_r2` | 1 | 0.34 | 20.00 | 0.0 | 0.0 | 0.0 | 17.3 | 19.1 | 16.8 | 0 (-) | 0 | 0 | 0 | latest:762 |
| `mobilevit_xxs_20fps_latest_q10_d0_p3b1_r3` | 5 | 0.34 | 20.00 | 0.0 | 0.0 | 0.0 | 17.4 | 19.2 | 16.9 | 0 (-) | 0 | 0 | 0 | latest:761 |
| `mobilevit_xxs_20fps_adaptive_c5_q10_d0_p3b1_r1` | 3 | 0.34 | 20.00 | 0.0 | 0.0 | 0.0 | 17.4 | 19.6 | 16.9 | 0 (-) | 0 | 0 | 0 | edf:760;no_estimate:1 |
| `mobilevit_xxs_20fps_adaptive_c5_q10_d0_p3b1_r2` | 2 | 0.34 | 20.00 | 0.0 | 0.0 | 0.0 | 17.4 | 19.5 | 16.9 | 0 (-) | 0 | 0 | 0 | edf:760;no_estimate:1 |
| `mobilevit_xxs_20fps_adaptive_c5_q10_d0_p3b1_r3` | 1 | 0.34 | 20.00 | 0.0 | 0.0 | 0.0 | 17.5 | 19.6 | 17.0 | 0 (-) | 0 | 0 | 0 | edf:760;no_estimate:1 |
| `mobilevit_xxs_60fps_legacy_q1_d0_p3b1_r1` | 3 | 0.94 | 60.00 | 0.0 | 0.0 | 0.0 | 16.3 | 21.9 | 15.6 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_xxs_60fps_legacy_q1_d0_p3b1_r2` | 2 | 0.94 | 60.00 | 0.0 | 0.0 | 0.0 | 16.6 | 21.3 | 15.7 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_xxs_60fps_legacy_q1_d0_p3b1_r3` | 1 | 1.02 | 56.99 | 5.0 | 0.0 | 5.0 | 25.8 | 34.5 | 17.1 | 0 (-) | 116 | 0 | 0 | - |
| `mobilevit_xxs_60fps_legacy_q5_d0_p3b1_r1` | 4 | 0.91 | 60.00 | 0.0 | 0.0 | 0.0 | 15.5 | 85.6 | 15.1 | 0 (-) | 1 | 0 | 0 | - |
| `mobilevit_xxs_60fps_legacy_q5_d0_p3b1_r2` | 3 | 0.94 | 60.02 | 0.0 | 0.0 | 0.0 | 16.3 | 46.2 | 15.6 | 0 (-) | 0 | 0 | 0 | - |
| `mobilevit_xxs_60fps_legacy_q5_d0_p3b1_r3` | 2 | 0.95 | 59.98 | 0.0 | 0.0 | 0.1 | 16.6 | 78.6 | 15.8 | 0 (-) | 1 | 0 | 0 | - |
| `mobilevit_xxs_60fps_fifo_c5_q10_d0_p3b1_r1` | 5 | 1.00 | 59.35 | 1.1 | 6.0 | 7.0 | 90.2 | 104.0 | 16.7 | 21 (queue_full_reject_newest:21) | 0 | 0 | 4 | fifo:2278 |
| `mobilevit_xxs_60fps_fifo_c5_q10_d0_p3b1_r2` | 4 | 1.00 | 59.26 | 1.3 | 6.2 | 7.4 | 91.8 | 103.0 | 16.7 | 24 (queue_full_reject_newest:24) | 0 | 0 | 5 | fifo:2273 |
| `mobilevit_xxs_60fps_fifo_c5_q10_d0_p3b1_r3` | 3 | 1.01 | 58.88 | 1.9 | 10.3 | 12.0 | 92.9 | 106.6 | 16.8 | 39 (queue_full_reject_newest:39) | 0 | 0 | 4 | fifo:2258 |
| `mobilevit_xxs_60fps_latest_q10_d0_p3b1_r1` | 1 | 1.00 | 59.24 | 1.3 | 0.0 | 1.3 | 25.6 | 34.2 | 16.7 | 29 (superseded:29) | 0 | 0 | 0 | latest:2275 |
| `mobilevit_xxs_60fps_latest_q10_d0_p3b1_r2` | 5 | 1.00 | 59.24 | 1.3 | 0.0 | 1.3 | 25.6 | 33.8 | 16.7 | 29 (superseded:29) | 0 | 0 | 0 | latest:2272 |
| `mobilevit_xxs_60fps_latest_q10_d0_p3b1_r3` | 4 | 1.01 | 58.92 | 1.8 | 0.0 | 1.8 | 25.9 | 34.0 | 16.8 | 41 (superseded:41) | 0 | 0 | 0 | latest:2262 |
| `mobilevit_xxs_60fps_adaptive_c5_q10_d0_p3b1_r1` | 2 | 1.00 | 59.14 | 1.4 | 0.0 | 1.4 | 24.6 | 35.1 | 16.7 | 33 (superseded:33) | 0 | 0 | 0 | edf:860;newest_feasible:1413;no_estimate:1 |
| `mobilevit_xxs_60fps_adaptive_c5_q10_d0_p3b1_r2` | 1 | 1.00 | 59.30 | 1.2 | 0.0 | 1.2 | 24.6 | 35.7 | 16.7 | 27 (superseded:27) | 0 | 1 | 0 | edf:1165;newest_feasible:1107;no_estimate:1 |
| `mobilevit_xxs_60fps_adaptive_c5_q10_d0_p3b1_r3` | 5 | 1.00 | 59.30 | 1.2 | 0.0 | 1.2 | 26.1 | 36.2 | 16.7 | 27 (superseded:27) | 0 | 0 | 1 | edf:1124;newest_feasible:1148;no_estimate:1 |
