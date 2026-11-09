# Correctness / Reproducibility Audit（P0 / P1 / P2）

- 日期：2026-11-09
- 基準：`main` @ `44c94d8`，另有未提交的 `src/eda_lite/plot_6lines.py`（新增 `os_aware_total_cost` 圖）
- 範圍：EDA-Lite（`src/eda_lite/`）、ROS 2 runtime 分析（`src/ros2_runtime/`）、ROS 2 pipeline 與實驗腳本（`src/ros2_uav_pipeline/`、`experiments/ros2/`、`scripts/`）、測試、依賴、README / AGENTS.md / `report/`
- 原則：本階段只做審查，**不修改既有程式邏輯**。唯一新增的程式是唯讀重現腳本 `scripts/audit_repro.py`。

## 0. 如何驗證本報告

```bash
python3 scripts/audit_repro.py            # 執行所有可自動重現的 case
python3 scripts/audit_repro.py P0-1 P1-1  # 只跑指定 case
# Batch 2 新增 case：P1-4S（EDA-Lite deadline 是否使用 effective latency 並記錄 deadline_ms）
```

每個 case 會印出 `REPRODUCED`（問題仍存在）或 `FIXED`（修正後不再出現），可直接當作修正的驗收工具。腳本只用標準函式庫與暫存目錄，不寫入 repo。標為「靜態審查」的項目只能讀程式碼確認，腳本無法重現（需要 ROS 2 環境）。

審查當下的基準狀態：

| 檢查 | 結果 |
|---|---|
| `python3 -m unittest discover -s tests` | 23/23 通過（Python 3.11.4） |
| `bash -n` 全部 `.sh` | 全部通過 |
| `python3 scripts/check_runtime_provenance.py` | **exit 1**：缺 raw CSV 與 `ros2_runtime_summary.csv` |
| `python3 scripts/audit_repro.py` | **9/9 REPRODUCED** |
| 重新產生 `eda_lite_mobilevit_profile_sweep.csv` | 與已追蹤檔案 byte-identical（simulation 端可重現） |

## 1. 摘要

| ID | 等級 | 主題 | 一句話 | 重現 |
|---|---|---|---|---|
| P0-1 | P0 | DP objective | DP 最小化的是 per-subgraph 加總 surrogate，不是報告中的 `os_aware_total_cost`（**Batch 2 已修正**） | `P0-1` |
| P0-2 | P0 | ROS 2 CSV 混用 | detector 以 append 寫入、`frame_id` 每次從 0 起算，重跑會讓掉幀率從 49.5% 變 0%（**PR-A1 已修正**） | `P0-2` |
| P0-3 | P0 | Provenance | 主流程吃的 22 個 `measured_*` profiles 無法從 repo 重建；已追蹤 runtime-aware CSV 已過期 | `P0-3` |
| P1-1 | P1 | Greedy 剪枝 | SRAM 可行性非單調，greedy 第一次不可行就停，會漏掉更長融合，甚至誤報不可行（**Batch 2 已修正**） | `P1-1` |
| P1-2 | P1 | Sweep 健壯性 | 任一 scheduler 不可行就整個 sweep 中止，SRAM 無法往下掃（**Batch 2 已修正**） | `P1-2` |
| P1-3 | P1 | OS-aware 鑑別力 | deadline 項恆為 0、22 個 OS profiles 從未改變任何排程、DP 與 greedy 88/88 相同（**Batch 2 已修正語意：`pure`、平手標示、profile 參數化；「不改變排程」是資料事實，已記錄**） | `P1-3` |
| P1-4 | P1 | Deadline 一致性 | ROS 2 用 100 ms、EDA-Lite 用 33.3 ms；dropped rows 會算進 miss 數但分母只算 processed（**Batch 1 修正 runtime 端；Batch 2 修正 EDA-Lite 端**） | `P1-4`、`P1-4S` + 靜態 |
| P1-5 | P1 | frame_id 掉幀推估 | 開頭/結尾掉幀看不到、explicit drop 會關掉 gap 推估、group key 未正規化（甚至 TypeError）（**Batch 1 已修正**） | `P1-5` |
| P1-6 | P1 | 時間戳記語意 | `inference_ms` 含假延遲、混用時鐘、warm-up 未剔除、`received_at_ns` 未使用（**Batch 1 已修正**） | `P1-6` |
| P1-7 | P1 | OS profile 正規化 | latency/memory baseline 跨模型取全域 min/max，S 模型 idle 也有 3.4× multiplier | `P1-7` |
| P1-8 | P1 | 實驗條件可追溯 | 資源限制 fallback 仍標 `normal`、tuned 只改 `rmem_max`、檔名沒有 run id | 靜態 |
| P2-1 | P2 | CI | 沒有任何 CI | 靜態 |
| P2-2 | P2 | 依賴 | `requirements.txt` 未鎖版本、Python 版本不一致、ROS 依賴不在清單 | 靜態 |
| P2-3 | P2 | Repo 衛生 | 18 個 `__pycache__`/`.DS_Store` 被追蹤；`*.csv` 被 ignore 但仍有 11 個 CSV 被追蹤 | 靜態 |
| P2-4 | P2 | 文件落差 | README / AGENTS.md / final_report 彼此矛盾，「Pure」標籤不實 | 靜態 |
| P2-5 | P2 | 測試缺口 | 沒有 DP oracle、greedy 非單調、CSV 混用等測試；測試依賴不可重建的 artifact | 靜態 |
| P2-6 | P2 | 其他 pipeline 細節 | model fallback 改名、`model_path` 未使用、QoS 只改 subscriber depth、profile chain 未驗證 | 靜態 |

