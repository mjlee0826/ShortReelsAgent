# Implementation Roadmap:分批落地策略

> 本文件記錄如何用 AI 協作(Claude Code)分批實作 `integrated_acceleration_plan.md` 的策略。
> 採用 9 個對話分批,每批獨立驗收,降低 context 失控與 regression 風險。
> 本文件與 `integrated_acceleration_plan.md` 配套使用,前者描述「做什麼」,本文件描述「怎麼一步一步做」。

---

## 目錄

- [Implementation Roadmap:分批落地策略](#implementation-roadmap分批落地策略)
  - [目錄](#目錄)
  - [1. 為什麼分批](#1-為什麼分批)
    - [1.1 一次跑完整份 plan 的四大風險](#11-一次跑完整份-plan-的四大風險)
    - [1.2 分批的原則](#12-分批的原則)
  - [2. 9 個對話總覽](#2-9-個對話總覽)
  - [3. Week 1:Layer 1 模型層獨立優化](#3-week-1layer-1-模型層獨立優化)
    - [範圍](#範圍)
    - [主要產出](#主要產出)
    - [驗收條件](#驗收條件)
    - [風險與緩解](#風險與緩解)
    - [不做](#不做)
  - [4. Week 2a:Pipeline 骨架 + LegacyStage 包裝](#4-week-2apipeline-骨架--legacystage-包裝)
    - [範圍](#範圍-1)
    - [主要產出](#主要產出-1)
    - [驗收條件](#驗收條件-1)
    - [風險與緩解](#風險與緩解-1)
    - [不做](#不做-1)
  - [5. Week 2b:Stage 拆解(image)](#5-week-2bstage-拆解image)
    - [範圍](#範圍-2)
    - [主要產出](#主要產出-2)
    - [驗收條件](#驗收條件-2)
    - [不做](#不做-2)
  - [6. Week 2c:Stage 拆解(video)+ StageGroup 編排](#6-week-2cstage-拆解video-stagegroup-編排)
    - [範圍](#範圍-3)
    - [主要產出](#主要產出-3)
    - [驗收條件](#驗收條件-3)
    - [不做](#不做-3)
  - [7. Week 3a:Dynamic Batching](#7-week-3adynamic-batching)
    - [範圍](#範圍-4)
    - [主要產出](#主要產出-4)
    - [驗收條件](#驗收條件-4)
    - [風險與緩解](#風險與緩解-2)
    - [不做](#不做-4)
  - [8. Week 3b:雙 GPU Qwen Pool + GPU Capacity Manager](#8-week-3b雙-gpu-qwen-pool--gpu-capacity-manager)
    - [範圍](#範圍-5)
    - [主要產出](#主要產出-5)
    - [驗收條件](#驗收條件-5)
    - [風險與緩解](#風險與緩解-3)
  - [9. Week 3c:Layer 4 WebSocket 接前端](#9-week-3clayer-4-websocket-接前端)
    - [範圍](#範圍-6)
    - [主要產出](#主要產出-6)
    - [驗收條件](#驗收條件-6)
    - [不做](#不做-5)
  - [10. Week 4a:Layer 0 雲端攝取](#10-week-4alayer-0-雲端攝取)
    - [範圍](#範圍-7)
    - [主要產出](#主要產出-7)
    - [驗收條件](#驗收條件-7)
    - [外部依賴(實機驗證)](#外部依賴實機驗證)
  - [11. Week 4b:Layer 5 前端 Asset Management UI](#11-week-4blayer-5-前端-asset-management-ui)
    - [範圍](#範圍-8)
    - [主要產出](#主要產出-8)
    - [驗收條件](#驗收條件-8)
    - [外部依賴(實機驗證)](#外部依賴實機驗證-1)
  - [12. 對話啟動範本](#12-對話啟動範本)
  - [13. 對話之間的交接](#13-對話之間的交接)
    - [13.1 一個對話完成後](#131-一個對話完成後)
    - [13.2 開新對話前](#132-開新對話前)
    - [13.3 對話中途斷線或卡住](#133-對話中途斷線或卡住)
  - [14. 外部依賴清單](#14-外部依賴清單)
  - [15. 整體時程估算](#15-整體時程估算)
    - [15.1 樂觀(順利不返工)](#151-樂觀順利不返工)
    - [15.2 實際(預留 buffer)](#152-實際預留-buffer)
    - [15.3 重要里程碑](#153-重要里程碑)

---

## 1. 為什麼分批

### 1.1 一次跑完整份 plan 的四大風險

| 風險 | 說明 |
|---|---|
| Context 失控 | 1500–2000 行新增 + 反覆 read 既有 8 個檔案,長對話後期會自動壓縮早期訊息,設計決策走偏 |
| 中段無法驗證 | 分層設計 Layer 1 錯 → Layer 2 跟著錯,沒有人類在中段檢查,4 週累積的錯誤可能整體重來 |
| 外部依賴擋路 | AWQ 下載模型、Google Drive OAuth、WebSocket 端對端、多 GPU 行為都不能在 sandbox 跑 |
| 業界共識漸進 | Anyscale / Cursor / Sourcegraph 的最佳實踐都是 vertical slice + small PR,review 100 行容易,review 2000 行不可能 |

### 1.2 分批的原則

- **每批 200–600 行**,大致對應一個 PR 規模
- **每批獨立可驗收**,即使停下也不留半成品
- **依賴順序明確**,前一批的產出是下一批的前提
- **外部依賴隔離**,需要實機驗證的批次自成獨立步驟
- **可平行批次明示**,純後端與純前端可同時推進

---

## 2. 9 個對話總覽

```
Week 1   ─ Layer 1 全部 + ProgressTracker 介面          ~400 行   獨立可驗收
   ↓
Week 2a  ─ Pipeline 骨架 + LegacyStage 包既有 process    ~600 行   ← 框架就緒
   ↓
Week 2b  ─ Stage 拆解(image)                          ~300 行
   ↓
Week 2c  ─ Stage 拆解(video)+ StageGroup 編排         ~400 行
   ↓
Week 3a  ─ Dynamic Batching(BatchCollector)            ~300 行   ← 高風險獨立做
   ↓
Week 3b  ─ 雙 GPU Qwen Pool + GPU Capacity Manager       ~300 行
   ↓
Week 3c  ─ Layer 4 WebSocket 接前端                      ~200 行
   ↓
Week 4a  ─ Layer 0(Google Drive + 同步 + Workspace)    ~500 行 ─┐
                                                                  ├─ 可平行
Week 4b  ─ Layer 5(前端 Asset Management UI)            ~600 行 ─┘
```

| 對話 | 範圍 | 約略行數 | 平行可行 | 驗收型態 |
|---|---|---|---|---|
| Week 1 | Layer 1 模型優化 + Tracker 介面 | 400 | 否 | 實機 GPU 測試 |
| Week 2a | Pipeline 骨架 + LegacyStage | 600 | 否(Week 1 之後) | 端到端輸出比對 |
| Week 2b | Image Stage 拆解 | 300 | 否(Week 2a 之後) | 輸出與 2a 一致 |
| Week 2c | Video Stage 拆解 + Group 編排 | 400 | 否(Week 2b 之後) | 輸出與 2b 一致 + 效能提升 |
| Week 3a | Dynamic Batching | 300 | 否(Week 2c 之後) | 壓測 + 結果一致 |
| Week 3b | 雙 GPU + Capacity Manager | 300 | 與 3a 可平行 | 多 GPU 實機測試 |
| Week 3c | WebSocket 進度推播 | 200 | 與 3a/3b 可平行 | wscat 訂閱驗證 |
| Week 4a | Google Drive Ingestion | 500 | 與 4b 可平行 | 雲端 + OAuth 實機 |
| Week 4b | 前端 Asset Management UI | 600 | 與 4a 可平行 | 瀏覽器互動驗證 |

---

## 3. Week 1:Layer 1 模型層獨立優化 ✅ 已完成(2026-05-30)

> **狀態:已完成並實機驗證**。程式碼在 commit `51ef717`(主體)+ `43a8d10`(device 鎖定修正)。
> Lock 機制完整設計另見 `docs/lock_design.md`。

### 範圍
純模型層改動,**完全不動現有 pipeline 架構**,只把模型本身換掉與加 GPU Gate。

### 主要產出(實際完成)
- ✅ Qwen 換成 **`cyankiwi/Qwen3-VL-8B-Instruct-AWQ-4bit`**(官方未釋出 AWQ,改用社群 4-bit 版),Flash Attention 2 啟用、失敗 fallback 到 sdpa
  - env var `QWEN_USE_AWQ`(預設 true)可一行切回 8-bit legacy 供品質回歸
  - **Processor 仍從官方 base `Qwen/Qwen3-VL-8B-Instruct` 載**(AWQ repo 不附 processor)
  - device_map 改 `{"": self.device}` **鎖定指定 GPU**(原 `"auto"` 在共用 GPU 會亂抓滿的卡,也破壞 Week 3b 多卡 Pool)
- ✅ `BaseModelManager` 加 **`GpuGate`(Strategy Pattern)層**,取代原規劃的裸 `GPU_SEMAPHORES`:
  - Week 1 預設 `BinaryGate`(= Semaphore(1));Week 3b 由 Capacity Manager 用 `register_gate_factory()` 一行換成 `BudgetGate`
  - 鎖序「L2 GpuGate → L3 model lock」,CPU/API 模型依 `self.device` 自動跳過 L2
  - Singleton key 從 `device_id` 改 **`(device_id, slot_id)` tuple**(為 Week 3b 同卡多 instance 鋪路,既有 caller 100% 相容)
- ✅ `ModelPool` 新增 **`slots`(`GpuSlot`)介面**,保留 `gpu_ids` 為 backward-compat alias
- ✅ 新增 `MUSIQ.score_batch()` / `LAION.score_batch()` / `Whisper.transcribe_batch()`(保留舊單張介面,尚未接入)
- ✅ 新增 `media_processor/pipeline/progress.py`:`ProgressObserver` / `ProgressTracker` / `ProgressEvent`(pydantic)+ `PrintProgressObserver`(無 WebSocket)
- ✅ `media_processor_config.py` 加入 batch size、`BATCH_COLLECT_TIMEOUT_MS`、`GPU_SAFETY_BUFFER_GB`、`QWEN_USE_AWQ_DEFAULT` 常數
- ✅ 新增 `model/gpu_gate.py`(`GpuGate` ABC + `BinaryGate`)

### 驗收條件達成狀態
- ✅ **FA2 實機生效**:`model.config._attn_implementation == "flash_attention_2"`,dtype `bfloat16`,單卡載入成功
- ⬜ 品質回歸 A/B(AWQ vs 8-bit 結構欄位一致)— 待跑真實 phase 1
- ⬜ 50 asset 同卡 Qwen+Whisper 不 OOM — 待跑
- ⬜ 單張 Qwen ~5s → ~1.5s 計時 — 待跑

### 外部依賴實況(在另一台機器要重現需注意)
- AWQ 模型需 **`compressed-tensors`**(cyankiwi 用 llm-compressor 量化,格式是 compressed-tensors 不是 autoawq)
- **torch 降到 2.10 / torchvision 0.25**:因 `compressed-tensors>=0.16` 要 `torch>=2.10`,且 flash-attn 預編譯 wheel 天花板就是 torch2.10
- flash-attn 用預編譯 wheel `v2.8.1+cu12torch2.10cxx11abiTRUE-cp312`(torch2.11 無 wheel,只能源碼編譯)
- `autoawq` 雖裝了但實際沒用到(此模型走 compressed-tensors 路徑),且官方已 deprecated

### 不做(維持原規劃)
- 不動 `director_service.py` 序列迴圈,既有流程照跑
- 不啟用 batch scoring 的呼叫(只新增方法,Week 3a 才接 BatchCollector)
- 不接 WebSocket(Week 3c)
- 同卡多 instance 紅利 Week 1 看不到(BinaryGate 仍序列化,需 Week 3b BudgetGate)

---

## 4. Week 2a:Pipeline 骨架 + LegacyStage 包裝

### 範圍
**框架建好但不拆 Stage**。新框架包舊邏輯,所有風險降到最低,但 director_service 已切換完。

### 主要產出
- 新增 `media_processor/pipeline/` 模組樹:
  - `context.py` — `AssetContext` dataclass
  - `stage.py` — `Stage` 抽象 + `StageMeta` + `ResourceType` + `StageError`
  - `stage_group.py` — `StageGroup`
  - `pipeline.py` — `Pipeline`
  - `runner.py` — `PipelineRunner` (Facade)
  - `builder.py` — `PipelineBuilder`
  - `executor/` — 四個 Executor + `ExecutorRegistry` + `ModelPoolRegistry`
  - `scheduler/` — `HybridScheduler`
  - `stages/legacy_image_stage.py` / `legacy_video_stage.py` — **整個 `processor.process()` 包成單一 Stage**
- 新增 `config/pipeline_config.py` 集中所有併發/timeout 常數
- 修改 `backend/services/director_service.py` L92 迴圈替換為 `PipelineRunner.run(...)`

### 驗收條件
- 跑同一組測試資料,新版輸出 `phase1_assets_metadata.json` 與 Week 1 結束時逐欄一致
- HybridScheduler 在 `max_assets_parallel=4` 下,4 個 asset 確實平行(觀察 print 或 ProgressTracker 事件)
- 多 GPU 環境下 ModelPool 自動分散到不同卡

### 風險與緩解
| 風險 | 緩解 |
|---|---|
| Executor / ModelPool / Scheduler 介面設計錯誤 | 先寫骨架 + LegacyStage,跑通後再進 Week 2b 拆 Stage |
| `AssetContext` 欄位設計遺漏 | 用 dataclass + Optional,後續可加欄位不需大改 |
| Eager warm up 拖慢後端啟動 | 啟動進度推 ProgressTracker;開發環境用 `EAGER_MODELS=false` 關閉 |

### 不做
- 不拆 Stage(Week 2b/2c 做)
- 不做 Dynamic Batching(Week 3a 做)
- 不做雙 GPU Qwen Pool(Week 3b 做)
- 不接 WebSocket(Week 3c 做)

---

## 5. Week 2b:Stage 拆解(image)

### 範圍
把 `LegacyImagePipelineStage` 內部展開成 10 個獨立 Stage,設計 image pipeline 的 StageGroup 編排。

### 主要產出
- `media_processor/pipeline/stages/` 內新增:
  - `decode_image_stage.py`
  - `saliency_stage.py`
  - `tech_score_stage.py`
  - `aes_score_stage.py`
  - `reject_filter_stage.py`
  - `cv_features_stage.py`
  - `face_detect_stage.py`
  - `exif_stage.py`
  - `semantic_image_stage.py`(內部依 strategy 呼叫 Qwen 或 Gemini)
  - `assembly_image_stage.py`
- `PipelineBuilder` 加入 `_build_image_pipeline()` 方法,定義 StageGroup 編排:
  - G0: `[DecodeImage]`
  - G1: `[TechScore]`(儘早 reject)
  - G2: `[RejectFilter]`(短路檢查)
  - G3: `[Saliency, AesScore, CVFeatures, FaceDetect, Exif]` 大平行
  - G4: `[SemanticImage]`
  - G5: `[AssemblyImage]`
- `LegacyImagePipelineStage` 保留作為 fallback 與 regression 比對

### 驗收條件
- 同一組圖片用 `LegacyImageStage` 與新拆 Stage 各跑一次,輸出逐欄一致
- 單張圖片耗時應略降(因為 G3 群組內並行)
- Early Rejection 觸發時,後續 Saliency / AesScore / SemanticImage 確實未呼叫(用 ProgressTracker 事件驗證)

### 不做
- 不拆 video Stage(Week 2c)
- 不做 image 的 batch scoring(Week 3a 才接 Dynamic Batching)

---

## 6. Week 2c:Stage 拆解(video)+ StageGroup 編排

### 範圍
把 `LegacyVideoPipelineStage` 內部展開,設計 video pipeline 的 StageGroup 編排,重點在於 G1 大平行群帶來的重疊紅利。

### 主要產出
- `media_processor/pipeline/stages/` 內新增:
  - `decode_video_stage.py`
  - `timecode_stage.py`(Complex only)
  - `audio_extraction_stage.py`
  - `audio_inference_stage.py`
  - `scene_cut_stage.py`
  - `middle_frame_stage.py`
  - `visual_scoring_video_stage.py`(Simple only)
  - `cv_features_video_stage.py`
  - `motion_intensity_stage.py`(Simple only)
  - `saliency_union_stage.py`(Simple only)
  - `semantic_video_stage.py`(依 strategy 呼叫 Qwen 或 Gemini)
  - `event_bbox_stage.py`(Complex only)
  - `assembly_video_stage.py`
- `PipelineBuilder._build_video_pipeline()` 定義 StageGroup:
  - G0: `[DecodeVideo]`
  - G1: `[Timecode*, AudioExtraction, SceneCut, MiddleFrame, MotionIntensity*, SaliencyUnion*]` 大平行群
  - G2: `[AudioInference, VisualScoringVideo*, CVFeaturesVideo]`
  - G3: `[SemanticVideo]`
  - G4: `[EventBbox]`(Complex only)
  - G5: `[AssemblyVideo]`
- `LegacyVideoPipelineStage` 保留作為 fallback

### 驗收條件
- 同一組影片(含 1 個 Complex)用 Legacy 與新拆 Stage 各跑一次,輸出逐欄一致
- **Simple 影片從 45s 壓到 ~27s**(G1 群組重疊生效)
- **Complex 影片從 110s 壓到 ~84s**(timecode 與其他 Stage 並行)
- StageGroup 內 Stage 寫入 `AssetContext` 不同欄位,無衝突

### 不做
- 不做 BatchCollector(Week 3a)
- 不做 Capacity Manager 細部邏輯(Week 3b)

---

## 7. Week 3a:Dynamic Batching

### 範圍
**單獨做 BatchCollector**,因為涉及 thread 同步 + Future dispatch,風險高,獨立一個對話降低出錯範圍。

### 主要產出
- 新增 `media_processor/pipeline/batch_collector.py`,實作:
  - submit 介面回傳 Future
  - 後台 worker thread 收集 + 觸發 batch + 分發結果
  - `batch_size` / `timeout_ms` 從 config 讀取
- 修改 `TechScoreStage` / `AesScoreStage` / `WhisperStage` / `AudioEnvStage` 改為走 BatchCollector
- 不支援 batch 的 Stage(Saliency / VAD / Gemini)維持單張呼叫

### 驗收條件
- 同一組 10 張圖跑 batch 與非 batch,結果逐欄一致(數值容差 ±0.01)
- batch size=16 下,MUSIQ 總耗時從 200ms × 16 = 3.2s 降到 ~480ms
- 末尾 asset 不會卡 timeout(`timeout_ms` 後仍會觸發)
- Stage 內 `BatchCollector` 為 singleton,跨 asset 共享

### 風險與緩解
| 風險 | 緩解 |
|---|---|
| Future dispatch race condition | 用 `threading.Event` + `queue.Queue`,單元手動測試覆蓋「滿 batch」「超時」「異常」三條路徑 |
| Batch padding 反而拖慢小模型 | config 提供 `enable_batch` 開關,壓測決定每個模型是否啟用 |
| 末尾 asset 卡死 | `timeout_ms` 強制觸發;觸發時若 batch < 1 則跳過 |

### 不做
- 不改 Stage 介面(BatchCollector 對 driver thread 透明)
- 不做 Qwen batch(VLM padding 複雜,留未來)

---

## 8. Week 3b:雙 GPU Qwen Pool + GPU Capacity Manager

### 範圍
啟用 Qwen 雙 GPU 共享,並加入動態 VRAM 偵測。**這批與 Week 3a 可平行做**(不同對話),因為兩者無直接依賴。

### 主要產出
- 新增 `model/gpu_capacity_manager.py`:
  - 啟動時用 `torch.cuda.mem_get_info()` 掃 free VRAM
  - 依 `GPU_SAFETY_BUFFER_GB` 與每個模型的預估 VRAM 預算決定 Pool size
  - 提供 `get_pool_size(model_class)` 介面給 `ModelPoolRegistry`
- 修改 `ModelPoolRegistry`:Qwen / Whisper / Saliency 等熱門模型 eager warm up,VRAM 不夠的卡自動降級為 lazy
- 修改 `SemanticImageStage` / `SemanticVideoStage` 使用雙 GPU Qwen Pool
- 修改 `ModelPool.borrow()`:借出前再檢查 VRAM,不夠就 block + 推 Observer 事件
- CUDA OOM 容錯:Stage 內 try/except,釋放 model + `empty_cache()` + 放回隊列重試最多 N 次

### 驗收條件
- 在雙 GPU 環境下,Qwen 同時在兩張卡推論(觀察 `nvidia-smi`)
- 故意用其他 process 佔用 GPU 1 部分 VRAM,啟動後 Capacity Manager 自動把 Qwen 只放 GPU 0
- 雙卡下單張 Qwen 吞吐約 2x(實測 5 張圖總耗時減半)
- 故意觸發 OOM(把 batch size 拉到爆),確認重試機制生效

### 風險與緩解
| 風險 | 緩解 |
|---|---|
| 單卡環境下雙 GPU 設定出錯 | `detect_gpu_ids()` 偵測到單卡時自動把 Qwen Pool size 設 1 |
| VRAM 預算估算不準 | 預算進 config 可調,啟動時 log 印出每張卡的 free / 載入量供觀察 |
| OOM 重試陷入死循環 | 重試上限 N(預設 3),超過則該 asset 標記 error,不阻擋其他 |

---

## 9. Week 3c:Layer 4 WebSocket 接前端

### 範圍
**與 Week 3a/3b 平行可行**。把 Week 1 已定義的 `ProgressObserver` 介面實作 WebSocket Observer,新增 FastAPI 端點。

### 主要產出
- 新增 `backend/api/progress.py`:
  - `WebSocket /ws/progress/{job_id}` 端點
  - `WebSocketProgressObserver` 訂閱 ProgressTracker
- 修改 `backend/api/director.py:/generate`:啟動工作流前建立 ProgressTracker + 註冊 WebSocketObserver + 回 `job_id` 給前端
- 修改 `DirectorService.run_workflow` 接受可選 `tracker` 參數

### 驗收條件
- 用 `wscat -c ws://localhost:5174/ws/progress/{job_id}` 訂閱
- 觀察事件序列:每個 asset 應依序發出 `decode → ... → assembly` 的 start/finish 事件
- WebSocket 斷線時 Observer 失敗隔離,不阻斷 Scheduler

### 不做
- 不接前端 React 元件(Week 4b 才做)

---

## 10. Week 4a:Layer 0 雲端攝取

### 範圍
Google Drive workspace → project 自動偵測。**與 Week 4b 可平行**。

### 主要產出
- 新增 `ingestion_engine/` 模組樹:
  - `google_drive_adapter.py` — rclone backend 封裝
  - `workspace_manager.py` — 多 workspace 管理
  - `poller.py` — 定期 polling background task
  - `oauth_flow.py` — Google `drive.file` scope 流程
- 新增 `backend/api/workspaces.py`:
  - `POST /api/workspaces` — 新增 workspace(OAuth 或 URL)
  - `GET /api/workspaces` — 列出 user 所有 workspace
  - `POST /api/workspaces/{id}/sync` — 手動觸發同步
- DB schema 變更:新增 `workspaces` 與 `projects` 表(若尚未存在)
- 修改 `backend/main.py`:啟動時拉起 poller background task

### 驗收條件
- User 在 Drive 把資料夾分享給 app,後端 list 出該資料夾
- 對 workspace 上傳新資料夾 / 檔案,5 分鐘內後端偵測到並建 project + 觸發 Phase 1
- 雲端刪除 asset → 標記 stale 但本地 metadata 保留
- OAuth token 過期 → 該 workspace 暫停同步,其他 workspace 不受影響

### 外部依賴(實機驗證)
- Google Cloud Console 建 OAuth app,取得 client_id / client_secret
- 安裝 rclone 並完成 gdrive backend 設定
- 設定環境變數 `GOOGLE_OAUTH_CLIENT_ID` 等

---

## 11. Week 4b:Layer 5 前端 Asset Management UI

### 範圍
**與 Week 4a 可平行**。前端純 React 工作,依賴 4a 的 API 但可先 mock。

### 主要產出
- 新增 `frontend/src/pages/AssetListPage.tsx` 路由 `/projects/{project_id}/assets`
- 元件:
  - `AssetGrid` — 縮圖網格
  - `AssetCard` — 單張 asset 卡片(縮圖、狀態、策略 toggle)
  - `BulkActionBar` — 全選 / 批量設策略 / 重新分析按鈕
  - `ProgressOverlay` — WebSocket 進度顯示
- WebSocket client 連 `/ws/progress/{job_id}`,訂閱 Stage 事件
- 串接 Week 4a 的 API:
  - `GET /api/projects/{id}/assets`
  - `POST /api/projects/{id}/generate`(帶 `asset_strategies`)
  - `POST /api/projects/{id}/reanalyze`
  - `PATCH /api/projects/{id}/assets/{asset_id}/strategy`
- 縮圖 URL 從 `temp_templates/thumbnails/{project_id}/` 讀取(Week 4a 同步時順手產出)

### 驗收條件
- 瀏覽器開啟 `/projects/{id}/assets`,看到縮圖網格
- 勾選 asset → 設 Complex → 點「開始生成」→ WebSocket 推來的事件即時更新卡片狀態
- 「重新分析」按鈕觸發 Phase 1 重跑,卡片狀態由「成功」變回「處理中」
- 策略變更後該 asset 標記 dirty,下次生成自動重跑

### 外部依賴(實機驗證)
- 真實瀏覽器互動測試,sandbox 跑不了

---

## 12. 對話啟動範本

每個對話開新 Claude Code session,啟動時餵以下 context,讓 Claude 從乾淨 state 進入工作:

```
我要實作 docs/integrated_acceleration_plan.md 與 docs/implementation_roadmap.md
的 [Week X] 階段。

請先讀:
- docs/integrated_acceleration_plan.md (整體設計)
- docs/implementation_roadmap.md 第 [N] 章 (本週範圍)
- CLAUDE.md (程式規範)
- [Week X 主要接觸的程式檔案,例如 model/base_model_manager.py]

請依 roadmap 第 [N] 章的「主要產出」清單實作,實作完成後告訴我:
1. 新增/修改了哪些檔案
2. 是否達成「驗收條件」清單
3. 有無偏離 plan 的設計決策(需要與我討論)
4. 需要實機驗證的部分(我去執行)
```

**重點原則**:
- 每個對話只給該週需要的 doc 章節 + 程式檔案,不要丟整份 doc
- 啟動時明確說「請依驗收條件實作」,不要讓 Claude 自由發揮
- 鼓勵 Claude 主動發問,而不是默默猜測

---

## 13. 對話之間的交接

### 13.1 一個對話完成後

```
[人類動作]
1. Claude 回報完成 → 自己 review diff (用 git diff 或 git log -p)
2. 跑 roadmap 第 N 章的「驗收條件」清單,逐項通過
3. git commit -m "feat: implement Week X - <範圍>"
4. 在 commit message 註記「對應 implementation_roadmap.md 第 N 章」
5. 若有偏離 plan 的設計決策,更新 plan 或 roadmap 對應章節
```

### 13.2 開新對話前

```
[人類動作]
1. 確認上一週的 commit 已 push 或保留在本地
2. 跑該週驗收條件再確認一次(避免下週開始才發現上週沒完成)
3. 若上週有未解決的 follow-up issue,寫進新對話的啟動 prompt
```

### 13.3 對話中途斷線或卡住

- **不要強行延續**,寧可 abandon 該次 attempt,git restore 後重啟對話
- 重啟時把斷線前的關鍵決策 (例如「Saliency 改成 lazy」) 寫進啟動 prompt
- 累積斷線次數 > 2 次表示該週範圍切太大,考慮再拆

---

## 14. 外部依賴清單

以下動作 Claude Code 在 sandbox 跑不起來,**必須由人類在實機完成**:

| 依賴 | 用在 | 操作 |
|---|---|---|
| AWQ 模型下載 | Week 1 | `huggingface-cli download Qwen/Qwen3-VL-8B-Instruct-AWQ` |
| Flash Attention 安裝 | Week 1 | `pip install flash-attn --no-build-isolation` |
| 多 GPU 環境 | Week 3b | 實機驗證雙卡 Qwen 同時推論 |
| 故意佔 VRAM 測試 | Week 3b | 用 `torch` 佔住 GPU 1 部分 VRAM 測 Capacity Manager |
| Google Cloud Console | Week 4a | 建 OAuth app,取得 credentials |
| rclone 安裝 + gdrive 設定 | Week 4a | `rclone config` 互動式 setup |
| 真實瀏覽器測試 | Week 4b | 開瀏覽器點按互動 |
| OAuth 互動授權 | Week 4a | 跑 OAuth flow 在瀏覽器同意授權 |

每個 Week 啟動對話前先確認對應外部依賴已就緒,避免 Claude 寫到一半才發現環境缺東西。

---

## 15. 整體時程估算

### 15.1 樂觀(順利不返工)

| 階段 | 工期 |
|---|---|
| Week 1 | 2 天(含實機驗證 AWQ 品質) |
| Week 2a | 3 天 |
| Week 2b | 2 天 |
| Week 2c | 2 天 |
| Week 3a | 2 天(高風險,壓測) |
| Week 3b | 2 天(需多 GPU 實機) |
| Week 3c | 1 天 |
| Week 4a + 4b 平行 | 4 天(實機 OAuth + 前端互動測試) |
| **總計** | **約 18 天(3.5 週)** |

### 15.2 實際(預留 buffer)

考量 30% 返工 + 對話中斷重啟 + 外部依賴設定卡關:

| 階段 | 工期 |
|---|---|
| **預計總工期** | **約 4–5 週** |

### 15.3 重要里程碑

| 里程碑 | 達成時點 | 紅利 |
|---|---|---|
| Qwen 加速 3x | Week 1 結束 | 可立即上線,單張圖片從 15s 降到 5s |
| Pipeline 框架就緒 | Week 2a 結束 | 即使不拆 Stage,asset 間並行已生效,4 卡可拿 4x |
| Image 端到端壓榨完成 | Week 2b 結束 | 圖片加速接近最終值 |
| Video 端到端壓榨完成 | Week 2c 結束 | 影片加速接近最終值,**Phase 1 核心目標達成** |
| Dynamic Batching 上線 | Week 3a 結束 | 小模型紅利,但實際影響佔比小 |
| 多 GPU 適應完成 | Week 3b 結束 | 研究室共用 GPU 場景安全可靠 |
| WebSocket 就緒 | Week 3c 結束 | 前端可訂閱進度 |
| 雲端同步上線 | Week 4a 結束 | Phase 1 背景化體驗就緒 |
| 前端 UI 上線 | Week 4b 結束 | **完整產品可發布** |

---

*文件最後更新:2026-05-30*
