# 開發歷程與報告索引

本文件整理自原 README 的 Project history，並將 [`../report/`](../report/) 中的各階段紀錄分類列出。各報告保留原始內容，這裡只提供導覽。

---

## 1. 階段總覽

| 階段 | 成果 | 主要報告 |
|---|---|---|
| **Phase 1** | EDA-Lite 模擬器、correctness / reproducibility audit 修正、CI、provenance 工具 | `report/PHASE1_*`、`report/audit_p0_p1_p2.md` |
| **Phase 2** | Linux + ROS 2 環境建置；75 個 constrained baseline run，provenance `VERIFIED` | `report/PHASE2_BATCH1_RESULT.md`、`report/PHASE2_BATCH2_RESULT.md` |
| **Phase 3** | 排程策略實作 + pilot；102 個 run 的正式 A/B benchmark 與 Deadline-Guard ablation | `report/PHASE3_BATCH1_RESULT.md`、`report/PHASE3_BATCH2_RESULT.md` |
| **Phase 4** | Dashboard、資料管線、文件；最終 QA、視覺設計精修與最終微調；README 改寫為繁中使用說明書，研究與開發紀錄移至 `docs/`；v1.0.0 發布準備（MIT LICENSE、GitHub Pages workflow） | `report/PHASE4_RESULT.md`、`report/FINAL_QA.md`、`report/UI_REFINEMENT_RESULT.md` |

### 方向演變

- 專案起點是 EDA-Lite 模擬器（以簡化 YOLO11 profile 起步）；YOLO 路線之後**暫停**，主線改為 MobileViT。
- 專案名稱從「OS-aware EDA-Lite」統一為 **OS-Aware Edge AI Runtime**；「EDA-Lite」現在只指離線模擬器元件。
- 研究重心從模擬器延伸到 ROS 2 實測：先建立可驗證的 baseline（Phase 2），再比較排程策略（Phase 3），最後以 Dashboard 呈現（Phase 4）。

---

## 2. 報告分類索引

### 2.1 正確性稽核（Audit）

| 檔案 | 內容 |
|---|---|
| [`report/audit_p0_p1_p2.md`](../report/audit_p0_p1_p2.md) | EDA-Lite、ROS 2 分析、pipeline、測試與文件的 P0 / P1 / P2 問題稽核 |

### 2.2 Phase 1：模擬器與工程品質

| 檔案 | 內容 |
|---|---|
| [`report/PHASE1_PR_A1_RESULT.md`](../report/PHASE1_PR_A1_RESULT.md) | ROS 2 實驗資料完整性（P0-2） |
| [`report/PHASE1_BATCH1_RESULT.md`](../report/PHASE1_BATCH1_RESULT.md) | ROS 2 量測正確性 |
| [`report/PHASE1_BATCH2_RESULT.md`](../report/PHASE1_BATCH2_RESULT.md) | Scheduler 與 cost model 正確性 |
| [`report/PHASE1_BATCH3_RESULT.md`](../report/PHASE1_BATCH3_RESULT.md) | 實驗 provenance 與 OS profile 校正 |
| [`report/PHASE1_BATCH4_RESULT.md`](../report/PHASE1_BATCH4_RESULT.md) | 工程品質與可重現性（CI、依賴拆分、結果追蹤規則） |
| [`report/PHASE1_FINAL_HANDOFF.md`](../report/PHASE1_FINAL_HANDOFF.md) | Phase 1 交接總結 |

### 2.3 Phase 2：ROS 2 環境與 baseline

| 檔案 | 內容 |
|---|---|
| [`report/PHASE2_BATCH1_RESULT.md`](../report/PHASE2_BATCH1_RESULT.md) | Linux ROS 2 環境建置與 smoke 驗證（含 DDS transport 掉 frame 問題） |
| [`report/PHASE2_BATCH2_RESULT.md`](../report/PHASE2_BATCH2_RESULT.md) | 正式 constrained baseline benchmark（75 runs）、runtime probe、跨 run 聚合 |

### 2.4 Phase 3：排程策略

| 檔案 | 內容 |
|---|---|
| [`report/PHASE3_BATCH1_RESULT.md`](../report/PHASE3_BATCH1_RESULT.md) | 排程策略與 queue 管理實作、交錯式 pilot |
| [`report/PHASE3_BATCH2_RESULT.md`](../report/PHASE3_BATCH2_RESULT.md) | 正式 A/B benchmark（102 runs）、Adaptive 驗證、Deadline-Guard ablation |

### 2.5 Phase 4：Dashboard 與發佈

| 檔案 | 內容 |
|---|---|
| [`report/PHASE4_RESULT.md`](../report/PHASE4_RESULT.md) | Dashboard、已驗證資料管線、作品集文件 |
| [`report/FINAL_QA.md`](../report/FINAL_QA.md) | 發佈前 QA 與待擁有者決定事項 |
| [`report/RELEASE_v1.0.0.md`](../report/RELEASE_v1.0.0.md) | v1.0.0 發布準備：LICENSE、GitHub Pages workflow、公開資訊檢查、驗證結果、PR 與 Pages 設定指引 |
| [`report/UI_REFINEMENT_RESULT.md`](../report/UI_REFINEMENT_RESULT.md) | Dashboard 視覺設計精修（§1–9）與 Final Visual Polish（§10：Overview 主結果、可放大架構圖、手機收合選單、Deadline-Guard 概念圖、用語修正）；截圖在 [`images/ui_refinement/`](images/ui_refinement/)（`before_*` / `after_*` 為精修前後，`polish_*` 為最終微調） |

### 2.6 整合、Provenance 與總報告

| 檔案 | 內容 |
|---|---|
| [`report/ros2_pipeline_integration.md`](../report/ros2_pipeline_integration.md) | ROS 2 pipeline 整合檢查清單 |
| [`report/runtime_result_provenance.md`](../report/runtime_result_provenance.md) | Runtime 結果的 provenance 追蹤說明 |
| [`report/final_report.md`](../report/final_report.md) | 期末報告草稿 |
| [`report/ai_interaction_log.md`](../report/ai_interaction_log.md) | AI 協作決策紀錄 |
