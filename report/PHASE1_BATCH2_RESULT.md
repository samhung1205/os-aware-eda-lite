# Phase 1 / Batch 2：Scheduling & Cost Model Correctness

- 日期：2026-11-10
- Branch：`fix/pr-a1-ros2-data-integrity`
- 基準：Batch 1 checkpoint commit `54667ab`（本批開始前建立；只含 Batch 1 檔案，不含使用者的 `plot_6lines.py`、`results/.DS_Store`、未追蹤 SVG 與 `~$*.pptx`）
- 本批次狀態：**未 commit、未 push、未 merge**
- 對應 audit：P0-1、P1-1、P1-2、P1-3、P1-4（EDA-Lite 端，新 case `P1-4S`）
- 結果：上述 audit case 全部由 `REPRODUCED` 變為 `FIXED`；測試共 94 個（原 71 + 新 23），全部通過；`dp` 與 exhaustive oracle 在所有檢查案例中 partition 與成本都完全一致。

## 1. 修改摘要

### P0-1 DP correctness
- **單一成本定義**：`cost_model.os_aware_cost` 是 reported `os_aware_total_cost` 與 `dp`/`exhaustive` 目標函數的唯一定義，作用在整個 schedule 的總量上：
  ```text
  L_eff = m·L
  C = E + α·L_eff + β·r·max(0, L_eff − D) + γ·p·P/SRAM + δ·d·L
  ```
  `E`、`L` 是各 subgraph 的總和，`P` 是各 subgraph peak 的最大值。舊 DP 將每個 subgraph 單獨算完整成本再加總，memory 項變成 Σpeak、deadline hinge 變成逐段計算，兩者都與 reported cost 不同。
- **新 DP（`dp_schedule`）**：prefix DP + Pareto labels。每個 prefix 保留 `(E, L, P)` 的非支配集合；最終成本對三者都非遞減（權重皆非負），延伸 schedule 時三者單調更新（sum、sum、max），所以被支配的 label 不可能導出更便宜的完整 schedule。只比較權重非零的座標：
  - 加總項 `A = E + (α·m + δ·d)·L`：一定比較；
  - `L`：只有 `β·r > 0`（deadline 項有作用）時比較；
  - `P`：只有 `γ·p > 0`（memory 項有作用）時比較。
- **Tie-break**：成本在相對誤差 `1e-9` 內視為平手，依序選 subgraph 數較少者、end index 序列字典序較小者。tie-break 偏好也納入支配判斷，因此 `dp` 回傳的 partition 與 oracle **完全相同**，而不只是成本相同。
- **Exhaustive oracle（`exhaustive_schedule`）**：窮舉 `2^(n−1)` 個 contiguous partition（n ≤ 20），以相同成本函數與 tie-break 選擇；也可在 config 中當 scheduler `exhaustive` 使用。
- `make_cost_config` 拒絕負權重（DP 精確性的前提）。`subgraph_objective_cost` 保留供診斷，docstring 註明它**不是**目標函數。

### P1-1 / P1-2 Greedy & sweep
- **Greedy**：SRAM 可行性對結束位置非單調，因此 SRAM 不可行時繼續掃描，只有遇到 non-fusible layer 才停止（之後的延伸一定不可行），並取最後一個可行的 end。Greedy 仍不回溯，所以可能在 DP 可行時失敗；此時明確拋出 `InfeasibleScheduleError`。
- **`InfeasibleScheduleError(ValueError)`**：所有 scheduler 找不到可行解時都拋出這個例外。Sweep 捕捉它並輸出 `feasible=false` 的列，數值欄位留空，`infeasible_reason` 說明原因；設定錯誤（未知 scheduler / OS profile、負權重）仍會中止。
- **Analyzer**：
  - 不可行列不參與比較，也不畫進圖；
  - 整組都不可行時，`best_scheduler` 留空；
  - `layerwise` 缺少或不可行時，reduction 欄位留空，`baseline_status` 標示 `missing` / `infeasible`。

