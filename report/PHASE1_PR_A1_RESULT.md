# Phase 1 / PR-A1：ROS 2 Experiment Data Integrity（P0-2）

- 日期：2026-11-10
- Branch：`fix/pr-a1-ros2-data-integrity`（從 `main` @ `44c94d8` 切出；**尚未 commit / push / merge**）
- 對應：`report/audit_p0_p1_p2.md` 的 P0-2
- 結果：P0-2 已修正。`python3 scripts/audit_repro.py P0-2` → `FIXED`；新增 19 個 regression tests，全部 42 個 tests 通過。

## 1. 修改檔案

| 檔案 | 變更 |
|---|---|
| `src/ros2_uav_pipeline/mobilevit_uav_pipeline/run_log.py`（新增，59 行） | 只用標準函式庫的 helper：`resolve_run_id`、`resolve_output_csv`、`create_run_csv`（以 `'x'` 模式獨佔建立檔案） |
| `src/ros2_uav_pipeline/mobilevit_uav_pipeline/mobilevit_detector_node.py` | 新增 `run_id` 參數（預設 `auto`）；`output_csv` 預設改為 `auto`（→ `results/raw/ros2/<run_id>.csv`）；CSV 第一欄改為 `run_id`；檔案已存在就啟動失敗，不再 append |
| `src/ros2_uav_pipeline/launch/mobilevit_uav_pipeline.launch.py` | 宣告 `run_id` 參數並傳給 detector；`output_csv` 預設改為 `auto` |
| `experiments/ros2/run_{fps,qos,overload}_sweep.sh` | `RUN_TAG`（預設 `<timestamp>_<pid>`）；每個 sweep 點的 `run_id = <scenario>_<model>_<resource_profile>_<fps>fps_qos<depth>_d<delay>_<RUN_TAG>`，CSV 為 `$RESULTS_DIR/<run_id>.csv`；啟動前先驗證字元，檔案已存在就中止（exit 1） |
| `scripts/run_{baseline,os_tuned}_experiments.sh` | 每個批次 export 一個共用的 `RUN_TAG` |
| `src/ros2_runtime/analyze_runtime.py` | 以「設定 + `run_id`」分組；summary 新增 `run_id` 欄；新增 `validate_run_integrity()`；同設定多個 run 時，圖上的標籤加 `run1/run2` 區分 |
| `tests/test_ros2_run_integrity.py`（新增） | 19 個 regression tests（見第 3 節） |
| `scripts/audit_repro.py` | P0-2 case 改為同時檢查「legacy 被拒絕」與「有 run_id 時能分開統計」；P1-5 的 `'20'` vs `'20.0'` 改在同一檔案內比較（避免被 run 分組干擾） |
| `README.md`、`AGENTS.md`、`experiments/ros2/README.md`、`report/ros2_pipeline_integration.md` | CSV 契約加入 `run_id`、補上 run identity 規則、`RUN_TAG` 說明、summary 欄位 |
| `report/audit_p0_p1_p2.md`、`report/ai_interaction_log.md` | P0-2 標註為已修正；新增決策紀錄 |

未動到：`src/eda_lite/plot_6lines.py`（使用者既有的未提交變更，原樣保留）、任何量測資料或 `results/`、`run_yolo11_comparison.sh`（已暫停的 legacy 腳本）。

## 2. 設計決策

1. **一次 detector 啟動 = 一個 run = 一個 CSV。** 根因是 detector 以 append 寫入、`frame_id` 每次從 0 起算。修法是在源頭讓每個 run 都有自己的檔案。檔案用 `open(path, 'x')` 獨佔建立：已存在就丟出 `FileExistsError`，**既不 append 也不覆寫**。
2. **`run_id` 兩層保證唯一。** 腳本用 sweep 參數 + `RESOURCE_PROFILE` + `RUN_TAG` 組成 `run_id`，檔名就是 `<run_id>.csv`，所以 run_id 可以直接對回檔案。直接 `ros2 launch` 不帶參數時，node 自動產生 `<timestamp>_<pid>_<uuid8>`。`run_id` 只允許 `[A-Za-z0-9._-]`，以免出現路徑穿越，或被 ROS 參數的 YAML 解析成數字。
3. **檔名加入 `RESOURCE_PROFILE`。** 舊版 baseline 與 OS-tuned 會寫到同一個檔名，現在分開。
4. **Analyzer 寧可報錯也不去重。** `validate_run_integrity()` 遇到以下情況會 `raise ValueError`，訊息會列出檔案、run 與設定：
   - 同一個「設定 + run」內出現重複的 `frame_id`；
   - 同一個 `run_id` 對應到多個設定（run_id 被重複使用）；
   - legacy 檔案內 `frame_id` 回跳（多次 run 被 append，即使 frame_id 沒有重疊）。
