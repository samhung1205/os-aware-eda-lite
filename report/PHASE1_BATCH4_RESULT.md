# Phase 1 / Batch 4：Engineering Quality & Reproducibility

- 日期：2026-11-10
- Branch：`fix/pr-a1-ros2-data-integrity`
- 基準：Batch 3 checkpoint commit `64a844f`（本批開始前建立，見 §1）
- 本批次狀態：**未 commit、未 push、未 merge**
- 對應 audit：P2-1 – P2-6（Phase 1 最後一批）
- 結果：`python3 -m unittest discover -s tests` **148/148 通過**（Batch 3 的 124 + 新增 24）；`python3 scripts/audit_repro.py --strict` **0/17 REPRODUCED**（P0-3、P1-8 仍為 BLOCKED）；`scripts/check_runtime_provenance.py` 維持 **BLOCKED（exit 1）**；`bash scripts/ci_checks.sh all` exit 0。GitHub Actions 尚未實際執行（沒有 push）。

## 0. 狀態總表

| 項目 | 狀態 | 說明 |
|---|---|---|
| P2-1 CI | **FIXED（本機驗證）** | `.github/workflows/ci.yml` + `scripts/ci_checks.sh`；YAML 以 PyYAML / Ruby 解析通過，所有步驟在本機與乾淨 clone 中執行通過；尚未在 GitHub 上跑過 |
| P2-5 測試與 intermittent error | **改善診斷，未找到根因** | 本批再出現 1 次（未保存輸出），之後約 145 次無法重現；所有 subprocess 測試改為失敗時輸出完整 stdout/stderr，CI 保留 verbose log 並重複執行 5 次 |
| P2-2 依賴與環境 | **FIXED（ROS 2 部分未實機驗證）** | stdlib simulator（空的 `requirements-sim.txt`）與 pinned ROS 2 依賴分離；`environment.yml` 尚未在 Linux 上 solve |
| P2-3 Repo 衛生 | **FIXED** | 18 個 cache / `.DS_Store` 移出 index（檔案保留在磁碟）；`.gitignore` 與 `results/README.md` 定義單一追蹤策略 |
| P2-4 文件 | **FIXED** | README、AGENTS.md、final_report、ROS 2 文件、audit 報告同步；四種資料類別明確區分 |
| P2-6 Pipeline 細節 | **FIXED** | 模型載入失敗不再 fallback；`model_path` 移除並拒絕；model profile 驗證；QoS / jitter / 隨機權重語意文件化 |

## 1. Batch 3 checkpoint commit

- 開始前 `git status`：Batch 3 的 41 個已追蹤檔案 + 7 個新檔未提交；使用者自己的變更：`plot_6lines.py` 的 `SIX_LINE_METRICS` hunk、`results/.DS_Store`、兩個未追蹤的 `results/figures/eda_lite/{s,xxs}/os_aware_total_cost_by_sram.svg`。
- Batch 3 測試：124/124 通過。
- `64a844f fix(provenance): runtime provenance chain, per-model OS profile calibration, run metadata (Phase 1 / Batch 3)`：逐一 stage Batch 3 檔案（沒有 `git add -A`）。`plot_6lines.py` 與 Batch 2 相同做法：移除使用者的兩個 hunk 得到「只含 Batch 3」的版本，以 `git hash-object -w` + `git update-index --cacheinfo` 放進 index；用 `git checkout-index` 匯出 index 到 scratch 目錄單獨跑測試（124/124）後才提交。
- 沒有提交：`results/.DS_Store`、兩個使用者 SVG、`~$*.pptx`。使用者的 `SIX_LINE_METRICS` hunk 仍未提交。

## 2. 修改摘要

### P2-1 / P2-5 CI 與測試

