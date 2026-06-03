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
  - [3. Week 1:Layer 1 模型層獨立優化 ✅ 已完成(2026-05-30;2026-06-01 實機落地修正)](#3-week-1layer-1-模型層獨立優化--已完成2026-05-302026-06-01-實機落地修正)
    - [範圍](#範圍)
    - [主要產出(實際完成)](#主要產出實際完成)
    - [驗收條件達成狀態](#驗收條件達成狀態)
    - [外部依賴實況(在另一台機器要重現需注意)](#外部依賴實況在另一台機器要重現需注意)
    - [不做(維持原規劃)](#不做維持原規劃)
  - [4. Week 2a:Pipeline 骨架 + LegacyStage 包裝 ✅ 已完成(2026-06-02)](#4-week-2apipeline-骨架--legacystage-包裝--已完成2026-06-02)
    - [範圍](#範圍-1)
    - [主要產出](#主要產出)
    - [驗收條件](#驗收條件)
    - [風險與緩解](#風險與緩解)
    - [不做](#不做)
  - [5. Week 2b:Stage 拆解(image) ✅ 已完成(2026-06-02)](#5-week-2bstage-拆解image--已完成2026-06-02)
    - [範圍](#範圍-2)
    - [主要產出](#主要產出-1)
    - [驗收條件](#驗收條件-1)
    - [不做](#不做-1)
  - [6. Week 2c:Stage 拆解(video)+ DAG 依賴圖編排 ✅ 已完成(2026-06-02)](#6-week-2cstage-拆解video-dag-依賴圖編排--已完成2026-06-02)
    - [範圍](#範圍-3)
    - [設計決策(偏離原 plan,以本區為準)](#設計決策偏離原-plan以本區為準)
    - [主要產出](#主要產出-2)
    - [依賴圖(取代原 G0–G5;`PipelineBuilder._build_simple_video_pipeline` / `_build_complex_video_pipeline`)](#依賴圖取代原-g0g5pipelinebuilder_build_simple_video_pipeline--_build_complex_video_pipeline)
    - [驗收條件](#驗收條件-2)
    - [不做](#不做-2)
  - [7. Week 3a:Dynamic Batching + 音訊 Stage 全拆 ✅ 已完成(2026-06-02)](#7-week-3adynamic-batching--音訊-stage-全拆--已完成2026-06-02)
    - [範圍](#範圍-4)
    - [主要產出(實際完成)](#主要產出實際完成-1)
    - [有效批量說明(重要)](#有效批量說明重要)
    - [驗收條件](#驗收條件-3)
    - [風險與緩解](#風險與緩解-1)
    - [不做](#不做-3)
  - [8. Week 3b:雙 GPU Qwen Pool + GPU Capacity Manager](#8-week-3b雙-gpu-qwen-pool--gpu-capacity-manager)
    - [範圍](#範圍-5)
    - [主要產出](#主要產出-3)
    - [驗收條件](#驗收條件-4)
    - [風險與緩解](#風險與緩解-2)
  - [9. Week 3c:Layer 4 WebSocket 接前端](#9-week-3clayer-4-websocket-接前端)
    - [範圍](#範圍-6)
    - [主要產出](#主要產出-4)
    - [驗收條件](#驗收條件-5)
    - [不做](#不做-4)
  - [10. Week 4a:Layer 0 雲端攝取](#10-week-4alayer-0-雲端攝取)
    - [範圍](#範圍-7)
    - [主要產出](#主要產出-5)
    - [驗收條件](#驗收條件-6)
    - [外部依賴(實機驗證)](#外部依賴實機驗證)
  - [11. Week 4b:Layer 5 前端 Asset Management UI](#11-week-4blayer-5-前端-asset-management-ui)
    - [範圍](#範圍-8)
    - [主要產出](#主要產出-6)
    - [驗收條件](#驗收條件-7)
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
| 外部依賴擋路 | 模型下載(Qwen base 等)、Google Drive OAuth、WebSocket 端對端、多 GPU 行為都不能在 sandbox 跑 |
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
Week 1   ─ Layer 1 全部 + ProgressTracker 介面          ~400 行   ✅ 已完成
   ↓
Week 2a  ─ Pipeline 骨架 + LegacyStage 包既有 process    ~600 行   ✅ 已完成(框架就緒)
   ↓
Week 2b  ─ Stage 拆解(image)                          ~300 行   ✅ 已完成
   ↓
Week 2c  ─ Stage 拆解(video)+ DAG 依賴圖編排          ~400 行   ✅ 已完成
   ↓
Week 3a  ─ Dynamic Batching + 音訊 Stage 全拆          ~500 行   ✅ 已完成
   ↓
Week 3b  ─ 雙 GPU Qwen Pool + GPU Capacity Manager       ~700 行   ✅ 已完成
   ↓
Week 3c  ─ Layer 4 WebSocket 接前端                      ~200 行
   ↓
Week 4a  ─ Layer 0(Google Drive + 同步 + Workspace)    ~500 行 ─┐
                                                                  ├─ 可平行
Week 4b  ─ Layer 5(前端 Asset Management UI)            ~600 行 ─┘
```

| 對話 | 範圍 | 約略行數 | 平行可行 | 驗收型態 |
|---|---|---|---|---|
| Week 1 ✅ | Layer 1 模型優化 + Tracker 介面 | 400 | 否 | 實機 GPU 測試 |
| Week 2a ✅ | Pipeline 骨架 + LegacyStage | 600 | 否(Week 1 之後) | 端到端輸出比對 |
| Week 2b ✅ | Image Stage 拆解 | 300 | 否(Week 2a 之後) | 輸出與 2a 一致 |
| Week 2c ✅ | Video Stage 拆解 + DAG 編排 | 400 | 否(Week 2b 之後) | 輸出與 2b 一致 + 效能提升 |
| Week 3a ✅ | Dynamic Batching + 音訊 Stage 全拆 | 500 | 否(Week 2c 之後) | 壓測 + 結果一致 |
| Week 3b ✅ | 雙 GPU + Capacity Manager(全模型接 pool）| 700 | 與 3a 可平行 | 多 GPU 實機測試 |
| Week 3c | WebSocket 進度推播 | 200 | 與 3a/3b 可平行 | wscat 訂閱驗證 |
| Week 4a | Google Drive Ingestion | 500 | 與 4b 可平行 | 雲端 + OAuth 實機 |
| Week 4b | 前端 Asset Management UI | 600 | 與 4a 可平行 | 瀏覽器互動驗證 |

---

## 3. Week 1:Layer 1 模型層獨立優化 ✅ 已完成(2026-05-30;2026-06-01 實機落地修正)

> **狀態:已完成並實機驗證**。程式碼在 commit `51ef717`(主體)+ `43a8d10`(device 鎖定修正)。
> Lock 機制完整設計另見 `docs/lock_design.md`。
>
> **⚠️ 2026-06-01 實機落地修正(真正跑 Phase 1 後發現的偏差,以本區為準,覆寫下方舊敘述)**:
> 1. **量化改 bitsandbytes 4-bit NF4**:原 cyankiwi compressed-tensors AWQ 在 **transformers 推理時會整包解壓成 bf16、runtime 不省 VRAM**(實測載入 7.5GB → 推理 **18GB**;真正的 4-bit kernel 只在 vLLM)。改用 bnb 4-bit 量化官方 base 後實測 **6.4GB**,VRAM 砍半才真正達成。旗標 `QWEN_USE_AWQ` → 改名 **`QWEN_USE_4BIT`**。
> 2. **torchaudio 須 2.10.0、torchcodec 須 0.10.0**:當初 torch 降 2.10 時這兩個漏降(留 2.11/0.11),造成 `.so` ABI 不相容、影片音訊鏈全掛。
> 3. **MediaPipe 改用 Tasks API `FaceDetector`**:mediapipe 0.10.22+ 官方 linux wheel 缺 `python/` 子套件、`mp.solutions` 不存在;pin **0.10.30**、走 Tasks(`.tflite` 首次自動下載)。
> 4. **Qwen 影片改走 `apply_chat_template(tokenize=True)`**:Qwen3-VL 需 video_metadata 算時間戳,舊的 `process_vision_info` 會 fallback 成 fps=24、token 暴增 OOM。
> 5. **AudioEnv 修 `inference()` 回傳順序**(embedding 被當分數而索引越界)、模型實為 PANNs **CNN14**(非 CNN6)。

### 範圍
純模型層改動,**完全不動現有 pipeline 架構**,只把模型本身換掉與加 GPU Gate。

### 主要產出(實際完成)
- ✅ Qwen 量化 + Flash Attention 2(失敗 fallback sdpa)。**量化最終採 bitsandbytes 4-bit NF4**(量化官方 base `Qwen/Qwen3-VL-8B-Instruct`)— 見上方落地修正第 1 點;原 cyankiwi AWQ 因 transformers 解壓不省 VRAM 已棄用
  - env var **`QWEN_USE_4BIT`**(預設 true)可一行切 bnb 8-bit 供品質回歸
  - **Processor 從官方 base 載入**(tokenizer + 影像/影片前處理)
  - device_map 改 `{"": self.device}` **鎖定指定 GPU**(原 `"auto"` 在共用 GPU 會亂抓滿的卡,也破壞 Week 3b 多卡 Pool)
- ✅ `BaseModelManager` 加 **`GpuGate`(Strategy Pattern)層**,取代原規劃的裸 `GPU_SEMAPHORES`:
  - Week 1 預設 `BinaryGate`(= Semaphore(1));Week 3b 由 Capacity Manager 用 `register_gate_factory()` 一行換成 `BudgetGate`
  - 鎖序「L2 GpuGate → L3 model lock」,CPU/API 模型依 `self.device` 自動跳過 L2
  - Singleton key 從 `device_id` 改 **`(device_id, slot_id)` tuple**(為 Week 3b 同卡多 instance 鋪路,既有 caller 100% 相容)
- ✅ `ModelPool` 新增 **`slots`(`GpuSlot`)介面**,保留 `gpu_ids` 為 backward-compat alias
- ✅ 新增 `MUSIQ.score_batch()` / `LAION.score_batch()` / `Whisper.transcribe_batch()`(保留舊單張介面,尚未接入)
- ✅ 新增 `media_processor/pipeline/progress.py`:`ProgressObserver` / `ProgressTracker` / `ProgressEvent`(pydantic)+ `PrintProgressObserver`(無 WebSocket)
- ✅ `media_processor_config.py` 加入 batch size、`BATCH_COLLECT_TIMEOUT_MS`、`GPU_SAFETY_BUFFER_GB`、`QWEN_USE_4BIT_DEFAULT` 常數
- ✅ 新增 `model/gpu_gate.py`(`GpuGate` ABC + `BinaryGate`)

### 驗收條件達成狀態
- ✅ **FA2 實機生效**:`model.config._attn_implementation == "flash_attention_2"`,dtype `bfloat16`,單卡載入成功
- ✅ **Qwen VRAM 砍半**:bnb 4-bit 實測載入/推理皆 **6.40GB**、峰值 6.64GB(對比 compressed-tensors AWQ 解壓後的 17.98GB)
- ✅ **Phase 1 端到端可跑**:torchaudio/torchcodec/mediapipe/fps/AudioEnv 一連串實機問題修正後,圖片與影片都能正常產出分析(見落地修正)
- ⬜ 品質回歸 A/B(bnb 4-bit vs 8-bit 結構欄位一致)— 待跑
- ⬜ 50 asset 同卡 Qwen+Whisper 不 OOM — 待跑(共用 GPU 被別人佔滿時仍會 OOM,屬 Week 3b Capacity Manager 範圍)
- ⬜ 單張 Qwen 計時 — 待跑

### 外部依賴實況(在另一台機器要重現需注意)
- **torch 2.10 全家鎖定**:torch 2.10 / torchvision 0.25 / **torchaudio 2.10 / torchcodec 0.10**(後兩者當初漏降成 2.11/0.11,造成 `.so` ABI 不相容,務必對齊);torch 定在 2.10 是因 flash-attn 預編譯 wheel 天花板就是 torch2.10
- flash-attn 用預編譯 wheel `v2.8.1+cu12torch2.10cxx11abiTRUE-cp312`(torch2.11 無 wheel,只能源碼編譯)
- **量化改 bitsandbytes**(原 compressed-tensors AWQ 在 transformers 解壓不省 VRAM 已棄用);`compressed-tensors` / `autoawq` 已非必要
- **mediapipe pin 0.10.30 + 走 Tasks API**(0.10.22+ wheel 缺 `python/`、`mp.solutions` 不存在)
- **執行環境在遠端 Leibniz/Turing 的共用 GPU**,常被別人佔滿 VRAM 而 OOM,與程式無關

### 不做(維持原規劃)
- 不動 `director_service.py` 序列迴圈,既有流程照跑
- 不啟用 batch scoring 的呼叫(只新增方法,Week 3a 才接 BatchCollector)
- 不接 WebSocket(Week 3c)
- 同卡多 instance 紅利 Week 1 看不到(BinaryGate 仍序列化,需 Week 3b BudgetGate)

---

## 4. Week 2a:Pipeline 骨架 + LegacyStage 包裝 ✅ 已完成(2026-06-02)

> **狀態:框架就緒、`director_service` 已切換為 `PipelineRunner.run(...)`**(commit `03b98bb`)。
> Pipeline / ExecutorRegistry / ModelPoolRegistry / HybridScheduler / Builder / Runner 全數落地,
> 圖片與影片皆以單一 LegacyStage 包整段 `process()`,輸出與 Week 1 序列版一致,Week 2b 起在此框架上拆 Stage。
>
> **⚠️ 編排原語變更**:2a 當時以 `StageGroup`(群組間 barrier)表達編排;**Week 2c 已改用 `StageNode`
> 依賴圖(DAG)取代,`stage_group.py` 已移除**(理由見第 6 章)。下方「主要產出」保留當時 StageGroup 字樣
> 作為歷史紀錄,實際現況以第 6 章為準。

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

## 5. Week 2b:Stage 拆解(image) ✅ 已完成(2026-06-02)

> **狀態:程式完成、本機結構/邏輯驗證通過;端到端實機 A/B 待跑。**
> - ✅ 11 新檔(`image_work.py` + 10 image Stage)+ builder image 編排 + `USE_LEGACY_IMAGE_PIPELINE` 旗標
> - ✅ 本機驗證:`py_compile` 全通過;builder 產出正確編排(semantic 與 saliency/aes/cv/face/exif 同層平行、
>   reject 後才解依賴);COMPLEX→Gemini / SIMPLE→Qwen、Legacy 回退、assembly 組裝 / reject 邏輯與原版逐欄一致
>   (bbox 覆蓋、crop_feasibility、round、reject reason 字串、metadata 欄位集合)
> - ⚠️ **編排與資料容器在 Week 2c 一併升級**:原以 StageGroup(G0–G5)表達,Week 2c 改成 `StageNode` 依賴圖
>   (DAG);per-frame 分析抽出共用的 `FrameAnalysis`(`image_work.py` 改持有 `frame: FrameAnalysis`),
>   讓 TechScore / AesScore / CVFeatures / FaceDetect / RejectFilter 與 video 共用。下方產出已反映現況。
> - ⬜ 待實機(Leibniz,需真實模型 / cv2 / 圖片):端到端逐欄一致 A/B、單張計時、Early Rejection 事件流、corrupt 圖韌性

### 範圍
把 `LegacyImagePipelineStage` 內部展開成 10 個獨立 Stage,設計 image pipeline 的依賴圖編排。

### 主要產出
- `media_processor/pipeline/stages/` 內新增:
  - `image_work.py`(`@dataclass ImageWork` 中間狀態容器 + `IMAGE_WORK_KEY`;取代裸 scratch dict;
    Week 2c 起改持有共用的 `frame: FrameAnalysis`)
  - `decode_image_stage.py`
  - `tech_score_stage.py`
  - `reject_filter_stage.py`
  - `saliency_stage.py`
  - `aes_score_stage.py`
  - `cv_features_stage.py`
  - `face_detect_stage.py`
  - `exif_stage.py`
  - `semantic_image_stage.py`(內部依 strategy 呼叫 Qwen 或 Gemini)
  - `assembly_image_stage.py`
- `config/pipeline_config.py` 加 `USE_LEGACY_IMAGE_PIPELINE`(預設 false=新拆;true=回退 Legacy 供 A/B 逐欄比對)
- `PipelineBuilder._build_image_pipeline()` 定義依賴圖(**Week 2c 由 StageGroup 改寫為 `StageNode` DAG**):
  `decode → tech → reject → {semantic, saliency, aes, cv, face, exif} → assembly`
  - reject 之後的六個 Stage 各只依賴 reject、彼此無依賴 → 同時可執行(取代原 G3 大平行 + G4 獨立 semantic)
  - **編排決策**:圖片 semantic 只依賴解碼後的圖,與其他並行 Stage 無依賴,故併入同一波次,不再排在 CPU stage 之後
    (避免 qwen 空等 cv/face/exif);assembly 是唯一 join(等齊六個 Stage),含 subject_bbox 解析 + crop_feasibility
  - reject 觸發時,後續六個 Stage 與 assembly 因依賴未解除而全被短路跳過
- `LegacyImagePipelineStage` 保留作為 fallback 與 regression 比對

### 驗收條件
- ⬜（實機）同一組圖片用 `USE_LEGACY_IMAGE_PIPELINE=true`(Legacy)與 `false`(新拆)各跑一次,輸出逐欄一致
  — 本機已證 assembly / reject 邏輯與原版逐欄一致,端到端 A/B 待 Leibniz
- ⬜（實機）單張圖片耗時應略降(平行群並行 + qwen 不被 CPU stage barrier 卡)
- ⬜（實機）Early Rejection 觸發時,後續 Saliency / AesScore / SemanticImage / CVFeatures / FaceDetect / Exif 確實未呼叫
  — Pipeline 既有短路(reject 設終止狀態後依賴它的 Stage 全跳過)已保證,用 ProgressTracker 事件確認
- ✅（本機已證)Legacy 與新拆切換、依賴圖結構、bbox/crop/round/reason 等值組裝

### 不做
- 不拆 video Stage(Week 2c)
- 不做 image 的 batch scoring(Week 3a 才接 Dynamic Batching)
- 不做 StageGroup priority(改 DAG 後無此概念;同卡 GPU 併發插空屬 Week 3b BudgetGate)

---

## 6. Week 2c:Stage 拆解(video)+ DAG 依賴圖編排 ✅ 已完成(2026-06-02)

> **狀態:程式完成、本機結構/邏輯驗證通過;端到端實機 A/B 與效能量測待跑。**
> - ✅ 14 新檔(10 video Stage + `frame_analysis.py` / `video_work.py` / `video_frame_utils.py` / `node.py`)
>   + builder Simple/Complex 兩條依賴圖 + `USE_LEGACY_VIDEO_PIPELINE` 旗標;`stage_group.py` 移除
> - ✅ 本機驗證:`py_compile` 全通過;Pipeline 建構期驗證依賴圖合法(名稱唯一 / 依賴存在 / 無環);
>   Simple / Complex DAG 結構與 resource type 正確;Legacy 回退單節點;assembly 逐欄對齊原
>   `VideoProcessor` / `ComplexVideoProcessor`(含 **Complex 無 faces 欄位**)
> - ⚠️ **三項偏離原 plan(見下方「設計決策」)**:StageGroup→StageNode DAG;不另建 video 專屬
>   visual_scoring / cv_features / middle_frame Stage(改抽 `FrameAnalysis` 共用);Simple 也走早 reject
> - ⬜ 待實機(Leibniz,需真實模型 / cv2 / ffmpeg / 影片):端到端逐欄一致 A/B、Simple/Complex 計時、Early Rejection 事件流

### 範圍
把 `LegacyVideoPipelineStage` 內部展開成細粒度 Stage,並把 image / video 的編排一起從 StageGroup(群組 barrier)
升級為 **`StageNode` 依賴圖(DAG)**,讓每個 Stage 只等自己宣告的真實上游依賴,彼此無依賴者真正並行。

### 設計決策(偏離原 plan,以本區為準)
1. **StageGroup → `StageNode` 依賴圖(DAG)**:原規劃用 StageGroup G0–G5(群組間 barrier),但「等整個前群組」過度約束
   —— 例:Complex 的 `SemanticVideo`(Gemini)只需要 `Timecode` 的產物,卻被迫等同群的音訊 / 視覺特徵。改成每個
   `StageNode` 宣告依賴的上游 Stage 名稱,由 `Pipeline` 以拓樸波次排程。`media_processor/pipeline/stage_group.py`
   **已刪除**,新增 `node.py`;`pipeline.py` 改依賴圖排程(單一可執行且無併發時 inline 跑、多個則分派各資源池並行)。
   image pipeline(Week 2b)亦一併改寫為 DAG。
2. **不另建 video 專屬的 visual_scoring / cv_features / middle_frame Stage**:原規劃列了
   `visual_scoring_video_stage.py` / `cv_features_video_stage.py` / `middle_frame_stage.py`;實作改抽共用的
   `FrameAnalysis`(一張 PIL 幀的 tech/aes/色彩/臉分析),讓 image 既有的 `TechScore` / `AesScore` / `CVFeatures` /
   `FaceDetect` / `RejectFilter` 五個 Stage 直接 media-agnostic 共用(透過 `get_frame_analysis` 分派 image/video)。
   代表幀(middle frame)併入 `DecodeVideoStage` 一次 cv2 session 取出。少 3 個檔、邏輯不重複。
3. **Simple 影片也走「早 reject」**:鏡像圖片 `decode → tech → reject`,reject 觸發時連 Whisper / Qwen 都省;
   原規劃 G1/G2 無明確 reject gate。

### 主要產出
- `media_processor/pipeline/stages/` 內新增(影片專屬 Stage):
  - `decode_video_stage.py`(影片 metadata + 中間代表幀,一次 cv2 session;DAG 起點,建立 `VideoWork`)
  - `timecode_stage.py`(Complex only:燒視覺時間碼供 Gemini 索引,IO)
  - `audio_extraction_stage.py`(ffmpeg 抽單聲道 wav,IO)
  - `audio_inference_stage.py`(VAD → 有語音才 Whisper → 環境音 PANNs CNN14,GPU)
  - `scene_cut_stage.py`(PySceneDetect 場景切點,CPU;失敗降級回空列表)
  - `motion_intensity_stage.py`(Simple only,CPU)
  - `saliency_union_stage.py`(Simple only:頭/中/尾三幀 bbox 聯集,GPU)
  - `semantic_video_stage.py`(Strategy:SIMPLE→Qwen `GLOBAL_ANALYSIS`(GPU)/ COMPLEX→Gemini `TIMECODED_ACTION_INDEX`(API))
  - `event_bbox_stage.py`(Complex only:逐 Gemini 事件於高潮秒數算精準 bbox,GPU)
  - `assembly_video_stage.py`(SIMPLE→`VideoMetadata` / COMPLEX→`ComplexVideoMetadata`;唯一 join)
- 共用輔助 / 中間容器(image / video 共享):
  - `frame_analysis.py`(`FrameAnalysis` per-frame 分析容器 + `get_frame_analysis` 依 media_kind 分派)
  - `video_work.py`(`VideoWork` 影片中間狀態 Blackboard + `get_video_work`)
  - `video_frame_utils.py`(cv2 取幀 / metadata / saliency-at-time 共用工具,引擎以依賴注入傳入)
- `media_processor/pipeline/node.py` 新增(`StageNode`:Stage + 依賴上游名稱 tuple,frozen 可跨 asset 共享)
- `pipeline.py` 改為依賴圖拓樸排程;`context.py` 加 `temp_paths`(集中暫存檔清理,success/reject/error 三路徑都清)
- `config/pipeline_config.py` 加 `USE_LEGACY_VIDEO_PIPELINE`(預設 false=新拆 DAG;true=回退單一 LegacyStage 供 A/B)
- 共用 per-frame Stage 改 media-agnostic:`TechScore` / `AesScore` / `CVFeatures` / `FaceDetect` / `RejectFilter`
  透過 `get_frame_analysis` 取幀,image / video 共用(不重寫 video 版)
- `LegacyVideoPipelineStage` 保留作為 fallback 與 regression 比對

### 依賴圖(取代原 G0–G5;`PipelineBuilder._build_simple_video_pipeline` / `_build_complex_video_pipeline`)
- **Simple**:`decode → tech → reject → {semantic(Qwen), audio_infer, scene, motion, saliency_union, aes, cv, face} → assembly`
  - `audio_extract` 只依賴 `decode`(便宜 IO,與 tech 重疊、不被 reject gate);`audio_infer` 依賴 `audio_extract` + `reject`
  - reject 觸發時 reject 之後的工作全被短路(連 Whisper / Qwen 都省)
- **Complex**:`decode → {audio_extract→audio_infer, timecode→semantic(Gemini)→event_bbox, scene, cv, face} → assembly`
  - `timecode`(最耗時的燒碼)只被 `semantic` 依賴,故與音訊鏈 / 場景 / 視覺特徵自然並行重疊;
    `semantic`(Gemini)不再被同群的 audio/cv/face 卡住(修正 StageGroup 時代的過度約束)
  - `event_bbox` 依賴 `semantic`(需事件清單);assembly 等齊 audio_infer / scene / cv / face / event_bbox

### 驗收條件
- ✅（本機已證)`py_compile` 全通過;Pipeline 建構期依賴圖驗證(唯一 / 存在 / 無環);Simple/Complex DAG 結構與
  resource type 正確;`USE_LEGACY_VIDEO_PIPELINE` 回退單節點;assembly 逐欄對齊原版(含 Complex 無 faces)
- ⬜（實機）同一組影片(含 1 個 Complex)用 `USE_LEGACY_VIDEO_PIPELINE=true`(Legacy)與 `false`(DAG)各跑一次,
  `phase1_assets_metadata.json` 逐欄一致
- ⬜（實機）**Simple 影片從 45s 壓到 ~27s**(reject 後平行群重疊生效)
- ⬜（實機）**Complex 影片從 110s 壓到 ~84s**(timecode 與音訊 / 場景 / 視覺特徵並行)
- ⬜（實機）DAG 內同時執行的 Stage 寫入 `VideoWork` 不同 attribute,無衝突(GIL 下單一賦值原子)
- ⬜（實機）Early Rejection:reject 觸發時後續 semantic / audio_infer / saliency_union 等確實未呼叫(ProgressTracker 事件)

### 不做
- 不做 BatchCollector(Week 3a)
- 不做 Capacity Manager 細部邏輯(Week 3b)

---

## 7. Week 3a:Dynamic Batching + 音訊 Stage 全拆 ✅ 已完成(2026-06-02)

> **狀態:程式完成、本機結構/邏輯驗證通過;端到端實機 A/B 與效能量測待跑。**
>
> **⚠️ 三項偏離原 plan 的設計決策(皆已與使用者確認,以本區為準)**:
> 1. **`AudioInferenceStage` 全拆** —— 原 VAD→Whisper→AudioEnv 合併在單一 Stage,Week 3a 拆成
>    `VadStage → WhisperStage(語音鏈)` + 獨立 `AudioEnvStage`(只依賴 audio_extract,修正 AudioEnv
>    被迫排在 Whisper 後的過度序列化)。影片 DAG 重開,**需重跑影片逐欄一致 A/B**。
> 2. **MUSIQ batch 前處理改 padding** —— Week 1 的 `score_batch` 用「center-crop 成正方形」
>    (破壞逐欄一致);Week 3a 改為「每張走與單張完全相同的 `_preprocess_single` 保比例縮放 +
>    對批內最大 H/W zero-padding」，內容區與單張逐像素一致,drift 僅來自 padding 區。
>    `MUSIQ_BATCH_ENABLED` 預設 True,實機 drift > ±0.01 時可設 false 回退。
> 3. **`MAX_ASSETS_PARALLEL` 動態化** —— `HybridScheduler.run()` 改用 `min(asset 數, 上限)`,
>    小批 batch 填得滿、大批受上限保護 RAM。預設上修為 8(env 可調到 16 逼近 batch_size)。

### 範圍
**單獨做 BatchCollector** + **音訊 Stage 全拆**,因為涉及 thread 同步 + Future dispatch,風險高,獨立一個對話降低出錯範圍。
影片 DAG 因音訊拆解而重開,與 Week 2c 的重開規模相近,需重跑影片 A/B。

### 主要產出(實際完成)

**新增 4 檔**
- `media_processor/pipeline/batch_collector.py` — `BatchSpec`(Value Object)+ `BatchCollector`
  (Producer–Consumer + Future;daemon worker;**滿批/timeout/例外傳遞/長度不符全批 set_exception 四路徑**)
  + `BatchCollectorRegistry`(Registry + Singleton,class-level + 雙重檢查鎖,對齊 `BaseModelManager._GPU_GATES`,
  跨 asset 共享同一個 collector)
- `media_processor/pipeline/stages/vad_stage.py` — `VadStage`(GPU,單張,VAD 不支援 batch)
- `media_processor/pipeline/stages/whisper_stage.py` — `WhisperStage`(GPU;依賴 VadStage;啟用時走 BatchCollector)
- `media_processor/pipeline/stages/audio_env_stage.py` — `AudioEnvStage`(GPU;**只依賴 audio_extract**,
  與語音鏈並行;啟用時走 BatchCollector)

**移除 1 檔**
- `media_processor/pipeline/stages/audio_inference_stage.py`(由上述三個取代;影片整段 rollback 仍由
  `USE_LEGACY_VIDEO_PIPELINE` 覆蓋)

**修改**
- `model/musiq_model_manager.py` — `score_batch` 重寫(移除 center-crop,改 padding)
- `model/audio_env_model_manager.py` — 新增 `classify_environment_batch`(Week 1 未備)+ 抽共用 `_topk_labels`
- `media_processor/pipeline/stages/tech_score_stage.py` / `aes_score_stage.py` — 接 BatchCollectorRegistry
- `media_processor/pipeline/stages/video_work.py` — 加 `audio_file_ready` 共用守門
- `media_processor/pipeline/builder.py` — Simple/Complex 影片 DAG 以 vad/whisper/audio_env 取代 audio_infer
- `media_processor/pipeline/scheduler/hybrid_scheduler.py` — 並行度改 `min(asset 數, 上限)`
- `media_processor/pipeline/runner.py` — `shutdown` 接 `BatchCollectorRegistry.shutdown_all()`
- `config/media_processor_config.py` — 加 `AUDIO_ENV_BATCH_SIZE = 4`
- `config/pipeline_config.py` — 加 `MUSIQ_BATCH_ENABLED` / `LAION_BATCH_ENABLED` / `WHISPER_BATCH_ENABLED`
  / `AUDIO_ENV_BATCH_ENABLED`(env-overridable,預設皆 True);`MAX_ASSETS_PARALLEL` 預設 4 → **8**

**影片 DAG(取代原 audio_infer 節點)**
- **Simple**:`audio_extract → vad(+reject) → whisper;audio_env(audio_extract+reject,並行)→ assembly`
- **Complex**:`audio_extract → vad → whisper;audio_env(audio_extract,並行)→ assembly`
- reject 觸發時:vad 被短路 → whisper 連帶短路;audio_env 同樣被短路(皆依賴 reject_filter)

### 有效批量說明(重要)
`batch_size` 是**上限**,非常態。合批有效批量由上游併發決定(timeout 驅動):
- 圖片 `tech`(MUSIQ)inline 在 driver thread 跑 → 有效批量 ≤ `MAX_ASSETS_PARALLEL`
- GPU-pool 類 stage(`aes`/`whisper`/`audio_env`)→ 有效批量 ≤ GPU pool size

驗收「batch=16 → 480ms」屬壓測情境,須 `MAX_ASSETS_PARALLEL=16`(env 調高)才填滿批次,
預設 8 時實際批量約 4–8。

### 驗收條件
- ✅ **本機已證**:全 15 檔 `py_compile` 通過;BatchCollector 滿批/timeout/例外/長度不符四路徑通過;
  `BatchCollectorRegistry` 同 key 回同一實例;Simple(15 節點)/Complex(12 節點)/Image DAG 建構期驗證通過
- ⬜（實機）同一組 10 圖,各 `*_BATCH_ENABLED` on/off 各跑一次 diff metadata:
  LAION 應完全一致;MUSIQ `technical_score` drift ≤ ±0.01(超標則 `MUSIQ_BATCH_ENABLED=false`)
- ⬜（實機）**影片逐欄一致 A/B**(`USE_LEGACY_VIDEO_PIPELINE` true/false):
  `has_speech` / `audio_transcript` / `spoken_language` / `environmental_sounds` 欄位一致
- ⬜（實機）末尾 asset 不卡 timeout(`timeout_ms=50ms` 後仍觸發)
- ⬜（實機）batch size=16(壓測)下 MUSIQ 總耗時從 200ms×16=3.2s 降到 ~480ms
- ✅ Stage 內 `BatchCollector` 為 singleton,跨 asset 共享(由 `BatchCollectorRegistry` 保證)

### 風險與緩解
| 風險 | 緩解 |
|---|---|
| Future dispatch race / driver 永久卡死 | `queue.Queue` + Future;強制檢查 `len(results)==len(batch)`,不符全批 set_exception |
| batch forward 比單張吃更多 VRAM | 單次 forward VRAM 由 batch_size 封頂;4 個 enable 旗標可逐模型關 |
| MUSIQ padding 仍與單張有 drift | 內容區前處理與單張逐像素相同,drift 僅來自 padding;超標則 `MUSIQ_BATCH_ENABLED=false` |
| 影片 DAG 重開造成 regression | `USE_LEGACY_VIDEO_PIPELINE=true` 整段回退;assembly 欄位集合不變 |

### 不做
- 不改 Stage 介面(BatchCollector 對 driver thread 透明)
- 不做 Qwen batch(VLM 變長輸入 padding 複雜,留未來)

---

## 8. Week 3b:雙 GPU Qwen Pool + GPU Capacity Manager ✅ 已完成(2026-06-03)

> **狀態:程式完成、本機結構/邏輯驗證通過;多 GPU / OOM 實機驗收待跑。**
> - ✅ 1 新檔(`model/gpu_capacity_manager.py`)+ 修改 13 檔(gate / 5 個 GPU manager / model_pool /
>   model_pool_registry / 2 semantic stage / 4 batch_fn / runner / scheduler / context / progress / 2 config)
> - ✅ 本機驗證(注入假 mem_scan / 假 manager,不需真 GPU):BudgetGate 預算併發 + 反餓死 + over-budget 單獨跑;
>   capacity 雙卡規劃 Qwen 2 槽、GPU1 佔滿時只放 GPU0;`apply()` 換 per-device BudgetGate 各帶正確預算;
>   `inference_guard` 正確帶 cost+priority;同卡兩 instance 共用一個 BudgetGate(L2 跨 instance)且 Qwen 反餓死;
>   `oom_resilient` 重試 N 次後 re-raise;`ModelPool.borrow` VRAM 重檢 wait/ready/逾時放行;三條 DAG 仍正常建構
> - ⚠️ **四項偏離原 plan(已與使用者確認,以本區為準)**(見下方「設計決策」)
> - ⬜ 待實機(多 GPU 機器):雙卡 Qwen 同時推論、佔 GPU1 自動退場、吞吐 2x、故意 OOM 重試

### 範圍
啟用 **所有 GPU 模型的多卡 ModelPool 共享**(Qwen 多卡 + whisper/aes/musiq/audio_env),
並加入動態 VRAM 偵測(`GpuCapacityManager` + `BudgetGate`)、eager warm up、OOM 容錯。
**這批與 Week 3a 可平行做**,兩者無直接依賴。

### 設計決策(偏離原 plan,以本區為準)
1. **所有 GPU 模型都接 pool(非只 Qwen)+ Qwen 兩層優先**:使用者要求全模型多卡,但資源優先給主瓶頸 Qwen。
   解法 (a) **placement priority**:`GpuCapacityManager` 依優先序 + check-before-load,Qwen 第一且鋪滿可放下的每張卡,
   其餘小模型用剩餘 VRAM 挑最寬鬆卡放單份;(b) **runtime admission priority**:`BudgetGate.acquire(cost, priority)`
   新增 `priority`,「有高優先(Qwen)在等時低優先讓路」,避免 MUSIQ/LAION 串流把 Qwen 大塊請求餓死。
2. **gate factory 簽名改帶 `device_id`**(`Callable[[], GpuGate]` → `Callable[[int], GpuGate]`):per-card 異質預算需要
   (每張卡 free 不同 → 不同 BudgetGate 預算)。`BinaryGate` 忽略 device_id,既有行為不變。
3. **OOM 容錯做成 `@oom_resilient` 裝飾器(套 `@synchronized_inference` 外層)+ GPU manager 不再吞 OOM**:
   原 plan 寫「Stage 內 try/except + 放回隊列」,但既有 manager 的 broad except 會把 OOM 吞成 null object、
   retry 看不到;改為 manager 遇 OOM `raise`、外層裝飾器在鎖外 `empty_cache`+backoff 重試 ≤ N,
   耗盡後 re-raise → Pipeline 標 asset error(非靜默 null object)。優先「等待重試」而非「卸載重載」(plan §5.3 note 1)。
4. **borrow 即時 VRAM 重檢接完整 ProgressTracker 事件**:`ModelPool.borrow` 以注入的 `PoolBorrowObserver`
   (model 層 Protocol,不依賴 pipeline)回呼;pipeline 側 `_TrackerBorrowObserver` adapter 發 `RESOURCE_WAIT` /
   `RESOURCE_ACQUIRED`(per-asset 經 `context.tracker`,跨 asset 的 batch 經 registry 啟動期 tracker)。逾 `max_wait` 盡力放行。

### 主要產出
- 新增 `model/gpu_capacity_manager.py`:`scan()`(`mem_get_info`,可注入假值)、`ModelVramProfile`(resident/transient)、
  `plan()`(優先序放置 + 每卡預算)、`get_pool_size` / `plan_slots` / `transient_gb` / `eager_models`、
  `apply()`(`register_gate_factory(lambda device_id: BudgetGate(...))`)。
- `model/gpu_gate.py` 新增 `BudgetGate`(Condition 預算記帳 + `priority` 反餓死 + over-budget 單獨放行)。
- `model/base_model_manager.py`:gate factory 帶 device_id;`INFERENCE_PRIORITY` 屬性;`inference_guard` 帶 cost+priority;
  `oom_resilient` / `is_cuda_oom` / `_release_gpu_memory`。
- 5 個 GPU manager(qwen/whisper/musiq/laion/audio_env):設 `INFERENCE_VRAM_COST_GB`(Qwen 另設高 `INFERENCE_PRIORITY`),
  推論方法套 `@oom_resilient` 且 OOM 不吞。
- `model/model_pool.py`:`borrow(observer=)` 加即時 VRAM 重檢(`mem_get_info` 輪詢 + 逾時盡力放行)+ `PoolBorrowObserver` Protocol。
- `ModelPoolRegistry`:process 級 `instance()`、capacity 整合(`plan_slots` 建 pool + 帶 `vram_need`)、`warm_up`(MODEL_WARMUP)、
  `apply_capacity_policy`、`borrow_for_batch`(batch_fn 用)、`_TrackerBorrowObserver` adapter。
- `SemanticImageStage` / `SemanticVideoStage` + 4 個 GPU batch_fn(whisper/aes/tech/audio_env)改走 `pool.borrow()`(`GPU_POOL_ENABLED` 可回退)。
- `runner` 串 capacity→apply→warm up;`scheduler` 注入 `context.tracker`;`progress` 加 `RESOURCE_WAIT/ACQUIRED`。
- config:`media_processor_config` 加各模型 VRAM 估值 / OOM 重試 / Qwen 優先序 / borrow 輪詢;`pipeline_config`
  `EAGER_MODELS_DEFAULT=True` + `GPU_POOL_ENABLED`。

### 驗收條件
- ✅(本機已證)BudgetGate 預算/優先/over-budget;capacity 雙卡 Qwen 2 槽、佔 GPU1 → Qwen 只放 GPU0;
  `apply` per-device 預算;`inference_guard` 帶 cost+priority;同卡跨 instance 共用 gate + Qwen 反餓死;
  `oom_resilient` 重試後 re-raise;borrow VRAM 重檢三路徑;三條 DAG 建構正常;全檔 `py_compile`
- ⬜(實機)雙 GPU 環境 Qwen 同時在兩張卡推論(`nvidia-smi`)
- ⬜(實機)故意用其他 process 佔 GPU 1 VRAM,啟動後 Capacity Manager 自動把 Qwen 只放 GPU 0(看啟動 log `describe()`)
- ⬜(實機)雙卡下 5 張圖 Qwen 吞吐約 2x
- ⬜(實機)故意觸發 OOM(batch 拉爆),確認 `[OOM Retry]` log + 重試機制生效
- ⬜(實機)校準 config 的各模型 VRAM 估值(`reset_peak_memory_stats` + `max_memory_allocated` 量 transient 峰值)

### 風險與緩解
| 風險 | 緩解 |
|---|---|
| 單卡 / 無 GPU 環境出錯 | capacity 偵測空 GPU → `apply`/`warm_up` no-op、維持 BinaryGate;單卡時 Qwen pool size 自動為 1 |
| VRAM 估值不準 | 估值全進 config 可調;啟動 log `describe()` 印每卡預算與放置供觀察;過大請求 BudgetGate 仍單獨放行不卡死 |
| OOM 重試死循環 | 重試上限 N(預設 3)+ 線性 backoff;耗盡 re-raise 標 asset error,不阻擋其他 asset |
| 鄰居長期佔 VRAM 致 borrow 永久等待 | borrow 重檢有 `max_wait`(預設 30s)逾時盡力放行,OOM 由 `oom_resilient` 兜底 |
| 小模型串流餓死 Qwen | BudgetGate `priority` 反餓死:Qwen 在等時低優先讓路 |

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
| Qwen base 模型下載 | Week 1 | `huggingface-cli download Qwen/Qwen3-VL-8B-Instruct`(~17GB,由 bnb 即時量化) |
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
| Week 1 | 2 天(含實機驗證 4-bit 量化品質) |
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
| Qwen 加速 3x | Week 1 結束 ✅ | 可立即上線,單張圖片從 15s 降到 5s |
| Pipeline 框架就緒 | Week 2a 結束 ✅ | 即使不拆 Stage,asset 間並行已生效,4 卡可拿 4x |
| Image 端到端壓榨完成 | Week 2b 結束 ✅ | 圖片加速接近最終值 |
| Video 端到端壓榨完成 | Week 2c 結束 ✅ | 影片加速接近最終值,**Phase 1 核心目標達成**(端到端計時待實機) |
| Dynamic Batching 上線 | Week 3a 結束 | 小模型紅利,但實際影響佔比小 |
| 多 GPU 適應完成 | Week 3b 結束 | 研究室共用 GPU 場景安全可靠 |
| WebSocket 就緒 | Week 3c 結束 | 前端可訂閱進度 |
| 雲端同步上線 | Week 4a 結束 | Phase 1 背景化體驗就緒 |
| 前端 UI 上線 | Week 4b 結束 | **完整產品可發布** |

---

*文件最後更新:2026-06-03(Week 3b 雙 GPU Pool + GpuCapacityManager + BudgetGate 落地;§8 全區改寫為已完成;
全模型接 pool + Qwen 兩層優先、gate factory 帶 device_id、oom_resilient、borrow 即時 VRAM 重檢 + ProgressTracker 事件、
EAGER_MODELS 預設開等設計決策補錄)*
