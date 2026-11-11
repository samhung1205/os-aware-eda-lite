# Final QA & Release Preparation

- 分支：`phase4/dashboard-finalization`（`main` = `6c743fc`，branch 比 `main` 多 12 個 commit，含 Phase 2–4）。
- 本次只做 QA 與有證據問題的最小修正；沒有新增功能、沒有重構。未 push、未 merge、未修改 `main`、未公開部署。
- **結論：工程與內容已達公開標準。正式公開前，還需要 repo 擁有者完成 3 項決定（§7，主要是 LICENSE）。**

## 1. 總覽

| 項目 | 結果 |
|---|---|
| UI/UX（6 個頁面 × 3 種寬度 × light/dark、篩選器、tooltip、表格） | **PASS**（找到 8 個問題，皆已修正並重測） |
| KPI、CI、限制與消融結論正確性 | **PASS**（525 個 paired 估計值經獨立重算，0 差異） |
| CI / audit / Phase 2 & 3 provenance / 表格重建 / bundle check | **PASS** |
| Phase 2/3 正式資料與 runtime 程式碼未被更動 | **PASS** |
| GitHub CI 在 shallow clone 下的 Phase 3 gate | **已修正**（原本 PR 一推上去 CI 就會失敗，見 §4.3） |
| 公開安全（secrets、憑證、內部 IP） | **PASS**：沒有發現 |
| 公開安全（個人 / 實驗室識別資訊） | **需擁有者決定**（低風險，見 §3） |
| 授權 | **需修正**：repo 沒有 LICENSE（見 §3.3） |

## 2. UI/UX Final Review

### 2.1 方法

- 使用真實 Firefox（headless），透過 geckodriver 的 W3C WebDriver 驅動。Client 是自寫的 stdlib 腳本，不需安裝任何套件。
- Server 只綁定 `127.0.0.1`。
- 檢查矩陣：
  - 頁面：Overview、Baseline、Scheduling、Mechanism、Evidence、Simulation。
  - 寬度：1440 px 桌面、820 px 平板、390 px 手機。Firefox 視窗最小寬度約 450 px，所以手機寬度是用 390 × 844 的 iframe 取得真實 viewport。
  - 主題：light / dark。
- 共 132 次頁面狀態稽核、447 個 SVG 圖表。每次都檢查：
  - JS 錯誤 callout、頁面水平捲動；
  - SVG 文字互相重疊、文字超出 panel 或被裁切；
  - HTML 元素超出 viewport、ellipsis 截斷。
- 互動：
  - 逐一點擊每個 segmented 篩選器，檢查 `aria-pressed`、URL hash 與重繪後的稽核結果；
  - 展開所有 `<details>` 資料表；
  - 用 deep link `#scheduling?c=s30&m=p99_latency_ms` 重新載入，確認狀態還原；
  - 真實滑鼠 hover：Scheduling 57/57、Mechanism 25/25，其他 view 抽樣 8/8；
  - 真實 Tab 鍵盤導覽，檢查 tooltip 與 focus ring。
- 人工檢視 desktop / phone / dark 的全頁截圖。

### 2.2 發現並已修正的問題（皆有重現證據）

