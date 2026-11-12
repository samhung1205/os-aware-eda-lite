# Phase 2 / Batch 1：Linux ROS 2 環境建置與 Smoke 驗證

- 日期：2026-11-10
- 分支：`phase2/batch1-ros2-smoke`（從 `main` @ `6c743fc` 建立；未 push、未 merge）
- Commits：`ce5487f`（修正 + lock + 測試 + 文件）、本報告的 commit
- 一句話結論：**真實 ROS 2 Humble + MobileViT-XXS 端到端 smoke test 成功**，unconstrained 與 constrained（`measurement_class=constrained`）都跑通。過程中發現並修正 1 個啟動 crash；另外確認預設 DDS transport 在這台 server 上會遺失 50–85% 的 frame。這不是 compute 瓶頸。加入 opt-in 的 Fast DDS SHM profile 後，遺失率降為 0%。Smoke 資料不是 measured evidence，沒有放進 `results/`；provenance 仍然是 `BLOCKED`。

## 1. 實際執行環境

| 項目 | 實測值 |
|---|---|
| Host | `ctwlab`，Ubuntu 22.04.4 LTS，kernel 6.8.0-90-generic，x86_64 |
| CPU | Intel i7-13700（hybrid）：P-cores = 邏輯 CPU 0–15（8 核 × SMT），E-cores = 16–23；governor `powersave` |
| 帳號可用 CPU | `Cpus_allowed_list: 0-23`（沒有用 cpuset 限制） |
| 記憶體 | 62 GiB，約 56 GiB available；**有 swap**（`/swapfile` 2G + `/dev/sdb5` 32G） |
| 磁碟 | `/` 可用 447 GB；沒有 `quota` 指令，也沒有看到 user quota |
| cgroup | v2（`cgroup2fs`）；`user@1007.service` 委派的 controllers：**`memory pids`**（沒有 `cpu`、`cpuset`） |
| systemd | 249；`systemctl --user` = running；Linger=no |
| 使用者 | `sam`（在 `sudo` group，但本批次**完全沒有使用 sudo**） |
| 系統 ROS 2 | 沒有（`/opt/ros` 不存在，shell 沒有 `ROS_*`/`AMENT_*`）→ 不可能混用 |
| Conda | miniforge3，conda 26.7.2 / mamba 2.9.0；新建獨立 env `eda_lite`（原本只有 `yolo-backend`、`yolo-web`，都沒有動） |
| Python（env） | 3.10.13；系統 Python 3.10.12 只用來跑 stdlib 測試 |
| ROS 2（env） | RoboStack Humble：`ros-base 0.10.0`、`rclpy 3.3.7`、`cv-bridge 3.2.1`、預設 RMW `rmw_fastrtps_cpp 6.2.2`（`rmw_cyclonedds_cpp` 也在） |
| Python 套件 | `torch 2.5.1+cpu`、`torchvision 0.20.1+cpu`、`timm 1.0.11`、`numpy 1.26.4`、`psutil 7.0.0`、conda `opencv 4.6.0` |
| Socket buffer | `net.core.rmem_max = rmem_default = wmem_* = 212992`（只讀取，沒有修改） |
| 背景負載 | load average 約 1.3；CPU 8 約 87% busy（root `anydesk`）。沒有其他 ROS 2 graph |

## 2. 環境建置

```bash
git switch -c phase2/batch1-ros2-smoke main
nice -n 10 mamba env create -y -f environment.yml        # solve 成功，未修改 environment.yml
conda activate eda_lite
conda env export --no-builds > environment.lock.yml      # 之後做了 portable 化處理（見下）
mamba env create --dry-run -n eda_lite_lockcheck -f environment.lock.yml   # 451 個 conda 套件 solve 成功
```