建議修正順序見第 5 節。

---

## 2. P0：會讓結果錯誤或無法重現

### P0-1 DP objective 與 reported `os_aware_total_cost` 不一致

> **狀態：已於 Phase 1 / Batch 2 修正**（見 `report/PHASE1_BATCH2_RESULT.md`）。`dp` 改為以 Pareto label DP 精確最小化整個 schedule 的 `os_aware_cost`；新增 `exhaustive_schedule` oracle（n ≤ 20）。單元測試：600 個隨機小模型 + MobileViT profiles，`dp` 與 oracle 的 partition 與成本完全一致。`python3 scripts/audit_repro.py P0-1` 顯示 `FIXED`。

**檔案**
- `src/eda_lite/schedulers.py:79-94`：`dp[end] = dp[start] + subgraph_objective_cost(candidate)`，即每個 subgraph 各自算完整 OS-aware cost 再加總。
- `src/eda_lite/cost_model.py:284-302`：`subgraph_objective_cost` 對單一 subgraph 呼叫 `os_aware_cost`。
- `src/eda_lite/cost_model.py:183-220`、`259-281`：reported cost 對**整個 schedule**算一次：`peak_sram_kb = max(...)`、`deadline_excess = max(0, Σlatency − deadline)`。

**問題**
`os_aware_cost` 有兩項不可加總，所以 DP 最佳化的目標與報告的成本不是同一個函數：

| 項 | DP 看到的（per-subgraph 加總） | 報告的（整個 schedule） |
|---|---|---|
| memory pressure | `γ·p·Σ_i peak_i / SRAM` | `γ·p·max_i peak_i / SRAM` |
| deadline | `β·r·Σ_i max(0, L_i − D)` | `β·r·max(0, Σ_i L_i − D)` |
| energy、latency、drop | 線性，可加總 | 一致 |

結果：(a) memory 項在 DP 中變成「每多一個 subgraph 就罰一次」，系統性偏向融合；(b) 每個 subgraph 的 latency 幾乎都低於 deadline，所以 DP 對 deadline 項是盲的。`final_report.md:75` 寫的「`dp`：找最低 OS-aware cost 的 contiguous partition」一般而言不成立。

**重現**（`python3 scripts/audit_repro.py P0-1`）
- repo 設定（2 模型 × 4 SRAM × 25 OS profiles = 200 cases）：surrogate 與 reported cost 最大差 **295.3**。對 200 個 case 窮舉所有 partition 比較後，DP 目前恰好都是最佳解，所以這是**潛伏性**錯誤：目前數字沒錯，但只要換 profile 或 config 就可能出錯。
- 兩層 toy model（`deadline_ms=5`，`deadline_miss_rate=1`）：DP reported cost **186.28** > greedy **162.24**，DP 輸給 greedy。

**最小修改建議**（不需要重構）
1. 新增 `exhaustive_schedule()` 當 oracle：直接以 `estimate_schedule_metrics(...).os_aware_total_cost` 為目標，窮舉 `2^(n−1)` 個 contiguous partitions。MobileViT 只有 7/9 層（64/256 個 partition），成本可忽略；`n ≤ 20` 時 `dp` 可直接委派給它。
2. 若要保留多項式時間的 DP：外層列舉 peak cap `P`（所有可行候選的 peak 值）；內層只允許 `peak ≤ P` 的候選，對每個 prefix 保留 `(additive_cost, Σlatency)` 的 Pareto front；最後再加 `β·r·hinge(Σlatency − D) + γ·p·P/SRAM`。
3. 不建議反過來把 reported cost 改成 per-subgraph 加總，因為「subgraph 越多 memory pressure 越大」在語意上說不通。

**驗收**：`P0-1` 顯示 `FIXED`；新增 unit test，用固定 seed 的小型 profiles 驗證 `cost(dp) == cost(exhaustive)`。

---

### P0-2 ROS 2 實驗 CSV 混用：append 寫入 + `frame_id` 重新起算

