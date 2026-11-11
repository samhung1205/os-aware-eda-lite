# Phase 4：Dashboard & Portfolio Finalization — 結果

- 分支：`phase4/dashboard-finalization`（基於 `b1786dc`）；未 push、未 merge、`main` 未修改。
- 狀態：**完成**。CI 全綠：266 tests OK，Phase 2 與 Phase 3 provenance 皆 `VERIFIED`，表格可從 raw 重建，dashboard bundle 為 `CURRENT`。
- 未修改：排程策略（`src/ros2_uav_pipeline/`）、成本模型（`src/eda_lite/`）、分析程式（`src/ros2_runtime/`）、正式量測資料與衍生表格（`results/raw`、`results/csv`、`results/figures`）、實驗設定。`results/` 下唯一的變更是 `results/README.md` 新增一列說明。

## 1. 功能

### Dashboard（`dashboard/`）

靜態網站：HTML、CSS 與原生 JS，圖表為 inline SVG。不使用 CDN、框架或後端，可離線使用，`file://` 直接開啟也能運作。

| 頁面 / View | 內容 |
|---|---|
| **Overview** | 研究問題與資料推導出的回答；主結果 Guard − Latest −10.65 pp 與 95% CI 條；Adaptive − Guard、Adaptive − Latest、動態負載、飽和吞吐量；系統架構圖；「量測 vs 估計」的區分 |
| **Baseline** | Processed vs offered FPS（飽和點）；實測 drop vs `1 − 1/ρ` 預測；queue depth 對 P50/P99 latency 的影響（含 deadline）；injected delay 與 effective miss 的關係；25 個 condition 的完整表。可依模型篩選 |
| **Scheduling** | 6 個 arm 的 per-run 點圖（application / legacy 分組）；每個 block 的 Latest → Guard → Adaptive slope；同架構的 paired forest（Guard−Latest、Adaptive−Latest、Adaptive−Guard）；**與 legacy 的比較放在另一張圖，並標示包含架構差異**；per-arm 表與 arm 定義。可依 condition 與 metric（effective miss / on-time FPS / P99）篩選 |
| **Mechanism** | Frame-age 上界（inter-arrival + service）vs deadline，以及預測與實測的 late %；drop / late 分解；inference 開始時的 frame age；Adaptive − Guard ablation（5 個 condition 與動態 phase）及 decision counts；動態負載 phase 的 small multiples |
| **Evidence** | Hash-chain 檢查結果；run inventory（75 + 102）；從每個 `meta.json` 讀出的 25 個控制變數；Phase 2 vs Phase 3 環境；統計方法；限制；排除的資料；重現指令；所有來源檔與 SHA-256 |
| **EDA-Lite simulation**（`simulation.html`，獨立入口） | 依 SRAM 預算 × scheduler × OS profile 的估計值；全頁標示 *Estimates*，與實測頁面分離。只使用 built-in OS profile 的資料列 |

### 資料管線（`src/dashboard/build_data.py`，stdlib only）

- **輸入**：只讀 Phase 2 baseline 與 Phase 3 formal 的 CSV 和 manifest（共 191 個輸入檔，含 raw run 的 `meta.json`）。重新驗證所有 aggregate / summary manifest 的 SHA-256。
- **排除規則**：
  - 路徑包含 `pilot`、`legacy_unverified`、`example`、`runtime_aware` → BROKEN。
  - run id 不符合 formal 格式、非 `constrained`、DDS 未驗證、block 不完整（缺 arm）→ BROKEN。
  - 模擬資料列不是 `builtin` profile → BROKEN。
- **輸出**：`dashboard/data/dashboard_data.json`、`.js`（`window.DASHBOARD_DATA`），以及 `.manifest.json`（輸入與輸出的 SHA-256）。
- **計算位置**：所有 KPI 與 finding 的文字都在 builder 裡從資料計算，前端只負責格式化。
- **可重現性**：輸出是 deterministic 的（沒有時間戳、沒有 HEAD），所以 `--check` 可以逐 byte 比對。
- **結束碼**：0 OK、1 BLOCKED（缺輸入）、2 BROKEN（hash 或不變量失敗、混入非正式資料）、3 STALE（已提交的 bundle 與重建結果不同）。發生錯誤時不寫出任何檔案。

### 其他

- `scripts/check_table_regeneration.py`：把 raw runs 重建成 Phase 2/3 表格（寫到暫存目錄），再與已提交的表格比對。
  - Phase 3 的 7 張表與 `ros2_baseline_conditions.csv`：逐 byte 相同。
  - Phase 2 的兩張 per-run 表：所有已提交欄位的值都相同。目前的 analyzer 在 Phase 3 新增了 20 欄，所以不改寫這兩個檔案。
