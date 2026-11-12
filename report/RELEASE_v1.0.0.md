# Release v1.0.0：Final Release Preparation

- 日期：2026-11-12
- 分支：`release/v1.0.0`，從 `b5f4242` 建立（Final Visual Polish 與 README / docs 改寫之後）。**未 push、未 merge、未修改 repository visibility。**
- 範圍：只做發布準備（LICENSE、GitHub Pages workflow、回歸測試、文件）。沒有修改正式原始資料、統計結果、runtime、排程演算法或 cost model；沒有 squash、rebase、cherry-pick 或改寫 history。

---

## 1. Git 狀態與 history

| 項目 | 狀態 |
|---|---|
| Remote | `origin` = `github.com/samhung1205/os-aware-eda-lite`；`origin/main` = `6c743fc`（Phase 1 合併） |
| Final Visual Polish | 已提交：`4c7e2ef`（dashboard）、`b5f4242`（README / docs） |
| Phase 2–4 原始 commits | 全部保留（`ce5487f` … `b5f4242`，17 個），未 squash / rebase |
| `7f0f160` 為 HEAD 的祖先 | 是（`git merge-base --is-ancestor`）；Phase 3 gate：runtime code unchanged `7f0f160..HEAD` |
| 本機 `main` | 在前一次工作中已 fast-forward 到 `b5f4242`（僅本機，未 push）。本次未再修改 |

待合併到 `origin/main` 的 commits（`origin/main..release/v1.0.0`，18 個，舊 → 新）：

```text
ce5487f fix(ros2): Phase 2 / Batch 1 fixes from the first real Linux ROS 2 smoke test
8e336f5 docs(report): Phase 2 / Batch 1 Linux ROS 2 environment & smoke validation result
7ba42a2 feat(ros2): runtime DDS transport probe, low-priority wrapper, baseline summary columns (Phase 2 / Batch 2)
bd458fe feat(ros2): baseline aggregation across runs; wait for node exit between runs (Phase 2 / Batch 2)
7377455 data(ros2): Phase 2 / Batch 2 constrained ROS 2 baseline (75 runs), summary, aggregates, verified OS profiles
fe3f2dc docs(report): Phase 2 / Batch 2 real ROS 2 baseline benchmark result
33c9bf5 feat(ros2): application scheduling (FIFO / Latest-Frame / Adaptive) with bounded queue and one inference worker (Phase 3 / Batch 1)
a4f1f01 data(ros2): Phase 3 / Batch 1 interleaved scheduling pilot (60 runs), aggregates, docs and report
7f0f160 feat(ros2): deadline_guard ablation, dynamic input rate, formal A/B driver with load gate (Phase 3 / Batch 2)
b9b242c feat(analysis): Phase 3 formal A/B analysis, dynamic-phase analysis, independent Phase 3 provenance gate
b1786dc data(ros2): Phase 3 / Batch 2 formal interleaved A/B benchmark (102 runs), analysis, docs and report
2983dbe feat(dashboard): Phase 4 static dashboard, verified data pipeline, portfolio docs
8c54a7c fix(release): final QA — dashboard UI fixes, shallow-clone CI gate, release notes
560d181 fix(dashboard): serve script picks the next free localhost port when 8765 is taken
be2a078 feat(dashboard): visual design refinement and OS-Aware Edge AI Runtime naming
4c7e2ef feat(dashboard): final visual polish — overview hero result, mobile nav, Deadline-Guard concept figure
b5f4242 docs: README as a Traditional Chinese user manual; research and development record moved to docs/
(this)  chore(release): v1.0.0 preparation — MIT license, verified GitHub Pages deployment, release report
```

---

## 2. 授權（LICENSE）

### 2.1 檢查