| # | 問題 | 證據 | 修正 |
|---|---|---|---|
| 1 | 鍵盤 focus 到畫面外的圖表標記時，tooltip 一出現就消失 | focus 會讓瀏覽器 scroll，觸發 `scroll → hide`。Tab 測試：Overview 1/5、Simulation 11/24 顯示 | `charts.js`：focus 中的標記在 scroll 時重新定位 tooltip，而不是隱藏 |
| 2 | Hover 在 CI 線、平均值刻度、row 文字上時沒有 tooltip | 這些元素蓋在 row 的 hit area 上面，`elementFromPoint` 回傳沒有 `data-tip` 的 `<line>` | `style.css`：`.chart svg *` 不接收 pointer，只有 `[data-tip]` 接收（1 條規則，涵蓋 forest / dot-row） |
| 3 | 窄螢幕上 Mechanism 圖的註記「158 ms · not overloaded, age ≈ 0」超出 panel | 488 / 390 px 截圖 | `hbars` 新增 `valueNote`：只有放得下時才顯示（同列已變灰，下方表格也有 regime 說明） |
| 4 | 窄螢幕上 row label「XXS · 30 FPS + 25 ms」被截斷 | 390 px 截圖 | 窄版 label 欄寬上限從 112 改為 140 px |
| 5 | 窄螢幕上 Simulation 的線末標籤「layerwise (no fusion)」超出 panel | 390 px 截圖、稽核結果 | `lineChart` 的右側留白改由最長的 label 計算 |
| 6 | Baseline 圖中 S / XXS 線末標籤重疊 5 px；只選 XXS 時「deadline 100 ms」超出；手機上「measured = predicted」超出 | 稽核結果 | 線末標籤間距由 14 改為 16 px；參考線標籤靠近右緣時改向左放；對角線標籤沿線下移到放得下為止 |
| 7 | Overview hero 的 CI 條在 dark mode 下刻度幾乎看不見，且兩種主題都沒有 0 參考線 | Dark 截圖；計算後 `fill` 為預設黑色、`stroke` 為 none | `.ci-strip` 套用與 `.chart` 相同的 tick / grid / zero / ring 樣式 |
| 8 | CI 條最左邊的刻度「−15」負號被裁掉，看起來像「-15」 | 截圖（非 `.chart` 的 SVG 預設 `overflow: hidden`） | 刻度範圍內縮 16 px |

修正後的最終 matrix：132 次稽核，沒有任何版面問題（重疊、裁切、超出、水平捲動、JS 錯誤皆為 0）。

### 2.3 經判斷不是問題的項目

- **Forest plot 的標籤與統計行 bbox 重疊 3–4 px**：這是字型 line box 的重疊，放大截圖確認字形沒有接觸。
- **Simulation 的 Tab 測試只有 12/24 顯示 tooltip**：後 12 次 Tab 已經離開文件（focusout → hide 是正確行為）。逐一檢查後，每個不同的標記都正確顯示。
- **初始版 hover 測試失敗**：測試是在 scroll 之後立刻 hover，而 scroll 本來就會隱藏 pointer tooltip（設計如此）；另外 polyline 的 bbox 中心點不在線上。把滑鼠先移開再 hover 後，結果為 57/57、25/25。
- **`.hit` 元素的 focus 沒有 outline**：focus 時改由同層的 `.hover-ring` 顯示，有可見的 focus 指示。

### 2.4 剩餘的外觀細節（不影響閱讀，不修改）

- 390 px 時，Mechanism m1 的「91 ms」「76 ms」數值標籤會碰到虛線 deadline，但仍可讀。
- Evidence 的指令區塊與寬表格在手機上需要水平捲動（容器內捲動，頁面本身不會水平捲動）。
- **測試範圍**：只在 Firefox 實測。Server 上沒有 Chromium / Safari；頁面只使用標準 DOM / SVG / CSS，沒有使用瀏覽器專屬 API，但建議公開前在 Chrome 與 Safari 手動看一次。

## 3. Public Release Safety

### 3.1 掃描結果

- 掃描範圍：全部 1175 個 tracked 檔案，包含 raw metadata、dashboard JSON、報告與截圖內容。
- AWS / GitHub / Slack / OpenAI / Google 金鑰、private key、`password=`、`token=`、私有 IP（10/8、172.16/12、192.168/16）：**皆為 0**。
- Dashboard bundle（`dashboard/data/*`）不含任何路徑、使用者名稱或主機名稱。截圖只顯示 dashboard 內容。

### 3.2 識別資訊（非機密；由擁有者決定是否處理）