- **`scripts/ci_checks.sh`**（CI 唯一的執行邏輯，本機可直接跑）：`tests`（`unittest -v`，log 寫到 `ci-logs/`，失敗時印出全部 FAIL/ERROR traceback）、`shell`（對所有 tracked `*.sh` 執行 `bash -n`）、`audit`（`audit_repro.py --strict`）、`provenance`（gate，見下）、`repeat N`、`all`。設定 `PYTHONFAULTHANDLER=1`、`PYTHONDONTWRITEBYTECODE=1`、`PYTHONHASHSEED=0`。
- **`.github/workflows/ci.yml`**：
  - `tests`：Ubuntu，Python 3.10 / 3.11 / 3.12 / 3.13 matrix，**不安裝任何套件**，上傳 log artifact。
  - `checks`：`bash -n`、audit regressions、provenance gate。
  - `repeat`：整套測試跑 5 次，**沒有 retry**，任一次失敗即失敗，上傳每次的 log。
  - 不安裝 ROS 2；ROS 2 節點、launch file、sweep scripts 由既有的 stdlib helper、stub launch modules、fake `ros2` / `timeout` 測試涵蓋。
- **Provenance gate**：`check_runtime_provenance.py` exit 1（BLOCKED）→ 印出 GitHub `::warning::`，不讓 CI 失敗；exit 2（BROKEN）→ 失敗；exit 0（VERIFIED）只有在 `results/raw/ros2/` 真的有 raw CSV 與 `meta.json` 時才接受，否則視為偽造而失敗。CI 不會把 BLOCKED 變成 VERIFIED（有測試以假 checker 驗證三種情況）。
- **`audit_repro.py`**：新增 `--strict`（任何 REPRODUCED → exit 1）與四個 case：`P2-1`（workflow 與四個步驟）、`P2-2`（依賴拆分與鎖版本）、`P2-3`（tracked cache；非 git checkout 時為 BLOCKED）、`P2-6`（fallback、`model_path`、profile chain）。在 Batch 3 commit 的乾淨 clone 上四個 case 皆為 **REPRODUCED**，目前皆為 **FIXED**。
- **Intermittent error 調查**：
  - Batch 3 曾出現 1 次 error。本批在剛修改 `model_loader.py` 後第一次執行時又出現 1 次（124 tests, errors=1），當時同時有另一個 clone 在背景跑測試；立即重跑無法重現，輸出未保存。
  - 重現嘗試（皆 0 失敗）：乾淨 clone 循序 40 次；兩個 clone 同時各 20 次；工作目錄 + clone 同時各 15 次；工作目錄 25 次；Batch 4 乾淨 checkout repeat 5 次與 Python 3.12 / 3.13 各 1 次。合計約 145 次。
  - 可能原因（未證實）：error（不是 failure）代表測試中丟出例外；最可疑的是 `subprocess.run(..., check=True)` 的 `CalledProcessError`，它不顯示子程序的 stderr。已全部改成 `tests/cli_support.run_cli`，失敗時以 AssertionError 輸出指令、cwd、exit code、完整 stdout/stderr；其他 `returncode` 斷言也附上 `describe_failure`。已用刻意失敗的測試確認輸出內容（§3）。
  - 沒有加 retry 或放寬斷言，以免掩蓋問題；之後再出現時，CI log 與 `ci-logs/` 會有足夠資訊。
- 新測試 `tests/test_engineering_quality.py`（24 個）：strict model loading、`model_path` 移除、profile validation、依賴拆分、simulator/analysis 只 import 標準函式庫、repo hygiene 與 `.gitignore` 策略、CI workflow 內容、`ci_checks.sh` 用法、provenance gate 行為、`audit_repro --strict`。

### P2-2 依賴與環境

| 檔案 | 用途 | 內容 |
|---|---|---|
| `requirements-sim.txt` | simulator、analysis、provenance、tests | 沒有套件（標準函式庫）；Python 3.10 – 3.13 |
| `requirements-ros2.txt` | ROS 2 nodes | `torch==2.5.1`、`torchvision==0.20.1`、`timm==1.0.11`、`numpy==1.26.4`、`psutil==7.0.0` |
| `environment.yml` | ROS 2 實機 | RoboStack `robostack-staging` + `conda-forge`，`python=3.10`、`ros-humble-ros-base`、`ros-humble-cv-bridge`、conda `opencv`，pip 段 `-r requirements-ros2.txt`（CPU wheel index） |
| `requirements.txt` | 相容舊指令 | `-r requirements-ros2.txt` |