### P1-3 OS-aware experiment semantics
- **`pure` 內建 profile**：`latency_multiplier=1.0`（保留正常 latency cost，不是 0），`deadline_miss_rate = memory_pressure = drop_rate = 0`，因此成本等於 `E + α·L`。已加入 `mobilevit_sram_sweep.json`、`mobilevit_profile_sweep.json`。
- **平手標示**：summary 的 `best_scheduler` 列出所有平手的 scheduler，以 `=` 連接（例如 `greedy=dp`）；新增 `num_tied_schedulers`、`tied_same_partition`。`final_report.md` 第 6 節原本寫的 `greedy` 已改為 `greedy=dp (tie)`，並加註說明。
- **移除硬編碼 profile**：`plot_6lines.py` 改為 CLI（`--model --pure-csv --os-csv --os-profile [--pure-profile pure] --out-dir`），並檢查 profile/model 是否存在於 CSV；`rebuild_eda_lite_figures.sh` 以環境變數 `PURE_PROFILE`、`OS_PROFILE_S`、`OS_PROFILE_XXS`、`FIGURES_ROOT` 指定（預設值與原本的 d150 profile 相同，只是移到腳本設定）。
- **Sensitivity**：新增 `mobilevit_sensitivity_sweep.json`（2 模型 × SRAM 128/192/256/384/512/1024/2048 × deadline 5/10/20/33.3/50/100 × 4 個內建 profiles × 4 個 scheduler，共 1344 列，執行約 0.2 s）。Config 新增可選的 top-level `deadline_ms` 清單作為 sweep 維度。SRAM 與 deadline 網格是規則網格，**沒有**為了製造差異而挑選數值。

### EDA-Lite deadline consistency（P1-4 第 1、2 點）
- Deadline 項改用 effective latency `m·L`，與 latency 項使用同一個經 OS 放大的 latency。舊版用未放大的 `L`，所以 `latency_multiplier` 永遠不會造成 deadline excess。Communication 項維持使用原始 `L`，沒有改動。
- **定義與對應**：
  - EDA-Lite `deadline_ms` 是 **simulated latency**（cost-model 單位）的單次推論預算；
  - ROS 2 `deadline_ms` 是每個 frame 的 **wall-clock** 端到端預算（publish → 推論完成）；
  - 兩者只透過無因次的 `deadline_miss_rate`（實測 miss 比例）與 `latency_multiplier`（實測 latency 比值）連結。不把 runtime deadline 數值複製到模擬中，因為 simulated latency 並未校準到 wall clock。
- 每列 simulation CSV 都記錄 `deadline_ms`、`effective_latency_ms` 與四個成本項（`latency_cost`、`deadline_cost`、`memory_pressure_cost`、`communication_pressure_cost`），讓「哪一項在何時起作用」可以直接從 CSV 驗證。

## 2. 演算法設計與複雜度

| Scheduler | 目標 | 時間複雜度 | 備註 |
|---|---|---|---|
| `layerwise` | — | O(n) | 單層不可行就 infeasible |
| `greedy` | 最長可行融合（heuristic） | O(n²) 次可行性檢查 | 只在 non-fusible 時 break；不回溯 |
| `dp` | **精確** min `os_aware_total_cost` | 候選 metrics O(n³) 預先計算；label 延伸 O(n²·K)，每個 prefix 的 front 維護 O(K²) | K = 最大 Pareto front；最壞情況 ≤ 2^(n−1)，實測 MobileViT K ≤ 4、隨機 9 層模型 K ≤ 12 |
| `exhaustive` | 精確（oracle） | O(2^(n−1)·n) | n ≤ 20 |

設計取捨：
- 沒有採用「n ≤ 20 時直接委派給 exhaustive」：Pareto DP 一樣精確，而且沒有層數上限。
- 沒有採用「把 reported cost 改成 per-subgraph 加總」：每多一個 subgraph 就多罰一次 memory pressure，語意上說不通（audit 建議 3）。
- 沒有採用 audit 建議的「外層列舉 peak cap」：3 維 Pareto label 已經涵蓋 peak 維度，實作更短。
- `dp` 的 label 數在最壞情況下是指數級的，這是精確最小化「加總項 + 總 latency 的 hinge」的本質代價（帶預算的最短路徑問題）；以目前的模型規模影響可忽略。

## 3. 測試結果

```bash
python3 -m unittest discover -s tests        # Ran 94 tests ... OK
python3 scripts/audit_repro.py               # Summary: 2/12 reproduced: P0-3, P1-7
```

