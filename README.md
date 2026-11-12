# OS-Aware Edge AI Runtime

在資源受限的 Linux 主機上，量測 **ROS 2 MobileViT 偵測節點的 frame scheduling（影格排程）**，並附一個離線的 **EDA-Lite layer-fusion simulator（層融合模擬器）**。

這份 README 是**使用說明書**：說明這個專案是什麼、怎麼安裝、怎麼看 Dashboard、怎麼執行模擬器與 ROS 2 實驗、怎麼驗證資料。研究結果的完整論述、開發過程與紀錄放在 [`docs/`](docs/)。

![Dashboard 總覽](docs/images/dashboard_overview.png)

---

## 目錄

1. [這個專案在做什麼](#1-這個專案在做什麼)
2. [環境需求](#2-環境需求)
3. [快速開始（5 分鐘）](#3-快速開始5-分鐘)
4. [使用 Dashboard](#4-使用-dashboard)
5. [使用 EDA-Lite 模擬器](#5-使用-eda-lite-模擬器)
6. [執行 ROS 2 實驗（進階）](#6-執行-ros-2-實驗進階)
7. [分析資料與驗證 Provenance](#7-分析資料與驗證-provenance)
8. [測試與 CI](#8-測試與-ci)
9. [專案結構](#9-專案結構)
10. [常見問題（FAQ）](#10-常見問題faq)
11. [使用限制與注意事項](#11-使用限制與注意事項)
12. [延伸文件](#12-延伸文件)
13. [授權與第三方資料](#13-授權與第三方資料)

---

## 1. 這個專案在做什麼

| 項目 | 說明 |
|---|---|
| **研究問題** | 當 ROS 2 視覺節點過載（overloaded）時，哪一種 frame scheduling policy 能讓最多 frame 在 100 ms 端到端 deadline 內完成？為什麼？ |
| **系統** | ROS 2 Humble · Fast DDS shared memory（每次 run 都在執行期驗證）· MobileViT-S / XXS（timm）· 2 顆綁定的 CPU core、4 GiB 記憶體、無 swap |
| **證據** | 177 個受限條件（constrained）run：75 個 baseline + 102 個交錯式 A/B benchmark（17 blocks × 6 policies），provenance gate 皆為 `VERIFIED` |
| **結論** | 丟棄「預測已無法趕上 deadline」的 frame（**Deadline-Guard**），在主要條件下比 Latest-Frame 降低 effective miss **10.65 pp**；Adaptive 的 utilisation switch 沒有可量測的額外效益。 |

專案由兩個彼此獨立的部分組成：

- **ROS 2 runtime（實測）**：publisher 以固定或分段速率送出 COCO128 影像，detector 用四種排程策略（`fifo`、`latest_frame`、`deadline_guard`、`adaptive`）或 legacy 路徑處理。每一個數字都可以用 SHA-256 從原始 per-frame log 一路追到 Dashboard。
- **EDA-Lite（模擬估計）**：受 *EDA: Energy-Efficient Inter-Layer Model Compilation for Edge DNN Inference Acceleration* 啟發的簡化 layer-fusion 模擬器，在 SRAM 限制下比較 `layerwise`、`greedy`、`dp`、`exhaustive` 排程，輸出 DRAM traffic、energy、latency 的**估計值**。它不重現原論文的 compiler，數值也不是硬體量測。

> **重要**：實測結果（ROS 2）與模擬估計（EDA-Lite）在 Dashboard 與文件中永遠分開呈現，不可混用。

主要發現摘要（完整數字與解讀見 [`docs/RESEARCH_REPORT.md`](docs/RESEARCH_REPORT.md)）：

1. 超過處理能力後，throughput 停在 service-time 上限（S 約 16.7 FPS、XXS 約 53.0 FPS），drop rate 符合 `1 − 1/ρ`。
2. 在 MobileViT-S 20 FPS 主要條件下，**Deadline-Guard − Latest-Frame = −10.65 pp**（95 % CI [−12.30, −9.01]，5/5 blocks 皆較低）。
3. **Adaptive − Deadline-Guard = +0.07 pp**（CI 含 0），utilisation switch 沒有可量測的貢獻。
4. 效益只出現在「過載 *且* inter-arrival + service time > deadline」的負載區間。

---

## 2. 環境需求

| 用途 | Python | 依賴套件 | 安裝方式 |
|---|---|---|---|
| Dashboard、EDA-Lite 模擬器、資料分析、provenance 工具、測試 | 3.10 – 3.13 | **只用 standard library** | 不需安裝任何套件 |
| ROS 2 實驗（publisher / detector 節點、sweep 腳本） | 3.10 | ROS 2 Humble（RoboStack）、conda `opencv`、`torch==2.5.1`、`timm==1.0.11` 等 | `conda env create -f environment.yml` |

- 只想**看結果、跑模擬器、跑測試**：有 `python3` 和 `bash` 就夠了，Linux / macOS 皆可。
- 想**重新量測 ROS 2**：需要 Linux、cgroup v2（`systemd-run`）、`taskset`、GNU `timeout`。詳見 [第 6 節](#6-執行-ros-2-實驗進階)。

> 請使用 `python3`，不是 `python`。

---

## 3. 快速開始（5 分鐘）

```bash
git clone <repo-url> os-aware-eda-lite     # 請用完整 clone，不要 --depth 1（原因見 FAQ）
cd os-aware-eda-lite

python3 -m unittest discover -s tests                      # 1. 跑測試：269 tests（ROS 2 部分以 mock 進行）
python3 scripts/check_runtime_provenance.py                # 2. Phase 2 baseline 資料驗證 → VERIFIED
python3 scripts/check_phase3_provenance.py --expect-runs 102   # 3. Phase 3 A/B 資料驗證 → VERIFIED
bash scripts/serve_dashboard.sh                            # 4. 開啟 Dashboard（127.0.0.1:8765）
```

第 4 步會先檢查 Dashboard 資料是否為最新，再啟動本機伺服器。用瀏覽器打開終端機顯示的網址即可。

---

## 4. 使用 Dashboard

Dashboard 是放在 [`dashboard/`](dashboard/) 的純靜態網站（HTML / CSS / JS、inline SVG 圖表），**不需要網路、不用任何 CDN 或框架**，也可以直接從檔案開啟。

### 4.1 開啟方式

| 情境 | 做法 |
|---|---|
| 線上版（GitHub Pages，啟用後） | `https://samhung1205.github.io/os-aware-eda-lite/`；只有通過所有驗證的 `main` 才會發布（見 [8.1](#81-github-pages-自動發布)） |
| 本機 | `bash scripts/serve_dashboard.sh`，打開 `http://127.0.0.1:8765/` |
| 遠端伺服器 + VS Code Remote SSH | 執行同一個指令；VS Code 會自動轉發 port（Ports 面板 → Open in Browser） |
| 遠端伺服器 + 一般 SSH | 本機執行 `ssh -L 8765:127.0.0.1:8765 <server>`，再打開 `http://127.0.0.1:8765/` |
| 不想啟動伺服器 | 直接用瀏覽器開啟 `dashboard/index.html`（`file://` 也能用） |

`serve_dashboard.sh` 的行為：

- 只綁定 `127.0.0.1`，不會對外網路開放。
- 若 8765 已被占用（例如共用伺服器上的其他使用者），自動改用 8766–8799 中第一個空閒 port，並在終端機提示。
- 指定 port：`PORT=9000 bash scripts/serve_dashboard.sh`（被占用時直接報錯，不會換 port）。
- 啟動前會執行 `python3 -m src.dashboard.build_data --check`；資料過期時拒絕啟動並提示重建指令。
- 按 `Ctrl-C` 停止。

### 4.2 五個主要頁面 + 模擬頁

| 頁面 | 網址 | 回答的問題 |
|---|---|---|
| **Overview** 總覽 | `index.html#overview` | 研究問題；主要結果（S 20 FPS：Latest-Frame 26.5 % → Deadline-Guard 15.9 %，Adaptive 15.9 % 並列；−10.65 pp、95 % CI）與限制說明；系統架構圖（點擊可開啟原尺寸 SVG） |
| **Baseline** 基準量測 | `index.html#baseline` | Throughput 飽和、drop model `1 − 1/ρ`、queue depth 與 latency、注入延遲（Phase 2） |
| **Scheduling** 排程比較 | `index.html#scheduling` | 每個條件下六種 policy：每個 run 的點、block 間連線、paired difference 與 95 % CI；legacy 比較獨立成一個面板 |
| **Mechanism** 機制解釋 | `index.html#mechanism` | Deadline-Guard 如何決定 serve / drop 的概念示意（標示 *Concept illustration*，範例數值非實測）；之後是標示 *Measured* 的量測圖：Frame-age bound vs deadline、drop / late 分解、queueing age、Adaptive − Guard ablation、動態負載 |
| **Evidence** 證據 | `index.html#evidence` | Hash-chain 檢查、run 清單、每個 `meta.json` 的控制變因、方法、限制、排除資料、各來源的 SHA-256 |
| **EDA-Lite simulation**（獨立頁） | `simulation.html` | 不同 SRAM budget、scheduler、OS profile 下的 layer-fusion 估計值，全頁標示 *Estimates* |

| Scheduling | Mechanism | 手機版 |
|---|---|---|
| ![Scheduling](docs/images/dashboard_scheduling.png) | ![Mechanism](docs/images/dashboard_mechanism.png) | ![Phone](docs/images/dashboard_mobile.png) |

### 4.3 篩選條件與分享連結

篩選狀態會寫在網址裡，複製網址即可分享同一個畫面。例如：

```text
index.html#scheduling?c=s20&m=on_time_fps
index.html#baseline?model=mobilevit_xxs
```

| 參數 | 適用頁面 | 可用值 |
|---|---|---|
| `c` | Scheduling | `s20`（預設，主要條件）、`s10`、`s30`、`xxs30d25`、`sdyn`（S 10→20→10 FPS 動態負載） |
| `mc` | Mechanism | 同上，但不含動態條件 `sdyn` |
| `m` | Scheduling | `effective_miss_rate_pct`（預設）、`on_time_fps`、`p99_latency_ms` |
| `model` | Baseline | `both`（預設）、`mobilevit_s`、`mobilevit_xxs` |

其他操作：

- **導覽**：桌面版頂端直接列出所有頁面；手機（寬度 ≤ 640 px）點 **Sections** 按鈕展開選單，點選連結、按 `Esc` 或點選單外即收合。模擬頁的導覽同樣列出全部五個量測頁。
- **圖表**：滑鼠移過或用鍵盤（`Tab`）聚焦圖上的點可看 tooltip；每張圖下方都有對應的資料表。
- **主題**：依系統設定自動切換淺色 / 深色。
- **標籤**：*Measured* 為實測、*Estimates* 為模擬估計、*Concept illustration* 為示意圖。

### 4.4 重建 Dashboard 資料

只有在修改了正式表格或 `src/dashboard/build_data.py` 之後才需要：

```bash
python3 -m src.dashboard.build_data          # 重建 dashboard/data/dashboard_data.{json,js} 與 manifest
python3 -m src.dashboard.build_data --check  # 只檢查是否為最新
```

| Exit code | 狀態 | 意義 |
|---|---|---|
| 0 | `OK` / `CURRENT` | 成功 / 已是最新 |
| 1 | `BLOCKED` | 缺少輸入檔 |
| 2 | `BROKEN` | Hash 或不變量檢查失敗，或混入 pilot / legacy-unverified / example 資料 |
| 3 | `STALE` | （`--check`）已提交的 bundle 與重新建置的結果不同 |

---

## 5. 使用 EDA-Lite 模擬器

EDA-Lite 讀取簡化的 MobileViT block profile（`data/model_profiles/mobilevit_{xxs,s}_simplified.json`），在 SRAM 限制下選擇 layer fusion 切分方式，輸出 CSV 估計值。**全部只需 standard library。**

### 5.1 比較 MobileViT-XXS 與 MobileViT-S

```bash
python3 -m src.eda_lite.run_profile_sweep \
  --config experiments/eda_lite/mobilevit_profile_sweep.json \
  --output /tmp/eda_lite_mobilevit_profile_sweep.csv
```

輸出旁會產生 `.provenance.json` sidecar，記錄 config、profile 與輸出的 SHA-256。

### 5.2 單一 profile 的 SRAM sweep

```bash
python3 -m src.eda_lite.run_simulation \
  --profile data/model_profiles/mobilevit_xxs_simplified.json \
  --config experiments/eda_lite/mobilevit_sram_sweep.json \
  --output /tmp/eda_lite_mobilevit_xxs_sram_sweep.csv
```

### 5.3 摘要與 SVG 圖表

```bash
python3 -m src.eda_lite.analyze_results \
  --input /tmp/eda_lite_mobilevit_profile_sweep.csv \
  --summary-output /tmp/eda_lite_mobilevit_profile_summary.csv \
  --figures-dir /tmp/eda_lite_figures \
  --plot-os-profile normal \
  --plot-model mobilevit_s_simplified_profile_estimate
```

CSV 含多個模型時，**一定要加 `--plot-model`**，避免把不同模型畫在同一張圖。

### 5.4 可用的設定檔

| 設定檔 | 用途 |
|---|---|
| `experiments/eda_lite/mobilevit_profile_sweep.json` | XXS vs S 比較 |
| `experiments/eda_lite/mobilevit_sram_sweep.json` | 單一 profile 的 SRAM / scheduler / OS profile sweep |
| `experiments/eda_lite/mobilevit_sensitivity_sweep.json` | SRAM 128–2048 KB × 模擬 deadline × 內建 profile，四種 scheduler |
| `experiments/eda_lite/mobilevit_runtime_aware_sweep.json` | 從外部 JSON 讀 OS profile（預設是 **example** 檔，不是量測資料） |

### 5.5 輸出欄位怎麼讀

- **Scheduler**：`layerwise`（不融合，baseline）、`greedy`、`dp`（精確最小化總成本）、`exhaustive`（窮舉 oracle，層數 ≤ 20，用來驗證 `dp`）。
- **內建 OS profile**：`pure`（純 compiler，無 OS 壓力）、`normal`、`high_latency`、`high_memory_pressure`。
- **主要欄位**：selected subgraphs、DRAM traffic、energy、latency、peak SRAM、max fusion depth、`os_aware_total_cost` 及其各項、`feasible` / `infeasible_reason`。
- 所有 energy / latency 都是 **cost-model 單位的估計值**，不是硬體量測；摘要中 scheduler 平手會標成 `greedy=dp`。

成本模型公式、profile 與 config 格式見 [`docs/REFERENCE.md`](docs/REFERENCE.md)。

---

## 6. 執行 ROS 2 實驗（進階）

> 只有想**重新量測**時才需要。看結果與驗證資料不需要 ROS 2。

### 6.1 安裝

```bash
conda env create -f environment.yml          # ROS 2 Humble（RoboStack）、Python 3.10、pinned torch / timm
# 或用凍結版：conda env create -f environment.lock.yml
bash experiments/ros2/prepare_coco128.sh     # 下載 COCO128 影像到 data/raw/images/（git-ignored）
```

- `cv2` 來自 conda-forge `opencv`，請勿在 ROS 環境中 `pip install opencv-python`；`numpy` 必須 `< 2`。
- Detector 使用 `timm.create_model(..., pretrained=False)`：**隨機權重，只量 latency，不量 accuracy**。

### 6.2 系統架構

![Architecture](dashboard/assets/architecture.svg)

- **Publisher** `image_stream_node`：以固定速率或分段速率（`fps_schedule="10@20,20@20,10@20"`）送出約 1 MB 的 COCO128 影像，每個 frame 寫一列 log。
- **Transport**：Fast DDS SHM-only profile（16 MiB segment）。每次 run 會用 runtime probe 證明沒有開 UDP socket、segment 大小正確，否則該 run 失敗。
- **Detector** `mobilevit_detector_node`，兩種執行路徑：
  - *legacy*：在 DDS callback 內直接推論，KEEP_LAST depth 是唯一的 queue；
  - *application*：ingestion callback → bounded queue（capacity 5）→ 單一 inference worker，policy 為 `fifo`、`latest_frame`、`deadline_guard` 或 `adaptive`。
- **每個 run 的證據檔**：detector CSV、publisher CSV、`meta.json`（讀回的資源限制、版本、git commit / dirty）、`probe.json`。

### 6.3 排程策略說明

| Policy | 行為 |
|---|---|
| `legacy_qos` | 推論在 DDS callback 內，等於 Phase 2 原始路徑 |
| `fifo` | 依到達順序處理 |
| `latest_frame` | 永遠處理最新的 frame |
| `deadline_guard` | 若 `frame age + 預估 service time > deadline` 就丟棄（`deadline_infeasible`），再處理最新的可行 frame |
| `adaptive` | 同 Deadline-Guard，但預估 utilisation ρ̂ < 1 時改用 EDF（最舊的可行 frame） |

`deadline_guard` 與 `adaptive` 共用 P90 service-time 估計（最近 32 個 frame）。

### 6.4 執行實驗

建議設定（Phase 2 / 3 使用的受限條件）：

```bash
export CPU_SET=12,14 MEMORY_MAX=4G MEMORY_SWAP_MAX=0 NICE_LEVEL=10
export ROS_DOMAIN_ID=87 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTRTPS_DEFAULT_PROFILES_FILE="$PWD/experiments/ros2/fastdds_shm_large.xml"
```

`CPU_SET` 請選擇**本機允許且閒置的 CPU**，不要假設是 `0,1`。

| 目的 | 指令 |
|---|---|
| Baseline（FPS / QoS / overload sweep，受限 scope） | `bash scripts/run_baseline_experiments.sh` |
| 單一 sweep | `bash experiments/ros2/run_fps_sweep.sh`、`run_qos_sweep.sh`、`run_overload_sweep.sh` |
| 單一條件下比較所有 policy | `SWEEPS=sched bash scripts/run_baseline_experiments.sh` |
| 正式交錯式 A/B benchmark | `bash experiments/ros2/run_sched_formal.sh` |
| 只印出計畫不執行 | 在 pilot / formal driver 前加 `DRY_RUN=1` |

注意事項：

- 腳本**不會**執行 `sudo` 或修改 sysctl；資源限制無法讀回驗證時，run 會在啟動前失敗。
- 每個 run 寫獨立的 `<run_id>.csv`，不會覆寫或附加到既有資料；失敗的 run 會被改名為 `*.failed`。
- 正式 driver 在每個 block 前要求 git tree 乾淨（否則 exit 3），並等待主機負載降低（`host_load_gate`，逾時 exit 4）。

完整的環境變數與參數：[`experiments/ros2/README.md`](experiments/ros2/README.md)、[`docs/REFERENCE.md`](docs/REFERENCE.md)。

---

## 7. 分析資料與驗證 Provenance

### 7.1 資料流

```text
results/raw/{ros2,ros2_phase3_formal}/<run_id>.{csv,publisher.csv,meta.json,probe.json}   （原始資料，永不修改）
  → results/csv/*_summary.csv + .manifest.json                    analyze_runtime
  → results/csv/ros2_baseline_*.csv、ros2_phase3_formal_*.csv + manifests
  → scripts/check_runtime_provenance.py / check_phase3_provenance.py   VERIFIED
  → dashboard/data/dashboard_data.{json,js} + .manifest.json       src.dashboard.build_data
```

### 7.2 常用指令

```bash
# 分析 ROS 2 原始 CSV → 每個 run 的摘要 + SVG
python3 -m src.ros2_runtime.analyze_runtime \
  --input results/raw/ros2 \
  --summary-output /tmp/ros2_runtime_summary.csv \
  --figures-dir /tmp/ros2_figures

# 驗證資料鏈
python3 scripts/check_runtime_provenance.py                    # Phase 2
python3 scripts/check_phase3_provenance.py --expect-runs 102   # Phase 3

# 從 raw 重建所有正式表格並比對
python3 scripts/check_table_regeneration.py
```

### 7.3 驗證結果代碼

| Exit code | 狀態 | 意義 |
|---|---|---|
| 0 | `VERIFIED` | 原始資料 → 摘要 → 表格的 SHA-256 全部吻合 |
| 1 | `BLOCKED` | 缺少某個環節（例如 CI 沒有 ROS 2 時屬正常） |
| 2 | `BROKEN` | Hash 不符、資料過期，或資源限制未驗證 |

`results/raw/ros2_phase3_pilot/` 的 pilot 資料因當時 working tree 是 dirty，gate 會刻意回報 `BROKEN`，該資料僅作紀錄、從未使用。

各結果檔案的追蹤規則與可信程度見 [`results/README.md`](results/README.md)；完整的可重現性說明見 [`docs/DATA_PROVENANCE.md`](docs/DATA_PROVENANCE.md)。

---

## 8. 測試與 CI

```bash
python3 -m unittest discover -s tests     # 269 tests，stdlib only
bash scripts/ci_checks.sh all             # 與 GitHub Actions 完全相同的檢查
```

`ci_checks.sh` 也可以只跑單一步驟：

| 步驟 | 內容 |
|---|---|
| `tests` | 單元 / 整合測試 |
| `shell` | 所有 shell script 的 `bash -n` 語法檢查 |
| `audit` | `scripts/audit_repro.py --strict` 回歸檢查 |
| `provenance` | Phase 2 + Phase 3 provenance gate |
| `dashboard` | Dashboard bundle 是否為最新 |
| `repeat [N]` | 連續跑 N 次測試（預設 5） |

CI（`.github/workflows/ci.yml`）在 Python 3.10–3.13 上執行上述檢查，不安裝 ROS 2。

### 8.1 GitHub Pages 自動發布

`.github/workflows/pages.yml` 在 push 到 `main` 或手動執行（`workflow_dispatch`）時：

1. 以完整 Git 歷史 checkout（`fetch-depth: 0`，Phase 3 gate 需要量測 commit `7f0f160`）。
2. 依序檢查：Phase 2 provenance、Phase 3 provenance（102 runs）、表格可從 raw 重建、Dashboard bundle 為最新。任一步失敗就不發布；`BLOCKED` 也算失敗。
3. 全部通過後，用 GitHub 官方 actions（`configure-pages`、`upload-pages-artifact`、`deploy-pages`）**只發布 `dashboard/`**。

不需要 ROS 2、外部 CDN 或後端；Dashboard 只用相對路徑，可在 `/<repository>/` 子路徑下運作（有測試檢查）。首次使用需在 GitHub repo 的 **Settings → Pages → Build and deployment → Source** 選 **GitHub Actions**。

---

## 9. 專案結構

```text
src/ros2_uav_pipeline/   ROS 2 package：publisher、detector、排程策略（scheduling.py）、launch file
src/ros2_runtime/        分析工具：analyze_runtime、aggregate_{baseline,scheduling}、analyze_dynamic_phases、
                         run_metadata、runtime_probe、host_load_gate、build_os_profiles、plot_scheduling
src/eda_lite/            模擬器：model_loader、cost_model、schedulers、run_simulation、run_profile_sweep…
src/dashboard/           build_data.py：已驗證表格 → Dashboard 資料 bundle
src/provenance.py        SHA-256 紀錄、manifest、provenance 狀態
dashboard/               index.html、simulation.html、assets/、data/
experiments/ros2/        sweep / 正式 A/B driver、Fast DDS SHM profile
experiments/eda_lite/    模擬設定、OS profile（verified / example / legacy-unverified）
data/model_profiles/     簡化的 MobileViT block profile
results/                 raw/（原始 run）、csv/（表格 + manifest）、figures/（腳本產生的 SVG）
scripts/                 CI 步驟、provenance gate、表格重建檢查、Dashboard 伺服器
tests/                   unittest，stdlib only
.github/workflows/       ci.yml（每次 push 的 CI）、pages.yml（驗證後發布 Dashboard 到 GitHub Pages）
LICENSE                  MIT
docs/                    使用參考手冊、研究報告、資料來源報告、開發歷程、截圖
report/                  各階段的詳細結果報告、final report 草稿、AI interaction log
```

---

## 10. 常見問題（FAQ）

**Q：`check_phase3_provenance.py` 回報 `BROKEN`，但我什麼都沒改？**
A：這個 gate 會確認量測時的 commit `7f0f160` 是 `HEAD` 的祖先，且 runtime 程式碼之後沒有變動。請使用完整 clone（不要 `--depth 1`）；合併此歷史時不要 squash 或 rebase。

**Q：`serve_dashboard.sh` 說資料不是最新？**
A：執行 `python3 -m src.dashboard.build_data` 重建，然後提交 `dashboard/data/`（CI 會檢查）。

**Q：Port 8765 被占用？**
A：腳本會自動改用下一個空閒 port 並提示；或用 `PORT=<port>` 指定。

**Q：可以把 EDA-Lite 的 energy 當成實際耗電嗎？**
A：不行。EDA-Lite 的 energy / latency 都是 cost-model 估計值；本專案**沒有量測任何能耗**。

**Q：為什麼 detector 用隨機權重？**
A：本研究只關心排程與 latency，不評估偵測準確度；隨機權重的計算量與預訓練權重相同。

**Q：`runtime_os_profiles.example.json` 或 `legacy_unverified` 的資料可以當量測結果引用嗎？**
A：不行。example 是範例，legacy-unverified 沒有原始資料可驗證。只有 provenance gate 回報 `VERIFIED` 的 ROS 2 資料才能稱為「measured」。

---

## 11. 使用限制與注意事項

- **單一主機、單一 session**：結果僅描述這台 i7-13700（兩顆 P-core、`powersave` governor、共用主機）。
- **樣本數小**：主要條件 5 blocks，其他條件 3 blocks；只報告 effect size 與信賴區間，不宣稱統計顯著。
- **單一參數組合**：100 ms deadline、queue capacity 5、一組 Adaptive 參數、一種負載階梯。
- **只量 latency**：隨機權重、無 accuracy、無能耗量測。
- **Legacy vs application** 的差異包含架構差異，不能歸因於 policy。
- **EDA-Lite 是簡化模擬器**：coarse block profile（非 ONNX 精確結構）；OS profile 只改變成本權重，在這些 profile 上不改變選出的切分。

詳細討論與未來工作見 [`docs/RESEARCH_REPORT.md`](docs/RESEARCH_REPORT.md)。

---

## 12. 延伸文件

| 文件 | 內容 |
|---|---|
| [`docs/README.md`](docs/README.md) | 文件索引 |
| [`docs/RESEARCH_REPORT.md`](docs/RESEARCH_REPORT.md) | 研究結果報告：主要發現、機制、方法、限制、未來工作 |
| [`docs/DATA_PROVENANCE.md`](docs/DATA_PROVENANCE.md) | 資料來源與可重現性報告 |
| [`docs/DEVELOPMENT_HISTORY.md`](docs/DEVELOPMENT_HISTORY.md) | 開發歷程與各階段報告索引 |
| [`docs/REFERENCE.md`](docs/REFERENCE.md) | 詳細指令參考、CSV 規格、設定檔格式、成本模型（英文） |
| [`experiments/ros2/README.md`](experiments/ros2/README.md) | ROS 2 實驗腳本與環境變數 |
| [`results/README.md`](results/README.md) | 結果檔案清單與 provenance 狀態 |
| [`AGENTS.md`](AGENTS.md) | 貢獻者 / AI agent 規則 |

---

## 13. 授權與第三方資料

- **本專案程式碼與文件**：[MIT License](LICENSE)，Copyright (c) 2026 samhung1205 and contributors。下列第三方資料、模型與軟體仍依其各自的授權。
- **影像不隨 repo 散佈**：benchmark 使用 COCO 2017 的 COCO128 子集（Ultralytics 版本），由 `experiments/ros2/prepare_coco128.sh` 下載到 git-ignored 的 `data/raw/images/`。COCO annotations 為 CC BY 4.0，影像保留原 Flickr 授權（[COCO terms of use](https://cocodataset.org/#termsofuse)）。`results/raw/` 只記錄 frame id 與時間，不含影像內容。
- **模型**：MobileViT（Mehta & Rastegari, ICLR 2022），透過 `timm`（Apache-2.0）建立隨機權重，不包含也不下載預訓練權重。`data/model_profiles/*` 是依公開架構整理的簡化 block 摘要。
- **Runtime**：ROS 2 Humble、eProsima Fast DDS（Apache-2.0）、PyTorch（BSD-3-Clause），需另行安裝，未隨 repo 提供。
- **Run metadata**：`results/raw/**/*.meta.json` 與 `*.probe.json` 記錄了量測主機的 kernel、CPU 型號、cgroup scope 及本機安裝路徑；它們是 SHA-256 provenance 鏈的一部分，保持原樣不修改。
