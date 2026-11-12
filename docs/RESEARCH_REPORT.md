# 研究結果報告：ROS 2 MobileViT Frame Scheduling

本報告整理自原 README 的研究內容（Key findings、Deadline-Guard vs Adaptive、Benchmark methodology、Limitations、Future work）。各階段的完整量測紀錄見 [`DEVELOPMENT_HISTORY.md`](DEVELOPMENT_HISTORY.md) 所列的 `report/` 檔案；資料如何驗證見 [`DATA_PROVENANCE.md`](DATA_PROVENANCE.md)。

---

## 1. 研究問題與答案

| | |
|---|---|
| **問題** | 當 ROS 2 視覺節點過載時，哪一種 frame scheduling policy 能讓最多 frame 在 100 ms 端到端 deadline 內完成？為什麼？ |
| **系統** | ROS 2 Humble · Fast DDS shared memory（執行期驗證）· MobileViT-S / XXS（timm）· 2 顆綁定 CPU core、4 GiB、無 swap |
| **證據** | 177 個 constrained run：75 個 baseline + 102 個交錯式 A/B（17 blocks × 6 policies），provenance gate `VERIFIED` |
| **答案** | 丟棄「已無法趕上 deadline」的 frame，在主要條件下比 Latest-Frame 降低 effective miss **10.65 pp**；Adaptive 的 utilisation switch 在此之上**沒有可量測的貢獻**。 |

---

## 2. 主要發現

所有數值皆為 block 內 paired difference（平均、95 % Student-t 區間、較低的 block 數 / 總 block 數），來源為 `results/csv/ros2_phase3_formal_paired.csv`，與 Dashboard 顯示一致。

### 2.1 Throughput 在 service-time 上限飽和；未過載時幾乎不掉 frame

- 飽和時 MobileViT-S 處理 **16.7 FPS**、MobileViT-XXS 處理 **53.0 FPS**（過載 run 的 processed FPS）。
- 未超過處理能力時，沒有任何 run 掉超過 0.03 % 的 frame。
- 超過處理能力時，drop rate 符合 `1 − 1/ρ`，平均誤差 0.76 pp。

### 2.2 丟棄預測會超時的 frame 可降低 effective miss

- 主要條件 MobileViT-S 20 FPS（事先指定，n = 5 blocks）：
  **Deadline-Guard − Latest-Frame = −10.65 pp**，95 % CI [−12.30, −9.01]，5/5 blocks 皆較低。
- 已處理 frame 中的 late 比例從 15.6 % 降到 0.3 %，代價是 drop 增加 2.7 pp。

### 2.3 Adaptive 相對 Deadline-Guard 沒有可量測的效益

- **Adaptive − Deadline-Guard = +0.07 pp**，95 % CI [−0.95, 1.09]（3 blocks 較低 / 2 blocks 較高）。
- 五個條件下 |Δ| ≤ 0.32 pp，所有區間都包含 0。
- 原因：在這個負載範圍內，queue 很少同時有兩個可行 frame，utilisation switch 幾乎不會改變被服務的 frame。
- 注意：「沒有差異」不等於「等價」，本研究沒有進行 equivalence test。

### 2.4 效益只出現在一個負載區間

- 效益出現在 detector 過載 **且** inter-arrival + service time 超過 deadline 時（S 20 FPS：50 + 57 ms > 100 ms）。
- 在 S 30 FPS、XXS 30 FPS + 25 ms 注入延遲、S 10 FPS 下，區間都包含 0，與一階 frame-age bound 的預測一致。

### 2.5 負載階梯下排序相同

- S 10 → 20 → 10 FPS（n = 3）：Guard − Latest **−4.32 pp** [−5.55, −3.09]，3/3 blocks；Adaptive − Guard +0.24 pp。

### 2.6 與 legacy 路徑的比較

Legacy 路徑（推論在 DDS callback 內）與 application 路徑的差異同時包含**架構差異**，因此另行報告，永遠不當作 policy 效果。

---

## 3. 機制：Deadline-Guard vs Adaptive

兩者共用同一個 queue、一個以最近 32 個 frame 計算的 P90 service-time estimator，以及同一個 feasibility check：若 `age + 預估 service time > deadline`，該 frame 會被丟棄（`deadline_infeasible`）。

