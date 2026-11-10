# Phase 1 / Batch 3：Experiment Provenance & OS Profile Calibration

- 日期：2026-11-10
- Branch：`fix/pr-a1-ros2-data-integrity`
- 基準：Batch 2 checkpoint commit `9eb6341`（本批開始前建立，見 §1）
- 本批次狀態：**未 commit、未 push、未 merge**
- 對應 audit：P0-3、P1-7、P1-8
- 結果：`python3 -m unittest discover -s tests` **124/124 通過**（原 94 + 新 30）；`python3 scripts/audit_repro.py` **0/13 REPRODUCED**，其中 P0-3、P1-8 為 **BLOCKED**（程式已修正，但需要實機 ROS 2 資料才能驗證）；`scripts/check_runtime_provenance.py` 回報 **BLOCKED（exit 1）**——repo 內沒有任何原始 ROS 2 資料，這是事實，沒有被繞過。

## 0. 狀態總表

| 項目 | 狀態 | 說明 |
|---|---|---|
| P0-3 provenance 機制（manifest、hash chain、status、sidecar、checker） | **FIXED** | 以合成暫存資料做端到端測試：verified / 竄改 / 缺 metadata / 限制未生效 / sidecar 過期 |
| P0-3 過期 artifact 與預設設定 | **FIXED** | 預設 runtime-aware config 改回 example；已追蹤 CSV 與重新產生結果逐列一致；4×2 張已追蹤圖加上 `[OS profile: UNVERIFIED]` |
| P0-3 22 個 `measured_*` profiles | **UNVERIFIED** | 數值原封不動，移到 `runtime_os_profiles.legacy_unverified.json` 並標示 `unverified`；模擬器預設拒用 |
| P0-3 實測資料鏈（raw → summary → profiles） | **BLOCKED** | 需實機重跑；不產生假資料、不讓 check 強制通過 |
| P1-7 per-model 校準、絕對 memory reference、不混用模型 | **FIXED** | 程式與測試完成 |
| P1-7 legacy profiles 重新校準 | **BLOCKED** | 缺每個 run 的 `avg_latency_ms` / `avg_memory_mb` 與記憶體上限；只能在報告中示意 latency 部分（§4.2，標示為衍生、未驗證） |
| P1-8 run metadata、requested vs effective、fallback 標示、不執行 sudo | **FIXED（程式）** | 以假 `/proc` 與 cgroup 樹做單元測試，在 macOS 上實際執行 collector |
| P1-8 Linux 上 taskset / cgroup v2 讀回 | **BLOCKED** | 尚未在 Linux + ROS 2 上執行 |

## 1. Batch 2 checkpoint commit

- 開始前 `git status`：Batch 2 的 18 個已追蹤檔案 + 3 個新檔未提交；使用者自己的變更是 `plot_6lines.py` 的 `SIX_LINE_METRICS` hunk、`results/.DS_Store`、兩個未追蹤的 `os_aware_total_cost_by_sram.svg`、`~$os-aware-eda-lite-final-presentation.pptx`。
- Batch 2 測試：94/94 通過。
- `9eb6341 fix(eda-lite): exact DP objective, greedy/sweep robustness, pure profile (Phase 1 / Batch 2)`：逐一 `git add` 指定的 Batch 2 檔案（沒有用 `git add -A`）。
- **`plot_6lines.py` 的分離方式**：從工作目錄版本移除使用者的兩個 hunk（`SIX_LINE_METRICS` 定義與迴圈改用它），得到「只含 Batch 2」的版本，以 `git hash-object -w` + `git update-index --cacheinfo` 放進 index。工作目錄保留完整版本，所以使用者的 hunk 仍是未提交狀態。提交前用 `git checkout-index` 把 index 匯出到 scratch 目錄，單獨跑過測試（94/94）。
- 沒有提交：`results/.DS_Store`、兩個使用者 SVG、`~$*.pptx`。

## 2. 修改摘要

### P0-3 Experiment provenance

