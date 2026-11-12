# Phase 2 / Batch 2：Real ROS 2 Baseline Benchmark

- 日期：2026-11-10（正式量測 15:24–16:41 +08:00）
- 分支：`phase2/batch2-ros2-baseline`，從 Batch 1 最新 commit `8e336f5` 建立；**未 push、未 merge、未修改 `main`**
- Commits：`7ba42a2`（runtime probe + wrapper + summary 欄位）、`bd458fe`（跨 run 聚合 + node 退出等待）、`7377455`（raw data + 衍生結果 + 文件），以及本報告的 commit
- 一句話結論：在 CPU 12,14 / MemoryMax 4G / swap 0 / Fast DDS SHM（**執行期驗證已載入**）的固定條件下，完成 2 模型 × 11 條件 × 3 次獨立 run 的正式 baseline（66 runs），再加上 XXS 40/50/60 FPS 的容量延伸測試（9 runs）。75 個 run 全部成功，DDS 全部驗證通過，provenance **VERIFIED**。
  - MobileViT-S 的處理能力約 **16.3 FPS**，20 FPS 以上屬於真實計算過載。
  - MobileViT-XXS 約 **52–54 FPS**，在 30 FPS 以內沒有任何過載，要到 60 FPS 才過載。
  - 低於容量時 transport loss 為 0；所有掉幀都可以用「過載 + KEEP_LAST 覆寫」量化解釋。

## 1. 環境與前置確認

| 項目 | 值 |
|---|---|
| Host | `ctwlab`，Ubuntu 22.04.4，kernel 6.8.0-90-generic，i7-13700（P-cores 0–15、E-cores 16–23），governor `powersave` |
| Git 起點 | `phase2/batch1-ros2-smoke` @ `8e336f5`，working tree clean（Batch 1 的修改都已提交） |
| Conda env | `eda_lite`（RoboStack Humble、Python 3.10.13、torch 2.5.1+cpu、timm 1.0.11），沒有系統 ROS 2 |
| RMW | 明確設 `RMW_IMPLEMENTATION=rmw_fastrtps_cpp`（wrapper 在設定 Fast DDS profile 時會固定使用它，並拒絕其他 RMW） |
| DDS profile | `experiments/ros2/fastdds_shm_large.xml`（SHA-256 `b2a1505f…3936`，SHM-only，16 MiB segment）；所有 75 個 run 都相同 |
| ROS_DOMAIN_ID | 87（所有 run） |
| 資源限制 | `taskset -c 12,14` + `systemd-run --user --scope -p MemoryMax=4G -p MemorySwapMax=0`；75/75 `measurement_class=constrained` |
| 優先權 | `nice -n 10`（`meta.json process.nice=10`；probe 讀到兩個 node 的 nice 都是 10）；**沒有 sudo，沒有 sysctl 修改** |
| Socket buffer | `net.core.rmem_max=212992`（只讀取）；不在本批次範圍內（不跑 tuned 實驗） |
| 共用主機負載 | 量測期間 1-min load 1.3–2.95；CPU 8/9 有 root `anydesk` 長期負載（避開）。CPU 12/14 量測前閒置（<5%）；SMT sibling 13/15 在量測期間最高 10.7% busy。主機上有 1.1 萬個 root `caddy` 的 zombie（不是我們的，對 pid_max 4194304 沒有影響） |
| Git 狀態 | 正式 66 runs 都是 `7ba42a2`、`dirty=false`；容量延伸 9 runs 是 `bd458fe`、`dirty=false`（兩者差異只有 probe/聚合/節點退出等待，pipeline 與 sweep 參數不變） |

### 1.1 DDS XML 是否真的被載入（不只看環境變數）

新增 `src/ros2_runtime/runtime_probe.py`。它和 launch 在同一個 scope 執行，只讀取資訊，每秒取樣一次，輸出 `<run_id>.probe.json`：

- 從 `/proc/<pid>/fd` 比對 `/proc/net/udp{,6}`，計算 publisher / detector **開啟的 UDP socket 數**。SHM-only profile 關掉 builtin transports，正確載入時應該是 0。
- 從 `/proc/<pid>/maps` 列出映射的 `/dev/shm/fastrtps_*` segment 及其大小。XML 設定 16 MiB；Fast DDS 預設約 512 KB。
- `run_metadata` 另外解析 XML 本身（`shm_only`、`segment_size`），作為 probe 的預期值。
- 若 probe 不能證實 profile 已生效，sweep script 會把該 run 標成 `*.failed`（`REQUIRE_DDS_VERIFIED=1`，有設 profile 時是預設）。

驗證（輸出在 repo 外 `~/phase2_smoke/batch2_20261110/diag/`）：

| 診斷 run | UDP sockets（pub / det） | 最大 SHM segment | 判定 |
|---|---|---|---|
| 正確 XML（preflight `pf1`） | 0 / 0 | 16,802,336 B | verified |
| 不設 XML（negative control） | 7 / 7 | 549,408 B（預設） | 不是 SHM-only profile，不驗證 |
| 壞掉的 XML（多一個非法元素） | 7 / 7 | 549,408 B | Fast DDS 印出 `XMLPARSER Error … Error parsing participant profile`，退回預設 → **run 被判 failed** |

也就是說，「環境變數有設但 profile 沒生效」這種情況現在會被偵測並拒絕。正式 75 個 run 的 probe 都是 `verified=true`：兩個 node 都是 0 個 UDP socket、16.8 MB segment、affinity `12,14`、nice 10、cgroup swap 0；kernel `RcvbufErrors` 增量也都是 0。

### 1.2 Preflight 短測（smoke，60 s 以下，資料不在 `results/`）

| Run | Published / processed（統計窗） | Drop | P50 / P99 (ms) | Inference (ms) | 判讀 |
|---|---|---|---|---|---|
| XXS 5 FPS 20 s | 83 / 83 | 0% | 19.3 / 21.2 | 18.4 | 正常 |
| S 5 FPS 20 s | 82 / 82 | 0% | 60.5 / 64.9 | 59.0 | 正常（MobileViT-S 第一次在本機執行） |
| XXS 30 FPS 30 s | 849 / 849 | 0% | 19.4 / 21.7 | 18.5 | SHM 在 30 FPS × ~1 MB 下無遺失 |
| S 30 FPS 30 s | 845 / 435 | 48.5% | 214.9 / 232.0 | 63.6 | processed 15.5 FPS ≈ 1000/64 ms → **計算過載**；1−1/ρ 預測 47.9% |

高 FPS 下 launch、publisher、detector、SHM 傳輸與統計都正常。XXS 在 30 FPS 下 0 遺失，因此 transport 在這個速率下是無損的。S 的掉幀率和「detector 飽和 + 無損 transport」的預測相差不到 1 個百分點。沒有發現需要停止正式實驗的異常。

## 2. 實驗矩陣與控制變數

| 家族 | 變動維度 | 固定 | 模型 | 次數 |
|---|---|---|---|---|
| FPS sweep | input FPS 5 / 10 / 20 / 30 | QoS depth 5，delay 0 | XXS、S | 3 runs |
| QoS sweep | subscriber KEEP_LAST depth 1 / 5 / 10 | 20 FPS，delay 0 | XXS、S | 3 runs |
| Overload sweep | artificial delay 0 / 30 / 80 / 150 ms | 20 FPS，depth 5 | XXS、S | 3 runs |
| 容量延伸（§4.1） | input FPS 40 / 50 / 60 | depth 5，delay 0 | XXS | 3 runs |

每個條件共同的設定：CPU 12,14、MemoryMax 4G、swap 0、nice 10、`rmw_fastrtps_cpp` + SHM profile、domain 87、publisher RELIABLE depth 10 → detector BEST_EFFORT KEEP_LAST `qos_depth`、COCO128 128 張循環、`RUN_SECONDS=60`、warm-up 10 frames 排除、deadline 100 ms、random-init 權重（只量延遲）。

- **重複方式**：以 repeat 為外層（r1 → r2 → r3），讓緩慢的主機漂移平均分布到所有條件。奇數 repeat 先跑 XXS，偶數 repeat 先跑 S。RUN_TAG 是 `b2r1/b2r2/b2r3`（容量延伸是 `b2cap_r1..3`）；每個 run 有唯一 run_id 和完整 metadata + probe。
- **統計單位是 run**。表中的 ± 是 3 個 run 的 summary 值之間的樣本標準差；min–max 是 run 之間的範圍。frames 沒有被合併成一個大樣本。
- 同一組設定（S/XXS、20 FPS、depth 5、delay 0）在三個家族中各跑了 3 次（共 9 runs），可以用來檢查跨家族的一致性（§4.3）。
- 正式資料：`results/raw/ros2/`（75 × csv / publisher.csv / meta.json / probe.json）。smoke / diagnostic 資料：`~/phase2_smoke/batch2_20261110/{preflight,diag,logs}`，**沒有**放進 `results/`。

## 3. 結果