| 檢查 | 結果 |
|---|---|
| Unit / integration tests | **94/94 通過**（Python 3.11.4；原 71 + `tests/test_eda_lite_scheduling.py` 23） |
| 新測試對照修改前的程式碼（`54667ab` 的 `src/`，只補上 API shim：`InfeasibleScheduleError=ValueError`、oracle 實作） | 23 個中有 **19 個失敗**；通過的 4 個是 latent case（MobileViT 上舊 DP 恰好正確）、oracle 上限、單層不可行、設定錯誤 |
| DP vs exhaustive oracle | 單元測試：600 個隨機小模型（固定 seed，含 0 權重、極端 deadline 與 memory 權重）+ MobileViT 2 模型 × 3 SRAM × 3 deadline × 4 profiles，partition 與成本完全一致。額外檢查（scratch）：1430 個 MobileViT 組合（含 22 個 measured profiles × 7 SRAM × 5 deadline）與 1875 個隨機案例，**0 個不一致** |
| Sensitivity sweep artifact | 336 組中 dp 與 exhaustive 的 partition/成本全部一致（`test_repository_sensitivity_sweep_is_consistent`） |
| `audit_repro.py` | P0-1、P1-1、P1-2、P1-3、P1-4S：修改前 REPRODUCED → 現在 **FIXED**；P0-2、P1-4、P1-5、P1-6、LAUNCH 維持 FIXED；P0-3、P1-7 仍為 REPRODUCED（不在本批範圍） |
| `bash -n`（`experiments/ros2/*.sh`、`scripts/*.sh`） | 全部通過 |

新增測試分類（`tests/test_eda_lite_scheduling.py`）：
- **DP objective（7）**：隨機模型 oracle、MobileViT oracle、audit deadline toy、memory 用 max peak 而非 Σpeak、tie-break、oracle 層數上限、負權重拒絕。
- **Greedy & sweep（5）**：audit 的兩組非單調資料、明確 infeasible、sweep 標示 `feasible=false` 而不中止、設定錯誤仍中止。
- **Analyzer（5）**：平手顯示 `greedy=dp`、不可行列不會勝出且 `baseline_status=infeasible`、缺少 baseline / 整組不可行、圖表略過不可行列並要求單一 deadline、simulation CSV → analyzer round trip。
- **OS-aware semantics（6）**：`pure` 保留 latency、其餘為 0；deadline 使用 effective latency；**各成本項何時改變排程**（toy：`pure` 融合 → 只有 memory pressure 時切開 → 再加緊 deadline 又融合 → 放寬 deadline 又切開）；MobileViT SRAM 可行性門檻；repo sensitivity config 一致性；六線圖 profile 來自參數。

## 4. 結果差異（修改前 vs 修改後）

所有 artifact 都可用 README 指令重新產生；修改前的數值是在 `54667ab` 上以相同 config 產生。

| Artifact | 列數 | Partition 改變 | 成本改變 | 原因 |
|---|---|---|---|---|
| `results/csv/eda_lite_mobilevit_profile_sweep.csv`（已追蹤，已重新產生） | 72 → 96（+24 列 `pure`） | 0 | 24 列（S 的 `high_latency`、`high_memory_pressure`），最大 +176.6（+5.97%） | deadline 改用 `m·L`：S 的 `L≈31.7–31.9 ms`，×1.35 = 42.9 > 33.3 |
| `results/csv/eda_lite_mobilevit_profile_summary.csv`（已追蹤，已重新產生） | 24 → 32 | — | 同上 | `best_scheduler` 由 `greedy` 改為 `greedy=dp`（32/32 組都是平手且 partition 相同）；新增欄位 |
| `eda_lite_mobilevit_{s,xxs}_pure.csv`（ignored，已重新產生） | 36 → 48 | 0 | S 24 列；XXS 0 列 | 同上 |
| `eda_lite_mobilevit_{s,xxs}_runtime_aware_sweep.csv`（ignored，已重新產生） | 264 → 264 | 0 | S 120 列、XXS 72 列；最大 +93,120（+1747%） | measured profiles 的 `latency_multiplier` 最高 30.2（例如 S 31.9 ms → 964.5 ms），deadline 項主導成本 |
| Legacy `edge_profile_sweep`（只在 scratch 比對，未覆寫） | 72 | 0 | 0 | — |
| Legacy `yolo11_profile_sweep`（paused；只在 scratch 比對，未覆寫） | 72 | **3**（yolo11s、`high_latency`、SRAM 512/1024/2048） | 24 | `m·L = 66.4 > 33.3`，deadline 項使 DP 多融合一段；這是 deadline 項確實改變決策的例子，但 YOLO 不是主線 |