| 位置 | 內容 | 風險 | 建議 |
|---|---|---|---|
| `report/PHASE2_BATCH1_RESULT.md:12`、`report/PHASE2_BATCH2_RESULT.md:15`、`report/PHASE3_BATCH1_RESULT.md:17` | 實驗室主機名稱 `ctwlab` | 低：揭露內部主機名稱 | 可在報告中改為「lab workstation」。這些是文件，不在 provenance chain 裡，修改不影響任何驗證 |
| `report/PHASE2_BATCH1_RESULT.md:156` | 擁有者個人 email（說明 commit identity 的句子） | 低：commit metadata 裡本來就有 | 可改寫成「repo 既有的 author identity」 |
| `report/PHASE2_BATCH1_RESULT.md:17, 67` | `user@1007.service`、`/home/sam/phase2_smoke/...` | 很低 | 同上，可改為通用描述 |
| `results/raw/**/*.meta.json`、`*.probe.json`（Phase 2 75 + Phase 3 formal 102 + pilot 60 個 run） | Linux 使用者名稱 `sam`（Python / Fast DDS profile 的路徑）、uid `1007`（cgroup scope 路徑）、kernel、CPU 型號 | 很低：沒有主機名稱、IP 或憑證 | **不要修改**。這些檔案在 SHA-256 provenance chain 中，改動會讓 Phase 2/3 gate 變成 BROKEN。README 的「Data and third-party notices」已揭露這一點 |
| Commit author metadata | 擁有者 email（本 PR 12 個 commit）；隊友的 gmail 已在 `main` 上（3 個 commit） | 低：本 PR 沒有新增他人的資訊 | 如果不希望公開個人 email，日後可在 GitHub 改用 noreply 地址。改寫既有 history 會改變被 provenance 引用的 commit hash，**不建議** |

### 3.3 第三方資料與授權

- **COCO128**：影像**沒有**放進 repo（`.gitignore` 排除 `data/raw/images/*`，由 `experiments/ros2/prepare_coco128.sh` 從 Ultralytics release 下載）。Raw log 只記錄 frame id 與時間，沒有影像內容或檔名。COCO annotations 為 CC BY 4.0，影像依原 Flickr 授權。沒有再散布的問題。
- **模型**：timm（Apache-2.0）的 MobileViT，random-init，不含也不下載任何權重。`data/model_profiles/*` 是根據論文架構整理的簡化摘要。
- **Runtime**：ROS 2 / Fast DDS（Apache-2.0）、PyTorch（BSD-3-Clause）都由使用者另外安裝，沒有放進 repo。`*.pdf`（含參考論文）已被 gitignore。
- **已補上**：README 新增「Data and third-party notices」一節。
- **需修正（擁有者決定）**：repo **沒有 LICENSE**。沒有授權時，其他人預設不能合法重用程式碼。Repo 內有隊友的 commit，選擇授權前應取得對方同意。程式碼常見選擇 MIT 或 Apache-2.0；資料（`results/`）可另外標示 CC BY 4.0。本次沒有代為決定。

## 4. Engineering Verification

### 4.1 檢查結果（最終工作樹）

| 檢查 | 結果 |
|---|---|
| `bash scripts/ci_checks.sh all` | exit 0 |
| Unit / integration tests | 266 tests OK（1 skipped，與先前相同）；在 shallow clone 中同樣 OK |
| `bash -n` 全部 shell script | 16/16 OK |
| Audit regressions（`audit_repro.py --strict`） | 0/17 reproduced |
| Phase 2 provenance | **VERIFIED**（75 raw CSV / 75 meta） |
| Phase 3 provenance | **VERIFIED**（102 runs @ `7f0f160`，dirty=false，runtime code 未變，17 blocks） |
| 表格重建（`check_table_regeneration.py`） | REPRODUCED：Phase 3 的 7 張表與 baseline conditions 逐 byte 相同；Phase 2 的兩張 per-run 表在所有已提交欄位上相同 |
| `build_data --check` | CURRENT（191 inputs） |
| 受保護路徑（`results/raw`、`results/csv`、`results/figures`、`experiments`、`src/ros2_uav_pipeline`、`src/eda_lite`、`src/ros2_runtime`、`src/provenance.py`）自 `b1786dc` 起的 diff | **空** |
| 自量測 commit `7f0f160` 起的 runtime 相關 diff | 只有 `experiments/ros2/README.md` 新增說明（文件）；Phase 3 gate 也確認 runtime code 未變 |