- `cv2` 改由 conda `opencv` 提供（`cv_bridge` 連結的同一份），不再 pip 安裝 `opencv-python`；`numpy` 維持 `< 2`（Humble 的 `cv_bridge`）。
- `ros-humble-desktop` → `ros-humble-ros-base`（pipeline 只需要 rclpy、launch、ros2cli、sensor_msgs）；`setup_env.sh` 不再安裝沒用到的 `pandas` / `matplotlib`，改裝 `requirements-ros2.txt`；`install_ros2_conda.sh` 與 `environment.yml` 一致。
- 版本選擇：與本機系統 Python 已安裝的 torch 2.5.1 / torchvision 0.20.1 / psutil 7.0.0 一致，numpy 沿用原本的 `< 2` 限制。**這組版本沒有在 Linux + ROS 2 上 solve 或執行過**；每個 run 的 `meta.json` 會記錄實際 import 到的版本，Phase 2 建好環境後應 `conda env export --no-builds > environment.lock.yml` 並提交。
- 新測試以 AST 確認 `src/eda_lite`、`src/ros2_runtime`、`src/provenance.py`、`scripts/*.py` 只 import 標準函式庫。

### P2-3 Repo 衛生

- `git rm --cached`：15 個 `__pycache__/*.pyc` 與 3 個 `.DS_Store`（`results/`、`src/`、`tests/`）。**磁碟上的檔案都保留**（包括使用者修改過的 `results/.DS_Store`），只是不再被追蹤。
- `.gitignore` 依用途分段；results 策略：
  - `results/raw/ros2/<run_id>.{csv,publisher.csv,meta.json}`：追蹤（provenance chain 的起點）；`*.failed` 忽略。
  - `results/csv/*.csv` 與其 `.provenance.json` / `.manifest.json`：一起追蹤（移除原本「只例外兩個 sidecar」的規則）。
  - 其他位置的 CSV 仍忽略；新增 `ci-logs/`。
- 新增 `results/README.md`：追蹤策略表與每個現有結果的 provenance 狀態（simulation / example / UNVERIFIED / legacy）。
- 因策略改變，Batch 3 在本機重新產生、原本被 ignore 的 6 個 CSV + 5 個 sidecar（`eda_lite_mobilevit_{xxs,s}_{pure,runtime_aware_sweep}`、`sensitivity_{sweep,summary}`）現在顯示為未追蹤。它們的 sidecar 在 provenance check 中皆為 `OK`；其中 `*_runtime_aware_sweep` 是 `unverified`（legacy profiles）。**沒有替使用者決定是否提交**，見 §6。

### P2-4 文件

- **README**：新增「Status at a glance」（simulation estimates / example profiles / unverified legacy / verified measurements = 無）、明確寫出尚未執行真實 ROS 2 benchmark、沒有 adaptive scheduler；新增 stdlib Quickstart；End-to-end 流程改為說明步驟 1–3 需要 Phase 2 實機；環境改用 `environment.yml`；Repository layout 改成實際結構；Requirements 改成兩欄對照；移除 `MODEL_PATH`；新增 model / QoS / latency 統計 / CPU-memory 語意；model profile 驗證規則；測試與 CI 段落；reporting rules 補充。
- **AGENTS.md**：pipeline 語意、CI / 依賴 / hygiene 新章節、測試指令、已完成 / 未完成清單、Phase 2 下一步、維護規則（stdlib-only 由測試強制、不得提交 cache）。
- **report/final_report.md**：摘要改為明確的 UNVERIFIED / BLOCKED 說法與「無 adaptive scheduling」；launch 參數與 CSV contract 更新；新增 §7.3.1 量測語意；limitations 補充隨機權重、jitter 定義、QoS 範圍、pins 未驗證。
- `experiments/ros2/README.md`、`report/ros2_pipeline_integration.md`（移除 `model_path`、補 provenance 規則）、`report/audit_p0_p1_p2.md`（P2 狀態）、`report/ai_interaction_log.md`。