> **狀態：已於 PR-A1 修正**（branch `fix/pr-a1-ros2-data-integrity`，見 `report/PHASE1_PR_A1_RESULT.md`）。`python3 scripts/audit_repro.py P0-2` 顯示 `FIXED`。

**檔案**
- `src/ros2_uav_pipeline/mobilevit_uav_pipeline/mobilevit_detector_node.py:72-80`：只有檔案不存在才寫 header；`123-129` 一律 `open(..., 'a')`。
- `src/ros2_uav_pipeline/mobilevit_uav_pipeline/image_stream_node.py:40`：`seq_id` 每次啟動都從 0 開始。
- `experiments/ros2/run_*_sweep.sh:47`：檔名只有 `scenario/model/fps/qos/delay`，沒有 `resource_profile`、時間或 run id。
- `src/ros2_runtime/analyze_runtime.py:20-27`（group key 沒有 run id）、`307-318`（`sorted({...})` 用 set 去重）、`321-331`（目錄下所有 `*.csv` 全部合併）。

**問題**
同一組設定重跑（失敗重試，或 `run_baseline_experiments.sh` 執行兩次）會把第二次的資料 append 進同一個檔案。analyzer 依 group key 合併，`frame_id` 重疊的部分被 set 去重，因此：
- 掉幀被「補洞」抹掉；
- `processed_frames` 加倍，latency/P95/jitter 混入兩次 run；
- `run_os_tuned_experiments.sh` 會寫入**同一批檔名**，只靠 `resource_profile` 欄位分組，檔案層級無法分辨。

**重現**（`python3 scripts/audit_repro.py P0-2`）
- run1 單獨：processed=50、dropped=49、drop_rate=**49.49%**
- run1 + run2 append：processed=150、dropped=0、drop_rate=**0%**

**最小修改建議**
1. Detector：每次 run 用 `'w'` 開檔，或檔案已存在就直接失敗；新增 `run_id`（啟動時間或 uuid）與 `deadline_ms` 欄位。
2. 腳本：`output_csv` 加上 `${RESOURCE_PROFILE}` 與 `$(date +%Y%m%dT%H%M%S)`（或 `RUN_ID`）。
3. Analyzer：`run_id` 存在時加入 group key；同一 group 內出現重複 `frame_id` 就 `raise ValueError`，不要靜默去重。

**驗收**：`P0-2` 顯示 `FIXED`（analyzer 拒絕或分開統計）；新增「append 兩次 run」的 unit test。

---

### P0-3 主流程的 runtime-derived 輸入無法重建；已追蹤結果已過期

**檔案**
- `experiments/eda_lite/mobilevit_runtime_aware_sweep.json:4`：`"os_profile_file": "runtime_os_profiles.json"`（22 個 `measured_*`）。
- `results/raw/ros2/` 只有 `.gitkeep`；`results/csv/ros2_runtime_summary.csv` 不存在。
- `results/csv/eda_lite_mobilevit_runtime_aware_sweep.csv`（已追蹤，commit `c5bea14`）。
- `tests/test_eda_lite.py:279-292`：測試**要求**所有 profile 名稱都以 `measured_` 開頭。

**問題**
1. `scripts/rebuild_eda_lite_figures.sh` 與六線圖使用的 OS profiles 沒有 raw CSV，也沒有 summary 可以重建；`check_runtime_provenance.py` 回傳 exit 1，但沒有任何流程會因此停止或標示。
2. 已追蹤的 runtime-aware CSV 只有 24 列，用的是 example profiles（`runtime_normal_20fps_q5_d0` 等）；目前 config 重跑會得到 264 列、22 個 `measured_*` profiles。repo 內的結果檔與 config 不一致。
3. `.gitignore` 忽略 `*.csv`，所以 `rebuild_eda_lite_figures.sh` 產生的 `*_pure.csv` / `*_runtime_aware_sweep.csv` 沒有被追蹤；但由它們畫出的 SVG 有被追蹤（或待追蹤），圖的來源資料不在版本庫中。

**重現**（`python3 scripts/audit_repro.py P0-3`）：會印出 provenance 檢查結果，以及已追蹤 CSV 與重新產生結果的 profile 集合差異。

**最小修改建議**
1. 把 raw CSV（或至少 `ros2_runtime_summary.csv`）放回 repo 或 release artifact，並附 `MANIFEST.sha256`（raw → summary → profiles JSON 的雜湊鏈）。
2. 在補齊前：讓 `rebuild_eda_lite_figures.sh` 先跑 `check_runtime_provenance.py`，失敗時在輸出檔名或圖標題加上 `UNVERIFIED`；或把 sweep config 指回 `runtime_os_profiles.example.json`。
3. 重新產生或刪除過期的 `results/csv/eda_lite_mobilevit_runtime_aware_sweep.csv`；把 `*_pure.csv` / `*_runtime_aware_sweep.csv` 加入追蹤（或改為不追蹤 SVG），讓「圖」與「資料」的追蹤策略一致。
4. 測試改用 `runtime_os_profiles.example.json` 或 fixture，不要依賴無法重建的 artifact。