定義：`offered_fps` 從 publisher log 計算；`processed_fps` 從 completion 時間戳計算；`service = preprocess + artificial delay + inference`（detector callback 單執行緒處理一個 frame 的時間）；`ρ = offered_fps × service / 1000`；「Expected overload drop」 = `100·max(0, 1−1/ρ)`，也就是 transport 無損、detector 飽和時應有的掉幀率；`drop_cause` 對每個 run 判定：`none` / `overload`（ρ ≥ 1）/ `below_capacity`（ρ < 1 卻有掉幀 = transport loss 或佇列 burst）。Latency 一律是 publish → inference 完成的端到端時間；`transport+queue` = publish → callback 開始（DDS 傳輸 + executor 佇列等待）。**`inference` 只包含 forward pass；artificial delay 是注入的 sleep，分開計時，兩者不混在一起。**

### A. Throughput / drop / deadline（mean ± SD across runs；n = runs）

| Scenario | Model | FPS | QoS | Delay | n | Offered FPS | Processed FPS | Drop % (min–max) | Expected overload drop % | ρ | Deadline miss % | Effective miss % | Drop cause |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fps | XXS | 5 | 5 | 0 | 3 | 5.00 ± 0.00 | 5.00 ± 0.00 | 0.00 ± 0.00 (0.00–0.00) | 0.0 ± 0.0 | 0.10 ± 0.00 | 0.0 ± 0.0 | 0.0 ± 0.0 | none |
| fps | XXS | 10 | 5 | 0 | 3 | 10.00 ± 0.00 | 10.00 ± 0.00 | 0.00 ± 0.00 (0.00–0.00) | 0.0 ± 0.0 | 0.19 ± 0.00 | 0.0 ± 0.0 | 0.0 ± 0.0 | none |
| fps | XXS | 20 | 5 | 0 | 3 | 20.00 ± 0.00 | 20.00 ± 0.00 | 0.00 ± 0.00 (0.00–0.00) | 0.0 ± 0.0 | 0.38 ± 0.00 | 0.0 ± 0.0 | 0.0 ± 0.0 | none |
| fps | XXS | 30 | 5 | 0 | 3 | 30.00 ± 0.00 | 30.00 ± 0.00 | 0.00 ± 0.00 (0.00–0.00) | 0.0 ± 0.0 | 0.57 ± 0.01 | 0.0 ± 0.0 | 0.0 ± 0.0 | none |
| fps | XXS | 40 | 5 | 0 | 3 | 40.00 ± 0.00 | 40.00 ± 0.00 | 0.00 ± 0.00 (0.00–0.00) | 0.0 ± 0.0 | 0.74 ± 0.01 | 0.0 ± 0.0 | 0.0 ± 0.0 | none |
| fps | XXS | 50 | 5 | 0 | 3 | 50.00 ± 0.00 | 50.00 ± 0.00 | 0.01 ± 0.02 (0.00–0.03) | 0.0 ± 0.0 | 0.92 ± 0.01 | 0.0 ± 0.0 | 0.0 ± 0.0 | below_capacity;none |
| fps | XXS | 60 | 5 | 0 | 3 | 60.00 ± 0.00 | 53.01 ± 1.45 | 11.68 ± 2.42 (9.63–14.35) | 9.3 ± 2.6 | 1.10 ± 0.03 | 13.3 ± 3.0 | 23.4 ± 4.7 | overload |
| fps | S | 5 | 5 | 0 | 3 | 5.00 ± 0.00 | 5.00 ± 0.00 | 0.00 ± 0.00 (0.00–0.00) | 0.0 ± 0.0 | 0.30 ± 0.00 | 0.0 ± 0.0 | 0.0 ± 0.0 | none |
| fps | S | 10 | 5 | 0 | 3 | 10.00 ± 0.00 | 10.00 ± 0.00 | 0.00 ± 0.00 (0.00–0.00) | 0.0 ± 0.0 | 0.61 ± 0.01 | 0.0 ± 0.0 | 0.0 ± 0.0 | none |
| fps | S | 20 | 5 | 0 | 3 | 20.00 ± 0.00 | 16.13 ± 0.21 | 19.54 ± 1.07 (18.67–20.74) | 18.7 ± 1.1 | 1.23 ± 0.02 | 100.0 ± 0.0 | 100.0 ± 0.0 | overload |
| fps | S | 30 | 5 | 0 | 3 | 30.00 ± 0.00 | 16.20 ± 0.18 | 46.11 ± 0.58 (45.44–46.48) | 45.5 ± 0.6 | 1.84 ± 0.02 | 100.0 ± 0.0 | 100.0 ± 0.0 | overload |
| qos | XXS | 20 | 1 | 0 | 3 | 20.00 ± 0.00 | 20.00 ± 0.00 | 0.00 ± 0.00 (0.00–0.00) | 0.0 ± 0.0 | 0.38 ± 0.01 | 0.0 ± 0.0 | 0.0 ± 0.0 | none |
| qos | XXS | 20 | 5 | 0 | 3 | 20.00 ± 0.00 | 20.00 ± 0.00 | 0.00 ± 0.00 (0.00–0.00) | 0.0 ± 0.0 | 0.38 ± 0.01 | 0.0 ± 0.0 | 0.0 ± 0.0 | none |
| qos | XXS | 20 | 10 | 0 | 3 | 20.00 ± 0.00 | 20.00 ± 0.00 | 0.00 ± 0.00 (0.00–0.00) | 0.0 ± 0.0 | 0.37 ± 0.00 | 0.0 ± 0.0 | 0.0 ± 0.0 | none |
| qos | S | 20 | 1 | 0 | 3 | 20.00 ± 0.00 | 16.67 ± 0.73 | 16.70 ± 3.65 (12.50–19.15) | 15.9 ± 3.7 | 1.19 ± 0.05 | 20.3 ± 4.8 | 33.5 ± 7.0 | overload |
| qos | S | 20 | 5 | 0 | 3 | 20.00 ± 0.00 | 17.44 ± 0.84 | 12.97 ± 4.20 (8.53–16.87) | 12.0 ± 4.3 | 1.14 ± 0.06 | 100.0 ± 0.0 | 100.0 ± 0.0 | overload |
| qos | S | 20 | 10 | 0 | 3 | 20.00 ± 0.00 | 17.16 ± 1.34 | 14.37 ± 6.64 (6.71–18.50) | 13.4 ± 6.8 | 1.16 ± 0.09 | 100.0 ± 0.0 | 100.0 ± 0.0 | overload |
| overload | XXS | 20 | 5 | 0 | 3 | 20.00 ± 0.00 | 20.00 ± 0.00 | 0.00 ± 0.00 (0.00–0.00) | 0.0 ± 0.0 | 0.38 ± 0.00 | 0.0 ± 0.0 | 0.0 ± 0.0 | none |
| overload | XXS | 20 | 5 | 30 | 3 | 20.00 ± 0.00 | 20.00 ± 0.00 | 0.00 ± 0.00 (0.00–0.00) | 0.0 ± 0.0 | 0.95 ± 0.01 | 0.0 ± 0.0 | 0.0 ± 0.0 | none |
| overload | XXS | 20 | 5 | 80 | 3 | 20.00 ± 0.00 | 10.00 ± 0.04 | 50.20 ± 0.21 (49.96–50.35) | 49.7 ± 0.2 | 1.99 ± 0.01 | 100.0 ± 0.0 | 100.0 ± 0.0 | overload |
| overload | XXS | 20 | 5 | 150 | 3 | 20.00 ± 0.00 | 5.88 ± 0.01 | 70.75 ± 0.04 (70.72–70.80) | 70.5 ± 0.0 | 3.39 ± 0.00 | 100.0 ± 0.0 | 100.0 ± 0.0 | overload |
| overload | S | 20 | 5 | 0 | 3 | 20.00 ± 0.00 | 16.82 ± 0.68 | 16.06 ± 3.35 (12.48–19.11) | 15.2 ± 3.4 | 1.18 ± 0.05 | 100.0 ± 0.0 | 100.0 ± 0.0 | overload |
| overload | S | 20 | 5 | 30 | 3 | 20.00 ± 0.00 | 11.12 ± 0.58 | 44.63 ± 2.87 (42.66–47.92) | 44.1 ± 2.9 | 1.79 ± 0.10 | 100.0 ± 0.0 | 100.0 ± 0.0 | overload |
| overload | S | 20 | 5 | 80 | 3 | 20.00 ± 0.00 | 7.05 ± 0.13 | 64.89 ± 0.61 (64.32–65.54) | 64.6 ± 0.7 | 2.83 ± 0.05 | 100.0 ± 0.0 | 100.0 ± 0.0 | overload |
| overload | S | 20 | 5 | 150 | 3 | 20.00 ± 0.00 | 4.70 ± 0.07 | 76.64 ± 0.34 (76.34–77.00) | 76.5 ± 0.3 | 4.25 ± 0.06 | 100.0 ± 0.0 | 100.0 ± 0.0 | overload |

### B. Latency and timing breakdown (ms, mean ± SD across runs)