- `environment.yml` 不需要任何修改：RoboStack channel 順序與 pins 都能 solve，所有套件都能 import。
- 驗證（handoff §6.1）：Python 3.10、`ROS_DISTRO=humble`、`ros2 --help`、`cv_bridge` 雙向轉換（`cv2_to_imgmsg` / `imgmsg_to_cv2`）、`timm.create_model('mobilevit_xxs'|'mobilevit_s', pretrained=False)` 都能做 forward pass（參數量分別為 1,272,024 / 5,578,632）。`cv2` 來自 env 的 conda build。
- **Handoff 指令修正**：§6.1 的 pin 檢查用 `md.version(n) != v` 比對，遇到 pip 回報的 `2.5.1+cpu`（CPU wheel 的 local version）會誤判失敗。本次比對時會忽略 `+cpu`；版本本身與 pin 一致。
- `environment.lock.yml`：移除機器專屬的 `prefix:`；channel 順序改回 `robostack-staging > conda-forge > nodefaults`（export 會打亂順序）；pip 區段加回 `--extra-index-url https://download.pytorch.org/whl/cpu`，否則 `torch==2.5.1+cpu` 裝不起來。dry run 只驗證 conda 部分；pip 部分沒有經過重新建 env 的驗證。
- pip 安裝 `psutil==7.0.0` 時，覆蓋了 conda 拉進來的 `psutil 7.2.2`（pip / conda 混裝，版本符合 pin）。
- Env 內的 `bash scripts/ci_checks.sh all`：exit 0，156 tests OK。

## 3. CPU / Memory 限制

| 驗證 | 結果 |
|---|---|
| `systemd-run --user --scope -p MemoryMax=4G taskset -c 12,14 python3 -m src.ros2_runtime.run_metadata ... --require-applied` | `constrained`，`cpus_allowed=[12,14]`，`memory.max=4294967296` |
| 沒有 wrapper 但宣告 requested limits | `constraint_failed`，exit 3（不會誤標成 constrained） |
| `MemoryMax=256M MemorySwapMax=0` 下配置 600 MB | 被 OOM kill（exit 137）→ memory limit **確實強制執行** |
| 真實 run 中的各 process | launch、publisher、detector 的 affinity 都是 `12,14`，且都在同一個 `run-*.scope` 中；detector threads 只跑在 CPU 12/14 |
| Torch threads | 在 `taskset -c 12,14` 下 `torch.get_num_threads()=2`；unconstrained 下是 16 |

選擇與限制：

- **CPU 12,14**：兩個不同的 P-core（core 6、7），測量時都很閒。避開 CPU 8/9（anydesk）與 E-cores。沒有預設 `0,1`。Wrapper 預設值仍然是 `0,1`，在這台機器上要明確傳入 `CPU_SET=12,14`。
- 沒有委派 `cpu` / `cpuset` controller：不能用 `CPUQuota` / `AllowedCPUs`，只能用 taskset（affinity）。SMT sibling（13、15）和其他核心仍然可能被其他使用者使用，不屬於獨占。
- **Memory 4 GiB**：真實需求很小。constrained run 的 scope `memory.peak` 約 338 MiB（以 `memory.current` 每秒取樣，最大約 331 MiB）；detector RSS 約 400 MB。RSS 比 cgroup 計費高，是因為共享 library 的 page cache 計在別的 cgroup。2G（wrapper 預設）也足夠；MobileViT-S 尚未測。
- **Swap**：主機有 swap。只設 `MemoryMax` 時，超出限制的頁面會被換出而不是 OOM。所以 wrapper 新增 `MemorySwapMax`（`MEMORY_SWAP_MAX`，預設 0），metadata 也會記錄 `memory.swap.max`（smoke run 讀回 0）。這個值不影響 `measurement_class` 的判定。
- 不需要管理員權限。如果需要「獨占核心」或 CPU quota，就需要管理員委派 `cpu`/`cpuset` controller，或提供 isolated cores。這不是 smoke 的 blocker。

## 4. Smoke Test

共同設定：MobileViT-XXS、5 FPS、`RUN_SECONDS=20`、QoS depth 5、deadline 100 ms、warm-up 10、COCO128 128 張（`prepare_coco128.sh`，zip SHA-256 `61e5e302…aeb8e`）、`ROS_DOMAIN_ID=87`（與其他使用者隔離）。

輸出都在 repo 外：`/home/sam/phase2_smoke/batch1_20261110/`（`smoke/<組別>/`、summaries + manifests、`logs/`、probe metadata、helper scripts）。沒有寫入 `results/raw/ros2/`。

### 4.1 Analyzer 結果（`analyze_runtime`，`frame_accounting=publisher_log`）