**驗收**：`check_runtime_provenance.py` exit 0；`P0-3` 顯示 `FIXED`。

---

## 3. P1：影響結論效度或健壯性

### P1-1 Greedy 在非單調 SRAM 可行性上提早剪枝

> **狀態：已於 Phase 1 / Batch 2 修正**（見 `report/PHASE1_BATCH2_RESULT.md`）。只在 non-fusible layer 停止掃描，記錄最後一個 SRAM 可行的 end；兩組 toy 資料已加為 unit test。`P1-1` 顯示 `FIXED`。

**檔案**：`src/eda_lite/schedulers.py:40-62`（`52-57` 的 `break`），`cost_model.py:223-243`。

**問題**：`SRAM(l..k) = in_l + out_k + max(out_l..out_{k−1}) + min(max w, tile)`。往後多接一層時，原本的 `out_k` 會從「final output」變成「intermediate」；如果下一層輸出很小，整體 SRAM 反而會**下降**。可行性對結束位置不是單調的，所以「第一次不可行就 break」並不等於 docstring 寫的 “longest feasible contiguous region”。更糟的是，greedy 可能把一個單獨不可行的層切出來，然後在 `_assert_schedule_fits` 誤報整個模型不可行。

只有 `fusible=False` 造成的中斷才是單調的，可以安全地 break。

**重現**（`P1-1`）
- `SRAM(l0)=111, SRAM(l0+l1)=261, SRAM(l0+l1+l2)=171`；SRAM=255 時 greedy 得到 `l0 | l1 | l2`，DP 得到 `l0+l1+l2`。
- 另一組資料在 SRAM=200 時 greedy 拋出 `Subgraph 'l1' requires 301KB`，但 DP 能找到可行的 `l0+l1+l2`。
- 目前 MobileViT profiles 不會觸發，因為 attention block 是 non-fusible，融合鏈最長只有 3 層。

**最小修改**：只在遇到 non-fusible 層時 `break`；SRAM 不可行時 `continue` 掃到 fusible 區段結尾，記錄最後一個可行的 `end`。若要保留舊行為，就把 docstring 改成 “stop at first infeasible extension”，並把它命名為 `greedy_first_fit`。
**驗收**：`P1-1` 顯示 `FIXED`；把 toy 兩組資料加為 unit test。

### P1-2 單一 scheduler 不可行就中止整個 sweep

> **狀態：已於 Phase 1 / Batch 2 修正**（見 `report/PHASE1_BATCH2_RESULT.md`）。不可行時拋出 `InfeasibleScheduleError`，sweep 輸出 `feasible=false`、數值欄位留空並附 `infeasible_reason`；設定錯誤（未知 profile/scheduler）仍會中止。Analyzer 排除不可行列，baseline 缺少或不可行時以 `baseline_status` 標示、reduction 留空。`P1-2` 顯示 `FIXED`。

**檔案**：`src/eda_lite/run_simulation.py:74-107`（沒有 per-row 例外處理），`schedulers.py:133-144`。

**問題**：`layerwise` 在小 SRAM 下不可行是合理結果，但目前會丟出 `ValueError`，整個 sweep 不輸出任何列。這使得 SRAM 無法掃到 256 KB 以下，而 P1-3 顯示 256 KB 以上幾乎沒有鑑別力。

**重現**（`P1-2`）：MobileViT-S、`sram_kb=[128,256]` → `Subgraph 'stem_conv' requires 168KB SRAM, above limit 128KB.`

**最小修改**：在 `_run_scheduler` 呼叫外包一層 `try/except ValueError`，輸出 `feasible=false` 的列，數值欄位留空；CSV 新增 `feasible` 欄，`analyze_results` 排除不可行列。

### P1-3 OS-aware 項在現有設定下沒有任何決策影響

> **狀態：Phase 1 / Batch 2 已處理**（見 `report/PHASE1_BATCH2_RESULT.md`）。新增內建 `pure` profile（multiplier 1.0、其餘 0）；summary 以 `greedy=dp` 標示平手並新增 `num_tied_schedulers`、`tied_same_partition`；`plot_6lines` 的 profile 改由 CLI / 腳本環境變數指定；新增 `mobilevit_sensitivity_sweep.json`（SRAM 128–2048 KB × deadline 5–100）。修正 deadline 後，deadline 項在部分 profile 下不再是 0，但在 MobileViT coarse profiles 上 OS profiles 與 deadline 仍**不改變任何排程**：fusion 同時降低 energy、latency 與 deadline 項，只有 SRAM 可行性會改變決策，memory 項需把 `gamma` 放大約 50–130 倍才會翻轉。這是資料與成本模型的事實，未為了製造差異而調整設定。`P1-3` 改為檢查上述語意修正，並照實印出這些事實；顯示 `FIXED`。