| Scenario | Model | FPS | QoS | Delay | P50 latency | P95 latency | P99 latency | Jitter | Transport+queue avg | Transport P95 | Preprocess | Artificial delay | Inference avg | Inference P95 | Service |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fps | XXS | 5 | 5 | 0 | 20.2 ± 0.3 | 21.3 ± 0.3 | 21.9 ± 0.4 | 1.0 ± 0.1 | 0.6 ± 0.0 | 0.9 ± 0.0 | 0.44 ± 0.01 | 0.0 ± 0.0 | 19.0 ± 0.3 | 20.1 ± 0.3 | 19.5 ± 0.3 |
| fps | XXS | 10 | 5 | 0 | 19.9 ± 0.3 | 21.2 ± 0.3 | 21.6 ± 0.4 | 0.9 ± 0.1 | 0.6 ± 0.0 | 0.9 ± 0.2 | 0.43 ± 0.03 | 0.0 ± 0.0 | 18.9 ± 0.2 | 20.0 ± 0.1 | 19.3 ± 0.2 |
| fps | XXS | 20 | 5 | 0 | 19.4 ± 0.3 | 20.9 ± 0.1 | 21.5 ± 0.0 | 1.0 ± 0.2 | 0.5 ± 0.0 | 0.7 ± 0.1 | 0.37 ± 0.01 | 0.0 ± 0.0 | 18.5 ± 0.2 | 19.9 ± 0.1 | 18.9 ± 0.2 |
| fps | XXS | 30 | 5 | 0 | 19.7 ± 0.6 | 21.1 ± 0.3 | 21.6 ± 0.6 | 1.1 ± 0.3 | 0.5 ± 0.0 | 0.8 ± 0.0 | 0.37 ± 0.01 | 0.0 ± 0.0 | 18.8 ± 0.5 | 20.1 ± 0.3 | 19.1 ± 0.5 |
| fps | XXS | 40 | 5 | 0 | 19.0 ± 0.5 | 20.5 ± 0.4 | 21.1 ± 0.3 | 0.9 ± 0.1 | 0.5 ± 0.0 | 0.8 ± 0.1 | 0.36 ± 0.02 | 0.0 ± 0.0 | 18.2 ± 0.3 | 19.4 ± 0.4 | 18.5 ± 0.4 |
| fps | XXS | 50 | 5 | 0 | 18.9 ± 0.2 | 20.7 ± 0.5 | 22.5 ± 1.0 | 1.1 ± 0.2 | 0.7 ± 0.1 | 1.6 ± 0.4 | 0.35 ± 0.02 | 0.0 ± 0.0 | 18.0 ± 0.1 | 19.3 ± 0.1 | 18.4 ± 0.1 |
| fps | XXS | 60 | 5 | 0 | 93.8 ± 0.6 | 101.7 ± 0.4 | 103.2 ± 0.3 | 5.4 ± 0.1 | 75.4 ± 0.1 | 83.0 ± 0.0 | 0.32 ± 0.00 | 0.0 ± 0.0 | 18.1 ± 0.5 | 19.3 ± 0.0 | 18.4 ± 0.5 |
| fps | S | 5 | 5 | 0 | 60.0 ± 1.1 | 62.5 ± 1.5 | 64.8 ± 0.8 | 1.8 ± 0.5 | 0.6 ± 0.0 | 0.7 ± 0.0 | 0.40 ± 0.00 | 0.0 ± 0.0 | 59.1 ± 0.9 | 61.5 ± 1.5 | 59.5 ± 0.9 |
| fps | S | 10 | 5 | 0 | 61.6 ± 0.6 | 64.5 ± 1.1 | 66.8 ± 1.6 | 1.6 ± 0.4 | 0.5 ± 0.0 | 0.6 ± 0.0 | 0.37 ± 0.01 | 0.0 ± 0.0 | 60.9 ± 0.7 | 63.6 ± 1.2 | 61.3 ± 0.7 |
| fps | S | 20 | 5 | 0 | 286.9 ± 0.9 | 310.1 ± 1.1 | 312.8 ± 1.4 | 16.2 ± 0.4 | 224.9 ± 0.2 | 248.2 ± 0.1 | 0.33 ± 0.00 | 0.0 ± 0.0 | 61.2 ± 0.8 | 64.3 ± 1.1 | 61.5 ± 0.8 |
| fps | S | 30 | 5 | 0 | 211.7 ± 0.8 | 227.0 ± 1.1 | 229.8 ± 1.9 | 9.8 ± 0.1 | 150.5 ± 0.1 | 165.7 ± 0.3 | 0.33 ± 0.00 | 0.0 ± 0.0 | 60.9 ± 0.7 | 63.6 ± 1.9 | 61.2 ± 0.7 |
| qos | XXS | 20 | 1 | 0 | 19.5 ± 0.3 | 21.1 ± 0.3 | 21.6 ± 0.2 | 0.9 ± 0.0 | 0.6 ± 0.0 | 0.8 ± 0.1 | 0.39 ± 0.01 | 0.0 ± 0.0 | 18.7 ± 0.3 | 20.0 ± 0.2 | 19.1 ± 0.3 |
| qos | XXS | 20 | 5 | 0 | 19.7 ± 0.6 | 21.2 ± 0.2 | 21.9 ± 0.4 | 1.1 ± 0.2 | 0.6 ± 0.0 | 0.9 ± 0.1 | 0.41 ± 0.02 | 0.0 ± 0.0 | 18.8 ± 0.4 | 20.0 ± 0.1 | 19.2 ± 0.4 |
| qos | XXS | 20 | 10 | 0 | 19.0 ± 0.2 | 20.7 ± 0.3 | 21.2 ± 0.2 | 0.9 ± 0.1 | 0.5 ± 0.0 | 0.7 ± 0.0 | 0.38 ± 0.02 | 0.0 ± 0.0 | 18.3 ± 0.2 | 19.7 ± 0.3 | 18.6 ± 0.2 |
| qos | S | 20 | 1 | 0 | 84.9 ± 2.1 | 107.3 ± 2.4 | 110.0 ± 2.7 | 14.5 ± 0.0 | 25.4 ± 0.2 | 48.1 ± 0.2 | 0.33 ± 0.00 | 0.0 ± 0.0 | 59.2 ± 2.6 | 61.4 ± 3.3 | 59.5 ± 2.6 |
| qos | S | 20 | 5 | 0 | 282.2 ± 2.8 | 305.3 ± 2.6 | 309.2 ± 3.8 | 16.1 ± 0.2 | 224.8 ± 0.2 | 248.3 ± 0.3 | 0.33 ± 0.00 | 0.0 ± 0.0 | 56.6 ± 2.7 | 60.4 ± 3.9 | 56.9 ± 2.7 |
| qos | S | 20 | 10 | 0 | 531.6 ± 6.3 | 556.2 ± 4.2 | 561.9 ± 2.0 | 43.6 ± 4.0 | 467.9 ± 0.6 | 497.8 ± 0.5 | 0.34 ± 0.02 | 0.0 ± 0.0 | 57.6 ± 4.4 | 64.2 ± 1.3 | 58.0 ± 4.4 |
| overload | XXS | 20 | 5 | 0 | 19.4 ± 0.1 | 21.0 ± 0.1 | 22.8 ± 2.1 | 1.2 ± 0.3 | 0.6 ± 0.0 | 0.8 ± 0.0 | 0.39 ± 0.02 | 0.0 ± 0.0 | 18.6 ± 0.2 | 19.9 ± 0.2 | 19.0 ± 0.2 |
| overload | XXS | 20 | 5 | 30 | 47.9 ± 0.5 | 49.8 ± 0.5 | 51.4 ± 1.2 | 1.1 ± 0.4 | 0.6 ± 0.1 | 1.0 ± 0.3 | 0.34 ± 0.01 | 30.2 ± 0.0 | 17.1 ± 0.4 | 18.6 ± 0.5 | 47.6 ± 0.4 |
| overload | XXS | 20 | 5 | 80 | 327.8 ± 3.4 | 347.9 ± 0.4 | 350.2 ± 0.2 | 15.5 ± 1.5 | 227.4 ± 1.4 | 248.4 ± 0.6 | 0.33 ± 0.00 | 80.4 ± 0.0 | 18.7 ± 0.4 | 20.1 ± 0.4 | 99.5 ± 0.4 |
| overload | XXS | 20 | 5 | 150 | 395.1 ± 0.4 | 417.3 ± 0.7 | 419.6 ± 0.5 | 14.5 ± 0.0 | 225.6 ± 0.3 | 247.6 ± 0.3 | 0.33 ± 0.00 | 150.7 ± 0.0 | 18.5 ± 0.2 | 19.5 ± 0.3 | 169.6 ± 0.2 |
| overload | S | 20 | 5 | 0 | 284.1 ± 2.3 | 307.6 ± 2.0 | 311.8 ± 1.0 | 16.9 ± 0.8 | 224.8 ± 0.7 | 248.1 ± 0.7 | 0.33 ± 0.00 | 0.0 ± 0.0 | 58.7 ± 2.4 | 63.5 ± 0.7 | 59.0 ± 2.4 |
| overload | S | 20 | 5 | 30 | 315.1 ± 4.3 | 338.2 ± 5.0 | 342.1 ± 4.5 | 14.8 ± 0.0 | 225.6 ± 0.3 | 248.5 ± 0.3 | 0.33 ± 0.00 | 30.2 ± 0.0 | 59.0 ± 4.8 | 63.5 ± 4.1 | 89.5 ± 4.8 |
| overload | S | 20 | 5 | 80 | 366.7 ± 2.2 | 389.7 ± 3.1 | 393.1 ± 4.4 | 14.7 ± 0.3 | 225.5 ± 0.2 | 248.0 ± 0.3 | 0.34 ± 0.01 | 80.4 ± 0.0 | 60.5 ± 2.6 | 63.5 ± 3.6 | 141.3 ± 2.6 |
| overload | S | 20 | 5 | 150 | 438.2 ± 2.7 | 461.2 ± 2.4 | 463.9 ± 3.0 | 14.6 ± 0.2 | 226.2 ± 0.7 | 248.5 ± 0.7 | 0.33 ± 0.00 | 150.7 ± 0.0 | 61.4 ± 3.0 | 65.1 ± 3.4 | 212.5 ± 3.0 |

