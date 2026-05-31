# Media Processor 加速架構設計筆記

> 這份文件記錄了 Pipeline Framework + Model 層優化的整合加速設計,涵蓋雲端攝取、模型優化、資源排程、觀測與前端體驗。
> 文件撰寫時程式碼尚未實作,供日後開發前閱讀。
> 本文件取代並擴充 `previous_plan.md`,後者聚焦純模型層優化,本文件涵蓋更完整的端到端體驗。

---

## 目錄

1. [現狀分析:為什麼目前慢、體驗為什麼不好](#1-現狀分析)
2. [整體架構分層](#2-整體架構分層)
3. [Layer 0:雲端攝取與 Workspace 機制](#3-layer-0雲端攝取與-workspace-機制)
4. [Layer 1:模型層優化](#4-layer-1模型層優化最大紅利來源)
5. [Layer 2:資源管理層](#5-layer-2資源管理層)
6. [Layer 3:Pipeline 排程層](#6-layer-3pipeline-排程層架構紅利)
7. [Layer 4:觀測層](#7-layer-4觀測層)
8. [Layer 5:前端 Asset Management UI](#8-layer-5前端-asset-management-ui)
9. [背景預跑策略](#9-背景預跑策略)
10. [Worker Pool 大小建議](#10-worker-pool-大小建議)
11. [業界對照:這套設計叫什麼](#11-業界對照這套設計叫什麼)
12. [預期效益總覽](#12-預期效益總覽)
13. [與其他方案的對照](#13-與其他方案的對照)
14. [風險清單與緩解](#14-風險清單與緩解)
15. [落地節奏與驗證方式](#15-落地節奏與驗證方式)
16. [關鍵核心檔案](#16-關鍵核心檔案)

---

## 1. 現狀分析

### 1.1 性能瓶頸:Phase 1 是線性累加

`backend/services/director_service.py:92` 是純序列迴圈,每個 asset 依序呼叫 `MediaProcessorFactory.create_processor(...).process(file_path)`:

```
單張圖片  ≈ 7–15 秒
單部影片  ≈ 20–60 秒 (Simple) / 60–110 秒 (Complex)
10 個 asset 線性累加 ≈ 303 秒(混合 5 圖 + 5 Simple 影片)
```

### 1.2 兩層瓶頸並存

**架構層**
- 處理流程把 IO/CPU/GPU/API 四種異質工作綁死同一條同步呼叫鏈,資源輪流閒置
- `ModelPool` 已寫好卻**未啟用**,多 GPU 紅利沒拿
- `@synchronized_inference` 鎖只保護「同模型」不保護「同 GPU」,**有潛在 OOM bug**(雙模型放同卡時雙 forward 同時跑)

**模型層**
- Qwen VLM 單張 5 秒,佔每張圖總耗時 ~70%
- 仍用 8-bit 量化、沒開 Flash Attention、沒做 batch
- MUSIQ/LAION 等輕量模型一張一張呼叫,GPU kernel 啟動成本完全沒被攤平
- 畫質不足的 asset 仍會跑 Qwen,浪費 30–50% 推論

### 1.3 體驗瓶頸:user 同步等待整條工作流

```
User 上傳 asset → User 寫 prompt → 按生成 → 等 5 分鐘 → 看到結果
                                            ↑
                                  Phase 1/2/3/4 全序列跑
```

User 寫 prompt 的時間後端完全閒置,沒有預跑能力。

---

## 2. 整體架構分層

```
┌──────────────────────────────────────────────────────────┐
│ Layer 5: 前端 Asset Management UI                          │
│  Asset 卡片網格 + Per-asset 策略勾選 + 進度顯示             │
├──────────────────────────────────────────────────────────┤
│ Layer 4: 觀測層                                            │
│  ProgressTracker + WebSocket 推播                          │
├──────────────────────────────────────────────────────────┤
│ Layer 3: 排程層(架構紅利)                                 │
│  Pipeline + StageGroup + HybridScheduler                  │
│  asset 間並行 + 群組內並行 + 跨 asset 自然 stage pipeline   │
├──────────────────────────────────────────────────────────┤
│ Layer 2: 資源管理層(安全紅利)                             │
│  ExecutorRegistry (IO/CPU/GPU/API 四 Pool)                │
│  ModelPool 啟用 + GPU-level Semaphore (修 OOM bug)        │
│  GPU Capacity Manager (動態 VRAM 偵測 + 共用 GPU 適應)     │
├──────────────────────────────────────────────────────────┤
│ Layer 1: 模型層(效能紅利,佔總加速最大頭)                │
│  Qwen AWQ + Flash Attention                              │
│  MUSIQ/LAION/Whisper batch inference                      │
│  Early Rejection 短路(省 30–50% VLM)                    │
│  雙 GPU 動態共用 Qwen pool                                 │
├──────────────────────────────────────────────────────────┤
│ Layer 0: 攝取層(獨立於 MediaProcessor)                   │
│  IngestionPipeline: 雲端 Workspace → 子資料夾自動成 project │
│  Google Drive (drive.file scope) + rclone mount + polling │
└──────────────────────────────────────────────────────────┘
```

每一層獨立帶來加速,**乘法疊加**:Layer 1 拿 3–5x,Layer 2 拿 1.5–2x(多 GPU),Layer 3 拿 1.5–2x(重疊),總合可達 6–9x。

---

## 3. Layer 0:雲端攝取與 Workspace 機制

### 3.1 設計目標

把「上傳到雲端 → 自動處理」做成天然體驗,user 拍照上傳就完成 Phase 1,不需手動上傳到後端。

**MVP 範圍**:只支援 Google Drive。其他雲端(Dropbox/S3/HTTP)列入未來擴展。架構不綁定來源,後續新增其他雲端只需註冊新的 rclone backend,不動 Ingestion 主邏輯。

### 3.2 Workspace → Project 自動偵測

核心概念:**使用者指定的雲端資料夾稱為 Workspace,其下每個子資料夾自動成為一個 Project**。

```
User Google Drive
  └── Workspace 1(user 指定的根資料夾,可掛 N 個)
        ├── Project A/          ← 自動偵測為 project
        │     ├── photo1.jpg
        │     └── video1.mp4
        ├── Project B/          ← 自動偵測為 project
        └── Project C/

User 拍照 → 手機自動上傳到 "Workspace 1/Project A"
        ↓ 後端 5 分鐘內偵測到新檔案
        ↓ MediaProcessor Pipeline 自動開跑
        ↓ 結果出現在前端
```

### 3.3 為什麼這樣設計

| 紅利 | 說明 |
|---|---|
| 自動化體驗 | 拍照 → 上傳 → 處理全自動,無需手動上傳到後端 |
| 隱私最小化 | 只授權 workspace 資料夾,user 其他 Drive 內容後端看不到 |
| 結構自然 | 子資料夾即 project,符合多數人對 Drive 的整理直覺 |
| 多 workspace | 同一 user 可掛 N 個 workspace(個人作品/客戶 A/客戶 B) |

### 3.4 授權機制(兩種方式並存)

**主要方式:Google OAuth `drive.file` scope**(推薦預設)
- App 只能存取 user 主動「分享給 app」的檔案/資料夾
- User 在 Drive 介面點分享 → 選 app 帳號 → 後端立刻看到
- 隱私範圍最小,user 操作直觀

**備援方式:URL 直貼**
- User 在前端貼 Drive 資料夾連結
- 後端解析連結 → 對應 rclone remote path
- 適合進階用戶或 drive.file 不便操作的情境

### 3.5 同步策略

- 每個 workspace 啟動 background poller(預設 5 分鐘)
- 每輪 polling:list 該 workspace 一層子資料夾 → 與 DB 比對 → 新增/重命名/刪除
- **深度限制**:只看一層,不遞迴(避免巨型樹掃描)
- **空資料夾**:偵測但不建 project,等有 asset 才建
- **雲端刪除**:標記為 archived,本地 metadata 保留(防誤刪)
- **手動觸發**:`POST /api/workspaces/{id}/sync`

### 3.6 為什麼選 rclone mount + polling

| 取捨 | rclone mount + polling | 雲端 SDK 直連 | Webhook event-driven |
|---|---|---|---|
| 多雲端統一 | ✅ 40+ 雲端統一介面 | ❌ 每個雲端各寫 | ✅ |
| MVP 實作 | ✅ 一週可上線 | 中 | ❌ 需對外 webhook URL |
| 反應速度 | 中(5 分鐘 polling) | 中 | ✅ 即時 |
| 斷網容錯 | ✅ rclone 自帶 cache 與重試 | 自己寫 | 中 |

MVP 選 rclone + polling,**未來升級到 webhook 隨時可換**。

---

## 4. Layer 1:模型層優化(最大紅利來源)

### 4.1 Qwen VLM 三層加速

Qwen 單張 5 秒 × 每張圖必跑,是絕對主瓶頸。三招複合:

| 招式 | 加速 | VRAM 變化 | 機制 |
|---|---|---|---|
| 4-bit 量化(bitsandbytes NF4) | 1.5–2x | **約 -65%**(實測推理 18GB → **6.4GB**) | 官方 base + `BitsAndBytesConfig(load_in_4bit, nf4)`(見下方註) |
| Flash Attention 2 | 1.5–2x | 略降 | 載入時加 `attn_implementation="flash_attention_2"` |
| 動態雙 GPU Qwen Pool | 2x | 兩卡各放一份 | Qwen 預載兩張 GPU,音訊處理完成後 GPU 1 接視覺工作 |

**複合效果:單張 Qwen 5s → 約 0.6–1s,5–8x 加速(這層最關鍵)**。

VRAM 砍半特別重要,讓單卡同時放下 Qwen + 其他模型、雙卡可各放一份 Qwen。

> **⚠️ 量化方案最終定案(2026-06-01,推翻原 AWQ 規劃)**:原規劃改用社群 AWQ `cyankiwi/Qwen3-VL-8B-Instruct-AWQ-4bit`(compressed-tensors 格式),
> 但**實測在 transformers 推理時會整包解壓成 bf16、runtime 完全不省 VRAM**(載入 7.5GB → 推理 18GB;真正的 W4A16 4-bit kernel 只在 vLLM)。
> 故**改用 bitsandbytes 4-bit NF4**:直接量化官方 base `Qwen/Qwen3-VL-8B-Instruct`,`BitsAndBytesConfig(load_in_4bit, bnb_4bit_quant_type="nf4", compute bf16, double_quant)`,
> 實測 runtime **6.4GB**,VRAM 砍半才真正實現。旗標 `QWEN_USE_4BIT`(true=4-bit、false=bnb 8-bit)。
> torch 仍定 2.10(flash-attn wheel 天花板),且 torchaudio/torchcodec 須對齊 2.10/0.10。詳見 `implementation_roadmap.md` 第 3 章。

### 4.2 輕量模型 Batch Scoring(Dynamic Batching)

MUSIQ、LAION、Whisper、AudioEnv 底層支援 batch。一張一張呼叫時,GPU kernel 啟動成本佔比極高:

| 模型 | 單張 | Batch 16 | 加速 |
|---|---|---|---|
| MUSIQ | 200ms | 30ms/張 | 6x |
| LAION | 200ms | 30ms/張 | 6x |
| Whisper | 8s/檔 | 1.5s/檔(batch 4) | 5x |

Saliency、VAD、Gemini 底層不支援 batch,維持單張。

### 4.3 Dynamic Batching 在 Pipeline 內怎麼運作

關鍵:**不是每個 asset 自己決定 batch,而是多個 asset 的同 Stage 在執行階段自動合併**。

```
Asset A driver 跑到 TechScoreStage → submit 到 BatchCollector → wait
Asset B driver 跑到 TechScoreStage → submit 到 BatchCollector → wait
Asset C driver 跑到 TechScoreStage → submit 到 BatchCollector → wait
Asset D driver 跑到 TechScoreStage → submit 到 BatchCollector → wait
       ↓ 達到 batch_size 或 timeout
BatchCollector 一次 forward 4 張 → 分發結果到 4 個 Future
       ↓ 4 個 driver 各自拿到結果,繼續下一個 Stage
```

- 每個支援 batch 的 Stage 內部持有一個 `BatchCollector`(singleton-per-stage)
- Stage 介面不變,driver thread 完全無感
- 兩個關鍵參數:`batch_size`(越大吞吐越好、延遲增加)、`timeout_ms`(避免末尾 asset 卡死)
- 這個機制等同於 **NVIDIA Triton Inference Server / vLLM 的 dynamic batching**,只是縮小到 Stage 內部

### 4.4 Early Rejection 短路(省呼叫次數)

跑完 MUSIQ batch 後,`technical_score < 40` 的 asset 直接標記 rejected,**完全不進入後續 Saliency / Aes / Qwen / Audio 等昂貴 stage**。

實測 30–50% 素材會被 reject(用戶丟一堆模糊照很正常),這部分等於**白送的加速**。

### 4.5 GPU-level Gate(修 OOM bug)✅ Week 1 已實作

現有 `@synchronized_inference` 只保證「同模型不重入」,**不保護「同 GPU 不被多模型同時推論」**。當雙模型放同卡(例如 GPU 1 同時放 Whisper + Qwen),兩條 thread 各自拿到自己模型的鎖就會同時跑 forward pass,**直接 VRAM OOM**。

**解法(實際實作:`GpuGate` Strategy Pattern,非裸 Semaphore)**:在 `BaseModelManager` 加一層全域 per-device `GpuGate`。鎖的取得順序:

```
L2 GpuGate(GPU 層,per-device)
    └── L3 _inference_lock(model 層,per-instance)
            └── 實際的 forward pass
```

取得順序永遠由外到內,釋放由內到外,**不會 deadlock**。

**為什麼做成 Strategy 而非寫死 Semaphore**:
- **Week 1 `BinaryGate`**(= Semaphore(1)):同卡序列化,修掉 OOM bug,代價是 VRAM 夠也不能同卡併發
- **Week 3b `BudgetGate`**:帶 per-model VRAM cost,VRAM 夠就放行同卡併發。由 GPU Capacity Manager 啟動時 `BaseModelManager.register_gate_factory(BudgetGate)` 一行替換,**Manager 子類零改動**
- CPU/雲端 API 模型依 `self.device` 自動跳過 L2(只取 L3)

**BudgetGate 的真實紅利場景**(釐清):是「**同卡跨不同 model 併發**」(例:GPU0 上 Qwen 5GB + Whisper 3GB 同時 forward),**不是**「同卡同 model 跑多 asset」—— 後者受限於 Pool 一卡一 instance,要同卡多 instance 才行(已備 `(device_id, slot_id)` 結構,Week 3b 才有效)。

完整三層鎖(L1 ModelPool / L2 GpuGate / L3 inference lock)的職責、不可省略反例、呼叫路徑見 **`docs/lock_design.md`**。

不影響介面、改動小,是後續多模型共卡的安全基礎。

### 4.6 為什麼模型層紅利最大

| 優化 | 加速 | 來源 |
|---|---|---|
| 4-bit + Flash Attn | 3x | 同一個 Qwen 跑得更快 |
| 雙 GPU Qwen Pool | 2x | 兩個 Qwen 並行 |
| Early Rejection | 30–50% | 跳過 Qwen 呼叫 |
| MUSIQ/LAION batch | 6x(但佔比小) | 攤平 kernel 啟動成本 |

這些**乘法疊加**砍掉主瓶頸,效益遠大於只做架構重疊。

---

## 5. Layer 2:資源管理層

### 5.1 ExecutorRegistry:四種 Worker Pool

每個 Stage 標註自己屬於哪種資源,自動路由到對應 Pool:

| Pool | 適用工作 | 限制因素 |
|---|---|---|
| IO Pool | FFmpeg subprocess、檔案讀寫、Gemini 上傳 | 高併發,可大量 |
| CPU Pool | cv2、KMeans、MediaPipe、SceneDetect | numpy/cv2 釋放 GIL,thread 有效 |
| GPU Pool | 所有 GPU 推論 | 與 ModelPool 整合 |
| API Pool | Gemini API 推論 | Semaphore 控 RPS |

不同 Pool 互不干擾,**確保 IO 與 GPU 可同時工作,不會「做 IO 時 GPU 全閒」**。

### 5.2 ModelPool 正式啟用 + Eager Warm Up

現有 `model/model_pool.py` 已寫好但未使用。本計畫透過 `ModelPoolRegistry` 集中管理各模型 Pool:

- 每張 GPU 一個模型 Singleton 實例(沿用現有 `BaseModelManager`)
- Pool 用 Queue 提供 `borrow()` Context Manager,自動分配空閒卡
- 多個 asset 共享同一份 Qwen,**不會每個 asset 載一份模型**

**模型載入策略改為 Eager Warm Up(重要變更)**:

現有 `@property` lazy load 設計**在新架構下會造成第一個 asset 卡 20–60 秒等模型載入**,user 體驗極差。改為:

- 後端啟動時就觸發「熱門模型清單」全部載入(Qwen / MUSIQ / LAION / Whisper / Saliency / VAD / AudioEnv / MediaPipe)
- 啟動慢 20–90 秒,但 runtime 第一個 asset 就快
- ProgressTracker 在啟動時推「模型載入中:Qwen on GPU 0」事件給前端
- 冷門模型(Gemini API client、實驗模型)仍可 lazy
- 開發環境可用 `EAGER_MODELS=false` 關閉,避免熱重載過慢
- VRAM 不夠時 GPU Capacity Manager 自動降級該模型為 lazy

這個策略對齊業界慣例(vLLM / Triton / TorchServe 都是啟動時 warm up,不 lazy)。

### 5.3 GPU Capacity Manager(共用 GPU 適應)

研究室工作站場景特別重要 — GPU 隨時可能被同學跑訓練佔走 VRAM。新增獨立模組封裝 VRAM 偵測邏輯:

- **啟動時掃描** — 列出每張 GPU 的 free VRAM,計算每張卡能放幾份模型
- **預留 buffer** — `GPU_SAFETY_BUFFER_GB`,別人臨時吃這個量不會炸到我們
- **動態決定 ModelPool size** — free VRAM 不足某模型最低需求的卡,直接從 pool 排除
- **執行時動態退場** — 每次 `borrow()` 前再檢查可用 VRAM,不夠就 block 等待 + 通知 Observer
- **OOM 容錯** — Stage 跑到一半遇 CUDA OOM,釋放當前 model + `empty_cache()` + asset 放回隊列重試最多 N 次

啟動時讀 `CUDA_VISIBLE_DEVICES`,搭配上述動態邏輯,**單卡/多卡/共用 GPU 三種環境完全自適應**,Worker 數不寫死。

---

## 6. Layer 3:Pipeline 排程層(架構紅利)

### 6.1 Pipeline 抽象

每個 asset 走一條 Pipeline,Pipeline 由「**StageGroup**」依序組成。

**同一群組內 Stage 並行,群組之間序列**。這個簡化版的 DAG 設計避免了傳統 pipeline 的複雜 callback 鏈,但保留了並行性。

群組邊界的設計原則:
- 把所有「只讀 decode 產出、互不依賴」的 Stage 塞進同一群組
- 把「依賴前面結果」的 Stage 放下一群組
- 在「省呼叫」最有效的位置插入 RejectFilter(例如 MUSIQ 後立刻 reject,避免後面整批 stage 浪費)

影片的群組編排是重點:Complex 影片的 60 秒燒時間碼(CPU)、音訊鏈(IO→GPU)、場景偵測(CPU)、視覺特徵(CPU+GPU)全部塞同一群組並行,**單部 Complex 影片從 110s 壓到約 84s**。

### 6.2 HybridScheduler:主力排程器

```
N 個 asset driver thread 同時推進(預設 4)
   ↓ 每個 driver 在自己的 asset 上一個群組一個群組推進
   ↓ 所有 driver 共享同一組 ExecutorRegistry
結果:
   asset A 在跑 Qwen (GPU)
   asset B 在抽音訊 (IO)
   asset C 在跑場景偵測 (CPU)
   → 不同類型資源永遠有東西在跑
```

這就是「asset 間粗粒度 + 群組內細粒度」的綜合方案,既拿到 ModelPool 多 GPU 紅利,也拿到 stage 重疊紅利。

### 6.3 Complex / Simple 策略(Per-asset 細粒度)

**前端可逐檔指定策略**,不再是整批共用:

- 前端在素材清單畫面為每個 asset 標記 Simple / Complex(預設 Simple)
- `run_workflow` 入口接受 `asset_strategies: dict[asset_id, {video|image: strategy}]`
- `PipelineBuilder` 為每個 asset 依其指定策略選 pipeline 變體
- 同一 batch 內 9 張 Simple + 1 張關鍵 Complex 可同時混合排程

策略只影響 `SemanticImageStage` / `SemanticVideoStage` 內部呼叫 Qwen 還是 Gemini,**Pipeline 其他 Stage 完全不變**,排程器無感。

**Batch 層級為 fallback**:若前端沒傳 `asset_strategies`,沿用既有的 `video_strategy` / `image_strategy` 全批參數,向後相容。

### 6.4 與既有元件協作

不破壞現有設計:
- `MediaProcessorFactory` / `MediaStrategy` 介面保留,Phase 1 期間可作為 Stage 內部呼叫
- `BaseModelManager` Singleton 不動,只加 GPU Semaphore
- `ModelPool` 直接拿來用,不改介面
- 最終輸出沿用 `ProcessorResult` Pydantic 格式,下游無感

### 6.5 風險自動處理

- **單一 asset 失敗不影響其他**:Stage 內 try/except,錯誤寫進 context,AssemblyStage 統一輸出 error 結果
- **資源不會踩爆**:Worker Pool 上限固定 + ModelPool Queue 自然 backpressure + GPU Semaphore 限同卡併發
- **VRAM 不堆疊**:Singleton 模型共享,N 個 asset 不會載 N 份 Qwen

---

## 7. Layer 4:觀測層

### 7.1 ProgressTracker(Observer Pattern)

每個 Stage 開始/結束時發 event,Observer 訂閱。FastAPI 新增 WebSocket 端點 `/ws/progress/{job_id}`,前端訂閱後可即時顯示「asset × stage」的進度矩陣。

設計重點:
- Observer 失敗只影響該 observer,**絕對不阻斷流水線**
- Tracker 為廣播模式,可同時推播至 log、metrics、WebSocket
- 啟用為可選,單元測試或 CLI 場景可不接 observer

### 7.2 延伸用途

同一套 ProgressTracker 介面未來可接:
- 結構化 log(取代現有 print)
- Prometheus metrics
- 失敗事件告警

---

## 8. Layer 5:前端 Asset Management UI

### 8.1 路由與位置

- 新增路由 `/projects/{project_id}/assets`
- 從 Project List 頁面點 project 卡片進入
- 取代現有「直接觸發生成」流程,改成「先審閱 → 選策略 → 觸發生成」

### 8.2 頁面元素

**Asset 卡片網格**:
- 縮圖(圖片直接顯示、影片顯示中間幀,Layer 0 同步時順手產出 thumb)
- 卡片資訊:檔名、大小、上傳時間、處理狀態
- **策略切換器**:Simple ⇄ Complex toggle(預設 Simple)
- 處理狀態:未處理 / 處理中 / 成功 / 拒絕(技術分過低)/ 失敗

**篩選與批量操作**:
- 篩選:只看影片 / 只看圖片 / 只看未處理 / 只看失敗
- 全選 / 反選
- 一鍵「全選設 Complex」「全選設 Simple」

**重新分析按鈕**:
- 「重新分析選中」:對勾選的 asset 強制重跑 Phase 1
- 「重新分析全部」:整個 project 重跑
- 用途:量化/模型升級、之前失敗想重試、想重新審視 metadata

**策略變更自動重跑**:
- User 把某張 asset 從 Simple 改成 Complex(或反之),自動標記為 `strategy_dirty`
- 下次按「開始生成」時,dirty 的 asset 會自動重跑 Phase 1(用新策略),非 dirty 沿用既有 metadata
- 比手動按重新分析更自然,避免 user 忘記重跑

**進度區塊(連動 Layer 4 WebSocket)**:
- 處理中的 asset 卡片顯示當前 Stage(例如「分析中:semantic」)
- 頁面頂部進度條:已完成 N / 總 M

**觸發按鈕**:
- 底部固定「開始生成」按鈕
- 點擊時打包 `{asset_strategies: {asset_id: strategy, ...}}` 送後端
- WebSocket 推播即時更新

### 8.3 後端 API 變更

- `GET /api/projects/{id}/assets` — 列出所有 asset 與當前狀態
- `POST /api/projects/{id}/generate` — 接受 `asset_strategies`(取代/擴充現有 `/api/director/generate`)
- `POST /api/projects/{id}/reanalyze` — 接受可選 `asset_ids`,強制重跑 Phase 1(None = all)
- `PATCH /api/projects/{id}/assets/{asset_id}/strategy` — 更新單一 asset 策略,標記 dirty

### 8.4 視覺設計原則

- 縮圖網格仿 Apple Photos / Google Photos 的密集排列
- 策略切換明顯但不搶眼(右下角小 badge,點擊切換)
- 失敗/拒絕 asset 在卡片用色塊與圖示明示原因

---

## 9. 背景預跑策略

關鍵體驗設計:**user 寫 prompt 的時間就是後端跑 phase 的時間**,user 按下「生成」後等待時間最小化。

### 9.1 各 Phase 是否可預跑

| Phase | 觸發時機 | 依賴 prompt? | 可預跑 |
|---|---|---|---|
| Phase 1(Per-asset 分析) | Asset 上傳到 Drive | 不依賴 | ✅ 可 |
| Phase 2(Template DNA) | User 選 template | 不依賴 | ✅ 可 |
| Phase 3(Music Search) | User 按生成 | **依賴**(從 prompt 萃取搜尋詞) | ❌ 不可 |
| Phase 4(Director Brain) | User 按生成 | 依賴 | ❌ 不可 |

### 9.2 Phase 1 自動背景化(本計畫範圍)

由 Layer 0 自然驅動:

```
Asset 上傳到 Google Drive
        ↓ 5 分鐘內偵測到新檔案
Phase 1 Pipeline 自動背景跑(user 完全無感)
        ↓
Asset metadata 預先就緒
        ↓
User 寫 prompt + 設定策略
        ↓ 按「生成」
Phase 2/3/4 跑(Phase 1 已完成)
```

### 9.3 Phase 2 也可預跑(未來擴展)

Template 與 prompt 無關(template 本身就是參考影片),user 在 Asset Management 頁面選定 template 的瞬間,後端可立刻背景啟動 Phase 2(Template DNA 萃取)。

User 按「生成」時若 Template DNA 已就緒,Phase 4 直接取用。

### 9.4 Phase 3 必須等 prompt

Phase 3 的搜尋詞需要從 user prompt 的語意推導(例如「歡樂家庭聚會」→ 上揚輕快音樂)。雖然「音樂策略」(search_copyright / search_free / none)可以預選,但**實際執行必須等 user 按生成**。

### 9.5 注意事項

- **User 改主意**:取消前一次背景任務(Task Cancellation),重新啟動
- **失敗顯式化**:Phase 3 yt-dlp 失敗時前端要明示「找不到音樂,要不要換策略」,而不是靜默 fallback
- **背景任務生命週期**:與 project session 綁定,user 離開頁面或關閉專案時取消所有相關背景任務

### 9.6 為什麼 Phase 2/3 不放進 MediaProcessor Pipeline 內

- Phase 2/3 都是 N=1 單一任務,沒有「N 個並行流動」的紅利
- Pipeline framework 的紅利來自 per-asset 並行,拆 Stage 反而增加複雜度
- **正確抽象層次**:Pipeline framework 服務 Phase 1 的 N-asset 場景,`WorkflowOrchestrator`(未來)服務 Phase 1/2/3 上層編排

### 9.7 預留擴展點

本計畫的 ExecutorRegistry / ProgressTracker / GPU Capacity Manager **故意設計為通用**,不綁定 asset 概念。未來新增 `WorkflowOrchestrator` 薄層即可接入 Phase 2 背景預跑與 Phase 3 主流程編排:
- Phase 2 Gemini call 走既有 API Pool
- Phase 3 yt-dlp 走既有 IO Pool
- Phase 2/3 進度也走同一個 ProgressTracker,前端 lane 顯示

---

## 10. Worker Pool 大小建議

所有數字進 `config/pipeline_config.py`,從預設開始,壓測後依 `nvidia-smi` 與 CPU 利用率調整。

| Pool | 預設值 | 上限 | 限制因素 |
|---|---|---|---|
| IO Pool | `min(8, cpu_count)` | 16 | FFmpeg subprocess 也吃 CPU |
| CPU Pool | `cpu_count // 2` | `cpu_count` | numpy/cv2 釋放 GIL,但 context switch 仍有成本 |
| GPU Pool | GPU 數 × 2 | GPU 數 × 3 | GPU Semaphore 鎖住同卡只能一個 inference,multiplier 大只是讓 CPU 預處理重疊,效益遞減 |
| API Pool(Gemini) | 4 | 看付費等級 | Free tier 15 RPM → 1–2 並發;Pro tier 360 RPM → 8 |
| Asset Driver Pool(`max_assets_parallel`) | 4 | 8 | 每 asset 解碼後 PIL/numpy 約 50–200MB,4 個約 1GB RAM |

**共用 GPU 場景特別建議**:
- IO / CPU Pool 可拉到上限(不會與其他人爭)
- GPU Pool 走 GPU Capacity Manager 動態決定,不寫死
- Asset Driver Pool 設 4–6,平衡 RAM 與並行度

**調校訊號**:
- GPU 利用率 < 70% → 加 Asset Driver Pool
- CPU 利用率 < 50% → 加 CPU Pool
- 出現 OOM → 減 GPU multiplier 或加 GPU safety buffer

---

## 11. 業界對照:這套設計叫什麼

本計畫的架構在業界有成熟術語與類似產品,不是憑空發明:

| 本計畫元件 | 業界術語 | 代表產品 |
|---|---|---|
| Stage + StageGroup + Pipeline | Dataflow Execution / Stage Pipeline | Ray Data, NVIDIA DALI, Apache Beam |
| Asset 間並行 + 群組內並行 | Hybrid Parallelism | Ray Data |
| ExecutorRegistry 依資源類型路由 | Heterogeneous Resource Scheduling | Ray Core, Slurm |
| BatchCollector(Dynamic Batching) | Dynamic / Adaptive Batching | NVIDIA Triton, vLLM |
| ModelPool 多 GPU 共享 | Model Replication / Data Parallelism | TorchServe, Ray Serve |
| ProgressTracker | Observability Layer / Event Streaming | OpenTelemetry, Prometheus |

**一句話定位**:本設計 = **單機版的 Ray Data + Triton Dynamic Batching + Eager Warm Up**,專為「N 個 asset 異質工作負載(IO/CPU/GPU/API 混合)」的 batch 場景設計。

**為什麼不直接用 Ray Data 或 Triton**:
- Ray cluster runtime 對單機小專案 overkill
- 既有 `BaseModelManager` Singleton + ModelPool 設計要重新適配 Ray Actor 模型,工程成本高
- Triton 是線上 inference server,不是 batch processing pipeline
- 自己寫薄層更貼合既有架構,且未來真要分散式仍可平滑升級到 Ray

---

## 12. 預期效益總覽

| 場景 | 現況 | 只做架構層 | 只做模型層 | 完整方案 |
|---|---|---|---|---|
| 10 asset / 單 GPU | 303s | 120s(2.5x) | 90s(3.4x) | **60s(5x)** |
| 10 asset / 雙 GPU | 303s | 75s(4x) | 60s(5x) | **35s(8.7x)** |
| 含 Complex 影片 / 雙 GPU | ~600s | ~150s(4x) | ~120s(5x) | **~80s(7.5x)** |

完整方案的關鍵:**模型層提供的是 Qwen 主瓶頸的直接砍,架構層提供的是其他資源的重疊,兩者乘法疊加**。

---

## 13. 與其他方案的對照

| 面向 | A. 純架構 Pipeline | B. 純模型優化 | C. 整合方案(本計畫) |
|---|---|---|---|
| 絕對速度(10 asset 單卡) | 120s(2.5x) | 90s(3.4x) | **60s(5x)** |
| 絕對速度(10 asset 雙卡) | 75s(4x) | 60s(5x) | **35s(8.7x)** |
| 加新 Stage 成本 | 低 | 高 | 低 |
| 加新處理類型(例如音樂分析) | 低 | 高 | 低 |
| 多 GPU 擴展 | 線性 | 線性 | **超線性**(兩者疊加) |
| 觀測能力 | 高 | 無 | 高 |
| OOM 安全性 | 低 | 高 | **高** |
| 研究室共用 GPU 適應性 | 弱 | 弱 | **強**(Capacity Manager) |
| 雲端 URL 下載擴展 | 中 | 低(Queue 不利) | 中(Layer 0 獨立) |
| 量化模型品質風險 | 無 | 有 | 有(Week 1 先驗證) |
| 開發工時 | 7–12 天 | 5–8 天 | 12–18 天(分週) |
| 維護成本 | 低 | 中 | 中 |

選擇 C 的理由:研究室共用 GPU + 需要持續演進 + 要進度條,A 的擴展性與 B 的速度紅利缺一不可。

---

## 14. 風險清單與緩解

| 風險 | 緩解 |
|---|---|
| 4-bit 量化品質下降 | Week 1 先單獨驗證 caption / mood / scene_tags 與 8-bit 版本的差異,不通過則退回 |
| Flash Attention 安裝失敗 | 加可選旗標,失敗時 fallback 到預設 attention |
| Batch padding 拖慢(小模型沒受益) | 各模型 batch 大小走 config,壓測決定;單張仍可走原路徑 |
| 雙 GPU Qwen Pool 在單卡環境出錯 | `detect_gpu_ids()` 偵測到單卡時自動關閉雙 Qwen 設定 |
| 群組內 Stage 寫入 context 同欄位衝突 | PipelineBuilder 編排階段保證群組內欄位互斥 |
| Gemini API 429 | APIExecutor Semaphore 限併發 |
| WebSocket 斷線拖累工作流 | Observer 失敗隔離,不阻斷 Scheduler |
| Google Drive OAuth token 過期 | 通知 user 重新授權,該 workspace 暫停同步,其他 workspace 不受影響 |
| Eager warm up 拖慢後端啟動 | 啟動進度透過 ProgressTracker 推播,前端顯示「後端啟動中」;開發環境可關閉 |

---

## 15. 落地節奏與驗證方式

### 15.1 漸進落地節奏(一次到位但分週驗證)

**Week 1** ✅ **已完成(2026-05-30,commit `51ef717` + `43a8d10`)**:Layer 1 模型層獨立優化
- ✅ Qwen 4-bit 量化(最終採 **bitsandbytes NF4**,實測 runtime 6.4GB;原 cyankiwi AWQ 在 transformers 解壓不省 VRAM 已棄用)+ Flash Attention 2,實機生效
- ✅ GpuGate(BinaryGate)加入 → 修 OOM bug;Singleton key 改 tuple、ModelPool slots 介面備好 Week 3b
- ✅ MUSIQ/LAION/Whisper batch 方法、ProgressTracker 介面、gpu_gate.py 全部就緒
- 舊版迴圈仍可用,`QWEN_USE_4BIT=false` 可切 bnb 8-bit 測品質差異
- ⬜ 待跑:品質回歸 A/B、單張計時、50-asset 同卡 OOM 驗證

**Week 2**:Layer 2 + Layer 3 架構底座
- ExecutorRegistry + ModelPool Registry + Pipeline + StageGroup + HybridScheduler
- Stage 拆解,把現有 `process()` 邏輯搬到對應 Stage
- Early Rejection 短路機制
- 替換 `director_service.py` 呼叫端

**Week 3**:Layer 1 batch + Layer 4 觀測
- MUSIQ / LAION / Whisper batch scoring 接入對應 Stage(Dynamic Batching)
- 雙 GPU Qwen Pool 啟用
- ProgressTracker + WebSocket
- 端到端壓測

**Week 4**:Layer 0 + Layer 5
- Google Drive `drive.file` OAuth 接入
- Workspace → Project 自動偵測 + polling
- 前端 Asset Management UI

### 15.2 驗證方式

1. **品質回歸**:同一組 asset 用舊版與新版各跑一次,比對 `phase1_assets_metadata.json` 欄位差異;4-bit 量化帶來的 caption 文字微差可接受,但 `technical_score` / `subject_bbox` / `scene_cuts` 等結構化欄位必須一致
2. **效能驗證**:同一組 asset(5 圖 + 5 影,含 1 個 Complex)計時,單卡須達 4x 以上、雙卡須達 7x 以上
3. **GPU 安全驗證**:故意把 Qwen + Whisper 設同卡,跑 50 個 asset 確認不再 OOM(驗證 GPU Semaphore 生效)
4. **進度推播驗證**:WebSocket 客戶端訂閱,觀察事件流是否完整覆蓋所有 asset 與 stage
5. **韌性驗證**:放入 corrupt 圖片,確認該 asset 標記為 error 但其他 asset 完成
6. **下游相容性**:跑完 Phase 1 後,Phase 2-4(Template DNA、Director Brain、Blueprint)須能正常產出
7. **多 GPU 偵測**:切換 `CUDA_VISIBLE_DEVICES` 驗證 ModelPool 大小自動調整
8. **共用 GPU 偵測**:用 stress test 工具佔 GPU 部分 VRAM,確認 GPU Capacity Manager 偵測到並避開該卡或降級
9. **雲端同步驗證**:對 Google Drive workspace 上傳新檔案,5 分鐘內確認後端偵測到並觸發 Phase 1
10. **前端 UI 驗證**:策略勾選後送出生成請求,WebSocket 進度即時更新

---

## 16. 關鍵核心檔案

落地時的主要接觸點(其餘皆為新增模組):

| 檔案 | 改動類型 | 說明 |
|---|---|---|
| `backend/services/director_service.py` | 修改(Week 2a) | 呼叫端替換,L92 序列迴圈改為 `PipelineRunner.run(...)` |
| `model/base_model_manager.py` | ✅ Week 1 已改 | GpuGate(L2)整合 + Singleton key 改 `(device_id, slot_id)` + `register_gate_factory()` |
| `model/gpu_gate.py` | ✅ Week 1 新增 | `GpuGate` ABC + `BinaryGate`(Week 3b 加 `BudgetGate`) |
| `model/qwen_model_manager.py` | ✅ Week 1 已改 | **bnb 4-bit NF4** + FA2 fallback + device_map 鎖定 + `apply_chat_template` 推理 |
| `model/musiq_model_manager.py` | ✅ Week 1 已改 | 新增 `score_batch()`(未接入) |
| `model/laion_model_manager.py` | ✅ Week 1 已改 | 新增 `score_batch()`(未接入) |
| `model/whisper_model_manager.py` | ✅ Week 1 已改 | 新增 `transcribe_batch()`(未接入) |
| `model/model_pool.py` | ✅ Week 1 已改 | 新增 `slots`/`GpuSlot` 介面,`gpu_ids` 保留 alias |
| `model/mediapipe_model_manager.py` | ✅ 2026-06-01 改 | legacy `mp.solutions` → Tasks `FaceDetector`(0.10.22+ wheel 缺 solutions) |
| `model/audio_env_model_manager.py` | ✅ 2026-06-01 改 | 修 `inference()` 回傳順序(CNN14 embedding 索引越界) |
| `media_processor/pipeline/progress.py` | ✅ Week 1 新增 | ProgressObserver/Tracker/Event + PrintObserver |
| `config/media_processor_config.py` | ✅ Week 1 已改 | batch size / GPU buffer / `QWEN_USE_4BIT_DEFAULT` 量化切換常數 |
| `config/model_config.py` | ✅ Week 1 已改 | Qwen 官方 base id + `QWEN_USE_4BIT` flag + mediapipe Tasks 模型常數 |
| `docs/lock_design.md` | ✅ Week 1 新增 | L1/L2/L3 鎖層級完整設計 |
| `media_processor/abstract_image_processor.py` | 邏輯沿用(Week 2b) | 內部方法搬到對應 Stage |
| `media_processor/abstract_video_processor.py` | 邏輯沿用(Week 2c) | 內部方法搬到對應 Stage |
| `media_processor/pipeline/`(其餘) | 新增(Week 2a+) | Stage / Pipeline / Executor / Scheduler 模組樹 |
| `config/pipeline_config.py` | 新增(Week 2a) | 集中所有併發/timeout 常數 |
| `model/gpu_capacity_manager.py` | 新增(Week 3b) | VRAM 偵測 + `BudgetGate` |
| `backend/api/progress.py` | 新增(Week 3c) | WebSocket 進度端點 |
| `backend/api/workspaces.py` | 新增(Week 4a) | Google Drive workspace 管理 API |
| `ingestion_engine/` | 新增(Week 4a) | Layer 0 攝取模組(rclone + Google Drive polling) |
| `frontend/src/pages/AssetListPage.tsx` | 新增(Week 4b) | Layer 5 前端 UI |

---

*文件最後更新:2026-05-31*