### P2-6 Pipeline

- **模型載入**（`run_log.create_model_strict`，標準函式庫、可單元測試）：以 `pretrained=False` 建立**指定**模型，失敗時丟出 RuntimeError（訊息含原因與「Refusing to fall back」），不會改用 `mobilevit_xxs`。detector 移除 fallback；模型在建立 CSV **之前**載入，所以載入失敗不會留下 CSV，node 結束 → launch shutdown → sweep 將該 run 標為失敗。detector 啟動時記錄權重為 `random_init`。
- **`model_path`**：從 launch `ARGUMENTS` 與三個 sweep script 移除（metadata 改記 `model_weights=random_init`）。沒有改成「載入權重檔」，因為那是新功能，而隨機權重對延遲量測已足夠。為了不讓舊指令被默默忽略：launch 收到 `model_path` 時 raise；sweep scripts 偵測到 `MODEL_PATH` 環境變數時 exit 2（`run_common.sh`）。
- **Model profile 驗證**（`model_loader.validate_layer_chain` 等）：數值必須 finite（json 允許 NaN/Infinity）、layer 名稱不可重複、`layers[i].output_kb == layers[i+1].input_kb`（相對誤差 1e-6）。repo 內 6 個 profile 全部通過，模擬結果不變。
- **量測語意**（只寫文件與 docstring，不改行為）：QoS sweep 只改 subscriber depth（publisher 固定 RELIABLE depth 10）；`jitter_ms` = 每 frame end-to-end latency 的母體標準差（不是 inter-arrival jitter）；P95/P99 為 nearest-rank；`cpu_percent` 為 per-process（可 > 100，第一次為 0.0）；隨機權重只量延遲、不量準確率。
- 沒有修改 DP / greedy / cost model；沒有重構 ROS 2 pipeline。

## 3. 測試與 CI 驗證

```bash
python3 -m unittest discover -s tests            # Ran 148 tests ... OK
bash scripts/ci_checks.sh all                     # exit 0
python3 scripts/audit_repro.py --strict           # 0/17 reproduced; Blocked: P0-3, P1-8
python3 scripts/check_runtime_provenance.py       # STATUS: BLOCKED (exit 1)
for f in $(git ls-files '*.sh') scripts/ci_checks.sh; do bash -n "$f"; done   # 全部通過
```

| 檢查 | 結果 |
|---|---|
| Unit / integration tests（工作目錄，Python 3.11.4） | **148/148** |
| 乾淨 checkout 模擬 CI（Batch 3 commit + 只有 Batch 4 檔案，無使用者檔案、無 ignored 本機檔案） | `ci_checks.sh all` exit 0；`repeat 5`：0/5 失敗；Python 3.12.x、3.13.7（空的 venv，無任何套件）各 148/148 |
| Python 3.10 | **未實際執行**（本機沒有 3.10）；以 `ast.parse(feature_version=(3, 10))` 檢查全部 `src/`、`tests/`、`scripts/` 無語法問題，也沒有使用 3.11+ 標準函式庫 API；由 CI matrix 驗證 |
| Workflow YAML | PyYAML 6.0.2 與 Ruby YAML 皆可解析；jobs = `tests`、`checks`、`repeat`。沒有 `actionlint`，GitHub 上尚未執行 |
| Audit（修改前 = `64a844f` 乾淨 clone） | P2-1、P2-2、P2-3、P2-6：**REPRODUCED** |
| Audit（修改後） | 17 個 case：15 FIXED、2 BLOCKED（P0-3、P1-8）、0 REPRODUCED |
| Provenance gate | 本 repo：BLOCKED（exit 1，gate 通過並警告）；測試中以假 checker 驗證 BLOCKED → 通過、VERIFIED 但無 raw → 失敗、BROKEN → 失敗 |
| 失敗診斷 | 刻意失敗的 `run_cli` 測試：CI 輸出包含 traceback、指令、cwd、exit code、子程序 stdout 與 stderr |
| Quickstart 指令 | `run_profile_sweep` 寫出 96 列 + `.provenance.json` |