**Hash chain**（新增 `src/provenance.py`，只用標準函式庫）：

```text
results/raw/ros2/<run_id>.csv, .publisher.csv, .meta.json
  └─ analyze_runtime → results/csv/ros2_runtime_summary.csv
                        + ros2_runtime_summary.manifest.json   (summary 與每個 raw 檔的 SHA-256、每個 run 的 metadata 與 measurement_class)
       └─ build_os_profiles → experiments/eda_lite/runtime_os_profiles.json
                               metadata.source_summary / source_manifest (SHA-256), provenance_status
            └─ run_simulation / run_profile_sweep → <out>.csv + <out>.provenance.json
                                                   (output、config、model profile、OS profile 檔的 SHA-256 與 status)
```

- JSON 內的路徑一律相對於該 JSON 所在目錄，整個 repo 搬移後仍可驗證。
- **Status**（每列模擬結果都寫入新欄位 `os_profile_provenance`）：`builtin`、`inline`、`example`、`verified`、`unverified`。`verified` 必須同時滿足：檔案宣告 verified、summary 與 manifest 雜湊仍相符、manifest 往下驗證到每個 raw 檔，而且每個 run 都有 metadata，`measurement_class` 為 `constrained` 或 `unconstrained`。沒有 metadata 區塊的舊檔一律視為 `unverified`。
- **模擬器把關**：`unverified` 檔案預設拒用（`ValueError`，訊息列出原因）；config 必須明確寫 `"allow_unverified_os_profiles": true` 才能使用，結果列標示為 `unverified`。
- **`scripts/check_runtime_provenance.py`** 改寫：exit 0 = `VERIFIED`、1 = `BLOCKED`（缺環節）、2 = `BROKEN`（雜湊不符、run 限制未驗證、sidecar 過期）。legacy / example 檔只列為 INFO，永遠不會讓 check 通過。`--root` 參數讓測試可以在暫存目錄驗證整條鏈。
- **既有 measured profiles**：`git mv runtime_os_profiles.json → runtime_os_profiles.legacy_unverified.json`。`os_profiles` 與 `os_profile_definitions` 與原檔**完全相同**（已用程式比對），只新增 `metadata`：`provenance_status: unverified`、三條原因（無原始資料 / legacy 跨模型校準 / 限制未驗證）、由 profile 名稱解析出的 model 等欄位（註明來源是名稱）。`runtime_os_profiles.json` 保留給實機 pipeline 的輸出。
- **預設設定**：`mobilevit_runtime_aware_sweep.json` 改回 `runtime_os_profiles.example.json`（AGENTS.md 原本的意圖）。新增 `mobilevit_runtime_aware_sweep_legacy_unverified.json`，以 opt-in 方式重現隊友提供的圖。
- **過期 artifact**：
  - `results/csv/eda_lite_mobilevit_runtime_aware_sweep.csv`：以預設 config 重新產生，24 列的 partition 與成本與已追蹤版本完全相同，只多出欄位；新增 sidecar。
  - `results/csv/eda_lite_mobilevit_profile_sweep.csv`：96 列，數值不變，只多 `os_profile_provenance=builtin`；新增 sidecar。summary 檔 byte-identical。
- **圖表重建**：`rebuild_eda_lite_figures.sh` 先跑 provenance check（`BROKEN` 時停止）；OS profile 來源由 `RUNTIME_SWEEP_CONFIG` 指定（預設是 legacy-unverified，維持原本六線圖的內容）；`plot_6lines.py` 依 CSV 的 `os_profile_provenance` 在標題加上 `[OS profile: UNVERIFIED]` / `[OS profile: EXAMPLE]`。8 張已追蹤的 `results/figures/eda_lite/{s,xxs}/*.svg` 已重新產生，**只有標題改變**（每張 diff 1 行；這 4 個指標只取決於 partition）。
- **`.gitignore`**：忽略 `results/csv/*.provenance.json`，但保留兩個已追蹤 CSV 的 sidecar；另外忽略 Office 鎖定檔 `~$*`。