| Run | Class | Transport | Published / processed（統計窗） | Drop | Avg / P95 / P99 latency (ms) | Jitter | Avg inference (ms) | Transport (ms) | CPU % | RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|
| `u_shm1` | unconstrained | SHM profile | 83 / 83 | 0% | 12.02 / 15.97 / 16.16 | 2.05 | 10.80 | 0.72 | 134 | 401 |
| `c_shm1` | constrained | SHM profile | 83 / 83 | 0% | 19.37 / 20.88 / 21.47 | 0.69 | 18.39 | 0.57 | 9.7 | 400 |
| `c_shm2` | constrained | SHM profile | 83 / 83 | 0% | 19.94 / 21.10 / 21.39 | 0.80 | 18.86 | 0.63 | 10.1 | 402 |
| `c_shm3` | constrained | SHM profile | 83 / 83 | 0% | 19.43 / 20.92 / 21.56 | 0.74 | 18.34 | 0.63 | 9.8 | 402 |
| `c_final`（clean commit `ce5487f`，`git.dirty=false`） | constrained | SHM profile | 83 / 83 | 0% | 19.90 / 21.33 / 21.73 | 0.83 | 18.78 | 0.65 | 10.0 | 402 |
| `c_def1` | constrained | RMW 預設，`ROS_LOCALHOST_ONLY=1` | 43 / 37 | 14.0% | 20.49 / 21.39 / 21.90 | 0.71 | 19.36 | 0.64 | 9.7 | 387 |

時間戳記檢查（從 publisher / detector log 直接計算，包含 warm-up）：SHM 組的 publish rate 是 5.00 FPS（間隔 198.6–201.7 ms），processed rate 也是 5.00 FPS，100% 的 published frame 都有處理。`c_def1` 只處理了 47/92（51%），processed rate 2.95 FPS。所有 run 的 deadline miss 都是 0%（latency 約 20 ms，deadline 100 ms）。

合理性：

- Constrained 下 inference 約 18.4–18.9 ms（2 threads），unconstrained 約 10.8 ms（16 threads）。三次 constrained 重複的 avg latency 差距在 0.6 ms 以內。
- CPU：constrained 約 10%，符合 18.5 ms × 5 FPS ≈ 9% 的單核用量。unconstrained 134% 是 torch / OpenMP 16 threads 的 spin 消耗，不代表效能比較差。`avg_cpu_percent` 只量 detector process。
- Analyzer 的 `published_frames` 是 83 而不是 93，因為統計窗從最後一個 warm-up frame 之後開始（既有語意）。
- 失敗路徑：`MODEL_NAME=mobilevit_typo` 讓 detector 以 `Failed to create model ... Refusing to fall back` 結束，launch 隨之結束，run 被改名為 `*.failed`，exit 1。`MODEL_PATH=weights.pt` 則 exit 2。都符合預期。
- Launch 都在 timeout（exit 124）時正常結束，各有 `.csv` / `.publisher.csv` / `.meta.json` 三個檔案。metadata 有 run_id、git、host、套件、RMW、`ROS_DOMAIN_ID`、QoS、`net.core.*`、requested/effective limits、`dds_profile`（含 SHA-256 `b2a1505f…3936`）。
- Provenance 機制在真實資料上也能運作：`build_os_profiles --require-verified` 用 `c_final` 的 summary + manifest 產生了 `provenance_status=verified` 的 profile。這個檔案只放在 smoke 目錄，**沒有提交**。

### 4.2 診斷 run（全部 unconstrained，修正前或修正中，只用於診斷）

| Run | 條件 | Processed / published（含 warm-up） | Kernel UDP RcvbufErrors Δ |
|---|---|---|---|
| `smoke_u1` | 原始程式 | 啟動 crash（見 §5.1），`*.failed` | — |
| `smoke_u2` | 修正 §5.1 後，RMW 預設，`ROS_LOCALHOST_ONLY=1` | 22 / 98 | — |
| `diag_lo1` | RMW 預設，`ROS_LOCALHOST_ONLY=1` | 47 / 98 | 0 |
| `diag_lo0` | RMW 預設，`ROS_LOCALHOST_ONLY=0` | 15 / 98 | 0 |
| `diag_cyc` | `rmw_cyclonedds_cpp`（UDP） | 1 / 98 | **+233** |
| `diag_shm` | Fast DDS SHM-only，16 MB segment | 93 / 98（遺失的 0–4 是 detector 啟動前發布的 frame，見 §5.3） | 0 |