### C. CPU / memory (mean ± SD across runs)

| Scenario | Model | FPS | QoS | Delay | Detector CPU % (CSV, psutil) | Detector CPU % (probe) | Publisher CPU % (probe) | Detector RSS avg MB | RSS max MB | cgroup memory.peak MB | Max busy % of SMT siblings 13/15 | Load avg max |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fps | XXS | 5 | 5 | 0 | 10.2 ± 0.1 | 10.7 ± 0.1 | 1.3 ± 0.1 | 401 ± 1 | 404 ± 1 | 349 ± 2 | 1.1 ± 1.0 | 1.98 ± 0.38 |
| fps | XXS | 10 | 5 | 0 | 20.1 ± 0.3 | — | 2.5 ± 0.1 | 402 ± 0 | 406 ± 2 | 351 ± 4 | 0.8 ± 0.1 | 1.80 ± 0.46 |
| fps | XXS | 20 | 5 | 0 | 39.2 ± 0.3 | — | 4.9 ± 0.2 | 402 ± 0 | 406 ± 1 | 353 ± 2 | 1.1 ± 0.6 | 2.04 ± 0.19 |
| fps | XXS | 30 | 5 | 0 | 59.6 ± 1.5 | — | 7.4 ± 0.6 | 402 ± 0 | 405 ± 0 | 353 ± 2 | 0.9 ± 0.7 | 2.15 ± 0.06 |
| fps | XXS | 40 | 5 | 0 | 77.1 ± 1.6 | 77.0 ± 1.6 | 9.9 ± 0.5 | 402 ± 0 | 406 ± 1 | 350 ± 3 | 2.5 ± 1.0 | 2.50 ± 0.33 |
| fps | XXS | 50 | 5 | 0 | 95.2 ± 0.7 | 95.0 ± 0.8 | 12.3 ± 0.5 | 403 ± 0 | 406 ± 0 | 354 ± 4 | 3.1 ± 0.9 | 2.60 ± 0.25 |
| fps | XXS | 60 | 5 | 0 | 100.4 ± 0.0 | 100.4 ± 0.0 | 14.9 ± 0.5 | 411 ± 2 | 414 ± 1 | 364 ± 2 | 2.9 ± 1.9 | 2.64 ± 0.10 |
| fps | S | 5 | 5 | 0 | 30.1 ± 0.4 | 30.6 ± 0.4 | 1.3 ± 0.1 | 438 ± 2 | 444 ± 3 | 395 ± 1 | 1.3 ± 0.4 | 1.80 ± 0.27 |
| fps | S | 10 | 5 | 0 | 62.0 ± 0.7 | — | 2.6 ± 0.1 | 439 ± 1 | 443 ± 0 | 397 ± 1 | 1.5 ± 0.9 | 2.29 ± 0.23 |
| fps | S | 20 | 5 | 0 | 100.2 ± 0.0 | — | 5.4 ± 0.2 | 451 ± 2 | 454 ± 1 | 409 ± 1 | 5.2 ± 1.4 | 2.49 ± 0.06 |
| fps | S | 30 | 5 | 0 | 100.2 ± 0.0 | — | 7.5 ± 0.3 | 448 ± 4 | 452 ± 3 | 412 ± 2 | 1.9 ± 0.8 | 2.63 ± 0.11 |
| qos | XXS | 20 | 1 | 0 | 39.6 ± 0.7 | 39.9 ± 0.7 | 5.0 ± 0.4 | 402 ± 1 | 405 ± 1 | 349 ± 3 | 1.0 ± 0.8 | 2.17 ± 0.11 |
| qos | XXS | 20 | 5 | 0 | 40.0 ± 1.0 | — | 5.0 ± 0.3 | 402 ± 0 | 407 ± 1 | 352 ± 0 | 1.0 ± 0.5 | 2.12 ± 0.47 |
| qos | XXS | 20 | 10 | 0 | 38.7 ± 0.4 | — | 4.8 ± 0.0 | 401 ± 1 | 406 ± 1 | 357 ± 6 | 1.0 ± 0.6 | 2.21 ± 0.22 |
| qos | S | 20 | 1 | 0 | 100.1 ± 0.0 | 100.1 ± 0.0 | 5.0 ± 0.1 | 442 ± 4 | 446 ± 3 | 402 ± 3 | 6.0 ± 3.2 | 2.72 ± 0.13 |
| qos | S | 20 | 5 | 0 | 100.2 ± 0.0 | — | 5.4 ± 0.5 | 452 ± 10 | 456 ± 6 | 411 ± 8 | 8.3 ± 3.4 | 2.66 ± 0.00 |
| qos | S | 20 | 10 | 0 | 100.2 ± 0.0 | — | 5.3 ± 0.3 | 455 ± 2 | 461 ± 1 | 417 ± 4 | 4.3 ± 2.6 | 2.65 ± 0.07 |
| overload | XXS | 20 | 5 | 0 | 39.5 ± 0.4 | 39.9 ± 0.4 | 4.9 ± 0.2 | 401 ± 1 | 406 ± 2 | 350 ± 2 | 1.7 ± 0.7 | 2.34 ± 0.09 |
| overload | XXS | 20 | 5 | 30 | 36.0 ± 0.8 | — | 4.7 ± 0.1 | 406 ± 1 | 408 ± 1 | 354 ± 3 | 1.2 ± 0.7 | 2.29 ± 0.15 |
| overload | XXS | 20 | 5 | 80 | 19.8 ± 0.3 | — | 4.7 ± 0.0 | 410 ± 2 | 414 ± 1 | 361 ± 2 | 0.9 ± 0.5 | 2.08 ± 0.35 |
| overload | XXS | 20 | 5 | 150 | 11.5 ± 0.1 | — | 4.9 ± 0.3 | 409 ± 1 | 413 ± 2 | 362 ± 1 | 0.4 ± 0.1 | 1.87 ± 0.08 |
| overload | S | 20 | 5 | 0 | 100.2 ± 0.0 | 100.1 ± 0.0 | 5.2 ± 0.3 | 449 ± 1 | 456 ± 5 | 407 ± 3 | 5.2 ± 3.1 | 2.74 ± 0.19 |
| overload | S | 20 | 5 | 30 | 66.5 ± 1.7 | — | 4.9 ± 0.1 | 453 ± 3 | 456 ± 2 | 415 ± 4 | 3.1 ± 1.6 | 2.58 ± 0.08 |
| overload | S | 20 | 5 | 80 | 43.4 ± 1.0 | — | 4.8 ± 0.0 | 445 ± 4 | 451 ± 2 | 415 ± 4 | 1.6 ± 0.7 | 2.47 ± 0.09 |
| overload | S | 20 | 5 | 150 | 29.4 ± 1.0 | — | 4.7 ± 0.0 | 447 ± 4 | 453 ± 8 | 415 ± 4 | 0.8 ± 0.4 | 2.39 ± 0.06 |


### 主要圖表（`results/figures/ros2_baseline/`，由 `aggregate_baseline` 產生；點 = 單一 run，鬚 = run 間 min–max）

| 圖 | 內容 |
|---|---|
| `fps_throughput.svg` | processed vs offered FPS（含 processed = offered 參考線）：S 在 ~16 FPS 飽和，XXS 到 50 FPS 都沿對角線，60 FPS 才偏離 |
| `fps_latency.svg` | P50 / P99 vs FPS |
| `fps_drop_rate.svg` | 掉幀率 vs FPS |
| `qos_latency_p50.svg`、`qos_drop_rate.svg` | 20 FPS 下 queue depth 的影響 |
| `overload_p50_latency.svg`、`overload_drop_rate.svg`、`overload_effective_miss.svg` | 注入延遲的影響 |
| `latency_breakdown.svg` | 每個條件的 transport+queue / preprocess / artificial delay / inference 堆疊 |