### P1-7 OS profile calibration（`src/ros2_runtime/build_os_profiles.py`）

- **Latency**：`latency_multiplier = avg_latency_ms / baseline(model, resource_profile)`。baseline 取**同模型、同 resource profile** 的 idle 條件：`fake_delay_ms = 0`，優先 `fps_sweep`，最低 `input_fps`，再取最低 `qos_depth`；同條件的重複 run 取平均。模型之間不互相正規化；找不到 idle run 就報錯，不會改用其他模型。可用 `--baseline-resource-profile normal` 讓 `tuned` 以 `normal` 的 idle run 為基準（用來看 tuning 的效果），或用 `--baseline-latency-ms 40` / `MODEL=VALUE` 明確指定。
- **Memory**：`memory_pressure = avg_memory_mb / reference`，reference 依序為 CLI `--memory-reference-mb`、該 run 實際生效的 cgroup `memory.max`（`memory_limit_mb`）、主機 RAM（`host_memory_mb`）。沒有任何 reference 就報錯；**移除**「以所有模型最大 RSS 正規化」。
- **Metadata**：記錄每個 baseline（數值、條件、run_ids、來源）、每個 profile 的 model / run / scenario / measurement_class / baseline / memory reference 與來源、calibration 公式。
- **不混用模型**：MobileViT model profile 新增可選欄位 `runtime_model_name`（`mobilevit_xxs` / `mobilevit_s`）。從檔案讀到的 profile 清單會過濾成同一模型；config 明確列出其他模型的 profile 會報錯；model-specific profiles 遇到沒有 `runtime_model_name` 的 model profile 也會報錯。
- `--require-verified`：provenance 無法驗證時不寫出任何檔案（exit 1）。

### P1-8 Experiment reproducibility

- **新增 `src/ros2_runtime/run_metadata.py`**（標準函式庫）：每個 run 在 launch 前，於**同一個** taskset / systemd-run scope 內寫入 `<run_id>.meta.json`：
  - 環境：run_id、git commit + dirty、OS/kernel、CPU 型號、邏輯 CPU 數、主機 RAM、Python、torch / timm / numpy / opencv / psutil 版本；
  - ROS 2：`ROS_DISTRO`、`RMW_IMPLEMENTATION`（未設定就記為 null，代表 distro 預設，不做假設）、DDS transport 相關環境變數、node QoS（reliable publisher depth 10 → best-effort subscriber depth `qos_depth`；有測試檢查 node 原始碼與描述一致）；
  - 網路：讀取 `net.core.{r,w}mem_{max,default}`，並附註「只記錄、不假設有效；同機 Fast DDS 可能走 shared memory」；
  - 資源限制：**requested**（`REQUESTED_CPUS`、`REQUESTED_MEMORY_MAX`）與 **effective**（`sched_getaffinity`、cgroup v2 路徑上最緊的 `memory.max`、`cpu.max`）分開記錄，並給出 `measurement_class`：`constrained` / `unconstrained` / `constraint_unverified` / `constraint_failed`；
  - 實驗參數：scenario、model、fps、QoS depth、delay、deadline、run 秒數、warm-up、dataset、launch target。
- **Scripts**：
  - `run_common.sh` 新增 `run_capture_metadata`：要求的限制未驗證生效時，run 在 launch 前失敗（metadata 改名為 `*.meta.json.failed`）；`ALLOW_UNVERIFIED_LIMITS=1` 可以繼續，但會記為 unverified/failed，由它建出的 OS profiles 也保持 `unverified`。`run_prepare` / `run_finish` 一併處理 `.meta.json`。
  - 三個 sweep script 在每個 run 前呼叫 `run_capture_metadata`。
  - Baseline / tuned wrappers：限制改為可設定的 `CPU_SET` / `MEMORY_MAX` 並 export 成 `REQUESTED_*`；找不到 `taskset` / `systemd-run` 時 label 改為 `unconstrained` / `tuned_unconstrained`（不再標 `normal` / `tuned`）。
  - **`run_os_tuned_experiments.sh` 不再執行 `sudo sysctl`**：只檢查 `net.core.rmem_max >= TARGET_RMEM_MAX`，不足就印出需要手動執行的指令並結束；註解與 README 說明 UDP buffer 不一定影響 DDS。