5. **Legacy 相容。** 沒有 `run_id` 欄位或值的資料，視為「每個檔案一個 run」，`run_id = legacy:<CLI 給的 csv 路徑>`。乾淨的 legacy 檔照常分析；舊版 baseline 與 tuned 寫在同一檔案的情形，因 `resource_profile` 不同，仍可安全分開。無法安全分開的情形（重複或回跳）則明確報錯，並提示如何處理。
6. **Detector 邏輯抽成純 Python 模組。** 這樣不需要 rclpy 就能測試。node 以 `try: from mobilevit_uav_pipeline.run_log ... except ImportError: from run_log ...` 匯入，兩種啟動方式都支援：installed package，以及 launch 檔直接以路徑執行。
7. **Summary 每個 run 一列。** 同一設定重複執行時，會產生多列 summary；`build_os_profiles` 既有的 `_unique_name` 會加上 `_2` 後綴，不會互相覆蓋。跨 run 聚合（平均、信賴區間）不在本 PR 範圍。

## 3. 測試結果

```bash
python3 -m unittest discover -s tests
```

- **42/42 通過**（原有 23 + 新增 19；Python 3.11.4，macOS）。
- **證明新測試確實能抓到 P0-2**：把新測試放到原始 `HEAD`（`git archive HEAD`）上執行，結果是 `FAILED (failures=15, errors=7)`。19 個新測試中有 18 個失敗；唯一通過的是刻意設計為新舊版都要通過的相容性測試 `test_legacy_file_with_baseline_and_tuned_rows_stays_separable`。

新增測試（`tests/test_ros2_run_integrity.py`）：

| 類別 | 測試 | 涵蓋 |
|---|---|---|
| Analyzer | `test_repeated_runs_with_run_ids_are_summarised_per_run` | 重複執行同一設定 → 兩列，掉幀 49.49% / 0% 各自正確 |
| | `test_two_run_ids_in_one_file_are_separated` | 同檔案內兩個 run_id 也能分開 |
| | `test_duplicate_frame_id_within_one_run_is_rejected` | 同一 run 重複 frame_id → 報錯 |
| | `test_same_run_id_copied_into_two_files_is_rejected` | 跨檔案混用（複製檔案）→ 報錯並列出兩個檔名 |
| | `test_run_id_reused_for_different_configurations_is_rejected` | run_id 被重複用在不同設定 → 報錯 |
| | `test_rows_are_never_silently_deduplicated` | 原始 P0-2 重現情境（legacy append）→ 報錯，不再顯示 0% |
| Legacy | `test_clean_legacy_csv_is_one_run_per_file` | 乾淨 legacy 檔照常分析，`run_id=legacy:<path>` |
| | `test_legacy_file_with_frame_id_restart_is_rejected` | frame_id 不重疊但回跳（99→0）→ 報錯 |
| | `test_legacy_file_with_baseline_and_tuned_rows_stays_separable` | 舊腳本 normal/tuned 同檔 → 依 resource_profile 分開 |
| 輸出 | `test_summary_csv_and_figures_carry_run_identity` | summary CSV 有 `run_id` 欄；圖上標籤 `run1/run2` |
| | `test_os_profiles_keep_repeated_runs_distinct` | 重複 run 產生的 OS profile 名稱不衝突 |
| Detector | `test_auto_run_ids_are_unique_and_explicit_ids_are_kept` | 20 次自動產生 run_id 都不重複；明確指定的值會保留 |
| | `test_invalid_run_id_is_rejected` | `../escape`、`a b`、`a/b`、`-leading-dash` 都被拒絕 |
| | `test_auto_output_csv_uses_run_id` | `auto` → `results/raw/ros2/<run_id>.csv` |
| | `test_existing_csv_is_never_appended_or_overwritten` | 第二次建立同一檔案時失敗，內容不變 |
| | `test_detector_header_and_launch_file_include_run_id` | node header 第一欄是 `run_id`、使用 `create_run_csv`；launch 有宣告並傳遞 `run_id` |
| 腳本 | `test_repeated_sweeps_write_separate_csvs_that_analyze_per_run` | 三個 sweep 腳本各跑兩次（假的 `ros2`/`timeout`）→ 4 個獨立 CSV，`run_id == 檔名`，分析出 4 個 run |
| | `test_reused_run_tag_refuses_to_touch_existing_csv` | 重複使用 `RUN_TAG` → exit 1，既有檔案內容不變，`ros2` 沒有被呼叫 |
| | `test_invalid_run_tag_is_rejected_before_launch` | 非法 `RUN_TAG` → exit 2，`ros2` 沒有被呼叫 |