- Repo 內沒有既有 LICENSE、沒有第三方授權檔或 vendored 程式碼；tracked 檔案中沒有其他授權宣告（唯一命中是 `environment.lock.yml` 中套件 metadata）。
- 第三方元件皆未放入 repo：COCO128 影像（下載到 git-ignored 目錄）、timm / PyTorch / ROS 2 / Fast DDS（另行安裝）、無預訓練權重。README 第 13 節列出各自授權。
- **貢獻者**：history 中有另一位作者 `jay900411`（4 個 commit），其程式碼仍存在於 HEAD：原始 ROS 2 nodes（`image_stream_node.py` 78 行、`mobilevit_detector_node.py` 69 行）、`plot_6lines.py` 106 行、4 個 scripts、package metadata、`results/figures/{ros2,eda_lite}/*.svg`。只有著作權人能授權自己的貢獻，因此先向擁有者確認。
- **擁有者決定**（本次確認）：對方已同意以 MIT 釋出；copyright holder 使用 GitHub 帳號名。git 作者名只有「Sam」，無法確認法定姓名，因此不自行填寫。

### 2.2 結果

- 新增標準 MIT `LICENSE`：`Copyright (c) 2026 samhung1205 and contributors`。
- README 第 13 節改為「授權與第三方資料」，說明 MIT 只涵蓋本專案程式碼與文件，第三方資料 / 模型 / 軟體依原授權。
- **未修改**：`src/ros2_uav_pipeline/package.xml` 與 `setup.py` 仍寫 `license TODO` 與佔位 maintainer（`emo@example.com`）。該目錄屬於 Phase 3 gate 的 `RUNTIME_PATHS`，修改會讓 gate 變成 `BROKEN`。根目錄 LICENSE 已涵蓋整個 repo。

---

## 3. GitHub Pages workflow

`.github/workflows/pages.yml`（原有 `ci.yml` 保留、未修改）：

| 要求 | 實作 |
|---|---|
| 觸發 | `push` 到 `main`、`workflow_dispatch`；build job 有 `if: github.ref == 'refs/heads/main'`，從其他分支手動觸發不會發布 |
| 完整 checkout | `actions/checkout@v6`，`fetch-depth: 0` |
| 驗證 | 依序：`check_runtime_provenance.py`、`check_phase3_provenance.py --expect-runs 102`、`check_table_regeneration.py`、`build_data --check`。直接呼叫腳本，因此 `BLOCKED`（exit 1）也會中止，比 CI 更嚴格 |
| 驗證成功才部署 | 驗證步驟在 `upload-pages-artifact` 之前；`deploy` job `needs: build` |
| 官方 actions | `actions/configure-pages@v5`、`actions/upload-pages-artifact@v4`、`actions/deploy-pages@v4`（版本已用 `git ls-remote` 確認存在） |
| 只發布 `dashboard/` | `path: dashboard`（唯一的 `path:`） |
| 不需 ROS 2 / CDN / 後端 | 只用 Python 3.10 standard library；不 `pip` / `conda` / `apt` / `npm` |
| 權限 | 全域 `contents: read`；只有 deploy job 有 `pages: write`、`id-token: write`；`concurrency: github-pages`，不取消進行中的部署 |

本次的工作樹中原本已有一份未追蹤的草稿（結構相同）；本次保留其結構與 action 版本，加上說明註解、timeout 與步驟名稱。YAML 已用 PyYAML 解析確認。

新增回歸測試（`tests/test_engineering_quality.py`）：

- `test_pages_workflow_verifies_before_publishing_dashboard_only`：觸發條件、main guard、`fetch-depth: 0`、四個檢查的確切順序且都在 upload 之前、只上傳 `dashboard`、不安裝套件、`ci.yml` 仍存在。
- `test_dashboard_uses_only_relative_paths_inside_dashboard`：HTML / JS / CSS 中 35 個 `src` / `href` / `url()` 參照都是相對路徑、不以 `/` 開頭、不含 `..`、不指向外部、目標檔案存在且位於 `dashboard/` 內。
- `test_license_is_mit`。

---

## 4. 公開資訊檢查

