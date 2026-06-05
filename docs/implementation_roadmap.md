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
  - [8. Week 3b:雙 GPU Qwen Pool + GPU Capacity Manager ✅ 已完成(2026-06-03)](#8-week-3b雙-gpu-qwen-pool--gpu-capacity-manager--已完成2026-06-03)
    - [範圍](#範圍-5)
    - [設計決策(偏離原 plan,以本區為準)](#設計決策偏離原-plan以本區為準-1)
    - [主要產出](#主要產出-3)
    - [驗收條件](#驗收條件-4)
    - [風險與緩解](#風險與緩解-2)
    - [後續強化(2026-06-04,本機結構/邏輯已驗;實機待跑)](#後續強化2026-06-04本機結構邏輯已驗實機待跑)
    - [再後續(2026-06-05,共用工作站實機除錯後的修正,本機驗;commit `3b8cf36`/`ff2b4c5`/`5e45393`/`e771b40`/`5004206`)](#再後續2026-06-05共用工作站實機除錯後的修正本機驗commit-3b8cf36ff2b4c55e45393e771b405004206)
  - [9. Week 3c:Layer 4 WebSocket 接前端 ✅ 已完成(2026-06-05)](#9-week-3clayer-4-websocket-接前端--已完成2026-06-05)
    - [範圍](#範圍-6)
    - [設計決策(偏離原 plan,以本區為準)](#設計決策偏離原-plan以本區為準-2)
    - [主要產出](#主要產出-4)
    - [驗收條件](#驗收條件-5)
    - [不做](#不做-4)
  - [10. Week 4a:Layer 0 雲端攝取 ✅ 已完成(2026-06-05)](#10-week-4alayer-0-雲端攝取--已完成2026-06-05)
    - [範圍](#範圍-7)
    - [設計決策(偏離原 plan,以本區為準)](#設計決策偏離原-plan以本區為準-3)
    - [主要產出](#主要產出-5)
    - [驗收條件](#驗收條件-6)
    - [外部依賴(實機驗證)](#外部依賴實機驗證)
    - [已知限制 / 待補(本批範圍外)](#已知限制--待補本批範圍外)
  - [11. Week 4b:Layer 5 前端 Asset Management UI ⬜ 未開始](#11-week-4blayer-5-前端-asset-management-ui--未開始)
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
| 外部依賴擋路 | 模型下載(Qwen base 等)、Drive API key + 公開資料夾、WebSocket 端對端、多 GPU 行為都不能在 sandbox 跑 |
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
Week 3c  ─ Layer 4 WebSocket 接前端                      ~200 行   ✅ 已完成
   ↓
Week 4a  ─ Layer 0(Google Drive + 同步 + Workspace)    ~500 行 ✅ 已完成(後端)─┐
                                                                  ├─ 可平行
Week 4b  ─ Layer 5(前端 Asset Management UI)            ~600 行 ⬜ 未開始     ─┘
```

| 對話 | 範圍 | 約略行數 | 平行可行 | 驗收型態 |
|---|---|---|---|---|
| Week 1 ✅ | Layer 1 模型優化 + Tracker 介面 | 400 | 否 | 實機 GPU 測試 |
| Week 2a ✅ | Pipeline 骨架 + LegacyStage | 600 | 否(Week 1 之後) | 端到端輸出比對 |
| Week 2b ✅ | Image Stage 拆解 | 300 | 否(Week 2a 之後) | 輸出與 2a 一致 |
| Week 2c ✅ | Video Stage 拆解 + DAG 編排 | 400 | 否(Week 2b 之後) | 輸出與 2b 一致 + 效能提升 |
| Week 3a ✅ | Dynamic Batching + 音訊 Stage 全拆 | 500 | 否(Week 2c 之後) | 壓測 + 結果一致 |
| Week 3b ✅ | 雙 GPU + Capacity Manager(全模型接 pool）| 700 | 與 3a 可平行 | 多 GPU 實機測試 |
| Week 3c ✅ | WebSocket 進度推播(+ async job 化) | 200 | 與 3a/3b 可平行 | wscat 訂閱驗證 |
| Week 4a ✅ | Google Drive Ingestion(後端,公開資料夾 + API key) | 500 | 與 4b 可平行 | Drive API key + 公開資料夾實機 |
| Week 4b | 前端 Asset Management UI | 600 | 與 4a 可平行 | 瀏覽器互動驗證 |

---

## 3. Week 1:Layer 1 模型層獨立優化 ✅ 已完成(2026-05-30;2026-06-01 實機落地修正)

> **狀態:已完成並實機驗證**。程式碼在 commit `51ef717`(主體)+ `43a8d10`(device 鎖定修正)。
> Lock 機制完整設計另見 `docs/lock_design.md`。
>
> **⚠️ 2026-06-05 模型換代(最新,覆寫下方所有 8B / HF-Whisper 敘述)**:
> 1. **Qwen 8B → 4B**(`Qwen/Qwen3-VL-4B-Instruct`,commit `5e45393`):semantic 只做 SIMPLE/全局分析,4B 已足夠且更快更省;
>    4-bit 常駐由 8B ~6.4GB 降到 **~3.5GB**(估值)。下方所有「8B / 6.4GB」為換代前數字,保留作歷史。
> 2. **Whisper:HF transformers large-v3 → faster-whisper(CTranslate2)large-v3-turbo**(commit `5e45393`):
>    turbo decoder 4 層、CT2 量化 kernel,VRAM ~3GB→~1.6GB;補 `info.language` 讓 `spoken_language` 生效。
>    `transcribe_batch` 改**循序**(faster-whisper 無多檔 forward)。**外部依賴改變**:語音鏈不再經 HF/torchaudio,
>    改依 `faster-whisper`(已入 `pyproject.toml`);torch 2.10 家族仍因 VAD/影格鏈而保留。
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

### 後續強化(2026-06-04,本機結構/邏輯已驗;實機待跑)

Week 3b 主體完成後,依使用者實機回饋再補的強化(本機注入假值驗證通過):

- ✅ **同卡多 instance 自動規劃**:`QWEN_MAX_SLOTS_PER_GPU`(`0`=依 VRAM 自動算可並行份數、`>0`=上限);
  per-model 上限表讓 Saliency 用 `1`(每卡一份)。
- ✅ **placement 強化**:單卡小模型集中到「最不排擠 Qwen lane 的卡」(min-displacement,非最空卡);
  放置硬條件改為「放得下 常駐+暫態+buffer」才放 —— 移除舊「min-1 強制至少一份」在瀕死/共用卡硬塞跑不動的
  Qwen(實機共用 GPU hang 根因之一)。
- ✅ **跨卡 OOM failover**:`ModelPool.run_with_failover` —— 某卡持續 OOM 自動換卡(補 `oom_resilient` 只能同卡重試的盲區)。
- ⚠️ **~~Saliency 納入 capacity(綁 GPU)~~ → 2026-06-05 已推翻、改純 CPU pool**(見下方「再後續」):
  Week 3b 曾把 onnxruntime 綁「最空卡」cuda:N + 走 BudgetGate,但共卡仍 hang/OOM,最終移出 GPU。
- ✅ **全模型 warmup**:VAD / MediaPipe / Saliency 走 `_warm_up_auxiliary`(皆 CPU pool);
  Gemini 刻意跳過(雲端 client、無權重、未設 `GEMINI_API_KEY` 會讓啟動報錯)。VAD stage 為 `ResourceType.CPU`。
- ✅ **觀測性**:啟動印 `StartupReporter` 佈局表(每卡 VRAM / 模型放置 / 各 pool 並行度);`StallWatchdog` 心跳印
  進行中 stage + **`faulthandler` dead-man dump**(GIL 被 C 擴充凍住也能從 C 層 dump 全 thread 堆疊;另註冊 `SIGUSR1`
  手動 dump,免 py-spy / root);Phase 1 總耗時計時(`runner.last_run_elapsed_sec`)。
- ✅ **Worker pool 調校**:`MAX_ASSETS_PARALLEL`、IO/CPU/GPU/API 池大小依實機(40 核 / 4×24GB)調整;GPU 池綁 `MAX_ASSETS_PARALLEL` 下限。
- ⬜(實機)上述多卡放置、OOM 換卡,仍待多 GPU 機驗證(saliency 綁卡項已作廢,見下方)。

### 再後續(2026-06-05,共用工作站實機除錯後的修正,本機驗;commit `3b8cf36`/`ff2b4c5`/`5e45393`/`e771b40`/`5004206`)

Week 3b 落地到共用 GPU 工作站後,實機暴露數個「共卡 / 原生庫 / 餓死」問題,逐一修正:

- ✅ **Saliency 移出 GPU 改純 CPU pool**(推翻上方「納入 capacity」):onnxruntime `CUDAExecutionProvider` 與
  PyTorch 各自 CUDA allocator/context 互不知情,共卡偶發 hang/OOM。改固定 `CPUExecutionProvider` +
  `self.device='cpu'`(跳過 L2、borrow 即時放行),由 `model_pool_registry` 獨立 **CPU pool**(`SALIENCY_POOL_SIZE`,
  預設 4)管併發;CPU EP 釋放 GIL。GpuCapacityManager 不再規劃 saliency GPU slot。
- ✅ **VAD 改 CPU pool**(commit `5004206`):原單例 + `@synchronized_inference` 把多影片 VAD 序列化(實測 3 片排到 250s+)。
  改放 `VAD_POOL_SIZE`(預設 4)份「不同 slot_id」Silero,各有獨立 L3 lock → 多影片真平行;`MediaPipe` 亦為 CPU pool。
- ✅ **BudgetGate 反餓死軟化**(commit `5004206`,「wait time computer bug」):舊硬規則「有 Qwen 在等就全擋低優先」
  把同卡小模型整場餓死(aes 實算 ~50ms 卻卡 91s)。改保留低優先車道 `BUDGET_GATE_LOW_PRIORITY_RESERVE_RATIO`(0.5)。
- ✅ **GIL-freeze 修復**:4K 推論幀在送模型前統一縮到短邊 `INFERENCE_MAX_SHORT_SIDE=720`(commit `3b8cf36`,
  MediaPipe tflite / Saliency ONNX 在 ~8M px 不釋放 GIL 凍住 watchdog);K-means 改 `cv2.kmeans`(避開 sklearn/
  threadpoolctl 的 `dl_iterate_phdr` 持動態連結器鎖)+ 啟動期單執行緒預熱原生庫(commit `ff2b4c5`,解多執行緒 import 死結)。
- ✅ **觀測強化**:新增 `SystemHealthProbe`(`[SysHealth]` 印 CPU load/RAM/**swap 速率**/各卡 free VRAM)、
  `ResourceWaitClock`(把 stage 耗時拆「等資源」vs「真 compute」),與既有 `StallWatchdog` + `faulthandler` 同行(commit `e771b40`)。
- ⬜(實機)上述 CPU pool 真平行、反餓死軟化、4K-resize 心跳不凍,仍待共用 GPU 機完整回歸。

---

## 9. Week 3c:Layer 4 WebSocket 接前端 ✅ 已完成(2026-06-05)

> **狀態:程式完成、全檔 `py_compile` 通過;結構/邏輯單元(假 hub/tracker)與實機 wscat 端到端待跑。**
> - ✅ 2 新檔(`backend/api/progress.py`、`backend/services/job_manager.py`)+ 修改 6 檔
>   (events / tracker / runner / director_service / director(api)/ main / app_config)
> - ⚠️ **六項偏離原 plan(已與使用者確認,以本區為準)**:`/generate` 改 **async job model**(見下方「設計決策」)
> - ⬜ 待實機:`curl POST /api/jobs/generate` 取 job_id → `wscat` 訂閱看事件流 → `GET /api/jobs/{id}` 取結果

### 範圍
**與 Week 3a/3b 平行可行**。把 Week 1 已定義的 `ProgressObserver` 介面實作 WebSocket Observer,並把
`/generate` 由「阻塞、跑完才回 blueprint」改為 **async job model**(立即回 job_id、背景跑、WS 串流進度、
`GET /jobs/{id}` 取結果),讓前端能在工作流進行中即時看到「asset × stage」進度。

### 設計決策(偏離原 plan,以本區為準)
原 plan 是「保持 `/generate` 阻塞、只注入 tracker、回 job_id 給前端」。但 `/generate` 阻塞時無法在請求中途
回 job_id 供訂閱,且請求被長時間(Phase 1–4 數分鐘)持開。經與使用者確認改採 async job model:
1. **async job 化**:新增 `POST /api/jobs/generate`(authed,立即回 `{job_id}`、背景 `asyncio.create_task`
   跑 `run_workflow`)+ `GET /api/jobs/{job_id}`(取狀態 / 結果);`DirectorService.run_workflow` 與
   `PipelineRunner.run` 接 optional `tracker`(原項保留)。
2. **expand/contract,不動現有阻塞 `/generate`**:現前端 `api.service.js` 仍以阻塞方式取 blueprint,保留舊端點
   避免破壞 `main`;Week 4b 前端切到新流程後,後續清理再移除舊阻塞路徑。
3. **新增 `JOB_FINISHED` / `JOB_ERROR` 事件型態 + `JobManager`**:工作流層級終端訊號(涵蓋 Phase 1–4,與
   per-asset `PIPELINE_FINISH` 區隔)+ 結果落地(GET 取結果、WS 重連可補取)。`JobManager` 為 in-memory
   Singleton,以 `created_at` + 保留期 lazy 清除。
4. **`ProgressHub` 加 bounded replay buffer**:解「job_id 由後端產生、WS 連線稍晚會漏掉開頭事件」競態;
   WS attach 時於鎖內「snapshot buffer + 註冊佇列」原子完成,先 replay 再串流即時事件,**不漏不重**。
5. **執行緒→event loop 橋接**:`ProgressObserver.on_event` 在 pipeline worker thread 被呼叫,WS `send` 是
   event loop 上的 coroutine,故經 per-connection `asyncio.Queue` + `loop.call_soon_threadsafe` 轉交。
6. **WS 認證寬鬆**:job_id(UUID)當 capability;`?token=` 有帶才驗 JWT + 比對 job 擁有者(符合無 token 的
   wscat 驗收,日後可收緊為強制)。

### 主要產出
- 新增 `backend/api/progress.py`:`ProgressHub`(連線中樞 + replay buffer + 佇列 fan-out)+
  `WebSocketProgressObserver`(訂閱 ProgressTracker,委派給 Hub)+ `WebSocket /ws/progress/{job_id}` 端點
  (replay → 串流 → 哨兵收尾;常駐 receiver task 偵測斷線)。
- 新增 `backend/services/job_manager.py`:`Job`(pydantic)+ `JobManager`(Singleton,執行緒安全 + lazy sweep)。
- 修改 `media_processor/pipeline/progress/events.py`:`ProgressEventType` 加 `JOB_FINISHED` / `JOB_ERROR`。
- 修改 `media_processor/pipeline/progress/tracker.py`:加 `emit_job_finished` / `emit_job_error` 語法糖。
- 修改 `media_processor/pipeline/runner.py`:`run(..., tracker=None)` 注入則沿用、未注入則自建(行為相容)。
- 修改 `backend/services/director_service.py`:`run_workflow(..., tracker=None)` 透傳給 `PipelineRunner.run`。
- 修改 `backend/api/director.py`:加 `POST /api/jobs/generate` + `GET /api/jobs/{job_id}` + `_run_job` 背景協程;
  現有阻塞 `POST /api/generate` 不動。
- 修改 `backend/main.py`:掛 `progress_router`(不加 `/api` 前綴,路徑即 `/ws/progress/{job_id}`)。
- 修改 `config/app_config.py`:加 `PROGRESS_BUFFER_MAXLEN` / `PROGRESS_JOB_RETENTION_SEC` 具名常數。

### 驗收條件
- ✅(本機已證)全 9 檔 `py_compile` 通過。
- ⬜(本機待跑)結構/邏輯單元(假 hub/tracker):replay(attach 前發布補播)、worker thread 經
  `call_soon_threadsafe` 即時送達、`finish` 推哨兵 None、無 job_id 事件忽略、tracker→observer→hub 路由、
  `JobManager` 狀態機與擁有權、`TestClient` WS 端到端往返。
- ⬜(實機)`curl -X POST /api/jobs/generate`(帶 JWT)取回 `{job_id}`;`wscat -c ws://…/ws/progress/{job_id}`
  觀察每個 asset 依序 `pipeline_start → stage_start/finish(decode→…→assembly)→ pipeline_finish`,末筆 `job_finished`。
- ⬜(實機)replay:先 POST 拿 job_id、故意慢 1–2 秒再開 wscat,確認開頭事件仍被補播。
- ⬜(實機)`GET /api/jobs/{job_id}` 在 `job_finished` 後回 `status:"done"` + `result.blueprint`。
- ⬜(實機)WS 斷線時 Observer 失敗隔離(`ProgressTracker.publish` 既有 try/except),不阻斷 Scheduler、工作流照常完成。

### 不做
- 不接前端 React 元件(Week 4b 才做)
- 不移除舊阻塞 `/generate`(expand/contract,待 Week 4b 前端切換後再清)

---

## 10. Week 4a:Layer 0 雲端攝取 ✅ 已完成(2026-06-05)

> **✅ 2026-06-05 已完成並改版為「公開資料夾 URL + Drive API key」(以本區為準,覆寫下方 rclone / Workspace / OAuth 描述)**
> - **改版重點**:徹底拿掉 rclone 與 OAuth。資料夾設「知道連結的人可檢視」(anyone-with-link)、貼資料夾 URL,
>   後端以一把全站共用 `GOOGLE_API_KEY` 走 Drive API v3 列檔／`alt=media` 下載。模型壓平為
>   **一個 URL = 一個 project**(不列舉子資料夾,資料夾內檔案即素材);雲端來源與同步狀態折進該 project 的
>   `project_meta.json`(`source=gdrive` / `drive_folder_id` / `source_url` / `phase1_status` / `sync_status` /
>   `last_asset_signature` / `last_synced_at` / `last_sync_error`),**不另建註冊檔**;poller 改掃所有 project 找 `source=gdrive` 者同步。
> - **新增**:`ingestion_engine/{exceptions,cloud_storage_adapter,public_drive_api_adapter,cloud_ingestion_service}.py`、
>   改寫 `models.py` / `poller.py` / `__init__.py`、`config/ingestion_config.py`(Drive API 具名常數)、
>   `backend/api/projects.py` 新端點。
> - **刪除**:`google_drive_adapter.py`(rclone)、`oauth_flow.py`、`workspace_store.py`、`workspace_manager.py`、`backend/api/workspaces.py`。
> - **API**:`POST /api/projects/from-drive`(貼 URL 建 project + 背景首同步)、`POST /api/projects/{name}/sync`(手動)、
>   `GET /api/projects` 露出同步欄位(`ProjectMeta` 已加 Optional 欄位)。**移除 `/api/workspaces`**。
> - **依賴**:新增 `httpx`;`.env` 需 `GOOGLE_API_KEY`(+ 可選 `ENABLE_INGESTION_POLLER`)。**不需 rclone、不需 Google Cloud Console OAuth app**。
> - ✅ sandbox 驗(stub httpx + fake adapter,無需網路/GPU):adapter `parse_source`(各 URL/裸 ID/非法)、分頁列檔、
>   folder-file 與副檔名過濾、串流下載 + 同 size 增量跳過、`401·403→RemoteAuthError`、`500·壞 JSON→RemoteAccessError`;
>   service 首同步 / idempotent / 新檔重跑 / auth 暫停(`paused_auth_error`) / access error / Phase 1 失敗隔離 / 非雲端跳過;
>   poller 只挑到期 gdrive、略過 paused 與本地 project。
> - ⬜ 待實機:`.env` 填 `GOOGLE_API_KEY` → 資料夾設公開 → `POST /api/projects/from-drive` 貼 URL → ≤5 分(或手動 sync)
>   建 project + `phase1_status=done`;資料夾轉私人 → 該 project `paused_auth_error`、其他正常。
> - ⚠️ **下方「設計決策／主要產出／驗收條件／外部依賴／已知限制」多為改版前 rclone MVP 的描述,已被本區覆寫,保留作為演進紀錄;個別已明顯失真者另於原處加註。**

### 範圍
Google Drive workspace → project 自動偵測 + 背景觸發 Phase 1。**與 Week 4b 可平行**;本批只做後端攝取與 API。

### 設計決策(偏離原 plan,以本區為準)
1. **不導入資料庫,持久化用檔案系統 JSON**:原 plan 寫「新增 workspaces 與 projects 表」,但全專案無 DB
   (project = `ASSETS_DIR/{user_id}/{name}/` + `project_meta.json`)。改為:workspace 註冊存
   `ASSETS_DIR/{user_id}/.workspaces.json`(`WorkspaceStore` Repository);project 的雲端來源連結直接擴充
   `project_meta.json`(新增 `source`/`workspace_id`/`remote_folder`/`phase1_status`/`phase1_updated_at`/`archived`)。
2. **MVP 採「rclone 擁有 token + `remote:path` 註冊」,非 app 自有 drive.file 網頁 OAuth**:背景輪詢須長期持有
   refresh token,而 rclone 本就會在 `rclone config` 存 token 並自動刷新。故 MVP 由 rclone 擁有 token、workspace
   以 `gdrive:資料夾路徑` 註冊;`oauth_flow.py` 僅為清楚標注的 stub 接縫(`GoogleOAuthFlow` 介面 +
   `RcloneConfigOAuthFlow`)。app 自有 OAuth 留待下一批 additive 補上(adapter 介面不變,屆時只是改用注入 token
   建 rclone remote)。**因此本批不需 Google Cloud Console OAuth app。**
3. **rclone 走 subprocess CLI(`lsjson`/`copy`),非 FUSE mount;素材下載到本地 `ASSETS_DIR` 再交既有 pipeline**
   (沿用「讀本地檔」流程,避開 `app_config` 註記的 NFS/FUSE hang 風險)。
4. **抽出 standalone `run_phase1`**:原 `run_workflow` 為 monolithic(必跑到 Phase 4),背景預跑只需 Phase 1,
   故把 Phase 1 段抽成 `DirectorService.run_phase1`,`run_workflow` 內部改呼叫(輸出逐欄不變)。
5. **背景預跑觀測用 `project_meta.json` 的 `phase1_status`**(pending/processing/done/failed + 時間),REST/讀檔可查;
   本批不接 WebSocket(Week 4b 前端輪詢)。

### 主要產出
- 新增 `ingestion_engine/` 模組樹:
  - `models.py` — pydantic Value Objects(`RemoteEntry` / `Workspace` / `ProjectLink` / `SyncReport` + 狀態常數)
  - `google_drive_adapter.py` — `CloudStorageAdapter`(ABC,多雲端預留)+ `GoogleDriveAdapter`(rclone subprocess 封裝 + 錯誤分類)
  - `workspace_store.py` — `WorkspaceStore`(Repository,per-user `.workspaces.json`,鎖 + temp-rename 原子寫)
  - `workspace_manager.py` — `WorkspaceManager`(Facade:register/list/remove/sync;sync 做偵測→建 project→下載→觸發 Phase 1→archived 標記→auth 隔離)
  - `poller.py` — `IngestionPoller`(async 背景輪詢,到期 workspace 並行 `to_thread` sync,per-workspace 不重疊)
  - `oauth_flow.py` — `GoogleOAuthFlow` 介面 + `RcloneConfigOAuthFlow` stub(接縫)
  - `__init__.py`
- 新增 `config/ingestion_config.py` — rclone/輪詢/媒體副檔名/registry/OAuth 接縫具名常數(`ENABLE_INGESTION_POLLER` 可關)
- 新增 `backend/api/workspaces.py`(掛 `/api`,`Depends(verify_token)`):
  - `POST /api/workspaces` — 註冊 workspace(body `{display_name, source_url}`,`source_url` 為 rclone `remote:path`)
  - `GET /api/workspaces` — 列出 user 所有 workspace
  - `POST /api/workspaces/{id}/sync` — 手動觸發同步(`to_thread`)
  - `DELETE /api/workspaces/{id}` — 解除註冊(保留本地 projects)
- 新增 `backend/services/ingestion_provider.py` — Composition Root(組裝單例 + 注入 `phase1_runner`=既有 `director_service`,避免循環 import)
- 修改 `backend/services/director_service.py` — 抽出 `run_phase1()`
- 修改 `backend/main.py` — `lifespan` 啟停 poller + 掛 `workspaces_router`

### 驗收條件
- ✅(sandbox)雲端刪除子資料夾 → 對應 project 標 `archived`、本地 metadata 保留
- ✅(sandbox)授權失效 → 該 workspace `paused_auth_error`、其他 workspace 照常 sync
- ⬜(實機)`rclone config` 授權後,`POST /api/workspaces` 以 `gdrive:資料夾` 註冊 → `GET` 列出
- ⬜(實機)Drive 該資料夾下新增子資料夾 + 素材,≤5 分(或手動 sync)建 project + `phase1_assets_metadata.json`、`phase1_status=done`

### 外部依賴(實機驗證)
- 安裝 rclone(系統執行檔),`rclone config` 建一個 gdrive remote 並完成授權(token 由 rclone 擁有/自動刷新)
- `.env` 設 `ENABLE_INGESTION_POLLER=true`(及可選 `RCLONE_BINARY` / `WORKSPACE_POLL_INTERVAL_SEC` / `POLLER_TICK_SEC`)
- **本批不需** Google Cloud Console OAuth app 或新 Python 套件(app 自有 drive.file OAuth 那批才需要)
- Phase 1 仍需既有 GPU/模型堆疊(Week 1–3b);無模型機器上 project 仍會建立、素材會下載,但 `phase1_status=failed`

### 已知限制 / 待補(本批範圍外)
- **無通用媒體上傳 API**:後端只有 `upload_music`,沒有圖片/影片上傳端點。手動建的空 project 目前只能靠雲端同步或
  直接放檔到伺服器資料夾補素材;瀏覽器拖拉上傳留待後續(可加 `POST /api/projects/{name}/upload`)。
- ~~**`phase1_status` 尚未經 `GET /api/projects` 露出**~~ ✅ 已解決(2026-06-05 改版):`ProjectMeta` 已加
  `source`/`phase1_status`/`sync_status`/`last_synced_at`/`last_sync_error`/`source_url` 等 Optional 欄位,前端可輪詢。
- **前端無雲端 project 同步 UI / api.service 方法**:屬 Week 4b(§11);本批雲端 project 只能經 API(curl)操作。
- ~~**MVP 註冊吃 `remote:path` 非 Drive 網址**~~ ✅ 已解決(2026-06-05 改版):`POST /api/projects/from-drive`
  直接吃 Drive 資料夾 URL(涵蓋 `/folders/{ID}`、`open?id=`、`?usp=sharing` 等),`parse_source` 解析成 folder ID。
- **同步未產縮圖**:原設計(plan §8.2 / §11)預期「Layer 0 同步時順手產 thumbnail」,本批**未實作**;
  Week 4b 需縮圖時,於同步時補產或前端 on-demand 生成。

---

## 11. Week 4b:Layer 5 前端 Asset Management UI ⬜ 未開始

### 範圍
**與 Week 4a 可平行**。前端純 React 工作,依賴 4a 的 API 但可先 mock。
> **狀態**:尚未開始(無 `frontend/src/pages/AssetListPage.tsx`)。

### 主要產出
- 新增 `frontend/src/pages/AssetListPage.tsx` 路由 `/projects/{project_id}/assets`
- 元件:
  - `AssetGrid` — 縮圖網格
  - `AssetCard` — 單張 asset 卡片(縮圖、狀態、策略 toggle)
  - `BulkActionBar` — 全選 / 批量設策略 / 重新分析按鈕
  - `ProgressOverlay` — WebSocket 進度顯示
- WebSocket client 連 `/ws/progress/{job_id}`,訂閱 Stage 事件
- 串接後端 API(**注意:以下 per-project asset 端點 Week 4a 未建**,屬 4b 後端工作;4a 交付 `/api/projects/from-drive`
  與 `/api/projects/{name}/sync`,以及既有 `/api/projects`、`/api/jobs/generate`):
  - `GET /api/projects/{id}/assets`
  - `POST /api/projects/{id}/generate`(帶 `asset_strategies`)
  - `POST /api/projects/{id}/reanalyze`
  - `PATCH /api/projects/{id}/assets/{asset_id}/strategy`
- 縮圖 URL 從 `temp_templates/thumbnails/{project_id}/` 讀取(**Week 4a 未實作縮圖產出**,需 4b 或 4a 後續補:
  同步時順手產出或 on-demand 生成)

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

注意，你在寫程式時的註解，不該包含跟實作無關的事情(如Week X)
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
| Qwen base 模型下載 | Week 1（2026-06-05 換 4B） | `huggingface-cli download Qwen/Qwen3-VL-4B-Instruct`(~8GB,由 bnb 即時量化;原 8B ~17GB 已棄用) |
| Flash Attention 安裝 | Week 1 | `pip install flash-attn --no-build-isolation` |
| faster-whisper 權重 | Week 1（2026-06-05 換後端） | `large-v3-turbo` 由 faster-whisper 首次自官方 CT2 repo 下載到 `MODEL_WEIGHTS_DIR`(避開 NFS) |
| 多 GPU 環境 | Week 3b | 實機驗證雙卡 Qwen 同時推論 |
| 故意佔 VRAM 測試 | Week 3b | 用 `torch` 佔住 GPU 1 部分 VRAM 測 Capacity Manager |
| Drive API key + 公開資料夾 | Week 4a（2026-06-05 改版） | Cloud Console 啟用 Drive API → 建 API key 填 `.env` `GOOGLE_API_KEY`；目標資料夾設「知道連結的人可檢視」。**不需 rclone、不需 OAuth** |
| 真實瀏覽器測試 | Week 4b | 開瀏覽器點按互動 |

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
| Week 4a + 4b 平行 | 4 天(實機 Drive API key + 前端互動測試) |
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
| WebSocket 就緒 | Week 3c 結束 ✅ | 前端可訂閱進度(async job + WS 串流) |
| 雲端同步上線 | Week 4a 結束 ✅(後端) | Phase 1 背景化體驗就緒(公開資料夾 + Drive API key;實機待驗) |
| 前端 UI 上線 | Week 4b 結束 | **完整產品可發布** |

---

*文件最後更新:2026-06-05(Week 4a **改版**:Layer 0 攝取改走「公開資料夾 URL + 全站共用 Drive API key」,
徹底移除 rclone 與 OAuth —— 新增 `ingestion_engine/{exceptions,cloud_storage_adapter,public_drive_api_adapter,
cloud_ingestion_service}.py`、改寫 `models`/`poller`/`__init__`/`config/ingestion_config.py`、`backend/api/projects.py`
新端點(`POST /api/projects/from-drive`、`POST /api/projects/{name}/sync`、`GET /api/projects` 露出同步欄位);
刪除 `google_drive_adapter`/`oauth_flow`/`workspace_store`/`workspace_manager`/`backend/api/workspaces.py`。
模型壓平為 **一個 URL = 一個 project**、同步狀態折進 `project_meta.json`、poller 改掃 project;新依賴 `httpx`、
`.env` 需 `GOOGLE_API_KEY`。§10 頂部加改版總覽 callout、§14 外部依賴 / §15.3 里程碑 / 已知限制同步更新;
`integrated_acceleration_plan.md §3` 加對應 callout)*
*前版:2026-06-05(Week 4a 完成:Layer 0 Google Drive 攝取**後端**(rclone MVP)—— `ingestion_engine/` + `config/ingestion_config.py`
+ `backend/api/workspaces.py` + `ingestion_provider`;`director_service` 抽出 `run_phase1`、`main.py` lifespan 拉起 poller)*
*前版:2026-06-05(Week 3c 完成:Layer 4 WebSocket 進度推播 + `/generate` 改 **async job model**;
§9 全區改寫為已完成 + 設計決策(async job 化、expand/contract 保留舊 `/generate`、`JOB_FINISHED`/`JOB_ERROR` +
`JobManager`、`ProgressHub` replay buffer、執行緒→event loop 橋接、WS 認證寬鬆);TOC / §2 總覽 / §15.3 里程碑同步標記 ✅)*
*前版:2026-06-05(模型換代 + 共用機實機修正:Qwen **8B→4B**、Whisper 改 **faster-whisper turbo**(§3 加換代塊)、
§8 加「再後續」—— Saliency **移出 GPU 改 CPU pool**、VAD 改 CPU pool、BudgetGate 反餓死軟化、4K-resize/cv2.kmeans GIL 修復、
SystemHealthProbe/ResourceWaitClock 觀測;§9/§10/§11 標記 ⬜ 未開始、§14 外部依賴更新 4B + faster-whisper)*
*前版:2026-06-03(Week 3b 雙 GPU Pool + GpuCapacityManager + BudgetGate 落地;§8 全區改寫為已完成;
全模型接 pool + Qwen 兩層優先、gate factory 帶 device_id、oom_resilient、borrow 即時 VRAM 重檢 + ProgressTracker 事件、
EAGER_MODELS 預設開等設計決策補錄)*