- **Analyzer**：讀取 `<run_id>.meta.json`（run_id 不符或重複時報錯），summary 新增 `measurement_class`、`memory_limit_mb`、`host_memory_mb`、`run_metadata` 欄位，並寫出 manifest。

## 3. 驗證結果

```bash
python3 -m unittest discover -s tests          # Ran 124 tests ... OK
python3 scripts/audit_repro.py                 # Summary: 0/13 reproduced; Blocked: P0-3, P1-8
python3 scripts/check_runtime_provenance.py    # STATUS: BLOCKED (exit 1)
for f in experiments/ros2/*.sh scripts/*.sh; do bash -n "$f"; done   # 全部通過
```

| 檢查 | 結果 |
|---|---|
| Unit / integration tests | **124/124**（Python 3.11.4）；新增 `tests/test_provenance_calibration.py` 30 個；更新 2 個既有測試（見下）。收尾驗證時有 1 次執行出現 1 個 error，但當時沒有保存輸出；之後連續 37 次完整執行全部通過，無法重現。可能是不穩定的測試，尚未確認原因 |
| Audit cases | P0-1、P0-2、P1-1–P1-6、P1-4S、P1-7、LAUNCH：FIXED；**P0-3：BLOCKED**；**P1-8（新 case）：BLOCKED** |
| Provenance check（repo） | BLOCKED：缺 raw CSV、summary、verified profiles；legacy 檔 `UNVERIFIED`、example 檔 `EXAMPLE`；`results/figures/ros2/*.svg` 標為 UNVERIFIED；7 個 simulation sidecar 雜湊一致 |
| Provenance check（測試中的合成鏈） | 完整鏈 → VERIFIED；竄改 raw CSV → BROKEN 且模擬器拒用；缺 metadata → `--require-verified` exit 1；限制未生效 → BROKEN；config 改動 → sidecar STALE |
| `run_metadata` 實際執行（macOS） | 要求 `0,1`/`2G` → `constraint_unverified`，exit 3；未要求 → `unconstrained`，exit 0 |
| 重新產生的已追蹤 artifact | runtime-aware CSV：24 列與舊版逐列一致；profile sweep：96 列數值一致；profile summary：byte-identical；8 張 SVG：只有標題改變 |

更新的既有測試（行為是**刻意**改變的）：
- `test_eda_lite.py::test_mobilevit_runtime_aware_sweep_config_uses_os_profile_file`：預設 config 改用 example profiles，並檢查 `os_profile_provenance=example`（原本依賴無法重建的 `runtime_os_profiles.json`，即 audit P2-5）。
- `test_ros2_run_integrity.py::test_os_profiles_keep_repeated_runs_distinct`：傳入 `memory_reference_mb=2048`，因為已移除 max-RSS fallback。

新測試分類：provenance chain（7，暫存目錄內的合成資料）、repo provenance（7）、calibration（8）、run metadata 與 scripts（8，含假 cgroup 樹與 `run_capture_metadata` 的 bash 整合測試）。新測試依賴新模組，無法在 `9eb6341` 上 import，所以修改前後的對照以 `audit_repro.py` 為準：`9eb6341` 上 P0-3、P1-7 為 REPRODUCED。P1-8 是新 case，需要 import 新模組，無法直接在 `9eb6341` 執行；但它對 scripts 的靜態檢查（會執行的 `sudo sysctl` 行、fallback 仍標 `normal`、沒有 metadata capture）在舊 scripts 上三項都會被判定為缺陷。

## 4. 校準前後比較