- **Deadline-Guard**：永遠服務最新的可行 frame。
- **Adaptive**：當預估 utilisation ρ̂ < 1 時，額外切換成 EDF（服務最舊的可行 frame）。

這個切換只有在「ρ̂ < 1 且 queue 中有 ≥ 2 個可行 frame」時才會造成差異；在本研究的條件下這種情形太少，所以無法量測到差異。

---

## 4. Benchmark 方法

| 項目 | 設定 |
|---|---|
| 主機 | Intel i7-13700、Ubuntu 22.04、kernel 6.8；以 `taskset` 綁定 CPU 12 與 14；`systemd-run --scope` MemoryMax 4 GiB、swap 0；`nice 10`；不使用 sudo、不修改 sysctl |
| Middleware | ROS 2 Humble、`rmw_fastrtps_cpp`、SHM-only XML（記錄 hash，每個 run 探測實際套用狀態）、`ROS_DOMAIN_ID=87` |
| 工作負載 | COCO128 影像；publisher RELIABLE depth 10 → detector BEST_EFFORT KEEP_LAST；timm MobileViT 隨機權重（只量 latency） |
| 指標 | Effective miss = (late + dropped) / published；on-time FPS；P50 / P95 / P99 端到端 latency；drop 與 late 比例；開始推論時的 frame age；CPU / RSS / cgroup peak |
| Phase 2 baseline | 2 個模型 × 輸入速率 / queue depth / 注入延遲，每個條件 3 次，每次 60 s（75 runs） |
| Phase 3 正式 A/B | 5 個條件 × 6 arms，交錯式 blocks、輪替 arm 順序（S 20 FPS：5 blocks；其餘：3 blocks），每次 65 s，每個 block 前執行 load gate，從乾淨的 detached worktree 量測（102 runs） |
| 統計 | 以 run 為單位。Block 內 paired difference、95 % Student-t 區間、block 正負號計數、exact sign-flip p（n = 5 時下限 0.0625，因此只當作一致性指標，不當作顯著性）。分析計畫與 Adaptive 參數在正式資料取得前即已固定 |
| 控制變因 | 從每個 Phase 3 `meta.json` 讀出 25 項設定並要求完全一致（見 Dashboard Evidence 頁） |

---

## 5. 限制

- **單一主機、每個 phase 單一 session。** 結果描述的是這台 i7-13700（兩顆 P-core、`powersave` governor、共用主機，以 load gate + nice 處理）。不能推論到其他硬體。
- **樣本數小。** 主要條件 5 blocks，其他 3 blocks。只報告 effect size 與區間，不宣稱統計顯著。
- **單一參數組合。** 100 ms deadline、queue capacity 5、一組 Adaptive 參數、一種階梯模式。Utilisation switch 可能在 ρ ≈ 1 且 queue 較長、deadline 遠大於 service time，或 service time 變異很大時才有作用；尚未測試。
- **架構效應。** Legacy 與 application 的差異不只是 policy（XXS application arms 每個 frame 慢約 1.2 ms；legacy 的 service time 在 run 之間變異較大，原因未量測）。
- **只量 latency。** 隨機初始化權重、無 accuracy。**沒有量測任何能耗**；EDA-Lite 的 energy 是 cost-model 估計值。
- **EDA-Lite 是簡化模擬器。** Coarse block profile（非 ONNX 精確結構）、輕量成本模型；受 EDA compiler 論文啟發但不重現它。OS profile 會改變成本權重，但在這些 profile 上不改變選出的切分。

---

## 6. 未來工作

- 探測 Adaptive 可能產生差異的區間：ρ ≈ 1 且 queue 較長、更大的 deadline / service 比、突發或高變異的 service time。
- 在其他硬體、不同日期重複量測；加入 CPU governor / isolation sweep。
- 使用預訓練權重，同時報告 accuracy 與 latency。
- 使用已驗證的 `runtime_os_profiles.json` 重新執行 EDA-Lite runtime-aware sweep（目前只用過 example / legacy profile）。
- 以事先宣告的 margin 對 Adaptive vs Guard 進行正式 equivalence test（TOST）。