| 檢查 | 結果 |
|---|---|
| Tracked 檔案 | 1197 個（本次 + 2：`LICENSE`、`pages.yml`，另加本報告） |
| `__pycache__`、`.pyc`、`.DS_Store`、`~$*`、`*.failed`、`ci-logs/`、`.env`、金鑰檔 | 0 |
| 單檔 > 5 MB | 0 |
| 金鑰 / token / private key 樣式 | 0（唯一命中是 `FINAL_QA.md` 描述掃描規則的文字） |
| 私有 IP | 0 |
| **發布的 `dashboard/`**（1.1 MB） | 不含 `/home/`、主機名稱、email、uid；所有參照為相對路徑；無外部 URL、無 CDN |
| 截圖（`docs/images/`） | 只有 dashboard 內容，無瀏覽器網址列或系統資訊 |
| README / docs 連結 | 全部相對連結存在；Pages 網址只在 README 4.1 出現 |

**仍存在、由擁有者決定（與 `FINAL_QA.md` §3.2 相同，本次未修改）：**

- `report/PHASE2_BATCH1_RESULT.md`、`PHASE2_BATCH2_RESULT.md`、`PHASE3_BATCH1_RESULT.md`：實驗室主機名稱、`/home/sam/...` 路徑、`user@1007.service`；`PHASE2_BATCH1_RESULT.md` 有擁有者 email。這些是報告，不在 provenance chain，可改為通用描述而不影響驗證。
- `results/raw/**/*.meta.json`、`*.probe.json`：Linux 使用者名稱、uid、kernel、CPU 型號。**不可修改**（在 SHA-256 chain 中）；README 已揭露。
- Commit author email：已在 history 中；改寫會改變被 provenance 引用的 commit hash，**不建議**。不想公開時可在 GitHub 設定日後改用 noreply 地址。

---

## 5. 驗證結果（release 分支，最終工作樹）

| 檢查 | 結果 |
|---|---|
| `bash scripts/ci_checks.sh all` | exit 0 |
| `python3 -m unittest discover -s tests` | 269 tests OK（1 skipped） |
| `bash scripts/ci_checks.sh repeat 5` | 0/5 failed |
| `python3 scripts/check_runtime_provenance.py` | `VERIFIED`（75 raw runs + metadata） |
| `python3 scripts/check_phase3_provenance.py --expect-runs 102` | `VERIFIED`（102 runs @ `7f0f160`，dirty=false，runtime code unchanged，25 controls，17 blocks） |
| `python3 scripts/check_table_regeneration.py` | `REPRODUCED`（7 張 Phase 3 表與 baseline condition 表 byte-identical） |
| `python3 -m src.dashboard.build_data --check` | `CURRENT`（191 verified inputs） |
| `python3 scripts/audit_repro.py --strict` | exit 0（P1-8 為既有的 `BLOCKED`：需要實機 ROS 2 run 才能確認，非 regression） |

---

## 6. Pull Request

**Base** `main` ← **compare** `release/v1.0.0`

**Title**

```text
Release v1.0.0: constrained ROS 2 scheduling benchmark, provenance-checked dashboard, MIT license, GitHub Pages
```

**Description（建議）**

```markdown
## Summary
- Phase 2: 75-run constrained ROS 2 baseline (MobileViT-S / XXS, Fast DDS SHM verified per run).
- Phase 3: scheduling policies (FIFO / Latest-Frame / Deadline-Guard / Adaptive) and a 102-run interleaved A/B benchmark.
- Phase 4: static, offline dashboard built only from SHA-256-verified tables; final visual polish.
- Docs: README rewritten as a Traditional Chinese user manual; research, provenance and history reports in docs/.
- Release: MIT LICENSE; `.github/workflows/pages.yml` publishes `dashboard/` only after both provenance gates, table regeneration and the bundle check pass.

## Key result (S · 20 FPS, n = 5 blocks)
Deadline-Guard − Latest-Frame = −10.65 pp effective miss, 95 % CI [−12.30, −9.01], 5/5 blocks lower.
Adaptive − Deadline-Guard = +0.07 pp [−0.95, 1.09] (no measurable difference; not an equivalence test).

## Verification
`bash scripts/ci_checks.sh all` exit 0 (269 tests), Phase 2 + Phase 3 provenance VERIFIED,
tables REPRODUCED from raw, dashboard bundle CURRENT.

## Merge
Use **Create a merge commit**. Do not squash or rebase: the Phase 3 gate requires the measurement
commit 7f0f160 in the history of main.
```