FPS sweep 圖中 XXS 的 40/50/60 FPS 點來自容量延伸（commit `bd458fe`，控制變數相同）。

## 4. 效能瓶頸分析

### 4.1 處理能力（capacity）與過載點

| 模型 | Service time（run 平均的範圍） | Capacity = 1000/service | 無過載的最高測試速率 | 首個過載點 | 證據 |
|---|---|---|---|---|---|
| MobileViT-S | 56.9–61.5 ms（條件平均）；單 run 52.6–64.6 ms | **≈ 16.3 FPS**（條件平均 16.0–17.6） | 10 FPS（ρ 0.61） | 20 FPS（ρ 1.14–1.23） | 20 FPS processed 16.1–17.4、30 FPS processed 16.2 ± 0.2 → 飽和平台；detector CPU 100%（一個核心） |
| MobileViT-XXS | 18.4–19.5 ms | **≈ 51–54 FPS** | 50 FPS（ρ 0.92） | 60 FPS（ρ 1.10 ± 0.03） | 60 FPS processed 53.0 ± 1.5、掉幀 11.7 ± 2.4%、P50 94 ms、deadline miss 13% |

- XXS 在原定 FPS 5–30 範圍內**沒有任何真實計算過載**（ρ ≤ 0.57，0 掉幀）。依指示先分析容量（service ≈ 19 ms → ~52 FPS），再補做少量 40/50/60 FPS（ρ ≈ 0.74 / 0.92 / 1.10）。這不是為了製造掉幀；只是補足容量邊界兩側各一點，其他控制變數都沒有改。
- 50 FPS 有 1/3 個 run 少了 1 個 frame（0.034%）。查證後確認是 **最後一個發布的 frame（2934）在 launch 被 timeout 終止時尚未處理**，屬於 run 結束時的截斷假象，不是負載下的遺失；該 run 的最大延遲只有 36 ms。Analyzer 依既有定義仍然把它算成 drop，所以表中顯示為 `below_capacity;none`。
- 過載點的 drop rate 都和 `1−1/ρ` 預測一致：S 20 FPS 實測 19.5% vs 預測 18.7%；S 30 FPS 46.1% vs 45.5%；XXS 60 FPS 11.7% vs 9.3%（差值小於 1 SD）；overload sweep 每個點的差距都 ≤ 0.6 個百分點。

### 4.2 掉幀來源：transport loss vs 計算過載 vs 佇列

1. **Transport loss = 0（在 ρ < 1 時）。** 所有 ρ < 1 的 run（XXS 最高到 50 FPS、S 最高到 10 FPS），除了上述結束時的截斷 frame 之外，0 掉幀；kernel UDP `RcvbufErrors` 增量為 0；probe 確認沒有使用 UDP。SHM profile 在 ~1 MB × 50 FPS（約 50 MB/s）以內無遺失。
2. **計算過載是所有掉幀的根因。** 在 ρ ≥ 1 時，processed FPS ≈ capacity（例如 S overload d150：processed 4.70 vs 1000/212.5 = 4.71）；drop rate ≈ 1−1/ρ。
3. **佇列決定「丟哪些」和「等多久」，不決定「丟多少」。** Detector 是 BEST_EFFORT + KEEP_LAST(depth)。過載時，新 frame 覆寫佇列中最舊的 frame，而單執行緒 executor 每次取佇列中最舊的那張：
   - 掉幀樣式是規律的跳號（S 30 FPS r1：frame_id 間隔 2 出現 804 次、1 出現 128 次、3 出現 1 次），不像 Batch 1 預設 transport 那種連續整段遺失。
   - 佇列等待 ≈ depth / input_fps：S 20 FPS depth 5 → 225 ms（預測 250）；depth 10 → 468 ms（500）；depth 1 → 25 ms（≈ 半個週期）；S 30 FPS depth 5 → 150 ms（167）；XXS 60 FPS depth 5 → 75 ms（83）。這也解釋了 **S 在 30 FPS 的延遲（212 ms）反而比 20 FPS（287 ms）低**：佇列中保留 5 張的時間跨度變短了。
   - Depth 對 S 的 drop rate 沒有顯著影響（depth 1 / 5 / 10：16.7 ± 3.7 / 13.0 ± 4.2 / 14.4 ± 6.6%，範圍重疊，都符合各自 ρ 的預測），但對延遲影響很大：P50 85 / 282 / 532 ms。只有 depth 1 能把部分 frame 壓在 100 ms deadline 內（deadline miss 20%、effective miss 33.5%）；depth 5 / 10 是 100%。
   - XXS 在 20 FPS（ρ 0.38）時 depth 1/5/10 完全沒有差異（P50 19.0–19.7 ms，0 掉幀）：沒有過載時佇列幾乎是空的。
4. **Artificial delay 與真實 inference 是分開的。** Overload sweep 中 inference 保持在 XXS 17.1–18.7 ms / S 58.7–61.4 ms；artificial delay 實測 30.2 / 80.4 / 150.7 ms（sleep 的 overshoot 約 0.2–0.7 ms）。注入的延遲是 sleep，**不消耗 CPU**（XXS d150 時 detector CPU 只有 11.5%），所以 overload sweep 模擬的是「service time 過長」，不是 CPU 競爭。XXS d30（ρ 0.95）剛好不過載：0 掉幀、P50 48 ms；d80 起過載（50% 掉幀）。

### 4.3 CPU / 記憶體與其他瓶頸

- **Detector 的有效平行度約只有 1 個核心。** 每 frame 的 CPU 時間約等於 inference 的 wall time（S 5 FPS：59 ms × 5 = 0.30 → CPU 30%；XXS 30 FPS：19 ms × 30 = 0.57 → CPU 60%）；過載時 detector 停在 100%（一個核心），而 cgroup 允許 2 個 CPU。第二個 CPU 主要給 publisher 使用（5 FPS 時約 1.3%，60 FPS 時約 15%：imread + cv_bridge + DDS publish）。因此 capacity 的上限是「單一 callback × 約 1 核 inference」，不是記憶體、也不是 transport。（Batch 1 量到 `torch.get_num_threads()=2`；batch=1 的小模型在 2 threads 下，實際 CPU 時間≈wall time。本批次沒有再細分 intra-op 平行效率。）
- **記憶體不是瓶頸。** cgroup `memory.peak` XXS 347–366 MB、S 394–421 MB；detector RSS 最高 462 MB；上限 4 GiB，swap 0（`memory.swap.current` 一直是 0）。過載與 queue depth 10 會讓 RSS 增加約 10–15 MB（佇列中的影像）。
- **Preprocess 很小**（0.32–0.44 ms），不是瓶頸。

### 4.4 變異與不確定性

- **XXS 很穩定**：33 個正式 run 的 inference 18.5 ± 0.6 ms（CV 3%）。同條件 3 個 run 的 P50 SD ≤ 0.6 ms。
- **S 的 inference 在 run 之間有明顯變動**：33 個 run 為 52.6–64.6 ms（平均 59.6，SD 2.7，CV 4.5%），repeat 平均 58.5 / 61.1 / 59.0 ms。它和 SMT sibling 負載、load average 不相關（r = −0.49 / −0.12）。較可能的原因是 `powersave` governor / turbo / 溫度狀態，以及共用主機的 L3 / 記憶體頻寬；在沒有管理員權限（不能固定頻率、沒有 cpuset 獨占）的情況下無法排除。
- 因為 ρ 接近 1，上述變動被放大成 **S 在 20 FPS 時 drop rate 的大幅變異**：同一設定（20 FPS / depth 5 / delay 0）在三個家族的 9 個 run 中，drop 為 8.5–20.7%，processed FPS 為 15.9–18.1。三個家族的平均值（19.5 / 16.1 / 13.0%）彼此差異沒有超過 run 間變異。**所以 S 在 20 FPS 的掉幀率應該引用為範圍（約 9–21%），而不是單一數值。** 對 Phase 3 來說，比較排程策略時要在同一 run 時段內交錯執行，並使用 ≥ 3 個 run。
- n = 3 run／條件：SD 本身的不確定性很大；只能宣稱「差異大於 run 間範圍」，沒有做正式的顯著性檢定。
- Latency 在過載下的 P50 / P99 非常穩定（SD 1–6 ms），因為它主要由 depth / FPS 決定（§4.2），對 inference 變動不敏感。
- 已知量測假象：
  1. Run 結束時最後 1 個 frame 可能被截斷（只影響 50 FPS 的 1 個 run，0.034%）。
  2. 正式 66 run 中，在同一個 scope 裡第 2 個以後的 run，probe 的第一個取樣抓到前一個 run 仍在退出中的 detector（0.1 s PID 追蹤顯示，前一個 detector 在 launch 停止後約 0.5 s 才退出，和下一個 run 的啟動重疊約 0.2 s；下一個 run 的 frame 0 在約 1.4 s 後才發布）。這**沒有和量測窗重疊**：repeat 1 中，該類 run 前 20 個量測 frame 的 inference 中位數和其餘 frame 的比值是 0.94–1.20，與沒有重疊的 run（0.95–1.11）同樣分散，沒有系統性偏高。不過 probe 的 detector CPU 會跨兩個 process 計算，所以這些 run 的「Detector CPU % (probe)」欄位留空（以 detector CSV 的 psutil CPU 為準）。`bd458fe` 已修正：run 之間等待 node 退出，probe 遇到 PID 改變就重新起算；容量延伸的 9 個 run 沒有再出現這個問題。