### 4.2 KPI、CI 與結論的獨立驗證

- **獨立重算**：不使用專案的 aggregation 程式碼，直接從 `results/csv/ros2_phase3_formal_runs.csv` 依 block 配對，重算 dashboard 中**全部 525 個** paired 估計值（5 個 condition × 所有比較 × 所有 metric）的 mean、95% Student-t 區間、block 正負計數與 n。**0 差異。**
- **主要結果**：Guard − Latest @ S 20 FPS = −10.65 pp [−12.30, −9.01]，5/5 blocks；Adaptive − Guard = +0.07 pp [−0.95, 1.09]，3↓/2↑；5 個 condition 的 |Δ| ≤ 0.32 pp，且所有 CI 都包含 0；動態負載 Guard − Latest = −4.32 pp [−5.55, −3.09]。
- **消融結論的措辭**：「Adaptive's utilisation switch adds no measurable benefit」，並明確寫出「Not an equivalence test」。沒有 significant、跨硬體或能耗的宣稱（`tests/test_dashboard.py` 有檢查）。
- **研究限制**：Evidence view、README 與 PHASE4 報告一致：單一主機、n = 3–5 blocks、單一參數組、只量 latency、未量測能耗、EDA-Lite 為估計值。跨架構（legacy）比較另外標示，不歸因於排程策略。

### 4.3 發現並修正：GitHub CI 的 Phase 3 gate 在 shallow clone 下會失敗

- **問題**：`actions/checkout@v4` 預設 `fetch-depth: 1`。Phase 3 gate 需要量測 commit `7f0f160` 在 history 中，而且是 HEAD 的祖先。
- **重現**：
  ```text
  git clone --depth 1 ... → check_phase3_provenance.py → STATUS: BROKEN, "commit 7f0f160… is not in this repository" (exit 2)
  git clone (full)        → STATUS: VERIFIED (exit 0)
  ```
  本機是完整 clone，所以本機 CI 一直通過；但 PR 一推上 GitHub，`checks` job 就會失敗。
- **修正**：`.github/workflows/ci.yml` 中執行 gate 的 `checks` job 加上 `fetch-depth: 0`。
- **防回歸**：`tests/test_engineering_quality.py` 新增檢查，已確認改回 `fetch-depth: 1` 時測試會失敗。
- **連帶的 merge 限制**：squash merge 或 rebase merge 會讓 `7f0f160` 不再是 `main` 的祖先，Phase 3 gate 會在 `main` 上變成 BROKEN。**必須用「Create a merge commit」。** README 的 Reproducibility 一節已補充說明。

## 5. GitHub Release Preparation

### 5.1 Commit history 與 PR diff 檢查

`main..HEAD` 共 12 個 commit，作者皆為 repo 擁有者，訊息格式一致：

```text
2983dbe feat(dashboard): Phase 4 static dashboard, verified data pipeline, portfolio docs
b1786dc data(ros2): Phase 3 / Batch 2 formal interleaved A/B benchmark (102 runs), analysis, docs and report
b9b242c feat(analysis): Phase 3 formal A/B analysis, dynamic-phase analysis, independent Phase 3 provenance gate
7f0f160 feat(ros2): deadline_guard ablation, dynamic input rate, formal A/B driver with load gate (Phase 3 / Batch 2)
a4f1f01 data(ros2): Phase 3 / Batch 1 interleaved scheduling pilot (60 runs), aggregates, docs and report
33c9bf5 feat(ros2): application scheduling (FIFO / Latest-Frame / Adaptive) with bounded queue and one inference worker (Phase 3 / Batch 1)
fe3f2dc docs(report): Phase 2 / Batch 2 real ROS 2 baseline benchmark result
7377455 data(ros2): Phase 2 / Batch 2 constrained ROS 2 baseline (75 runs), summary, aggregates, verified OS profiles
bd458fe feat(ros2): baseline aggregation across runs; wait for node exit between runs (Phase 2 / Batch 2)
7ba42a2 feat(ros2): runtime DDS transport probe, low-priority wrapper, baseline summary columns (Phase 2 / Batch 2)
8e336f5 docs(report): Phase 2 / Batch 1 Linux ROS 2 environment & smoke validation result
ce5487f fix(ros2): Phase 2 / Batch 1 fixes from the first real Linux ROS 2 smoke test
```