**檔案**：`experiments/eda_lite/mobilevit_*.json`（`deadline_ms: 33.3`、`sram_kb ≥ 256`）、`data/model_profiles/mobilevit_*_simplified.json`、`src/eda_lite/analyze_results.py:116`、`src/eda_lite/plot_6lines.py:100,120,127`。

**問題（實驗設計，不是程式錯誤）**
1. **Deadline 項永遠是 0**：simulated latency 最大只有 31.93 ms（S、layerwise）< 33.3 ms，所以 `β=0` 時所有 cost 完全相同。ROS 2 量到的 `deadline_miss_rate`（最高 1.0）對 EDA-Lite 沒有任何影響。
2. **OS profiles 從未改變排程**：在每個 SRAM 下，22 個 measured profiles 的 DP partition 都只有 1 種；runtime-aware 只是在 reported cost 上加一個偏移量。
3. **Scheduler 比較沒有鑑別力**：DP 與 greedy 的 partition 在 88/88 個 runtime-aware groups、24/24 個 profile-sweep groups 中完全相同。`final_report.md:158-178` 的 `best_scheduler = greedy` 其實是 `min()` 遇到平手時取第一個（CSV 順序是 layerwise→greedy→dp）的結果。
4. **SRAM sweep 退化**：XXS 所有可融合候選的 peak 最大只有 192 KB，所以 256–2048 KB 完全相同；S 最大 268 KB，只有 256 KB 與其他值不同（這就是報告提到的「512 KB 後 plateau」）。
5. **“Pure” 並不 pure**：`plot_6lines.py:100` 用 `normal` profile 當 “Pure”，但 `normal` 仍有 `deadline_miss_rate=0.02, memory_pressure=0.2`，而且 DP 也是在這組懲罰下最佳化的。README 步驟 4 的「Pure（無 OS 懲罰）」因此不正確。六線圖用的 `d150` profile 是寫死的。

**重現**（`P1-3`）。

**最小修改**
- 在 summary 中明確標出平手（例如 `best_scheduler = "greedy=dp"`），或加入固定的 tie-break 規則與 `tie_count` 欄位。
- 新增 `pure` profile（四個參數全為 0），並以 CLI 參數取代寫死的 profile。
- 在報告中說明 deadline 項目前沒有作用；若要讓它有作用，請把 deadline 改成與 simulated latency 同一單位（見 P1-4），或改用 normalized latency。
- 修好 P1-2 之後，把 SRAM sweep 擴到 `64/128/192 KB`。

### P1-4 Deadline / QoS 語意在各層之間不一致

> **狀態：runtime 端已於 Phase 1 / Batch 1 修正**（第 3、4 點與 CSV 的 `deadline_ms`；見 `report/PHASE1_BATCH1_RESULT.md`，`python3 scripts/audit_repro.py P1-4` 顯示 `FIXED`）。**EDA-Lite 端（第 1、2 點）已於 Batch 2 修正**（見 `report/PHASE1_BATCH2_RESULT.md`）：deadline 項改用 effective latency `latency_multiplier × L`；每列記錄 `deadline_ms`；文件明確定義 simulation deadline（simulated latency 單位）與 ROS 2 deadline（wall-clock）不同，兩者只透過 `deadline_miss_rate` 與 `latency_multiplier` 連結，不做數值換算；可用 top-level `deadline_ms` 清單做 sweep。`P1-4S` 顯示 `FIXED`。第 5 點（QoS 文件）仍待處理。

**檔案**：`mobilevit_detector_node.py:23,118`（預設 100 ms、`>`）、`experiments/ros2/run_*_sweep.sh:13`（100）、`experiments/eda_lite/mobilevit_*.json`（33.3）、`cost_model.py:270-272`、`analyze_runtime.py:137,154-156,286-288`。

**問題**
1. ROS 2 的 deadline 是 100 ms（實測 wall-clock latency），EDA-Lite 是 33.3 ms（simulated latency，單位不同）。兩者都和 frame period（`1000/fps`）無關；但 FPS sweep 從 5 掃到 30 FPS，deadline 卻固定不變。
2. `latency_multiplier` 只作用在 `latency_cost`；deadline 判斷用的是**未放大**的 latency（`cost_model.py:271`），所以 high-latency profile 不會造成更多 deadline miss。
3. CSV 沒有記錄 `deadline_ms`，analyzer 無法用統一門檻重新推算 miss；README 的 logger contract 也沒列出這個欄位，但 analyzer 的推算邏輯依賴它。
4. `deadline_misses` 會把 dropped rows 一起算進去，分母卻只有 `processed_count`。重現（`P1-4`）：2 個準時處理的 frame + 2 個 dropped(miss=1) → **100%** miss rate。
5. QoS sweep 只改 subscriber 的 KEEP_LAST depth（BEST_EFFORT）；publisher 固定 RELIABLE / depth 10（`image_stream_node.py:25`），文件沒有說明。

