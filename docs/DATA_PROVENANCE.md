# 資料來源與可重現性報告

本報告整理自原 README 的 Data pipeline、Reproducibility 與資料說明段落，說明每一個量測數字如何從原始 log 追溯到 Dashboard，以及如何自行驗證。各結果檔案的追蹤規則與可信程度見 [`../results/README.md`](../results/README.md)。

---

## 1. 原則

- 每一個 runtime 數字都以 SHA-256 從原始 per-frame log 串到 Dashboard。
- 模擬估計（EDA-Lite）與量測結果在所有輸出中都明確分開。
- 只有實際 ROS 2 run 產生、且 provenance gate 回報 `VERIFIED` 的資料才稱為「measured」；只有 `meta.json` 標示 `measurement_class=constrained` 的 run 才稱為「constrained」。
- Pilot、legacy-unverified、example 資料永遠不進入 Dashboard。

---

## 2. 資料鏈

```text
results/raw/{ros2,ros2_phase3_formal}/<run_id>.{csv,publisher.csv,meta.json,probe.json}   （永不修改）
  → results/csv/*_summary.csv + .manifest.json                  analyze_runtime
  → results/csv/ros2_baseline_*.csv、ros2_phase3_formal_*.csv + manifests
  → scripts/check_runtime_provenance.py / check_phase3_provenance.py   VERIFIED
  → dashboard/data/dashboard_data.{json,js} + .manifest.json     src.dashboard.build_data
```

| 檔案 | 內容 |
|---|---|
| `<run_id>.csv` | Detector 每個 frame 一列 |
| `<run_id>.publisher.csv` | Publisher 每個發布的 frame 一列（完整的 drop 計算所需） |
| `<run_id>.meta.json` | 讀回的資源限制、版本、git commit / dirty、QoS、DDS profile |
| `<run_id>.probe.json` | 執行期探測：UDP socket、`/dev/shm` segment 大小、CPU / RSS / affinity / nice、cgroup 記憶體、主機負載 |

---

## 3. Dashboard 資料管線

`python3 -m src.dashboard.build_data`：

- 只讀取 Phase 2 baseline 與 Phase 3 formal 表格（另加給獨立模擬頁使用的內建 profile 模擬估計）。
- 重新驗證每一份 SHA-256 manifest，一路追到原始 run。
- 寫出 `dashboard/data/dashboard_data.{json,js}` 與 manifest。
- 所有 KPI 與結論句都在這裡計算；前端只負責格式化。
- 輸出是 deterministic（不含時間戳記），因此 `--check` 可以逐 byte 比對。

拒絕寫出的情況：

| Exit code | 狀態 | 情況 |
|---|---|---|
| 1 | `BLOCKED` | 缺少輸入 |
| 2 | `BROKEN` | Hash 或不變量失敗，或出現 pilot / legacy-unverified / example 資料 |
| 3 | `STALE` | `--check`：已提交的 bundle 與重新建置結果不同 |

---

## 4. Provenance gate

| Gate | 範圍 | 檢查內容 |
|---|---|---|
| `scripts/check_runtime_provenance.py` | Phase 2 baseline（`results/raw/ros2/`） | raw → summary → OS profiles → simulation 的 hash 鏈 |
| `scripts/check_phase3_provenance.py` | Phase 3 formal（`results/raw/ros2_phase3_formal/`） | `git.dirty=false`、單一量測 commit 且 runtime 程式碼到 `HEAD` 未變、25 項控制變因一致、DDS probe、完整 blocks、summary 與 aggregate manifest |

結果代碼：0 `VERIFIED`、1 `BLOCKED`（環節缺失）、2 `BROKEN`（hash 不符 / 過期）。

**量測 commit 注意事項**：Phase 3 gate 會確認量測 commit `7f0f160` 是 `HEAD` 的祖先，且 runtime 程式碼自那之後沒有變更。請使用完整 clone（不要 `--depth 1`），合併此歷史時不要 squash 或 rebase，否則 gate 會回報 `BROKEN`。

**Pilot 資料**：`results/raw/ros2_phase3_pilot/` 保留作為紀錄；因量測時 working tree 為 dirty，其 gate 刻意回報 `BROKEN`，從未被使用。

---

## 5. 從原始資料重建表格

```bash
python3 scripts/check_table_regeneration.py
```

此腳本將所有 Phase 2 / Phase 3 表格從原始 run 重建到暫存目錄後比對：

- 7 張 Phase 3 表格與 baseline condition 表格**逐 byte 相同**；
- 兩張 Phase 2 per-run 表格在所有已提交欄位上一致（目前的 analyzer 會額外附加 20 個 Phase 3 欄位）。

確切的指令寫在該腳本與 [`REFERENCE.md`](REFERENCE.md) 中。重建表格後再執行 `python3 -m src.dashboard.build_data` 即可重建 Dashboard bundle。

---

## 6. CI

`.github/workflows/ci.yml`（本機：`bash scripts/ci_checks.sh all`）：

- Python 3.10–3.13 上的測試
- `bash -n` 語法檢查
- Audit 回歸（`scripts/audit_repro.py --strict`）
- 兩個 provenance gate
- 表格重建檢查
- Dashboard bundle 檢查

CI 不安裝 ROS 2；gate 回報 `BLOCKED` 時只當作警告，永遠不會被轉為 `VERIFIED`。

**GitHub Pages**（`.github/workflows/pages.yml`）比 CI 更嚴格：兩個 gate 必須回報 `VERIFIED`（`BLOCKED` 也會中止），表格必須可從 raw 重建、bundle 必須為最新，之後才只發布 `dashboard/`。發布內容只有 HTML / CSS / JS 與 bundle，不含 raw metadata。

---

## 7. Run metadata 與隱私

`results/raw/**/*.meta.json` 與 `*.probe.json` 記錄了量測主機的 kernel、CPU 型號、cgroup scope，以及 Python / Fast DDS profile 的本機安裝路徑。這些檔案是 SHA-256 provenance 鏈的一部分，因此保持原樣、不做編輯。原始 run log 只記錄 frame id 與時間，不含影像內容。