## 5. 發現與修正（`ce5487f`）

### 5.1 啟動 crash：float 參數收到整數字面值（已修正）

Sweep script 傳入 `input_fps:=5`、`deadline_ms:=100`，ROS 2 會把它們解析成 INTEGER，但 node 宣告的預設值是 `30.0` / `100.0`（DOUBLE）。結果 rclpy 拋出 `InvalidParameterTypeException`，publisher 一啟動就死。Phase 1 的 stub 測試無法發現這個問題。修正方式：兩個 node 的 float 參數改用 `ParameterDescriptor(dynamic_typing=True)`，再以 `float()` 轉換。

### 5.2 DDS transport 遺失大型 best-effort frame（新增 opt-in profile；正式設定待決定）

- 現象：5 FPS、inference 約 10 ms，CPU 遠遠沒有飽和，但 RMW 預設設定下有 50–85% 的 frame 從未到達，而且遺失是連續成段的。較大的影像遺失率較高，但沒有固定門檻。
- 證據：Fast DDS 預設設定遺失時，kernel UDP `RcvbufErrors` 沒有增加。CycloneDDS（純 UDP）幾乎全部遺失，而且 `RcvbufErrors` +233，與 212992 bytes 的 socket buffer 對上 0.4–1.2 MB 影像（UDP 分片）一致。Fast DDS 改成 SHM-only、16 MB segment 後就沒有遺失。所以 Fast DDS 預設設定的遺失應該出在它自己的 transport 層（推測與預設 512 KB 的 SHM segment / 分片有關，**根因未進一步確認**），不是 kernel socket buffer。
- 處理：新增 `experiments/ros2/fastdds_shm_large.xml`（用 `FASTRTPS_DEFAULT_PROFILES_FILE` 啟用，只影響本 process，不需 sudo、不改 sysctl、沒有網路流量）。`run_metadata` 記錄它的路徑與 SHA-256（`dds_profile`）。**沒有改變預設 transport。**
- 對研究設計的影響：專案原本的「tuned = 調大 `rmem_max`」假設，在 Fast DDS 預設設定下不一定成立，因為遺失不在 kernel buffer。用 SHM profile 時，rmem 與結果無關。這需要使用者決定（見 §8）。

### 5.3 啟動期間發布的 frame（已修正；影響小）

Detector 在 import torch 的約 1 秒內，publisher 已經發布 frame 0–4，這些 frame 會被記為「已發布未處理」。Analyzer 在 warm-up > 0 時，本來就會排除最後一個 warm-up frame 之前的 frame，所以**既有統計沒有被污染**。不過 `WARMUP_FRAMES=0` 時會被算成掉幀，raw publisher log 也不乾淨。修正方式：detector 在模型與 CSV 就緒後才建立 subscription；publisher 偵測到 subscriber 之後才開始 frame 0（包括編號與寫 log）。修正後 publisher 與 detector 都是 93 / 93。

### 5.4 其他

- Wrapper（`run_baseline_experiments.sh`、`run_os_tuned_experiments.sh`）：
  - 新增 `MODELS` / `SWEEPS`，可以縮小範圍。smoke test 就是透過真正的 wrapper 執行，而不是自己組指令。
  - 新增 `MemorySwapMax`（見 §3）。
  - 結束訊息改為印出實際的 `RESULTS_DIR`。
- `run_metadata`：新增 `dds_profile` 與 `memory_swap_max_bytes`；`FASTDDS_DEFAULT_PROFILES_FILE` 也納入 env 紀錄。
- 測試：`tests/test_phase2_linux_fixes.py`（8 tests，stdlib，source-level 與 fake cgroup）。
- 文件：README、`experiments/ros2/README.md`、AGENTS.md、`report/ai_interaction_log.md`。

## 6. 測試

| 檢查 | 結果 |
|---|---|
| `bash scripts/ci_checks.sh all`（系統 Python 3.10.12，修改前） | exit 0，148 tests OK |
| `bash scripts/ci_checks.sh all`（`eda_lite` env，Python 3.10.13，修改後） | exit 0，**156 tests OK**；`bash -n` 通過；audit `0/17 reproduced`；provenance **BLOCKED**（預期） |
| `python3 scripts/check_runtime_provenance.py` | exit 1 BLOCKED：`results/raw/ros2/` 沒有資料（smoke 資料刻意不放入） |
| 真實 ROS 2 smoke | 見 §4 |