**最小修改**：CSV 加入 `deadline_ms` 欄位；`deadline_misses` 只計算 processed rows（dropped 另計 `deadline_miss_or_drop`）；`deadline_cost` 改用 `estimated_latency_ms * latency_multiplier`；在 config 中明確定義 `deadline_policy`（`fixed` 或 `frame_period`）。

### P1-5 `frame_id` 掉幀推估的邊界情況

> **狀態：已於 Phase 1 / Batch 1 修正**（見 `report/PHASE1_BATCH1_RESULT.md`）。`python3 scripts/audit_repro.py P1-5` 顯示 `FIXED`。

**檔案**：`src/ros2_runtime/analyze_runtime.py:116-120,134-136,149,307-318`。

**問題與重現**（`P1-5`）
1. **開頭/結尾掉幀看不到**：gap 推估從第一個收到的 id 開始。detector 要先載入 timm 模型（需要數秒），publisher 卻早已開始發布，所以啟動期間的掉幀與 timeout 前的尾端都不會被計入。重現：0..39 從未收到 → dropped=0。
2. **只要有一筆 explicit drop，整組 gap 推估就關閉**（`inferred = 0 if explicit_drops else ...`）。重現：frame 2..9 缺失，只算到 1 筆 drop。
3. **Group key 是原始字串**：`"20"` 與 `"20.0"` 會被分成兩組（node 寫的是 float `20.0`，手動 CSV 常寫 `20`）。
4. **`sort_key` 混用 float 與 str**：某個檔案缺 `input_fps` 欄位時（預設值 `"unknown"`）→ `TypeError`，整個分析中止。
5. `total_rows` 實際上是 `processed + dropped`，不是 CSV 列數；沒有 latency 且未標記 dropped 的列會被靜默丟棄。

**最小修改**：用 publisher 的 `seq_id` 範圍（`first_published=0`，`last_published = published count − 1`）做邊界，或由 publisher 另寫一份 publish log；explicit 與 gap 推估改成「取聯集」；group key 的數值欄位先 `float()` 正規化再格式化；`sort_key` 改成 `(is_numeric, value)` tuple；把 `total_rows` 改名為 `total_frames`，並新增真正的 `csv_rows` 與 `discarded_rows`。

### P1-6 時間戳記與量測語意（靜態審查）

> **狀態：已於 Phase 1 / Batch 1 修正**（見 `report/PHASE1_BATCH1_RESULT.md`）。`python3 scripts/audit_repro.py P1-6` 顯示 `FIXED`。

**檔案**：`mobilevit_detector_node.py:83-121`、`image_stream_node.py:62-66`。

1. `inference_ms` 從 `time.sleep(fake_delay)` 之前開始計時，所以 overload sweep 的 `avg_inference_ms` 含注入的假延遲，名稱與語意不符。
2. 混用兩種時鐘：latency 用 ROS clock（`get_clock().now()`），inference 用 `time.time_ns()`（wall clock，非 monotonic，NTP 調整時會跳）。若啟用 `use_sim_time`，`published_at_ns` 與 `completed_at_ns` 會變成 sim time。建議 inference 改用 `time.perf_counter_ns()`，latency 明確使用 `SYSTEM_TIME`。
3. 有記錄 `received_at_ns`，但 analyzer 從未使用。latency 混合了 DDS 傳輸 + 排隊 + cv_bridge/resize 前處理 + 推論，無法分解。建議輸出 `queue_ms = received − published`、`preprocess_ms`、`compute_ms`。
4. 沒有 warm-up 剔除：第一個推論包含 torch lazy init，會拉高 P99/jitter。建議加 `warmup_frames` 參數，在 analyzer 端剔除。
5. `psutil.Process.cpu_percent()` 第一次呼叫固定回傳 0.0；多核時可能 > 100%，但沒有正規化說明。
6. 沒有記錄 publisher 實際達成的 FPS，只記錄目標 `input_fps`。

### P1-7 OS profile 正規化跨模型混用

**檔案**：`src/ros2_runtime/build_os_profiles.py:48-57`。