（再加上本次的 QA commit。）

- **Diff 組成**：1056 個檔案，其中 949 個是 `results/raw/`（75 + 102 + 60 個 run，每個 run 有 4 個檔案，另含 `load_gate.jsonl`）。不含 raw 的部分為 107 個檔案，+47.9k / −678 行，大部分是 dashboard bundle JSON 與報告。
- **意外檔案**：沒有。無 `__pycache__`、`.pyc`、`.DS_Store`、log、`*.failed`、`ci-logs/`、`.env`、暫存檔；沒有刪除任何檔案。
- **檔案大小**：最大的單一檔案為 1.2 MB（pilot raw CSV），tracked 總量約 128 MB，都在 GitHub 的限制內（單檔 100 MB）。

### 5.2 展示品質

- README 首屏依序是：一句話定位、dashboard 截圖、問題 / 系統 / 證據 / 答案 / dashboard 摘要表、中文摘要、5 個由資料推導的主要發現；之後是 dashboard 說明（3 張截圖）、架構圖、quickstart、methodology、reproducibility、limitations、future work、第三方聲明、phase 歷程。
- 所有本地連結都存在。截圖已在 UI 修正後重新產生（`docs/images/`，7 張，約 2.3 MB）。
- 建議的 GitHub repo 設定（需擁有者在 GitHub 上設定）：
  - Description：`Measured ROS 2 frame-scheduling benchmark for MobileViT on a constrained Linux host, with SHA-256 provenance and an offline dashboard; plus an EDA-inspired layer-fusion simulator.`
  - Topics：`ros2`、`real-time`、`scheduling`、`benchmark`、`edge-ai`、`mobilevit`、`reproducibility`、`data-provenance`、`dashboard`、`operating-systems`
  - Social preview：`docs/images/dashboard_overview.png`

### 5.3 建議的 PR Title

```text
Phase 2–4: constrained ROS 2 baseline, formal scheduling A/B benchmark, provenance-checked dashboard
```

### 5.4 建議的 PR Description