---

## 7. GitHub Pages 設定指引（擁有者操作）

1. **Pages 來源**：repo **Settings → Pages → Build and deployment → Source** 選 **GitHub Actions**（不要選 *Deploy from a branch*）。
2. **Visibility**：GitHub Free 方案的 Pages 需要 public repo（private repo 需 Pro / Team 以上）。Visibility 本次未修改，由擁有者決定。
3. **Environment**：首次部署會自動建立 `github-pages` environment；若在 **Settings → Environments → github-pages** 設了 deployment branch 限制，需允許 `main`。
4. **合併後**：在 PR 用 **Create a merge commit** 合併。push 到 `main` 會同時觸發 `CI` 與 `Deploy Dashboard to GitHub Pages`。到 **Actions** 頁確認兩者都通過；deploy job 的 environment URL 即網站網址：`https://samhung1205.github.io/os-aware-eda-lite/`（模擬頁：`.../simulation.html`）。
5. **手動重新部署**：Actions → *Deploy Dashboard to GitHub Pages* → **Run workflow**（branch 選 `main`）。
6. **合併後驗證**：在 `main` 執行 `python3 scripts/check_phase3_provenance.py --expect-runs 102`，應為 `VERIFIED`。之後可建立 tag：`git tag -a v1.0.0 -m "OS-Aware Edge AI Runtime v1.0.0"` 並 push，再在 GitHub 建立 Release。
7. **Repo 設定（建議）**：description、topics 與 social preview（`docs/images/dashboard_overview.png`）見 `FINAL_QA.md` §5.2；可將網站網址填入 repo 的 *Website* 欄位。

---

## 8. 發布後修正：GitHub Pages 權限（`fix/pages-permissions`）

PR #2 以 merge commit（`c58881c`）合併後，首次部署在 `actions/configure-pages@v5` 失敗：

```text
Get Pages site failed. HttpError: Resource not accessible by integration
```

- **根因**：§3 的 workflow 只在 workflow 層級宣告 `contents: read`。build job 沒有自己的 `permissions`，因此繼承這一組，token 沒有任何 `pages` 權限；`configure-pages` 需要讀取 Pages 站台設定（`GET /repos/{owner}/{repo}/pages`），因此回傳 403。Deploy job 有自己的 `permissions` 區塊，job 層級會**整組取代**（不是合併）workflow 層級，所以 deploy job 原本就有 `pages: write` 與 `id-token: write`，不受影響。
- **修正**：build job 加上 job 層級 `contents: read` + `pages: read`；workflow 層級維持只有 `contents: read`（之後新增的 job 預設最小權限）。Deploy job 不變。不使用 PAT、不新增 secrets、不開啟 `enablement`。
- **Node.js deprecation warning**（與本次失敗無關）：`configure-pages@v5` 執行於 Node 20；官方 `v6.0.0`（2026-03-25）唯一的功能變更是改用 Node 24，inputs / outputs 與 v5 完全相同，因此更新為 `@v6`。`deploy-pages@v4`（Node 20）與 `upload-pages-artifact@v4`（內含 `upload-artifact` v4）也會出現相同 warning，官方已有 `deploy-pages@v5` 與 `upload-pages-artifact@v5`（改用 `upload-artifact` v7）；不在本次範圍，留待之後確認。
- **測試**：新增 `test_pages_workflow_permissions_are_minimal_per_job`，逐 job 檢查確切權限並禁止 secrets / PAT / `enablement`；以修正前的 workflow 執行此測試會失敗。
- **驗證**：`bash scripts/ci_checks.sh all` exit 0（270 tests），Phase 2 / Phase 3 `VERIFIED`，tables `REPRODUCED`，bundle `CURRENT`。fetch-depth、四項檢查與只部署 `dashboard/` 皆未變。