**問題**：`baseline = min(avg_latency)`、`memory_reference = max(avg_memory)` 都是跨**所有模型、所有情境**取值。因此：
- MobileViT-S 在 idle（5 fps、d0）時 `latency_multiplier ≈ 3.3`，這只反映「S 比 XXS 慢」，不是 OS pressure；
- 22 個 profiles 的 `memory_pressure` 全部落在 0.934–1.0（RSS 主要被 torch 佔用），幾乎沒有鑑別力；
- XXS 的 runtime-aware sweep 也會跑到 11 個由 S 模型產生的 profiles。

**重現**（`P1-7`）：兩個 idle 情境 → XXS multiplier=1.0，S=3.0、memory=1.0；同時印出已追蹤 JSON 的 memory 範圍。

**最小修改**：依 `model_name` 分組，各自用該模型的 idle 情境（例如 `fps_sweep` 最低 FPS、d0）當 baseline；memory pressure 改用 `avg_memory_mb / MemoryMax`（cgroup 上限，例如 2048 MB）這種絕對參考；把使用的 baseline 與 reference 寫進 JSON 的 `metadata`；runtime-aware sweep 只載入同一模型的 profiles。

### P1-8 實驗條件可追溯性（靜態審查）

**檔案**：`scripts/run_baseline_experiments.sh:16-26`、`scripts/run_os_tuned_experiments.sh:13-17,21`、`src/ros2_uav_pipeline/launch/mobilevit_uav_pipeline.launch.py`。

1. 找不到 `taskset/systemd-run` 時，fallback 會在沒有資源限制的情況下執行，但 CSV 仍標 `resource_profile=normal`，與真正受限的 run 無法區分。
2. `systemd-run --user --scope -p MemoryMax=2G` 需要 cgroup v2 memory controller delegation，否則限制可能不生效；腳本沒有驗證，也沒有記錄。
3. 「tuned」只改 `net.core.rmem_max`，沒有改 `rmem_default`，DDS 也不一定會請求更大的 buffer。同機的 Fast DDS（Humble 預設）可能走 shared memory transport，這時 UDP buffer 根本無關。目前沒有記錄 `RMW_IMPLEMENTATION` 或 transport，也沒有驗證調整是否有效。
4. 沒有 run-level metadata（git commit、host、kernel、CPU model、torch/timm 版本、RMW、實際 cgroup 限制）。

**最小修改**：每次 run 寫一份 `<csv>.meta.json`（上述欄位 + 實際偵測到的限制）；fallback 時把 `RESOURCE_PROFILE` 改成 `unconstrained`；tuned 腳本同時記錄 `sysctl net.core.rmem_*` 與 `RMW_IMPLEMENTATION`。

---

## 4. P2：工程品質、文件與維護

### P2-1 沒有 CI
沒有 `.github/workflows` 或其他 CI 設定，測試只靠手動執行。**最小修改**：加一個 GitHub Actions workflow：Python 3.10 / 3.11 跑 `python3 -m unittest discover -s tests`、`bash -n experiments/ros2/*.sh scripts/*.sh`、`python3 scripts/audit_repro.py`（修好之後可改成斷言 `FIXED`）。ROS 2 部分先不放進 CI。

### P2-2 依賴與環境
- `requirements.txt` 完全沒鎖版本（`torch`、`timm`、`opencv-python`、`psutil`、`numpy<2.0.0`），推論延遲會隨版本改變。
- `rclpy`、`cv_bridge`、`sensor_msgs` 來自 RoboStack，不在任何清單中；`setup_env.sh` 另外裝了不需要的 `pandas`、`matplotlib`。
- Python 版本不一致：`.venv` 是 3.13.7、系統是 3.11.4、RoboStack 環境是 3.10。
- README「核心 simulator 只使用標準函式庫」在 simulator 範圍內是對的，但沒說明 ROS 節點需要 `requirements.txt`。

**最小修改**：拆成 `requirements-sim.txt`（空，只用 stdlib）與 `requirements-ros2.txt`（鎖定版本）；新增 `environment.yml`（RoboStack channel + `ros-humble-*` 版本）；在 README 寫明支援的 Python 版本。

### P2-3 Repo 衛生
- `git ls-files` 中有 18 個 `__pycache__/*.pyc` 與 `.DS_Store`，雖然 `.gitignore` 已列出，但它們在加入規則前就已被追蹤。
- `.gitignore` 忽略 `*.csv`，但 `results/csv/` 仍有 11 個 CSV 被追蹤（強制加入），其中至少一個已過期（P0-3）。
- 未追蹤的 `~$os-aware-eda-lite-final-presentation.pptx` 是 Office 鎖定檔。

**最小修改**：`git rm --cached` 移除 pyc 與 `.DS_Store`；明確決定 results 的追蹤策略（例如追蹤 `results/csv/*.csv`，並在 `.gitignore` 用 `!results/csv/*.csv` 例外）；忽略 `~$*`。

### P2-4 README / AGENTS.md / report 落差