### 4.1 新 builder，兩個 idle run（合成數字，`audit_repro.py P1-7`）

| | 修改前（全域 baseline / max RSS） | 修改後（per-model idle / 2048 MB limit） |
|---|---|---|
| XXS idle（40 ms，300 MB） | m = 1.0，memory = 0.5 | m = 1.0，memory = 0.146 |
| S idle（120 ms，600 MB） | m = **3.0**，memory = **1.0** | m = **1.0**，memory = 0.293 |

### 4.2 Legacy profiles：latency_multiplier（**衍生、UNVERIFIED，未寫入任何檔案**）

legacy multiplier 都是除以同一個全域最小值，因此「除以該模型 5 fps / d0 / normal 的 legacy multiplier」在數學上等於 per-model idle baseline（只差 6 位小數的四捨五入）。這只是**示意**，不是校準後的實測值：memory 無法這樣換算（需要 MB 數值與上限），legacy 檔本身也沒有更動。

| Profile（省略 `measured_` 前綴） | legacy m | per-model m |
|---|---:|---:|
| fps_sweep S 5 fps（idle） | 3.287 | 1.000 |
| fps_sweep S 30 fps | 3.783 | 1.151 |
| qos_sweep S q1 | 3.483 | 1.060 |
| overload S d30 | 6.016 | 1.830 |
| overload S d80 | 28.896 | 8.791 |
| overload S d150 | 30.203 | 9.189 |
| fps_sweep XXS 5 fps（idle） | 1.044 | 1.000 |
| fps_sweep XXS 30 fps | 1.017 | 0.975 |
| overload XXS d30 | 2.684 | 2.572 |
| overload XXS d150 | 23.485 | 22.505 |

（22 個 profile 的完整表格可用同樣方式重算；legacy `memory_pressure` 範圍 0.934–1.0，無法重新校準。）

**對 EDA-Lite 成本的影響**（SRAM 512 KB、`dp`、deadline 33.3、legacy-unverified config；兩組都 **UNVERIFIED**）：

| 模型 | Profile | legacy L_eff | legacy deadline_cost | legacy total | per-model L_eff | per-model deadline_cost | per-model total |
|---|---|---:|---:|---:|---:|---:|---:|
| S | fps 5（idle） | 104.0 | 25.8 | 2815.7 | 31.7 | **0** | 2717.5 |
| S | fps 30 | 119.7 | 358.4 | 4362.3 | 36.4 | 13.0 | 3933.6 |
| S | overload d30 | 190.4 | 4061.0 | 8065.1 | 57.9 | 636.7 | 4508.3 |
| S | overload d150 | 956.0 | 92274.2 | 97676.1 | 290.9 | 25756.9 | 30493.7 |
| XXS | fps 5（idle） | 9.24 | 0 | 1079.1 | 8.85 | 0 | 1078.7 |
| XXS | overload d150 | 207.9 | 17463.3 | 19198.3 | 199.3 | 16595.9 | 18322.3 |

- legacy 校準下，**idle 的 MobileViT-S 已經有 deadline 成本**，原因只是 S 比 XXS 慢；per-model 校準後為 0（`test_legacy_calibration_inflated_idle_mobilevit_s` 記錄了這個缺陷）。
- 兩種校準下 partition 都**沒有改變**（S、XXS 各 0 組），與 Batch 2「OS profiles 不改變 MobileViT 排程」的結論一致。

### 4.3 模型混用

| | 修改前（Batch 2） | 修改後 |
|---|---|---|
| XXS runtime-aware sweep | 264 列，22 個 profile（含 11 個 S 的 profile，例如 S d150 的 m = 30.2 套在 XXS 上） | 132 列，只有 11 個 XXS profile |
| S runtime-aware sweep | 264 列，含 11 個 XXS profile | 132 列，只有 11 個 S profile |

## 5. 剩餘 blocker