```markdown
## Summary
Measured study of frame scheduling for a MobileViT detector in ROS 2 on a constrained Linux host
(2 pinned cores, 4 GiB, Fast DDS SHM verified per run), plus a static dashboard built only from
provenance-verified tables.

- **Phase 2:** 75-run constrained baseline (capacity, drop model 1 − 1/ρ, queue depth, injected delay).
- **Phase 3:** FIFO / Latest-Frame / Deadline-Guard / Adaptive with a bounded application queue;
  102-run interleaved A/B in 17 blocks; independent Phase 3 provenance gate.
- **Phase 4:** offline dashboard (`dashboard/`), deterministic data builder with `--check`,
  table-regeneration check, README rewrite; Final QA (`report/FINAL_QA.md`).

## Key results (S · 20 FPS, n = 5 blocks)
- Deadline-Guard − Latest-Frame: −10.65 pp effective miss, 95 % CI [−12.30, −9.01], 5/5 blocks.
- Adaptive − Deadline-Guard: +0.07 pp [−0.95, 1.09] — the utilisation switch adds nothing measurable
  (not an equivalence test). Single host; no significance or energy claims.

## Verification
- `bash scripts/ci_checks.sh all`: 266 tests, audit 0/17, Phase 2 + Phase 3 provenance VERIFIED,
  tables rebuild from raw (byte-identical), dashboard bundle CURRENT.
- The `checks` job now uses `fetch-depth: 0` (the Phase 3 gate needs commit 7f0f160 in history).

## Merge
**Use "Create a merge commit". Do not squash or rebase:** the Phase 3 gate requires the measurement
commit 7f0f160 to be an ancestor of HEAD.

## Review notes
949 of 1056 changed files are raw run evidence under `results/raw/` (never edited; SHA-256 chained).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

### 5.5 部署方式

- **目前（已提供，不公開）**：在 server 上執行 `bash scripts/serve_dashboard.sh`，只綁定 `127.0.0.1:8765`，先檢查 bundle 再啟動。透過 VS Code Remote SSH 的 port forwarding（或 `ssh -L 8765:127.0.0.1:8765 <server>`）預覽。也可以直接用 `file://` 開啟 `dashboard/index.html`。
- **公開時（建議，未執行）**：用 GitHub Pages 發布 `dashboard/` 目錄。網站是純靜態，所有路徑都是相對路徑，可以在 `/<repo>/` 子路徑下運作。
  - 做法：新增一個 workflow，在 `main` push 時先執行 `python3 -m src.dashboard.build_data --check`，再用 `actions/upload-pages-artifact`（`path: dashboard`）與 `actions/deploy-pages` 部署。
  - 部署內容只有 HTML、CSS、JS 與 bundle，不含 raw metadata。
  - 需要擁有者在 repo Settings → Pages 啟用，並確認 repo 為 public。

## 6. 本次修改（最小修正）

| 檔案 | 修改 |
|---|---|
| `dashboard/assets/charts.js` | Focus tooltip 在 scroll 時跟隨；線末標籤 / 參考線標籤 / 對角線標籤不超出圖區；窄版 label 欄寬；`valueNote`；CI 條內縮 |
| `dashboard/assets/style.css` | 只有 `[data-tip]` 接收 pointer；`.ci-strip` 刻度 / 格線 / 零線 / ring 樣式 |
| `dashboard/assets/app.js` | m1 的註記改用 `valueNote`（1 行） |
| `.github/workflows/ci.yml` | `checks` job 加上 `fetch-depth: 0` |
| `tests/test_engineering_quality.py` | 新增 gate job 不可使用 shallow checkout 的檢查 |
| `README.md` | 「Data and third-party notices」一節；Reproducibility 補充 full clone / merge commit |
| `docs/images/*.png` | UI 修正後重新產生的截圖 |
| `report/FINAL_QA.md`、`report/ai_interaction_log.md` | 本報告與紀錄 |

Dashboard 資料、builder、任何正式資料、排程策略、成本模型與分析程式都沒有修改。

## 7. 是否已達公開發布標準

**工程、資料正確性與展示品質：已達標準。** 公開前的 checklist：

- [ ] **（必要）新增 LICENSE**：由擁有者選擇；需先取得隊友同意（`main` 上有對方的 commit）。
- [ ] （建議）決定報告中的 `ctwlab`、個人 email、`/home/sam` 是否改為通用描述（§3.2；只改 `report/`，不要動 `results/raw/`）。
- [ ] Push branch 後確認 GitHub Actions 全部 job 通過（tests × Python 3.10–3.13、`checks`、`repeat`；特別是使用 `fetch-depth: 0` 的 `checks` job）。
- [ ] 用 **Create a merge commit** 合併，不要 squash 或 rebase。
- [ ] 合併後在 `main` 上執行 `python3 scripts/check_phase3_provenance.py --expect-runs 102`，應為 VERIFIED。
- [ ] 設定 repo description、topics 與 social preview（§5.2）。
- [ ] （選擇性）啟用 GitHub Pages 發布 `dashboard/`（§5.5）。
- [ ] 將 repo visibility 改為 public。