更新的既有測試（只改診斷方式，不改斷言內容）：`test_provenance_calibration.py`、`test_ros2_measurement.py`、`test_ros2_run_integrity.py` 的 `check=True` subprocess 與 `returncode` 斷言改用 `run_cli` / `describe_failure`。

## 4. Git diff 概況

未提交；已追蹤檔案（排除含使用者 hunk 的 `plot_6lines.py`）：42 個檔案，**+469 / −164**，其中 18 個是移出 index 的二進位 cache / `.DS_Store`。新檔：

```text
.github/workflows/ci.yml          81   CI (tests matrix, checks, repeat)
scripts/ci_checks.sh             122   CI steps, runnable locally
tests/test_engineering_quality.py 314  24 new tests (P2-1/2/3/5/6)
tests/cli_support.py              42   subprocess helper with full diagnostics
environment.yml                   26   RoboStack Humble + Python 3.10
requirements-ros2.txt             22   pinned ROS 2 node deps
requirements-sim.txt              10   stdlib only (no packages)
results/README.md                 35   tracking policy + provenance status
report/PHASE1_BATCH4_RESULT.md         this report
```

主要修改：

```text
README.md                                   | 175 +++---  status table, quickstart, env, layout, semantics, CI
scripts/audit_repro.py                      | 113 +++    --strict, P2-1/P2-2/P2-3/P2-6 cases
src/eda_lite/model_loader.py                |  34 +     finite / unique names / output->input chain
AGENTS.md / report/final_report.md          |  34 / 34  docs
src/ros2_uav_pipeline/.../run_log.py        |  27 +     create_model_strict, MODEL_WEIGHTS
.../mobilevit_detector_node.py              |  22 +-    no fallback
.../mobilevit_uav_pipeline.launch.py        |  12 +-    model_path removed and rejected
experiments/ros2/run_*.sh, run_common.sh    |  20       model_path removed, MODEL_PATH rejected
.gitignore                                  |  25 +-    results policy
tests/test_*.py (3 files)                   |  54       run_cli / describe_failure
src/ros2_runtime/analyze_runtime.py         |   9 +     metric definitions (docstring)
```

注意事項：

- `git rm --cached` 讓 18 個刪除已在 index 中（`git status` 顯示 `D `）；其他變更都沒有 stage。
- `src/eda_lite/plot_6lines.py` 仍只有使用者未提交的 `SIX_LINE_METRICS` hunk（本批沒有修改它）。
- `results/.DS_Store` 已移出 index：磁碟上的檔案（含使用者的修改）保留，之後被 `.gitignore` 忽略。
- 兩個使用者 SVG、`~$*.pptx` 沒有被修改或刪除。

## 5. Phase 1 完成度

| ID | 狀態 |
|---|---|
| P0-1 DP objective | FIXED（Batch 2） |
| P0-2 ROS 2 CSV 混用 | FIXED（PR-A1） |
| P0-3 Provenance | 機制 FIXED（Batch 3）；**資料 BLOCKED**：需實機 raw CSV |
| P1-1 – P1-7 | FIXED（Batch 1 – 3） |
| P1-8 實驗條件可追溯 | 程式 FIXED（Batch 3）；**Linux taskset / cgroup 讀回 BLOCKED** |
| P2-1 – P2-6 | FIXED（本批）；P2-2 的 ROS 2 pins 與 `environment.yml` 尚待實機驗證；CI 尚未在 GitHub 上執行 |

**Phase 1 的程式端工作已全部完成**：17 個可自動檢查的 audit case 沒有任何一個 REPRODUCED。剩下的都需要 Linux + ROS 2 實機（Phase 2）：P0-3 的實測資料鏈、P1-8 的限制讀回、P2-2 的環境 solve。目前專題能如實報告的是 **simulation estimates**；不能宣稱已完成真實 ROS 2 benchmark 或 adaptive scheduling。