## 5. 驗證與 provenance

| 檢查 | 結果 |
|---|---|
| 75 個 run 的完成狀態 | 75/75 到時正常結束（exit 124），0 個 `*.failed` |
| Metadata 一致性 | 75/75 `constrained`，`ROS_DOMAIN_ID=87`、`rmw_fastrtps_cpp`、XML SHA-256 相同、nice 10、`git.dirty=false`；正式 66 = `7ba42a2`、容量 9 = `bd458fe` |
| Runtime DDS 驗證 | 75/75 `dds.verified=true`；negative controls（無 XML、壞 XML）分別被辨識 / 拒絕 |
| Analyzer | 75 個 summary row，`frame_accounting=publisher_log`，`timing_schema=v2`，warm-up 排除 10 |
| `python3 scripts/check_runtime_provenance.py` | **VERIFIED**（exit 0）：raw 75 detector CSV / 75 publisher / 75 meta → summary manifest → `runtime_os_profiles.json`（75 個 profile，`--require-verified`） |
| 聚合 manifest | `results/csv/ros2_baseline_conditions.manifest.json` 記錄 summary、summary manifest、75 個 probe 與所有輸出的 SHA-256 |
| `bash scripts/ci_checks.sh all`（eda_lite env） | exit 0：**171 tests OK**（1 skipped）、`bash -n` 通過、audit `0/17 reproduced`、provenance VERIFIED |
| 新測試 | `tests/test_phase2_batch2.py`（15 tests：XML 解析、probe 解析、DDS 判定、script wiring、P50 / FPS 欄位、聚合統計） |

說明：

- `runtime_os_profiles.json` 是為了讓 provenance 鏈完整而依既有流程產生的（每個 run 一個 profile）。**沒有修改任何 EDA-Lite sweep config**（`mobilevit_runtime_aware_sweep.json` 仍然指向 example 檔），也沒有重跑模擬。
- `results/figures/ros2/*.svg`（teammate 的 UNVERIFIED 舊圖）沒有被覆寫；本批次的圖都在 `results/figures/ros2_baseline/`。
- 沒有使用 legacy / synthetic 資料；所有表中的數字都來自 `results/raw/ros2/` 的真實 run。

## 6. Git diff（`8e336f5..7377455`，不含本報告）

```text
 AGENTS.md                                          |   20 +-
 README.md                                          |   18 +-
 experiments/eda_lite/runtime_os_profiles.json      | 1726 ++++++++++++++++++
 experiments/ros2/README.md                         |    6 +-
 experiments/ros2/run_common.sh                     |   71 +-
 experiments/ros2/run_fps_sweep.sh                  |    2 +
 experiments/ros2/run_overload_sweep.sh             |    2 +
 experiments/ros2/run_qos_sweep.sh                  |    2 +
 report/ai_interaction_log.md                       |   18 +
 results/README.md                                  |   13 +-
 results/csv/ros2_baseline_conditions.csv           |   26 +
 results/csv/ros2_baseline_conditions.manifest.json |  363 ++++
 results/csv/ros2_baseline_runs.csv                 |   76 +
 results/csv/ros2_runtime_summary.csv               |   76 +
 results/csv/ros2_runtime_summary.manifest.json     | 1894 ++++++++++++++++++++
 results/figures/ros2_baseline/*.svg (9 files)      |  838 +++++++++
 scripts/run_baseline_experiments.sh                |   17 +-
 src/ros2_runtime/aggregate_baseline.py             |  451 +++++
 src/ros2_runtime/analyze_runtime.py                |   69 +
 src/ros2_runtime/run_metadata.py                   |   52 +-
 src/ros2_runtime/runtime_probe.py                  |  411 +++++
 tests/test_phase2_batch2.py                        |  190 ++
 tests/test_phase2_linux_fixes.py                   |    5 +-
 31 files changed, 6322 insertions(+), 24 deletions(-)    （不含 results/raw）
 results/raw/ros2: 300 files changed, 197812 insertions(+)  （75 runs × csv / publisher.csv / meta.json / probe.json，28 MB）
```

程式碼修改範圍：

- **新增**：`runtime_probe.py`、`aggregate_baseline.py`、測試。
- **擴充**：
  - `analyze_runtime.py`：只在 summary 尾端追加欄位，既有欄位與順序不變。
  - `run_metadata.py`：記錄解析後的 XML 與 nice。
  - `run_common.sh` / sweep scripts：probe 的啟停、DDS gate、node 退出等待。
  - wrapper：nice，以及在使用 Fast DDS profile 時固定 RMW。
- **沒有更動**：pipeline node、QoS 語意、分析定義，也沒有架構重構。

Smoke / 診斷資料和 driver scripts 在 `~/phase2_smoke/batch2_20261110/`（`env.sh`、`run_point.sh`、`formal.sh`、`capacity.sh`、`logs/`、`preflight/`、`diag/`），沒有進 repo。Git identity 和 Batch 1 一樣，以 `git -c user.name/user.email` 指定，沒有修改 git config。

## 7. 限制

- 隨機初始化權重：只代表延遲，不代表準確率。
- 共用主機：只有 taskset 親和性，沒有 cpuset 獨占；governor 是 `powersave`，頻率不固定 → S 的 run 間變異（§4.4）。
- 只測 SHM transport。RMW 預設 transport 的結果（Batch 1：遺失 50–85%）不在本 baseline 中，也不可以與本 baseline 混合比較。Tuned（rmem）實驗沒有執行（需要管理員）。
- 掉幀判定以 publisher log 為準。佇列覆寫與 SHM 層級的丟棄無法從 subscriber 端直接區分；本報告用「ρ < 1 時為 0 + 過載時符合 1−1/ρ」來推論，而不是直接觀測。
- 單一 detector callback（SingleThreadedExecutor）是 pipeline 的既有設計；它決定了 capacity 的上限，但這是 baseline 的一部分，不是量測錯誤。

## 8. 結論：是否可以進入 Phase 3（FIFO / Latest-Frame / Adaptive Scheduling）？

**可以。** 目前已得到足夠可信的 baseline，可以進入 Phase 3：

1. **條件完整、可重現、可追溯**：
   - 2 模型 × 11 條件 × 3 個獨立 run，加上容量延伸，全部是 `constrained`。
   - 控制變數固定，並逐 run 記錄。
   - DDS profile 在執行期驗證。
   - provenance 是 VERIFIED。
2. **兩種模型都有明確的「不過載 / 過載」區間，且有因果證據**：
   - S：capacity ≈ 16 FPS，20 / 30 FPS 都是真實計算過載。
   - XXS：capacity ≈ 52–54 FPS，60 FPS 過載。
   - Overload sweep 用 artificial delay 讓兩個模型都進入 ρ = 1.8–4.2 的過載。
   - Phase 3 的策略因此有實際需要改善的對象。
3. **Transport 已排除**：低於容量時 0 遺失，所有掉幀都用 1−1/ρ 量化吻合。排程策略的效果不會被 middleware 遺失混淆。
4. **已經有可對照的現行策略**：現行行為 = BEST_EFFORT KEEP_LAST(depth) + 處理最舊 frame。
   - depth 5 / 10 會讓過載下的延遲達到 depth / FPS（S 為 282 / 532 ms）。
   - depth 1 是最接近 Latest-Frame 的現成參考點（S 85 ms，effective miss 33.5%）。
   - FIFO 與 Latest-Frame 可以直接和這些數字比較。

進入 Phase 3 時需要注意的事項（不是 blocker）：

- **S 在 20 FPS 附近的 drop rate 有 9–21% 的 run 間變異。** 新策略與 baseline 的比較應該在同一時段交錯執行（A/B/A/B），每個條件 ≥ 3 runs，以 run 為單位比較；不要和本報告的單一平均值直接相減。
- 主要評估指標建議用 **effective miss rate 與 P50 / P99 latency**，而不是只看 drop rate：在過載下，drop rate 由 ρ 決定，排程策略主要影響的是延遲與 deadline。
- XXS 只有在 ≥ 60 FPS 或使用 artificial delay 時才會過載；Phase 3 的 XXS 比較需要使用這些條件。
- 繼續使用同一組控制變數（CPU 12,14 / 4G / swap 0 / nice 10 / SHM profile + probe gate / domain 87），並以 `bd458fe` 之後的 scripts 執行。