## 7. Git diff（`main..phase2/batch1-ros2-smoke`，不含本報告）

```text
 AGENTS.md                                          |   9 +-
 README.md                                          |  22 +-
 environment.lock.yml                               | 485 +++++++++++++++++++++
 experiments/ros2/README.md                         |  13 +-
 experiments/ros2/fastdds_shm_large.xml             |  32 ++
 report/ai_interaction_log.md                       |  19 +
 scripts/run_baseline_experiments.sh                |  28 +-
 scripts/run_os_tuned_experiments.sh                |  28 +-
 src/ros2_runtime/run_metadata.py                   |  66 ++-
 .../mobilevit_uav_pipeline/image_stream_node.py    |  15 +-
 .../mobilevit_detector_node.py                     |  12 +-
 tests/test_phase2_linux_fixes.py                   | 134 ++++++
 12 files changed, 812 insertions(+), 51 deletions(-)
```

既有檔案都保留；沒有刪除檔案，也沒有改動 `results/`。這台 server 上沒有設定 git identity。本次**沒有修改 git config**，commit 時用 `git -c user.name=Sam -c user.email=shaojun5861@gmail.com` 指定 identity，與 repo 既有 commits 一致。

## 8. 剩餘 blocker 與待決事項

1. **（待使用者決定）正式 baseline 的 DDS transport**：使用 `fastdds_shm_large.xml`（遺失 0%，量的是 compute / OS scheduling），或使用 RMW 預設（遺失 50–85%，大部分是 middleware 造成的）。兩者不可以在同一個比較中混用。建議採用 SHM profile，並在報告中把「預設 transport 的遺失」當作獨立發現呈現。
2. **Tuned（rmem）實驗需要管理員**：`run_os_tuned_experiments.sh` 要求 `net.core.rmem_max >= 4194304`，目前是 212992，必須由管理員執行 `sysctl`（本批次沒有做）。另外依 §5.2，這個 tuning 對 Fast DDS 預設設定不一定有效，建議先重新確認 tuned 實驗的設計。
3. **尚未驗證**：MobileViT-S、更高 FPS（10/20/30）、QoS / overload sweep、60 s 長度。另外，SHM profile 在 30 FPS × 約 1 MB 下的行為也還沒測。
4. **共用主機干擾**：只能用 taskset，沒有 cpuset 獨占，SMT sibling 與其他核心可能被其他使用者佔用。CPU 8 有固定的背景負載；governor 是 powersave。正式量測時應記錄負載，並在離峰時段重複多次。
5. `environment.lock.yml` 的 pip 區段還沒有經過「從零重建 env」的驗證（conda 部分的 dry run 已通過）。
6. 這台 server 沒有設定 git identity（由使用者決定是否設定）。

## 9. 是否具備執行正式 Baseline Benchmark 的條件

**技術上已具備（MobileViT-XXS），但開始前需要先決定 §8.1 的 transport。** 環境可以重現（`environment.lock.yml`）。Pipeline 在真實 ROS 2 上端到端正常。資源限制能讀回且確實強制執行（`constrained`）。Metadata / manifest / `--require-verified` 鏈在真實資料上可以運作。失敗路徑也正確。

建議下一步（仍然**不是**完整 sweep）：

1. 決定 transport 後，用 `CPU_SET=12,14 MEMORY_MAX=4G` 和 `MODELS=mobilevit_s SWEEPS=fps FPS_VALUES=5 RUN_SECONDS=20` 做一次 MobileViT-S smoke。
2. 用 30 FPS 單點檢查 SHM 在高頻率下的行為。
3. 以上都通過後，再執行 `bash scripts/run_baseline_experiments.sh`，輸出到 `results/raw/ros2/`，至少兩個 `RUN_TAG`，並依 handoff §6.5 完成 provenance `VERIFIED`。

完整 baseline 每個模型有 11 個點（FPS 4 + QoS 3 + overload 4），每點 60 s；兩個模型約 22 分鐘加上啟動時間，每次重複都佔用 2 個邏輯 CPU。執行前請確認共用 server 的使用狀況。