## 6. 剩餘 blocker 與待使用者決定的事

1. **沒有真實 ROS 2 資料**：`results/raw/ros2/` 只有 `.gitkeep`，provenance 維持 BLOCKED（不會被 CI 繞過）。
2. **ROS 2 環境未驗證**：`environment.yml` / `requirements-ros2.txt` 沒有在 Linux 上 solve；沒有 lock 檔。
3. **CI 尚未在 GitHub 上執行**：需要 push 後確認（本批不 push）。若 GitHub runner 上 `run_metadata` 的 cgroup / affinity 行為與預期不同，相關測試會以完整輸出失敗。
4. **Intermittent error 根因未知**：診斷資訊已改善，CI repeat job 會繼續觀察。
5. **待使用者決定**：
   - 是否提交 6 個本機產生的 CSV + 5 個 sidecar（依新策略應追蹤；`*_runtime_aware_sweep` 為 `unverified`）。
   - 是否提交 `plot_6lines.py` 的 `SIX_LINE_METRICS` hunk 與兩個 `os_aware_total_cost_by_sram.svg`（它們由 Batch 2 前的成本模型產生、標題沒有 UNVERIFIED 標示；重新產生可執行 `bash scripts/rebuild_eda_lite_figures.sh`，會覆寫）。
   - Batch 4 本身的 commit（本批依指示未提交）。
   - legacy 的 `results/csv/eda_lite_{edge,yolo11,sram,summary,runtime_aware}*` 與 `results/figures/{edge_cnn_large,yolo11s,mobilevit_s}/` 已在 `results/README.md` 標為 historical、未刪除。

## 7. Phase 2 Linux / ROS 2 Preflight Checklist

在 repo 根目錄、`conda activate eda_lite` 後執行。**A = 可自動檢查**（指令有明確的通過條件），**M = 必須實機 / 人工確認**。

### 7.1 環境

| | 項目 | 指令 / 通過條件 |
|---|---|---|
| A | 環境建立 | `conda env create -f environment.yml` 成功；`conda env export --no-builds > environment.lock.yml` |
| A | Python / ROS | `python3 --version` → 3.10.x；`echo $ROS_DISTRO` → `humble`；`ros2 --help` exit 0 |
| A | 套件版本與 pins 一致 | `python3 -c "import torch, torchvision, timm, numpy, psutil, cv2; print(torch.__version__, torchvision.__version__, timm.__version__, numpy.__version__, psutil.__version__, cv2.__version__)"` → 與 `requirements-ros2.txt` 相同，numpy 1.x |
| A | cv_bridge 與 cv2 相容 | `python3 -c "from cv_bridge import CvBridge; import numpy as np; CvBridge().cv2_to_imgmsg(np.zeros((4,4,3), np.uint8), 'bgr8')"` exit 0 |
| A | 模型可建立且不 fallback | `python3 -c "import timm; [timm.create_model(m, pretrained=False) for m in ('mobilevit_xxs','mobilevit_s')]"` exit 0 |
| A | Repo 自我檢查 | `bash scripts/ci_checks.sh all` exit 0（provenance 應為 BLOCKED） |
| A | 工具 | `command -v timeout taskset systemd-run` 皆存在 |
| M | CPU 型號、核心數、是否關閉 turbo / 固定 governor、背景負載 | 人工記錄（metadata 只記錄型號與核心數，不控制頻率） |

### 7.2 資源限制

| | 項目 | 指令 / 通過條件 |
|---|---|---|
| A | cgroup v2 | `stat -fc %T /sys/fs/cgroup` → `cgroup2fs` |
| A | memory controller delegation | `cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.controllers` 含 `memory` |
| A | 限制實際生效 | `systemd-run --user --scope -p MemoryMax=2G taskset -c 0,1 python3 -m src.ros2_runtime.run_metadata --output /tmp/probe.meta.json --run-id probe --resource-profile normal --requested-cpus 0,1 --requested-memory-max 2G --require-applied` → exit 0，`measurement_class=constrained` |
| M | 失敗時的處理 | 不要用 `ALLOW_UNVERIFIED_LIMITS=1` 繞過；修好 delegation，或改跑 unconstrained 並如實標示 |
| M | 選用的 CPU 不是 0 號核心以外被大量中斷占用的核心 | 人工確認（`/proc/interrupts`） |