1. **沒有原始 ROS 2 資料**：`results/raw/ros2/` 只有 `.gitkeep`；沒有 summary、manifest、run metadata、verified `runtime_os_profiles.json`。P0-3 的驗收條件（check exit 0）只能靠實機重跑達成。
2. **Legacy profiles 無法重新校準或驗證**：缺每個 run 的 latency/memory 絕對值與記憶體上限；只能保持 UNVERIFIED。所有由它們衍生的數字與圖（`results/figures/eda_lite/*`、`results/figures/ros2/*`、使用者的 `os_aware_total_cost_by_sram.svg`）都不能作為實測結果。
3. **P1-8 Linux 讀回**：`sched_getaffinity` 與 cgroup v2 `memory.max` 的讀回只在假檔案樹上測試過；`systemd-run --user` 的 memory delegation 是否生效，要在目標機器上確認。
4. **Metadata 是 launch 前的快照**：限制在 run 開始時驗證，沒有持續監控（例如 run 途中被 OOM 或 cgroup 被修改）。

## 6. Git diff 概況

未提交，排除 `results/.DS_Store` 後：41 個已追蹤檔案，**+1642 / −541**（`git diff --stat HEAD`；包含 legacy JSON 的 rename：刪除 160 行、新增 400 行，其中 240 行是 metadata）。新檔：`src/provenance.py`（238）、`src/ros2_runtime/run_metadata.py`（351）、`tests/test_provenance_calibration.py`（541）、`experiments/eda_lite/mobilevit_runtime_aware_sweep_legacy_unverified.json`、兩個 sidecar（`results/csv/eda_lite_mobilevit_{profile_sweep,runtime_aware_sweep}.provenance.json`）、本報告。

```text
src/ros2_runtime/build_os_profiles.py          | 301 ++++++--   per-model calibration, metadata, provenance status
scripts/check_runtime_provenance.py            | 214 +++---   VERIFIED / BLOCKED / BROKEN chain check
results/csv/eda_lite_mobilevit_profile_sweep.csv | 194 +--     regenerated (+ os_profile_provenance)
src/eda_lite/run_simulation.py                 | 149 +++    provenance gate, model filter, sidecar
scripts/audit_repro.py                         | 117 ++     P0-3 / P1-7 updated, P1-8 added, BLOCKED verdict
src/ros2_runtime/analyze_runtime.py            | 116 ++     run metadata columns, manifest
scripts/rebuild_eda_lite_figures.sh            |  71 +-     provenance check, RUNTIME_SWEEP_CONFIG
README.md / AGENTS.md / report/*               | docs
experiments/ros2/*.sh, scripts/run_*_experiments.sh | metadata capture, honest labels, no sudo
src/eda_lite/plot_6lines.py                    |  31 +      provenance title tag (also contains the user's uncommitted SIX_LINE_METRICS hunk)
experiments/eda_lite/runtime_os_profiles.json → runtime_os_profiles.legacy_unverified.json (git mv, metadata added)
results/figures/eda_lite/{s,xxs}/*.svg (8)      | title only
```

注意事項：
- **`plot_6lines.py`** 仍同時包含使用者未提交的 `SIX_LINE_METRICS` hunk（自 `9eb6341` 起不在任何 commit 中）與本批的標題標示變更；提交時請再決定是否要一起提交。
- `git mv` 讓 rename 已經在 index 中（`git status` 顯示為 `RM`）；其他變更都沒有 stage。
- 沒有覆寫使用者未追蹤的 `results/figures/eda_lite/{s,xxs}/os_aware_total_cost_by_sram.svg`；它們是由 Batch 2 之前的成本模型與 UNVERIFIED profiles 產生，標題也沒有 UNVERIFIED 標示。需要更新時，請執行 `bash scripts/rebuild_eda_lite_figures.sh`（會覆寫）。
- `~$os-aware-eda-lite-final-presentation.pptx` 仍在磁碟上，只是被新的 `.gitignore` 規則 `~$*` 隱藏。
- 被 ignore 的本機 CSV（`eda_lite_mobilevit_{s,xxs}_{pure,runtime_aware_sweep}.csv`、sensitivity sweep / summary）已用目前程式重新產生，並附上被 ignore 的 sidecar。Batch 2 版本的備份：`/private/tmp/claude-502/-Users-SAM--claude-spares-spare-3sT7eo/2544efc5-08af-4cd2-b9df-2a18316cb7c7/scratchpad/before/`（session scratchpad，非永久）。