- `scripts/serve_dashboard.sh`：先執行 `build_data --check`，再以 `python3 -m http.server` 只綁定 `127.0.0.1`（預設 port 8765）。
- CI：
  - `scripts/ci_checks.sh` 新增 `dashboard` 步驟（表格重建 + bundle check），並納入 `all`。
  - `.github/workflows/ci.yml` 加入同一步驟。
  - stdlib-only 測試的掃描範圍加入 `src/dashboard`。
- 文件：
  - README 改寫為 portfolio 形式（摘要、主要發現、dashboard、架構、quickstart、methodology、reproducibility、limitations、future work、phase 歷程）。
  - 原 README 的詳細操作手冊原封不動移到 `docs/REFERENCE.md`。
  - 架構圖：`dashboard/assets/architecture.svg`。截圖：`docs/images/`。
  - 已更新 `AGENTS.md`、`results/README.md`、`report/ai_interaction_log.md`。

## 2. UI / UX

- **版面**：每個 view 以一句結論作為標題，下面是支撐的圖表，每張圖的副標說明資料來源與 n。不使用 KPI 卡片牆，只有一列 stat row 和一個 hero 數字。
- **色彩**：
  - 使用經過驗證的 categorical 色盤，並依固定順序配色：Latest 藍、Guard 橘、Adaptive 青，其餘依序。
  - 顏色跟著實體（arm 或模型）走，切換篩選器不會改變顏色。
  - Dropped / late 使用另外兩個色槽。
  - 支援 light / dark（`prefers-color-scheme`）。
- **圖表**：
  - 細線、直接標籤；兩個以上 series 時有 legend。
  - 參考線（deadline、0、`processed = offered`）標籤放在圖外。
  - 有 tooltip（hover 與鍵盤 focus 都可觸發）。
  - 每張圖都附可展開的資料表。
- **互動**：condition、metric、模型篩選器放在圖表上方同一列。狀態存在 URL，可分享，例如 `#scheduling?c=s20&m=on_time_fps`。
- **RWD**：
  - 寬度 ≤ 620 px 時改為單欄。
  - Forest plot 在窄螢幕把標籤疊在 CI 線上方。
  - 表格可水平捲動。
  - 已在 1440 px 與 390 px 截圖檢查。
- **誠實呈現**：
  - 同時顯示 Guard 與 Adaptive。Adaptive − Guard 寫成 "no measurable benefit (not an equivalence test)"。
  - 跨架構比較另外標示。
  - 樣本數、CI、block 符號計數隨處可見。
  - 不宣稱統計顯著、不宣稱跨硬體結果、不宣稱能耗。
- **錯誤狀態**：資料檔不存在時顯示 "Dashboard data not found" 與重建指令。JS 錯誤會以 callout 顯示，不會出現空白頁。

截圖：`docs/images/dashboard_{overview,baseline,scheduling,mechanism,evidence,simulation,mobile}.png`。

## 3. 驗證結果

| 檢查 | 結果 |
|---|---|
| `bash scripts/ci_checks.sh all` | exit 0 |
| Unit / integration tests | 266 tests OK（1 skipped：repo 有 raw 資料時，該 BLOCKED 測試改由 gate 本身檢查） |
| `bash -n` | 全部 OK |
| Audit regressions | 0/17 reproduced |
| Phase 2 provenance（`check_runtime_provenance.py`） | **VERIFIED**（75 raw CSV、75 meta） |
| Phase 3 provenance（`check_phase3_provenance.py`） | **VERIFIED**（102 runs @ `7f0f160`，dirty=false；runtime code 至 HEAD 未變；17 blocks；manifests hash-match） |
| 表格重建（`check_table_regeneration.py`） | REPRODUCED |
| `python3 -m src.dashboard.build_data --check` | CURRENT（191 inputs） |
| `serve_dashboard.sh` | `127.0.0.1:<port>` 回應 200，`ss` 顯示只在 loopback listen |

新增測試 `tests/test_dashboard.py`（28 tests）：

- **Bundle**：
  - 已提交的 bundle 是最新的。
  - Build 是 deterministic 的，沒有時間戳。
  - JS 與 JSON 內容相同。
  - Manifest hash 與輸入、輸出相符。
  - 來源只有 formal 資料。
  - Run 數等於 raw `meta.json` 的數量（75 / 102）。
- **KPI 一致性**：
  - 主要 KPI 等於 `ros2_phase3_formal_paired.csv` 的值（mean、CI、n_neg、n_blocks）。
  - Per-arm 表等於 `arms.csv`。
  - 每個 condition 都同時有 Guard、Adaptive 與 Adaptive−Guard 的配對。
  - Finding 文字引用的是 KPI 的數字，且不含 significant、energy 等詞。
  - 跨架構比較都有標記。
  - Feasibility 由資料推導。
  - 模擬資料獨立，且只用 builtin profile。