### 7.3 ROS 2 / DDS

| | 項目 | 指令 / 通過條件 |
|---|---|---|
| A | RMW 紀錄 | `echo "${RMW_IMPLEMENTATION:-<distro default>}"`；`ros2 doctor --report` 的 middleware 段（存檔） |
| A | 網路 buffer（僅 tuned 實驗） | `sysctl -n net.core.rmem_max` ≥ `TARGET_RMEM_MAX`（需手動 `sudo sysctl`，scripts 不會執行） |
| M | 同機 DDS 是否走 shared memory | 人工確認 transport 設定；SHM 時 UDP buffer tuning 無效，不可預設 tuning 有改善 |
| M | 沒有其他 ROS 2 graph 干擾 | `ros2 node list` 只看到本實驗的 node；必要時設定 `ROS_DOMAIN_ID` / `ROS_LOCALHOST_ONLY=1` |

### 7.4 Smoke run（正式 sweep 前）

| | 項目 | 指令 / 通過條件 |
|---|---|---|
| A | 資料集 | `bash experiments/ros2/prepare_coco128.sh`；`ls data/raw/images/coco128/images/train2017/*.jpg \| wc -l` > 0 |
| A | 單點 smoke | `FPS_VALUES=5 RUN_SECONDS=20 RESULTS_DIR=/tmp/smoke bash experiments/ros2/run_fps_sweep.sh` → 「到時正常結束」；`/tmp/smoke` 有 `.csv`、`.publisher.csv`、`.meta.json`，沒有 `*.failed` |
| A | 錯誤模型名稱會失敗 | `MODEL_NAME=mobilevit_typo FPS_VALUES=5 RUN_SECONDS=20 RESULTS_DIR=/tmp/smoke_bad bash experiments/ros2/run_fps_sweep.sh` → exit 1，沒有可分析的 `.csv` |
| A | Smoke 分析 | `python3 -m src.ros2_runtime.analyze_runtime --input /tmp/smoke --summary-output /tmp/smoke/summary.csv` → `frame_accounting=publisher_log`、`measurement_class` 符合預期 |
| M | 延遲數值合理 | 人工檢查 `avg_inference_ms` 與 `transport_ms` 的量級；同機 wall clock 一致 |
| M | Smoke 資料不得混入正式結果 | smoke 輸出放在 `/tmp`，不要複製到 `results/raw/ros2/` |

### 7.5 正式量測後

| | 項目 | 指令 / 通過條件 |
|---|---|---|
| A | 分析 | `python3 -m src.ros2_runtime.analyze_runtime --input results/raw/ros2 --summary-output results/csv/ros2_runtime_summary.csv --figures-dir results/figures/ros2` |
| A | Verified profiles | `python3 -m src.ros2_runtime.build_os_profiles ... --require-verified` exit 0 |
| A | Provenance | `python3 scripts/check_runtime_provenance.py` → **exit 0 VERIFIED**；`python3 scripts/audit_repro.py P0-3 P1-8` → FIXED |
| A | 提交完整鏈 | raw CSV + publisher log + meta.json + summary + manifest + `runtime_os_profiles.json` + sidecars + `environment.lock.yml` 一起提交（`results/README.md`）；CI 的 provenance gate 應變為 VERIFIED |
| M | 重複性 | 同一設定以不同 `RUN_TAG` 至少再跑 2 次，人工比較 run-to-run 變異 |
| M | 報告用語 | 只有 VERIFIED 的資料可稱 measured；constrained 只用於 `measurement_class=constrained` 的 run；註明隨機權重、jitter 定義、QoS 只改 subscriber depth |
