# Phase 1 Final Handoff

- 日期：2026-11-10
- Repository：`samhung1205/os-aware-eda-lite`
- Feature branch：`fix/pr-a1-ros2-data-integrity`（已 push）
- PR：[#1 Phase 1 finalization](https://github.com/samhung1205/os-aware-eda-lite/pull/1)，**Draft，未 merge**
- 一句話結論：Phase 1 的程式端工作全部完成，並由 GitHub Actions 驗證（Python 3.10–3.13）。目前能如實報告的只有 **simulation estimates**；真實 ROS 2 量測鏈仍然 **BLOCKED**，需要在 Phase 2 Linux 實機上執行。

## 1. Commits

| Commit | 分支 | 內容 |
|---|---|---|
| `a40816d` | main | PR-A1：每個 run 有唯一 `run_id`，不混用 run（P0-2） |
| `54667ab` | main | Batch 1：deadline、drops、timing、launch 的量測正確性（P1-4/5/6） |
| `9eb6341` | main | Batch 2：精確 DP objective、greedy / sweep 健壯性、`pure` profile（P0-1、P1-1/2/3） |
| `64a844f` | main | Batch 3：provenance chain、per-model 校準、run metadata（P0-3、P1-7、P1-8） |
| `4458373` | main | Batch 4（使用者提交並 push 到 `main`）：CI、依賴拆分、repo 衛生、文件、P2-6 pipeline 修正；同時包含使用者的 `SIX_LINE_METRICS` 變更、本機產生的 6 個 CSV + 5 個 sidecar，以及兩個舊版 SVG |
| `bc13360` | PR #1 | 取消追蹤兩個舊版 `os_aware_total_cost_by_sram.svg`（只移出 index，本機檔案保留） |
| （本報告） | PR #1 | `report/PHASE1_FINAL_HANDOFF.md` |

收尾時的狀況與處理：

- 本次工作開始前，Batch 4 已經由使用者以 `4458373` 提交，並直接 push 到 `origin/main`（`main` 與 feature branch 指向同一個 commit）。因為不能改寫 `main` 的歷史（需要 force push），所以保留 `4458373`，剩下的整理放在 feature branch 上，以 draft PR 送出。
- **`SIX_LINE_METRICS`**：已包含在使用者自己的 `4458373` 中。本次沒有修改或還原它（還原會覆寫使用者的修改）；它讓 `plot_6lines` 多產生一張 `os_aware_total_cost_by_sram.svg`，標題會帶 provenance 標示，測試全部通過。
- **舊版 SVG**：`results/figures/eda_lite/{s,xxs}/os_aware_total_cost_by_sram.svg` 是在 Phase 1 成本模型修正前，由 UNVERIFIED legacy profiles 產生，標題沒有 `[OS profile: UNVERIFIED]`。重新產生後，標題與數值都不同。`bc13360` 只把它們移出 index：檔案仍在磁碟上，之後會顯示為未追蹤。需要追蹤時，先執行 `bash scripts/rebuild_eda_lite_figures.sh` 產生帶標示的版本（會覆寫本機檔案），再提交。
- **CSV / sidecar**：依 `results/README.md` 的策略，`4458373` 中的 6 個 CSV 與 5 個 sidecar 全部保留追蹤：
  - 它們都可由 config 重現（見 §3）。
  - `*_pure` 與 `*_runtime_aware_sweep` 是 8 張已追蹤六線圖的輸入。
  - sensitivity summary 是報告會引用的表；sweep（約 390 KB）是它的來源，sidecar 也指向它。
  - `*_runtime_aware_sweep` 每一列都標示 `os_profile_provenance=unverified`。
- 沒有使用 `git add -A`、force push、reset 或 merge；沒有刪除任何本機檔案；沒有直接修改 `main`。

## 2. CI 狀態（GitHub Actions）

| Run | 觸發 | Commit | 結果 |
|---|---|---|---|
| [42763342658](https://github.com/samhung1205/os-aware-eda-lite/actions/runs/42763342658) | push `main` | `4458373` | **6/6 jobs 通過** |
| [42763869298](https://github.com/samhung1205/os-aware-eda-lite/actions/runs/42763869298) | push feature branch | `bc13360` | **6/6 jobs 通過** |
| [42763912283](https://github.com/samhung1205/os-aware-eda-lite/actions/runs/42763912283) | pull_request (PR #1) | `bc13360` | **6/6 jobs 通過** |
| PR #1 checks | push / pull_request | 本報告的 commit | 只新增文件；結果見 PR #1 的 checks |

`4458373` 各 job（GitHub 實際 log）：

| Job | 結果 |
|---|---|
| tests (Python 3.10) | 148 tests OK |
| tests (Python 3.11) | 148 tests OK |
| tests (Python 3.12) | 148 tests OK |
| tests (Python 3.13) | 148 tests OK |
| shell syntax, audit regressions, provenance gate | `bash -n` 通過；`Summary: 0/17 reproduced`；`provenance: BLOCKED`，並顯示 warning annotation「No verified ROS 2 measurements yet (raw CSVs: 0)」 |
| repeated test runs (flake detection) | 5/5 runs OK（`0/5 runs failed`） |

### 2.1 PR #1 checks

`bc13360` 的 push 與 pull_request 兩次 run 各 6 個 jobs 全部通過（tests 3.10–3.13、checks、repeat 5×）。沒有 CI 失敗需要修正。

非阻擋的 annotation（不影響結果，本次未處理，因為不做額外修改）：

- GitHub 表示 `actions/checkout@v4`、`actions/setup-python@v5`、`actions/upload-artifact@v4` 目標的 Node.js 20 已 deprecated，目前被強制以 Node.js 24 執行。之後可升級到支援 Node 24 的 major 版本。
- `ubuntu-latest` 自 2026-10-19 起逐步遷移到 Ubuntu 26。若 runner 行為改變（例如 cgroup / affinity），`run_metadata` 相關測試會以完整輸出失敗，便於診斷。

## 3. 本機驗證結果

| 檢查 | 結果 |
|---|---|
| `bash scripts/ci_checks.sh all`（feature branch，macOS，Python 3.11.4） | exit 0：148/148 tests、`bash -n` 全部通過、audit 0/17 reproduced（P0-3、P1-8 BLOCKED）、provenance BLOCKED |
| 乾淨 clone（`4458373`）重新產生 tracked artifacts | 7 個 MobileViT CSV（profile sweep、runtime-aware、`{xxs,s}` pure、`{xxs,s}` runtime-aware、sensitivity sweep）、2 個 summary、8 張帶 UNVERIFIED 標示的六線圖：**全部 byte-identical**。7 個 sidecar 只有 `git.commit` / `git.dirty` 不同（記錄產生時的 commit；SHA-256 都一致）。兩個舊版 `os_aware_total_cost_by_sram.svg` 無法重現（標題與數值不同），因此在 `bc13360` 移出 index |
| Provenance | `check_runtime_provenance.py` exit 1 **BLOCKED**：`results/raw/ros2/` 沒有 detector CSV，沒有 `ros2_runtime_summary.csv`，也沒有 `runtime_os_profiles.json`。這如實反映沒有實測資料；legacy 檔為 `UNVERIFIED`、example 檔為 `EXAMPLE`，7 個 simulation sidecar 為 `OK`。CI gate 只把 BLOCKED 當 warning，遇到沒有 raw 資料卻回報 VERIFIED 會失敗；沒有任何步驟繞過 |
| 使用者檔案 | `results/.DS_Store`、`~$os-aware-eda-lite-final-presentation.pptx`、兩個舊版 SVG 都保留在磁碟上 |

## 4. 已驗證 vs 仍需實機驗證

| 項目 | 已驗證（CI / 本機） | 仍需 Phase 2 實機 |
|---|---|---|
| EDA-Lite 排程與成本（P0-1、P1-1–P1-3、P1-4S） | DP = exhaustive oracle（隨機模型 + MobileViT）、greedy 非單調、infeasible rows、平手標示；結果可重現 | — |
| ROS 2 CSV 完整性與量測定義（P0-2、P1-4–P1-6） | 合成資料、fake `ros2` / `timeout`、stub launch modules | 真實 ROS 2 下的時間戳記、掉幀、warm-up 行為 |
| Provenance chain（P0-3） | 合成資料完整鏈：VERIFIED / 竄改 → BROKEN / 缺 metadata / sidecar 過期 | **真實 raw → summary → profiles → simulation 鏈（目前 BLOCKED）** |
| OS profile 校準（P1-7） | per-model idle baseline、記憶體 reference、不混用模型 | 以真實 summary 產生 verified `runtime_os_profiles.json` |
| Run metadata / 資源限制（P1-8） | 假 `/proc` 與 cgroup 樹；macOS 上 `constraint_unverified`；GitHub Ubuntu runner 上測試通過 | **`taskset` + `systemd-run --user` 在 cgroup v2 上真的生效，讀回為 `constrained`** |
| CI（P2-1） | GitHub Actions 6/6 jobs 通過 | — |
| 依賴（P2-2） | simulator 只用標準函式庫（測試強制）、Python 3.10–3.13 | **`environment.yml` 在 Linux 上 solve、pins 可安裝、`cv_bridge` 與 `cv2` 相容、產出 `environment.lock.yml`** |
| Repo 衛生 / 文件（P2-3、P2-4） | 沒有 tracked cache；`.gitignore` 策略有測試；文件四類資料分開 | — |
| Pipeline（P2-6） | 不 fallback、拒絕 `model_path`、profile 驗證（單元測試與 stub launch） | **真實 detector 以 timm 建立 `mobilevit_xxs` / `mobilevit_s`；錯誤名稱會讓 run 失敗** |
| Intermittent test error（Batch 3/4 各 1 次） | 之後本機約 145 次、GitHub 5× repeat + 4 個 matrix job 都沒有再出現；診斷資訊已改善 | 持續觀察 CI repeat job；根因未知 |

不可宣稱：已完成真實 ROS 2 benchmark、量測到的硬體能耗、adaptive / runtime scheduling、legacy `measured_*` profiles 是實測資料。

## 5. 未解決的 ROS 2 實機限制

1. `results/raw/ros2/` 沒有任何真實 run；provenance 維持 BLOCKED，直到提交完整的 raw → summary → profiles 鏈。
2. `environment.yml` / `requirements-ros2.txt` 沒有在 Linux 上 solve 或執行過；也沒有 lock 檔。
3. cgroup v2 memory delegation 與 `taskset` 是否真的生效，只在假檔案樹上測試過。
4. Metadata 是 launch 前的快照，沒有持續監控（例如 run 途中 OOM 或 cgroup 被修改）。
5. 同機 DDS 可能走 shared memory，UDP buffer tuning 不一定有效；需要從 metadata / `ros2 doctor` 確認 transport。
6. Detector 使用隨機權重（`pretrained=False`）：只量延遲，不量準確率。

## 6. Phase 2 指令（Linux + ROS 2 Humble）

以下指令都在 repo 根目錄執行。A = 指令會自動判斷通過與否（檢查區塊包在 `bash -euo pipefail <<'SH'` 中，遇到第一個失敗就停，不會關閉目前的 terminal，成功時印出 `PASSED`）；M = 需要人工確認。

### 6.1 環境（A）

```bash
git switch main && git pull --ff-only          # or the branch to be measured
conda env create -f environment.yml
conda activate eda_lite
conda env export --no-builds > environment.lock.yml
```

```bash
bash -euo pipefail <<'SH'
python3 -c "import sys; assert sys.version_info[:2] == (3, 10), sys.version"
test "$ROS_DISTRO" = humble
ros2 --help > /dev/null
command -v timeout taskset systemd-run
python3 - <<'PY'
import importlib.metadata as md
pins = dict(l.strip().split("==") for l in open("requirements-ros2.txt")
            if "==" in l and not l.lstrip().startswith("#"))
bad = {n: (v, md.version(n)) for n, v in pins.items() if md.version(n) != v}
assert not bad, f"version mismatch (pinned, installed): {bad}"
import cv2, numpy, timm
from cv_bridge import CvBridge
CvBridge().cv2_to_imgmsg(numpy.zeros((4, 4, 3), numpy.uint8), "bgr8")
for m in ("mobilevit_xxs", "mobilevit_s"):
    timm.create_model(m, pretrained=False)
print("env OK: cv2", cv2.__version__, "numpy", numpy.__version__)
PY
bash scripts/ci_checks.sh all                  # expect exit 0 with provenance BLOCKED
echo "6.1 PASSED"
SH
```

### 6.2 資源限制（A，失敗時不要用 `ALLOW_UNVERIFIED_LIMITS=1` 繞過）

```bash
bash -euo pipefail <<'SH'
test "$(stat -fc %T /sys/fs/cgroup)" = cgroup2fs
grep -qw memory "/sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.controllers"
rm -f /tmp/probe.meta.json
systemd-run --user --scope -p MemoryMax=2G taskset -c 0,1 \
  python3 -m src.ros2_runtime.run_metadata --output /tmp/probe.meta.json --run-id probe \
  --resource-profile normal --requested-cpus 0,1 --requested-memory-max 2G --require-applied
python3 -c "import json; c=json.load(open('/tmp/probe.meta.json'))['resource_limits']['measurement_class']; assert c=='constrained', c; print(c)"
echo "6.2 PASSED"
SH
```

### 6.3 ROS 2 / DDS 紀錄（M）

```bash
echo "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-<distro default>}"
ros2 doctor --report > /tmp/ros2_doctor_report.txt
ros2 node list                                   # should be empty before a run
sysctl net.core.rmem_max net.core.rmem_default   # tuned runs only; set manually with sudo if needed
```

人工確認：CPU 型號 / governor / 背景負載；transport 是否為 shared memory；沒有其他 ROS 2 graph（必要時 `export ROS_DOMAIN_ID=<unused>` 或 `ROS_LOCALHOST_ONLY=1`）。

### 6.4 Smoke test（A；輸出放在 `/tmp`，不要混入 `results/raw/ros2/`）

```bash
bash -euo pipefail <<'SH'
bash experiments/ros2/prepare_coco128.sh
test "$(ls data/raw/images/coco128/images/train2017/*.jpg | wc -l)" -gt 0

# 1) one sweep point must end by timeout with data
FPS_VALUES=5 RUN_SECONDS=20 RESULTS_DIR=/tmp/smoke bash experiments/ros2/run_fps_sweep.sh
ls /tmp/smoke/*.csv /tmp/smoke/*.publisher.csv /tmp/smoke/*.meta.json
fail() { echo "SMOKE FAILED: $*" >&2; exit 1; }
# (set -e ignores commands prefixed with '!', so negative checks use if/then)
if compgen -G '/tmp/smoke/*.failed' > /dev/null; then fail "failed run files in /tmp/smoke"; fi

# 2) a wrong model name must fail the run (no fallback, no analyzable CSV)
if MODEL_NAME=mobilevit_typo FPS_VALUES=5 RUN_SECONDS=20 RESULTS_DIR=/tmp/smoke_bad \
    bash experiments/ros2/run_fps_sweep.sh; then fail "unknown model did not fail the run"; fi
if compgen -G '/tmp/smoke_bad/*[!r].csv' > /dev/null; then fail "detector CSV left behind"; fi

# 3) MODEL_PATH is rejected
if MODEL_PATH=weights.pt bash experiments/ros2/run_fps_sweep.sh; then fail "MODEL_PATH accepted"; fi

# 4) analysis of the smoke run
python3 -m src.ros2_runtime.analyze_runtime --input /tmp/smoke \
  --summary-output /tmp/smoke/summary.csv
python3 - <<'PY'
import csv
rows = list(csv.DictReader(open("/tmp/smoke/summary.csv")))
assert rows and all(r["frame_accounting"] == "publisher_log" for r in rows), rows
for r in rows:
    print(r["run_id"], r["measurement_class"], "processed", r["processed_frames"],
          "avg_latency_ms", r["avg_latency_ms"], "avg_inference_ms", r["avg_inference_ms"])
PY
echo "6.4 SMOKE PASSED"
SH
```

人工確認：`avg_inference_ms` 與 `avg_transport_ms` 的量級合理；`measurement_class` 符合預期（以 wrapper 執行時應為 `constrained`）。

### 6.5 正式量測與驗收（A）

```bash
bash scripts/run_baseline_experiments.sh        # repeat with a new RUN_TAG at least twice
python3 -m src.ros2_runtime.analyze_runtime --input results/raw/ros2 \
  --summary-output results/csv/ros2_runtime_summary.csv --figures-dir results/figures/ros2
python3 -m src.ros2_runtime.build_os_profiles --input results/csv/ros2_runtime_summary.csv \
  --output experiments/eda_lite/runtime_os_profiles.json --profile-prefix measured --require-verified
python3 scripts/check_runtime_provenance.py      # must exit 0 (VERIFIED)
python3 scripts/audit_repro.py P0-3 P1-8         # expect FIXED
```

接著把 `experiments/eda_lite/mobilevit_runtime_aware_sweep.json` 的 `os_profile_file` 改為 `runtime_os_profiles.json`，重跑模擬 / 圖表，然後把 raw CSV、publisher log、`meta.json`、summary + manifest、profiles、sidecars、`environment.lock.yml` 一起提交（`results/README.md`）。之後 CI 的 provenance gate 應顯示 VERIFIED。

## 7. 待使用者決定

- PR #1 是否 merge（本次不 merge）。
- 是否重新產生並提交帶標示的 `os_aware_total_cost_by_sram.svg`（`bash scripts/rebuild_eda_lite_figures.sh` 會覆寫本機舊檔）。
- 是否在之後的 PR 升級 GitHub Actions 的 action 版本（Node.js 20 deprecation）。