- **失敗行為**（暫存 root：複製 CSV、symlink raw，修改後重算 hash）：
  - 缺少 CSV、sidecar 或 raw 目錄 → BLOCKED，且不寫出檔案。
  - 竄改表格 → BROKEN（SHA-256）。
  - 混入 pilot run → BROKEN。
  - 出現 unconstrained run → BROKEN。
  - 缺少 arm → BROKEN。
  - 非 builtin 模擬資料列 → BROKEN。
  - 讀取 pilot、legacy、example 路徑 → BROKEN。
  - 輸出被改過或缺檔 → STALE。
- **前端**：
  - 沒有外部 URL。
  - 引用的本地檔案都存在。
  - 5 個 view 加上獨立的模擬入口。
  - 有 empty state。
  - Preview server 只綁定 localhost。

## 4. 操作方式

```bash
# 在 server 上（VS Code Remote SSH 終端機）
bash scripts/serve_dashboard.sh            # 檢查資料後，服務 127.0.0.1:8765
# VS Code 會自動 forward port → Ports 面板 → Open in Browser
# 不用 VS Code：ssh -L 8765:127.0.0.1:8765 <server>，再開 http://localhost:8765
PORT=8800 bash scripts/serve_dashboard.sh  # 換 port

# 資料更新流程
python3 scripts/check_table_regeneration.py   # raw → 表格，與已提交的比對
python3 -m src.dashboard.build_data           # 表格 → dashboard/data/
python3 -m src.dashboard.build_data --check   # CI 使用；exit 3 = STALE
bash scripts/ci_checks.sh all
```

不需要伺服器時，也可以直接開啟 `dashboard/index.html`。沒有公開部署，也沒有開放任何網路埠；server 只綁定 loopback。

## 5. Git diff（相對於 `b1786dc`）

```text
 .github/workflows/ci.yml                    |     4 +-
 AGENTS.md                                   |     7 +-
 README.md                                   |   801 +-   (改寫；詳細手冊移至 docs/REFERENCE.md)
 dashboard/assets/{app,charts,simulation}.js |  1061 +
 dashboard/assets/{style.css,architecture.svg,favicon.svg} | 421 +
 dashboard/data/dashboard_data.{json,js,manifest.json}     | 生成檔（~0.9 MB）
 dashboard/{index,simulation}.html           |   113 +
 docs/REFERENCE.md                           |   543 +
 docs/images/*.png                           |   7 張截圖（2.3 MB）
 report/PHASE4_RESULT.md, report/ai_interaction_log.md
 results/README.md                           |     1 +
 scripts/check_table_regeneration.py         |   100 +
 scripts/ci_checks.sh                        |    15 +-
 scripts/serve_dashboard.sh                  |    23 +
 src/dashboard/{__init__,build_data}.py      |   834 +
 tests/test_dashboard.py                     |   359 +
 tests/test_engineering_quality.py           |     2 +-
```

## 6. 尚存限制

- **研究層面**（沿用 Phase 2/3）：單一主機（`powersave` governor、共用機器）；primary condition 5 個 block，其他 3 個；單一參數組（deadline 100 ms、queue 5、一組 Adaptive 參數）；random-init 權重（只量 latency）；沒有量測能耗。Adaptive − Guard 沒有做 equivalence test。
- **Dashboard 層面**：
  - Bundle 約 0.9 MB，會整份載入。對 177 個 run 來說足夠，但資料量再大一個數量級時應拆檔。
  - 截圖使用 headless Firefox。Chrome 和 Safari 只做了靜態檢查（沒有使用非標準 API），沒有實際測試。
  - 圖表有 tooltip 與鍵盤 focus，也都附資料表，但沒有用 screen reader 實測。
- **重現性**：Phase 2 的兩張 per-run 表是用較早版本的 analyzer 產生的。目前的 analyzer 會多輸出 20 欄，已提交欄位的值完全相同。為了不改動正式資料，這兩個檔案沒有重寫。
- **EDA-Lite**：模擬頁只使用 builtin profile 的 sweep。用 verified OS profile 重跑 runtime-aware sweep 仍列為 future work。

## 7. 完成狀態

| 項目 | 狀態 |
|---|---|
| Dashboard 5 個 view + 獨立模擬入口 | 完成 |
| 只使用正式資料、從 CSV / manifest 產生、無手寫數字 | 完成（builder 強制執行，測試覆蓋） |
| Guard / Adaptive 並列；註明 Adaptive 沒有額外貢獻 | 完成 |
| 樣本數、CI、控制變數、限制 | 完成（Evidence view） |
| README、架構圖、截圖 | 完成 |
| 從 raw 重建資料的方法 | 完成（`check_table_regeneration.py` + `build_data`，已納入 CI） |
| 測試（pipeline / manifest / KPI / 缺資料） | 完成（28 tests） |
| CI / audit / provenance，Phase 2/3 VERIFIED | 完成 |
| VS Code Remote SSH 預覽，不開放 port | 完成 |
| 不 push、不 merge、不改 main | 遵守（只在 `phase4/dashboard-finalization` 本地 commit） |