## 附錄 D. 每個 run 的結果（共 75 個；統計單位）

欄位：processed FPS、drop %、P50 / P95 / P99 latency (ms)、inference avg (ms)、service (ms)、effective miss %、DDS verified、cgroup memory.peak (MB)。完整欄位見 `results/csv/ros2_baseline_runs.csv`。


| run_id | Processed FPS | Drop % | P50 | P95 | P99 | Inference avg | Service | Effective miss % | DDS verified | memory.peak MB |
|---|---|---|---|---|---|---|---|---|---|---|
| `fps_sweep_mobilevit_s_normal_10fps_qos5_d0_b2r1` | 10.00 | 0.00 | 62.3 | 65.7 | 68.6 | 61.8 | 62.1 | 0.0 | true | 397 |
| `fps_sweep_mobilevit_s_normal_10fps_qos5_d0_b2r2` | 10.00 | 0.00 | 61.4 | 64.2 | 66.1 | 60.6 | 60.9 | 0.0 | true | 396 |
| `fps_sweep_mobilevit_s_normal_10fps_qos5_d0_b2r3` | 10.00 | 0.00 | 61.2 | 63.5 | 65.6 | 60.5 | 60.9 | 0.0 | true | 399 |
| `fps_sweep_mobilevit_s_normal_20fps_qos5_d0_b2r1` | 16.30 | 18.67 | 285.9 | 308.9 | 311.2 | 60.5 | 60.8 | 100.0 | true | 409 |
| `fps_sweep_mobilevit_s_normal_20fps_qos5_d0_b2r2` | 16.18 | 19.19 | 286.8 | 310.3 | 313.1 | 60.9 | 61.3 | 100.0 | true | 411 |
| `fps_sweep_mobilevit_s_normal_20fps_qos5_d0_b2r3` | 15.89 | 20.74 | 287.8 | 311.2 | 314.1 | 62.1 | 62.4 | 100.0 | true | 408 |
| `fps_sweep_mobilevit_s_normal_30fps_qos5_d0_b2r1` | 16.09 | 46.48 | 212.4 | 227.9 | 230.1 | 61.3 | 61.6 | 100.0 | true | 411 |
| `fps_sweep_mobilevit_s_normal_30fps_qos5_d0_b2r2` | 16.11 | 46.41 | 212.1 | 227.2 | 231.5 | 61.2 | 61.6 | 100.0 | true | 411 |
| `fps_sweep_mobilevit_s_normal_30fps_qos5_d0_b2r3` | 16.42 | 45.44 | 210.8 | 225.8 | 227.7 | 60.1 | 60.4 | 100.0 | true | 415 |
| `fps_sweep_mobilevit_s_normal_5fps_qos5_d0_b2r1` | 5.00 | 0.00 | 59.0 | 60.8 | 65.2 | 58.2 | 58.6 | 0.0 | true | 397 |
| `fps_sweep_mobilevit_s_normal_5fps_qos5_d0_b2r2` | 5.00 | 0.00 | 59.7 | 63.7 | 65.4 | 59.1 | 59.5 | 0.0 | true | 395 |
| `fps_sweep_mobilevit_s_normal_5fps_qos5_d0_b2r3` | 5.00 | 0.00 | 61.2 | 63.1 | 63.9 | 60.0 | 60.4 | 0.0 | true | 394 |
| `fps_sweep_mobilevit_xxs_normal_10fps_qos5_d0_b2r1` | 10.00 | 0.00 | 19.8 | 21.3 | 21.9 | 18.8 | 19.2 | 0.0 | true | 351 |
| `fps_sweep_mobilevit_xxs_normal_10fps_qos5_d0_b2r2` | 10.00 | 0.00 | 19.7 | 20.8 | 21.2 | 18.7 | 19.1 | 0.0 | true | 347 |
| `fps_sweep_mobilevit_xxs_normal_10fps_qos5_d0_b2r3` | 10.00 | 0.00 | 20.2 | 21.4 | 21.7 | 19.0 | 19.5 | 0.0 | true | 355 |
| `fps_sweep_mobilevit_xxs_normal_20fps_qos5_d0_b2r1` | 20.00 | 0.00 | 19.4 | 20.9 | 21.5 | 18.6 | 19.0 | 0.0 | true | 353 |
| `fps_sweep_mobilevit_xxs_normal_20fps_qos5_d0_b2r2` | 20.00 | 0.00 | 19.7 | 21.0 | 21.5 | 18.7 | 19.1 | 0.0 | true | 352 |
| `fps_sweep_mobilevit_xxs_normal_20fps_qos5_d0_b2r3` | 20.00 | 0.00 | 19.1 | 20.8 | 21.5 | 18.3 | 18.7 | 0.0 | true | 355 |
| `fps_sweep_mobilevit_xxs_normal_30fps_qos5_d0_b2r1` | 30.00 | 0.00 | 19.0 | 20.8 | 21.3 | 18.3 | 18.7 | 0.0 | true | 353 |
| `fps_sweep_mobilevit_xxs_normal_30fps_qos5_d0_b2r2` | 30.00 | 0.00 | 20.3 | 21.5 | 22.2 | 19.2 | 19.6 | 0.0 | true | 352 |
| `fps_sweep_mobilevit_xxs_normal_30fps_qos5_d0_b2r3` | 30.00 | 0.00 | 19.8 | 21.0 | 21.3 | 18.8 | 19.1 | 0.0 | true | 355 |
| `fps_sweep_mobilevit_xxs_normal_40fps_qos5_d0_b2cap_r1` | 40.00 | 0.00 | 19.5 | 20.9 | 21.4 | 18.6 | 18.9 | 0.0 | true | 353 |
| `fps_sweep_mobilevit_xxs_normal_40fps_qos5_d0_b2cap_r2` | 40.00 | 0.00 | 18.5 | 20.0 | 20.8 | 17.9 | 18.3 | 0.0 | true | 349 |
| `fps_sweep_mobilevit_xxs_normal_40fps_qos5_d0_b2cap_r3` | 40.00 | 0.00 | 18.9 | 20.5 | 21.1 | 18.0 | 18.4 | 0.0 | true | 348 |
| `fps_sweep_mobilevit_xxs_normal_50fps_qos5_d0_b2cap_r1` | 50.00 | 0.00 | 18.7 | 20.3 | 21.3 | 17.9 | 18.3 | 0.0 | true | 353 |
| `fps_sweep_mobilevit_xxs_normal_50fps_qos5_d0_b2cap_r2` | 50.00 | 0.00 | 19.0 | 20.4 | 22.9 | 18.0 | 18.4 | 0.0 | true | 350 |
| `fps_sweep_mobilevit_xxs_normal_50fps_qos5_d0_b2cap_r3` | 49.99 | 0.03 | 19.2 | 21.3 | 23.2 | 18.1 | 18.5 | 0.0 | true | 358 |
| `fps_sweep_mobilevit_xxs_normal_5fps_qos5_d0_b2r1` | 5.00 | 0.00 | 20.5 | 21.4 | 22.2 | 19.2 | 19.7 | 0.0 | true | 348 |
| `fps_sweep_mobilevit_xxs_normal_5fps_qos5_d0_b2r2` | 5.00 | 0.00 | 20.3 | 21.5 | 22.0 | 19.2 | 19.6 | 0.0 | true | 347 |
| `fps_sweep_mobilevit_xxs_normal_5fps_qos5_d0_b2r3` | 5.00 | 0.00 | 19.8 | 21.0 | 21.4 | 18.7 | 19.2 | 0.0 | true | 350 |
| `fps_sweep_mobilevit_xxs_normal_60fps_qos5_d0_b2cap_r1` | 54.24 | 9.63 | 93.3 | 101.4 | 102.9 | 17.6 | 18.0 | 19.6 | true | 363 |
| `fps_sweep_mobilevit_xxs_normal_60fps_qos5_d0_b2cap_r2` | 51.41 | 14.35 | 94.6 | 102.2 | 103.5 | 18.6 | 19.0 | 28.7 | true | 364 |
| `fps_sweep_mobilevit_xxs_normal_60fps_qos5_d0_b2cap_r3` | 53.39 | 11.05 | 93.7 | 101.6 | 103.1 | 17.9 | 18.2 | 21.8 | true | 366 |
| `overload_sweep_mobilevit_s_normal_20fps_qos5_d0_b2r1` | 17.54 | 12.48 | 281.5 | 305.3 | 310.7 | 56.2 | 56.5 | 100.0 | true | 406 |
| `overload_sweep_mobilevit_s_normal_20fps_qos5_d0_b2r2` | 16.20 | 19.11 | 285.7 | 308.8 | 312.6 | 60.9 | 61.2 | 100.0 | true | 405 |
| `overload_sweep_mobilevit_s_normal_20fps_qos5_d0_b2r3` | 16.72 | 16.61 | 285.3 | 308.6 | 312.1 | 59.0 | 59.3 | 100.0 | true | 410 |
| `overload_sweep_mobilevit_s_normal_20fps_qos5_d150_b2r1` | 4.76 | 76.34 | 435.4 | 458.7 | 461.3 | 58.6 | 209.6 | 100.0 | true | 417 |
| `overload_sweep_mobilevit_s_normal_20fps_qos5_d150_b2r2` | 4.63 | 77.00 | 440.9 | 463.4 | 467.1 | 64.6 | 215.6 | 100.0 | true | 417 |
| `overload_sweep_mobilevit_s_normal_20fps_qos5_d150_b2r3` | 4.70 | 76.58 | 438.4 | 461.5 | 463.2 | 61.1 | 212.2 | 100.0 | true | 410 |
| `overload_sweep_mobilevit_s_normal_20fps_qos5_d30_b2r1` | 11.39 | 43.31 | 313.1 | 335.9 | 339.3 | 56.7 | 87.2 | 100.0 | true | 417 |
| `overload_sweep_mobilevit_s_normal_20fps_qos5_d30_b2r2` | 10.46 | 47.92 | 320.0 | 344.0 | 347.3 | 64.6 | 95.1 | 100.0 | true | 417 |
| `overload_sweep_mobilevit_s_normal_20fps_qos5_d30_b2r3` | 11.52 | 42.66 | 312.1 | 334.8 | 339.7 | 55.8 | 86.3 | 100.0 | true | 410 |
| `overload_sweep_mobilevit_s_normal_20fps_qos5_d80_b2r1` | 7.18 | 64.32 | 364.3 | 386.5 | 388.9 | 58.0 | 138.8 | 100.0 | true | 417 |
| `overload_sweep_mobilevit_s_normal_20fps_qos5_d80_b2r2` | 6.92 | 65.54 | 368.8 | 392.7 | 397.7 | 63.2 | 144.0 | 100.0 | true | 417 |
| `overload_sweep_mobilevit_s_normal_20fps_qos5_d80_b2r3` | 7.06 | 64.81 | 366.9 | 389.9 | 392.6 | 60.3 | 141.0 | 100.0 | true | 410 |
| `overload_sweep_mobilevit_xxs_normal_20fps_qos5_d0_b2r1` | 20.00 | 0.00 | 19.3 | 20.9 | 21.4 | 18.4 | 18.8 | 0.0 | true | 347 |
| `overload_sweep_mobilevit_xxs_normal_20fps_qos5_d0_b2r2` | 20.00 | 0.00 | 19.4 | 21.0 | 25.2 | 18.7 | 19.1 | 0.0 | true | 351 |
| `overload_sweep_mobilevit_xxs_normal_20fps_qos5_d0_b2r3` | 20.00 | 0.00 | 19.5 | 21.1 | 21.8 | 18.8 | 19.2 | 0.0 | true | 350 |
| `overload_sweep_mobilevit_xxs_normal_20fps_qos5_d150_b2r1` | 5.89 | 70.72 | 394.6 | 416.5 | 419.0 | 18.3 | 169.4 | 100.0 | true | 362 |
| `overload_sweep_mobilevit_xxs_normal_20fps_qos5_d150_b2r2` | 5.88 | 70.74 | 395.5 | 417.5 | 419.9 | 18.6 | 169.7 | 100.0 | true | 360 |
| `overload_sweep_mobilevit_xxs_normal_20fps_qos5_d150_b2r3` | 5.88 | 70.80 | 395.1 | 417.7 | 419.8 | 18.6 | 169.6 | 100.0 | true | 363 |
| `overload_sweep_mobilevit_xxs_normal_20fps_qos5_d30_b2r1` | 20.00 | 0.00 | 47.6 | 49.1 | 50.1 | 16.7 | 47.2 | 0.0 | true | 353 |
| `overload_sweep_mobilevit_xxs_normal_20fps_qos5_d30_b2r2` | 20.00 | 0.00 | 48.5 | 50.1 | 51.4 | 17.5 | 48.0 | 0.0 | true | 352 |
| `overload_sweep_mobilevit_xxs_normal_20fps_qos5_d30_b2r3` | 20.00 | 0.00 | 47.7 | 50.1 | 52.5 | 17.0 | 47.5 | 0.0 | true | 358 |
| `overload_sweep_mobilevit_xxs_normal_20fps_qos5_d80_b2r1` | 9.97 | 50.30 | 327.4 | 347.6 | 350.4 | 19.0 | 99.8 | 100.0 | true | 359 |
| `overload_sweep_mobilevit_xxs_normal_20fps_qos5_d80_b2r2` | 9.98 | 50.35 | 331.3 | 348.3 | 350.0 | 18.9 | 99.6 | 100.0 | true | 360 |
| `overload_sweep_mobilevit_xxs_normal_20fps_qos5_d80_b2r3` | 10.05 | 49.96 | 324.6 | 347.9 | 350.2 | 18.2 | 99.0 | 100.0 | true | 363 |
| `qos_sweep_mobilevit_s_normal_20fps_qos10_d0_b2r1` | 18.70 | 6.71 | 524.3 | 551.3 | 559.6 | 52.6 | 53.0 | 100.0 | true | 418 |
| `qos_sweep_mobilevit_s_normal_20fps_qos10_d0_b2r2` | 16.45 | 17.90 | 534.8 | 558.2 | 562.6 | 59.9 | 60.3 | 100.0 | true | 421 |
| `qos_sweep_mobilevit_s_normal_20fps_qos10_d0_b2r3` | 16.32 | 18.50 | 535.7 | 559.0 | 563.6 | 60.4 | 60.8 | 100.0 | true | 413 |
| `qos_sweep_mobilevit_s_normal_20fps_qos1_d0_b2r1` | 16.18 | 19.15 | 86.3 | 108.9 | 111.9 | 61.0 | 61.3 | 38.5 | true | 405 |
| `qos_sweep_mobilevit_s_normal_20fps_qos1_d0_b2r2` | 16.33 | 18.45 | 85.9 | 108.5 | 111.1 | 60.4 | 60.7 | 36.5 | true | 402 |
| `qos_sweep_mobilevit_s_normal_20fps_qos1_d0_b2r3` | 17.51 | 12.50 | 82.4 | 104.6 | 107.0 | 56.3 | 56.6 | 25.4 | true | 400 |
| `qos_sweep_mobilevit_s_normal_20fps_qos5_d0_b2r1` | 16.67 | 16.87 | 284.6 | 307.7 | 313.3 | 59.2 | 59.5 | 100.0 | true | 418 |
| `qos_sweep_mobilevit_s_normal_20fps_qos5_d0_b2r2` | 17.33 | 13.51 | 282.9 | 305.7 | 308.2 | 56.9 | 57.2 | 100.0 | true | 403 |
| `qos_sweep_mobilevit_s_normal_20fps_qos5_d0_b2r3` | 18.33 | 8.53 | 279.0 | 302.5 | 306.0 | 53.7 | 54.0 | 100.0 | true | 413 |
| `qos_sweep_mobilevit_xxs_normal_20fps_qos10_d0_b2r1` | 20.00 | 0.00 | 19.3 | 21.0 | 21.4 | 18.4 | 18.8 | 0.0 | true | 364 |
| `qos_sweep_mobilevit_xxs_normal_20fps_qos10_d0_b2r2` | 20.00 | 0.00 | 18.8 | 20.5 | 21.0 | 18.2 | 18.6 | 0.0 | true | 352 |
| `qos_sweep_mobilevit_xxs_normal_20fps_qos10_d0_b2r3` | 20.00 | 0.00 | 18.9 | 20.6 | 21.2 | 18.1 | 18.5 | 0.0 | true | 356 |
| `qos_sweep_mobilevit_xxs_normal_20fps_qos1_d0_b2r1` | 20.00 | 0.00 | 19.8 | 21.2 | 21.7 | 18.9 | 19.3 | 0.0 | true | 349 |
| `qos_sweep_mobilevit_xxs_normal_20fps_qos1_d0_b2r2` | 20.00 | 0.00 | 19.6 | 21.2 | 21.7 | 18.8 | 19.2 | 0.0 | true | 347 |
| `qos_sweep_mobilevit_xxs_normal_20fps_qos1_d0_b2r3` | 20.00 | 0.00 | 19.1 | 20.7 | 21.4 | 18.3 | 18.7 | 0.0 | true | 352 |
| `qos_sweep_mobilevit_xxs_normal_20fps_qos5_d0_b2r1` | 20.00 | 0.00 | 20.1 | 21.4 | 21.7 | 19.1 | 19.5 | 0.0 | true | 352 |
| `qos_sweep_mobilevit_xxs_normal_20fps_qos5_d0_b2r2` | 20.00 | 0.00 | 19.1 | 20.9 | 21.7 | 18.3 | 18.7 | 0.0 | true | 352 |
| `qos_sweep_mobilevit_xxs_normal_20fps_qos5_d0_b2r3` | 20.00 | 0.00 | 20.0 | 21.2 | 22.4 | 18.9 | 19.3 | 0.0 | true | 352 |