| 位置 | 內容 | 實際情況 |
|---|---|---|
| AGENTS.md:164, 343 | ROS 2 pipeline 在外部、沒有 vendored | `src/ros2_uav_pipeline/` 已在 repo |
| AGENTS.md:347 | Final report 尚未存在 | `report/final_report.md` 已存在 |
| AGENTS.md:113 / README:319 | runtime-aware sweep 預設用 example profiles | config 指向 `runtime_os_profiles.json`（measured_*）；README:320 又寫相反的內容 |
| README:98-147 | 版面配置以 `OS_Final/` 為根目錄 | 缺 `scripts/`、`plot_6lines.py`、`ros2_uav_pipeline/`、`report/runtime_result_provenance.md` |
| README 步驟 4 | 「Pure（無 OS 懲罰）」 | 實際用 `normal` profile（有懲罰），見 P1-3 |
| README logger contract | 沒有 `deadline_ms` | analyzer 的 deadline 推算依賴這個欄位 |
| final_report.md:122 vs :298 / :305 | 「含 22 個 measured profiles」vs「尚無 measured CSV」「之後再把 example 換成 measured」 | 同一份報告前後矛盾 |
| AGENTS.md「Run Tests」/ CI | 只寫手動測試 | 沒有 CI（P2-1） |

**最小修改**：以本報告為準更新 AGENTS.md 的 “Current Implemented State” 與 “Still not implemented”；README 版面配置改成實際 `tree` 結果；final_report 統一 provenance 的說法。

### P2-5 測試缺口
現有 23 個測試全部通過，但沒有涵蓋本報告的任何一個缺陷：
- 沒有 DP 對 exhaustive oracle 的測試；`test_dp_cost_is_not_worse_than_layerwise`（`tests/test_eda_lite.py:61`）只比 layerwise，P0-1 的 toy 例子也能通過它。
- 沒有 greedy 非單調、sweep 遇不可行列、平手 tie-break 的測試。
- 沒有 append run / 重複 frame_id / 開頭掉幀 / 混合型別 group key 的測試。
- `plot_6lines.py`、`check_runtime_provenance.py`、`build_os_profiles` 的 CLI 預設正規化都沒有測試。
- `tests/test_eda_lite.py:279-292` 依賴無法重建的 `runtime_os_profiles.json`（P0-3）。

**最小修改**：把 `scripts/audit_repro.py` 的每個 case 轉成對應的 unit test（修正前標 `expectedFailure`，修正後移除）。

### P2-6 其他 pipeline 細節（靜態審查）
- `mobilevit_detector_node.py:58-63`：模型載入失敗時會靜默改用 `mobilevit_xxs`，CSV 檔名仍是 `..._mobilevit_s_...`，但列內容是 xxs。應該直接失敗，不要 fallback。
- launch 檔有宣告 `model_path`，但從未傳給任何 node；`pretrained=False` 是隨機權重（對延遲量測可接受，但應寫在報告裡）。
- `model_loader.py` 沒有驗證 `layers[i].output_kb == layers[i+1].input_kb`（目前兩個 MobileViT profiles 都一致，但新增 profile 時沒有保護）。
- `check_runtime_provenance.py` 只檢查檔案是否存在，沒有檢查 summary → profiles 是否一致（profile 數量、名稱、雜湊）。
- `_percentile` 用 nearest-rank 方法，`jitter_ms` 是 latency 的母體標準差（不是 inter-arrival jitter），應在報告中定義清楚。

---

## 5. 建議修正順序（每項都是小型 PR）

1. **PR-A（P0-2 + P1-5 + P1-4 的資料面）**：detector 改 `'w'`、加 `run_id`/`deadline_ms` 欄位、檔名加 resource_profile + timestamp；analyzer 偵測重複 frame_id、正規化 group key、修正 deadline 分母、explicit/gap 取聯集。附 unit tests。
2. **PR-B（P0-1）**：新增 `exhaustive_schedule` oracle + 測試；DP 改為 peak-cap + Pareto（或在 n≤20 時委派給 exhaustive）。
3. **PR-C（P1-1 + P1-2）**：greedy 只在 non-fusible 時 break；sweep 輸出 `feasible` 欄位。
4. **PR-D（P0-3 + P1-7）**：補回 raw CSV/summary + manifest；`build_os_profiles` 依模型正規化並寫入 metadata；重新產生已追蹤 CSV；測試改用 fixture。
5. **PR-E（P1-3 + P1-6 + P1-8）**：`pure` profile、tie 標示、deadline policy、run metadata、warm-up 剔除。這部分屬於實驗設計，需要先決定方法再動手。
6. **PR-F（P2）**：CI、依賴拆分與鎖版本、repo 衛生、文件同步。

每個 PR 合併後執行 `python3 scripts/audit_repro.py`，對應 case 應從 `REPRODUCED` 變為 `FIXED`。