MobileViT DP 成本（節錄，`normal` 與 XXS 全部不變）：

| 模型 / SRAM | profile | 修改前 | 修改後 | `deadline_cost` | `effective_latency_ms` |
|---|---|---:|---:|---:|---:|
| S / 256 | pure | — | 2769.05 | 0 | 31.80 |
| S / 256 | normal | 2778.74 | 2778.74 | 0 | 31.80 |
| S / 256 | high_latency | 2987.95 | 3161.34 | 173.39 | 42.93 |
| S / 256 | high_memory_pressure | 2884.96 | 2898.42 | 13.46 | 34.98 |
| S / 512 | high_latency | 2851.07 | 3020.86 | 169.79 | 42.73 |
| XXS / 256 | high_latency | 1120.95 | 1120.95 | 0 | 11.95 |

**Sensitivity 結論（如實陳述，不是 tuned 結果）**：
- **SRAM 是唯一改變 MobileViT 排程的因素**：
  - S 在 SRAM < 240 KB 時所有 scheduler 都不可行（non-fusible 的 `mobilevit_block_2_attention` 單獨需要 240 KB）；256 KB 時融合深度為 2，≥ 384 KB 時為 3。
  - XXS 在 ≥ 192 KB 時全部可行，融合深度為 3；128 KB 時不可行。
- **在 MobileViT 上，OS profiles 與 deadline 不改變任何排程**：
  - 每個 (模型, SRAM, deadline) 下，4 個 profile 的 DP partition 與 `pure` 相同，greedy 與 dp 在 264/264 組都平手。
  - Deadline 項只要 `m·L > D` 就會增加成本（例如 S 的 `normal` 在 D ≤ 20 時有作用），但融合會**同時**降低 energy、latency 與 deadline 項，所以它只會強化「盡量融合」的決策。
  - 只有 memory 項會推向較少融合，但以目前權重需要把 `γ` 放大約 50–130 倍（S：≈3000–4400；XXS：≈2500–6500；預設 50）才會翻轉任何排程。
- 因此，「OS-aware」在目前 MobileViT 主線上是**成本評估**，不是**決策差異**。報告中不應宣稱 OS profiles 改變了排程。

六線圖：以新 `pure` baseline 重新產生到 scratch 目錄時，`results/figures/eda_lite/{s,xxs}/` 中 4 個**已追蹤**的指標圖與修改前 **byte-identical**（partition 沒有改變）。只有使用者未追蹤的 `os_aware_total_cost_by_sram.svg` 會不同（pure 線改用 `pure` profile，OS-aware 線多了 deadline 成本）；依指示**沒有覆寫**，需要時請執行 `bash scripts/rebuild_eda_lite_figures.sh`。`results/figures/mobilevit_s/*.svg` 若重新產生，只會出現標題與樣式差異（來自較舊版本的 analyzer，資料相同），因此已還原，避免無關變動。

## 5. 限制

- **Runtime-aware 成本由 deadline 項主導**：measured `latency_multiplier` 是相對於跨模型全域最低 latency（P1-7），最高到 30.2。乘在 simulated latency 上後遠超過 33.3 ms，所以 runtime-aware sweep 的 `os_aware_total_cost` 數值主要反映 P1-7 的正規化問題。在 P1-7 / P0-3 修正前，這些數值不應被解讀為 OS 壓力的大小。
- Simulation deadline 與 ROS 2 deadline 單位不同，本批刻意不做數值換算；若要讓兩者可比較，需要先將 simulated latency 校準到實測 latency（不在範圍內）。
- `dp` 的 Pareto front 在最壞情況下是指數級的；oracle 只支援 n ≤ 20。
- 成本平手容差為相對 `1e-9`；summary 的 `best_*` 指標取第一個平手 scheduler（CSV 順序），`tied_same_partition` 標示平手的 scheduler 是否選了相同 partition。
- Greedy 仍是不回溯的 heuristic，可能在 DP 可行時回報不可行（已明確標示，不會中止 sweep）。
- 已追蹤的 `results/csv/eda_lite_mobilevit_runtime_aware_sweep.csv`（舊的 example profiles，P0-3）與 legacy edge/YOLO CSV **未重新產生**：前者的輸入 profiles 無法驗證，後者不是主線。
- 不在本批範圍：P0-3、P1-7、P1-8、P1-4 第 5 點（QoS 文件）、P2。