## 7. Phase 2 實機測試清單

環境：Linux（cgroup v2）、ROS 2（記錄實際 distro）、與報告相同的 conda/RoboStack 環境；repo 根目錄執行。

1. **前置檢查**
   - [ ] `stat -fc %T /sys/fs/cgroup` 為 `cgroup2fs`；`cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.controllers` 含 `memory`（`systemd-run --user` 的 delegation）。
   - [ ] `systemd-run --user --scope -p MemoryMax=2G taskset -c 0,1 python3 -m src.ros2_runtime.run_metadata --output /tmp/probe.meta.json --run-id probe --resource-profile normal --requested-cpus 0,1 --requested-memory-max 2G --require-applied` → exit 0、`measurement_class=constrained`。失敗時**不要**用 `ALLOW_UNVERIFIED_LIMITS` 繞過；先修好 delegation，或改跑 unconstrained 並如實標示。
   - [ ] 記錄 `echo $RMW_IMPLEMENTATION`（空值 = distro 預設）、`ros2 doctor --report` 的 RMW 區段。
   - [ ] `bash experiments/ros2/prepare_coco128.sh`。
2. **Baseline**：`bash scripts/run_baseline_experiments.sh`，兩個模型 × FPS（5/10/20/30）、QoS（1/5/10）、overload（0/30/80/150 ms）。確認每個 run 都有 `.csv`、`.publisher.csv`、`.meta.json`，而且沒有 `*.failed`。
3. **重複性**：同一組設定以不同 `RUN_TAG` 至少再跑 2 次（評估 run-to-run 變異；idle baseline 會自動平均重複 run）。
4. **Unconstrained 對照（選做）**：在沒有 wrapper 的情況下直接跑 sweep，label 為 `unconstrained`，與 constrained 分開報告。
5. **Tuned（選做）**：手動執行 `sudo sysctl -w net.core.rmem_max=4194304 net.core.rmem_default=4194304` 後再執行 `bash scripts/run_os_tuned_experiments.sh`。比較時使用 `build_os_profiles --baseline-resource-profile normal`；從 metadata 確認 RMW 與 transport（同機的 Fast DDS 可能走 SHM，此時 buffer 無效）；不要預設 tuning 會有改善。
6. **分析與建檔**：
   - [ ] `python3 -m src.ros2_runtime.analyze_runtime --input results/raw/ros2 --summary-output results/csv/ros2_runtime_summary.csv --figures-dir results/figures/ros2`
   - [ ] `python3 -m src.ros2_runtime.build_os_profiles --input results/csv/ros2_runtime_summary.csv --output experiments/eda_lite/runtime_os_profiles.json --profile-prefix measured --require-verified`
   - [ ] `python3 scripts/check_runtime_provenance.py` → **exit 0 VERIFIED**；`python3 scripts/audit_repro.py P0-3` → FIXED。
7. **模擬與圖**：把 `mobilevit_runtime_aware_sweep.json` 改指向 `runtime_os_profiles.json`；以 `RUNTIME_SWEEP_CONFIG=experiments/eda_lite/mobilevit_runtime_aware_sweep.json` 與新的 measured profile 名稱執行 `rebuild_eda_lite_figures.sh`，確認圖標題沒有 UNVERIFIED 標示、sidecar 為 `verified`。
8. **保存**：raw CSV、publisher log、meta.json、summary + manifest、profiles、sidecars 一起保存（`*.csv` 預設被 ignore，需要 `git add -f` 或放到 release artifact），否則 check 會再次變成 BLOCKED。