其他驗證：

| 檢查 | 結果 |
|---|---|
| `python3 scripts/audit_repro.py` | **P0-2 → FIXED**；其餘 8 個（P0-1、P0-3、P1-1/2/3/4/5/7）仍為 REPRODUCED（本 PR 不處理，符合預期） |
| `bash -n experiments/ros2/*.sh scripts/*.sh` | 10/10 通過 |
| `python3 -m py_compile`（ROS 2 node、launch、analyzer、audit 腳本） | 通過 |
| `python3 scripts/check_runtime_provenance.py` | 仍為 incomplete（P0-3，不在本 PR 範圍） |

## 4. 未解決事項與限制

- **沒有在真實 ROS 2 環境實跑。** 本機（macOS）沒有 `ros2`。Detector 的變更由 helper 單元測試與 AST 檢查涵蓋，腳本則以假的 `ros2`/`timeout` 測試；仍需在 Linux/RoboStack 上跑一次 `run_fps_sweep.sh`（例如 `FPS_VALUES=5 RUN_SECONDS=10`），確認 node 能匯入 `run_log`、CSV 第一欄是 `run_id`，以及重跑時會拒絕寫入。
- **launch 中途失敗時腳本不會察覺。** 若 detector 因檔案已存在而啟動失敗，`ros2 launch` 仍會等到 timeout（exit 124），腳本會當成成功。目前由腳本的事前檢查擋下常見情況；完整解法需要讓 launch 在 detector 結束時一起結束（`OnProcessExit` → `Shutdown`）。
- **summary schema 有變。** 新增 `run_id` 欄。下游 `build_os_profiles` 以欄名讀取，不受影響；手寫的外部工具若依欄位位置讀取，需要調整。
- **Legacy run 的識別依賴路徑。** 若同一批 legacy 檔案分別用相對路徑與絕對路徑分析，`run_id` 字串會不同（數值不受影響）。
- **跨 run 聚合尚未實作。** 同一設定的多次 run 目前各自一列，平均或變異數需要另外實作。
- **Tracked `.pyc` 會被改寫。** 執行測試時，Python 會改寫被追蹤的 `src/ros2_runtime/__pycache__/*.pyc`（audit P2-3）。本次交付前已還原，commit 時請排除這些檔案，或先處理 P2-3。
- 其餘 audit 項目（P0-1、P0-3、P1-x、P2-x）依要求未處理。

## 5. 下一步建議

1. **PR-A2（P1-4 / P1-5 資料面，同一區塊的延續）**
   - CSV 加入 `deadline_ms`；
   - deadline miss 只計算 processed frames；
   - explicit drop 與 frame-gap 推估取聯集；
   - group key 數值正規化（`20` vs `20.0`），並修掉混合型別造成的 `TypeError`；
   - 由 publisher 記錄已發布的 frame 範圍，以計入開頭與結尾的掉幀。
2. 在 ROS 2 環境做一次 smoke run，驗證第 4 節第一點，並補上 launch 的 `OnProcessExit` → `Shutdown`。
3. 接著依 audit 第 5 節進行 PR-B（DP objective，P0-1）與 PR-D（provenance，P0-3）。