## 6. Git diff 概況

- 已提交：`54667ab` Batch 1 checkpoint（20 個檔案，+1445 / −226；只含 Batch 1 檔案）。
- 本批未提交，排除使用者既有變更後共 **18 個已追蹤檔案，約 +989 / −314**（`git diff --stat`；這個數字包含使用者在 `plot_6lines.py` 原有的 +6/−1 與 `.DS_Store`），另有 2 個新檔：`tests/test_eda_lite_scheduling.py`（473 行）、`experiments/eda_lite/mobilevit_sensitivity_sweep.json`。主要變更：

```text
src/eda_lite/schedulers.py                    | 331 ++++++++++++++---
src/eda_lite/analyze_results.py               | 185 ++++++---
results/csv/eda_lite_mobilevit_profile_sweep.csv | 170 +++---  (regenerated)
src/eda_lite/run_simulation.py                | 133 +++++--
src/eda_lite/cost_model.py                    | 103 +++++-
scripts/audit_repro.py                        |  81 +++--
README.md                                     |  66 +++-
results/csv/eda_lite_mobilevit_profile_summary.csv |  58 ++-- (regenerated)
src/eda_lite/plot_6lines.py                   |  57 +++-  (含使用者原有的 SIX_LINE_METRICS 變更)
scripts/rebuild_eda_lite_figures.sh           |  27 +-
AGENTS.md / audit / final_report / ai log     | 文件更新
experiments/eda_lite/mobilevit_{sram,profile}_sweep.json | 加入 pure
tests/test_eda_lite.py                        |   3 +-  (72 → 96 列)
```

- **`src/eda_lite/plot_6lines.py` 同時含有使用者原本未提交的 `SIX_LINE_METRICS` hunk 與本批的 CLI 化變更**。本批沒有建立 commit；之後提交時請留意這一點。使用者原始版本的暫時備份（session scratchpad，非永久）：`/private/tmp/claude-502/-Users-SAM--claude-spares-spare-uurV62/e662f5b4-998e-412d-b818-674d3c442641/scratchpad/backup_ignored/plot_6lines.py`、`/private/tmp/claude-502/-Users-SAM--claude-spares-spare-uurV62/e662f5b4-998e-412d-b818-674d3c442641/scratchpad/backup_ignored/user_plot_6lines.patch`。
- 仍未提交、刻意保留的使用者變更：`results/.DS_Store`、`results/figures/eda_lite/{s,xxs}/os_aware_total_cost_by_sram.svg`、`~$os-aware-eda-lite-final-presentation.pptx`。
- 重新產生、但被 `.gitignore` 忽略的檔案：`results/csv/eda_lite_mobilevit_{s,xxs}_{pure,runtime_aware_sweep}.csv`、`results/csv/eda_lite_mobilevit_sensitivity_{sweep,summary}.csv`。舊版 ignored CSV 暫時備份於 `/private/tmp/claude-502/-Users-SAM--claude-spares-spare-uurV62/e662f5b4-998e-412d-b818-674d3c442641/scratchpad/backup_ignored/`。

## 7. 下一步建議

1. 檢查本批 diff 後提交。`plot_6lines.py` 需要決定是否與使用者的 `SIX_LINE_METRICS` 變更一起提交。
2. 執行 `bash scripts/rebuild_eda_lite_figures.sh` 更新六線圖（會覆寫未追蹤的 `os_aware_total_cost_by_sram.svg`）。
3. P1-7 + P0-3：依模型正規化 `latency_multiplier`、補回 raw CSV/summary，否則 runtime-aware 的 deadline 成本會持續失真。
