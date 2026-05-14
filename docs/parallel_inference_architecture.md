# 並行推論架構設計筆記

> 這份文件記錄了 model 層的加速策略與多 GPU 架構設計。
> 文件撰寫時，程式碼尚未實作，供日後開發前閱讀。

---

## 目錄

1. [現狀分析：為什麼目前慢](#1-現狀分析)
2. [各 Model 的 Batch 支援能力](#2-各-model-的-batch-支援能力)
3. [建議架構：4 階段 Pipeline](#3-建議架構4-階段-pipeline)
4. [Stage 3 加速：Qwen VLM](#4-stage-3-加速qwen-vlm)
5. [GPU-level Semaphore（安全多模型共 GPU）](#5-gpu-level-semaphore)
6. [動態 GPU 共用：Stage 4 閒置幫 Stage 3](#6-動態-gpu-共用)
7. [VRAM 預算試算](#7-vram-預算試算)
8. [建議實作順序](#8-建議實作順序)

---

## 1. 現狀分析

### 目前 ImageProcessor 的執行流程（一張圖）

```
Saliency (CPU/ONNX)  ≈ 200ms
    ↓
MUSIQ scoring (GPU)  ≈ 200ms   ← 可以 batch，變成 30ms/張
    ↓
LAION scoring (GPU)  ≈ 200ms   ← 可以 batch
    ↓
Early rejection gate（tech_score < 40）
    ↓
Qwen VLM (GPU)       ≈ 5000ms  ← 慢 10–20 倍，每張圖都要跑
```

**核心問題：** 不同 stage 的速度差距達 10–20 倍，卻綁在同一條執行路徑。
即使有 multithread，每個 thread 都要等自己的 Qwen 跑完。

### 現有架構的鎖機制

目前有兩層鎖：

| 鎖 | 位置 | 守護的資源 |
|---|---|---|
| `_creation_lock` | class 層級，每個 subclass 一把 | 建立 singleton 時防止 race condition |
| `_inference_lock` | instance 層級，每個 (model, device_id) 一把 | 防止同一 model instance 被多個 thread 同時呼叫 |

**現有架構的盲點：**  
`_inference_lock` 只知道「自己的 model 有沒有在跑」，不知道「同一張 GPU 上其他 model 有沒有在跑」。
若把 Qwen 和 Whisper 放在同一張 GPU，它們可以同時持有各自的 `_inference_lock`，導致 VRAM OOM。

---

## 2. 各 Model 的 Batch 支援能力

| Model | 底層是否支援 Batch | 實作難度 | 說明 |
|---|---|---|---|
| `MusiqModelManager` | ✅ | 低 | PyIQA 接受 `[B, C, H, W]`，需統一圖片尺寸 |
| `LaionModelManager` | ✅ | 低 | CLIPProcessor 直接接 list，MLP 支援 batch |
| `WhisperModelManager` | ✅ | 中 | HuggingFace pipeline 接受路徑 list，後處理需改寫 |
| `AudioEnvModelManager` | ✅ | 中 | GPU 部分可 batch，librosa 讀檔仍需序列 |
| `QwenModelManager` | ⚠️ | 高 | 技術可行，但 VLM padding 複雜，見 Section 4 |
| `SaliencyModelManager` | ❌ | — | rembg API 僅支援單張，無解 |
| `VadModelManager` | ❌ | — | Silero VAD utility 僅支援單筆音訊，無解 |
| `GeminiModelManager` | ❌ | — | 雲端 API，無 GPU batch 概念 |

---

## 3. 建議架構：4 階段 Pipeline

### 架構示意圖

```
[原始媒體檔案列表]
        │
        ▼
┌───────────────────────────────┐
│  Stage 1：Ingestion           │  CPU ThreadPool（4–8 workers）
│  讀檔、EXIF、ffmpeg decode    │  I/O bound，可大量並行
│  影片：分離音軌、burn timecode │
└──────────────┬────────────────┘
               │ Queue（有上限，防 RAM 爆炸）
               ▼
┌───────────────────────────────┐
│  Stage 2：Fast Filter         │  GPU Batch（1–2 workers）
│  MUSIQ + LAION batch scoring  │  一次處理 16–32 張
│  Saliency 可在 CPU 並行       │
│  未過門檻 → 直接輸出 rejected │  ← 省掉 30–50% 的 VLM 呼叫
└──────────────┬────────────────┘
               │ Queue（只有通過的檔案）
        ┌──────┴──────┐
        ▼             ▼
┌──────────────┐ ┌──────────────────────┐
│  Stage 3     │ │  Stage 4             │
│  VLM 分析    │ │  Audio 分析          │
│  Qwen/Gemini │ │  VAD → Whisper       │
│              │ │  → AudioEnv          │
│  ModelPool   │ │  ModelPool           │
│  每張 GPU    │ │  每張 GPU            │
│  一個 Qwen   │ │  一套音訊 models     │
└──────┬───────┘ └──────────┬───────────┘
       │                     │
       └──────────┬──────────┘
                  ▼
            [Result Queue]
            收集、寫入資料庫
```

### 各 Stage 的並行策略

| Stage | 並行方式 | 瓶頸 |
|---|---|---|
| Stage 1 | ThreadPoolExecutor（CPU）| 磁碟 I/O |
| Stage 2 | GPU batch，一次多張 | GPU 吞吐量 |
| Stage 3 | ModelPool 跨 GPU | Qwen forward pass |
| Stage 4 | ModelPool 跨 GPU | Whisper decode 長度 |

### Stage 2 Early Rejection 的價值

假設 100 張圖，30% 因畫質不足被 reject：

- **現在**：100 張全跑 Qwen → 100 × 5s = 500s
- **加 Stage 2**：70 張跑 Qwen → 70 × 5s = 350s（省 30%）
- **加 Stage 2 + Batch Scoring**：Stage 2 耗時 < 2s，幾乎不影響總時間

### Stage 間的 Queue 設計

每個 Queue 應設上限（bounded queue），防止 Stage 1 跑太快把 RAM 塞滿：

```pseudocode
ingestion_queue  = Queue(maxsize=50)   # Stage 1 → Stage 2
filtered_queue   = Queue(maxsize=20)   # Stage 2 → Stage 3/4
result_queue     = Queue(maxsize=100)  # Stage 3/4 → 輸出
```

---

## 4. Stage 3 加速：Qwen VLM

加速方向依實作難度由低到高排列：

### 4.1 Flash Attention（難度：低，預期加速 1.5–2x）

在 `from_pretrained` 加一個參數。需安裝 `flash-attn` 套件。

```pseudocode
model = from_pretrained(
    model_id,
    attn_implementation = "flash_attention_2",  ← 加這個
    ...
)
```

對長 token 序列（大圖、高解析度）效果最顯著。同時降低 VRAM 峰值。

### 4.2 4-bit AWQ 量化（難度：低，預期加速 1.5–2x，VRAM 砍半）

Qwen 官方提供 AWQ 量化版本，品質幾乎不降。

```pseudocode
# 原本
model_id = "Qwen/Qwen3-VL-8B-Instruct"       # 8-bit BnB, ~10GB VRAM

# 換成
model_id = "Qwen/Qwen3-VL-8B-Instruct-AWQ"   # 4-bit AWQ, ~5GB VRAM
# 移除 BitsAndBytesConfig，HuggingFace 自動識別 AWQ 格式
```

**這是最重要的一步**，因為省下的 VRAM 讓以下 Section 6 的 GPU 共用變得可行。

### 4.3 Small Batch Inference（難度：中，預期吞吐量 1.5–3x）

Qwen-VL 支援 batch，但每張圖的 image token 數不同，需要 padding 對齊。

```pseudocode
# 目前：一次一張
input = processor([single_message])
output = model.generate(input)

# Batch：一次 2–4 張
inputs = processor([msg1, msg2, msg3, msg4])   # padding 自動處理
outputs = model.generate(inputs)               # 一次 forward pass 出 4 個結果
```

注意事項：
- `max_pixels` 設定限制了每張圖的 token 上限，使 padding overhead 可控
- Batch size 受 VRAM 限制：4-bit AWQ 下可 batch 2–3 張，8-bit 下通常只能 1–2 張
- Batch inference 的速度提升不是線性的（padding overhead），實際需要壓測

### 4.4 vLLM（難度：高，預期加速 3–5x）

vLLM 是目前 LLM 推論最快的開源框架，透過 PagedAttention 和 continuous batching 大幅提升 GPU 利用率。支援 Qwen-VL。

架構改動：
```pseudocode
# 原本：直接載入模型
QwenModelManager → 持有 model weights in memory

# 換成：client-server 架構
vLLM Server（獨立 process）← 持有 model weights
QwenModelManager → 改成對 vLLM server 發 HTTP request
```

優點：PagedAttention 大幅減少 VRAM 碎片，continuous batching 自動把多個請求合批。  
缺點：需要維護一個獨立的 vLLM server process，架構複雜度提升。

### 加速方向對比

| 方向 | 預期加速 | VRAM 變化 | 實作複雜度 | 建議優先順序 |
|---|---|---|---|---|
| Flash Attention | 1.5–2x | 略降 | 低 | 1 |
| 4-bit AWQ | 1.5–2x | -50% | 低 | 2 |
| Small Batch | 1.5–3x | 需更多 | 中 | 3 |
| vLLM | 3–5x | 更少碎片 | 高 | 4（視需求） |

---

## 5. GPU-level Semaphore

### 為什麼需要

**現有鎖的盲點（隱藏的 OOM bug）：**

假設 GPU 1 上同時部署了 Whisper 和 Qwen：

```
Thread A：Whisper._inference_lock 拿到 → Whisper 正在推論
Thread B：Qwen._inference_lock 拿到    → Qwen 也在推論

兩個 forward pass 同時佔用 GPU 1 的 VRAM → OOM 💥
```

`_inference_lock` 只保護「同一個 model 不被重入」，不保護「同一張 GPU 不被多個 model 同時佔用」。

### 解法：在 `_inference_lock` 之上加一層 GPU Semaphore

```pseudocode
# 全局結構：每張 GPU 一個 Semaphore
GPU_SEMAPHORES = {
    0: Semaphore(1),   # GPU 0 同時只允許一個 forward pass
    1: Semaphore(1),   # GPU 1 同時只允許一個 forward pass
    ...
}
```

```pseudocode
# synchronized_inference 修改後的邏輯
def synchronized_inference(method):
    def wrapper(self, *args):
        gpu_sem = GPU_SEMAPHORES[self._device_id]   # 先拿 GPU 層鎖
        with gpu_sem:
            with self._inference_lock:               # 再拿 model 層鎖
                return method(self, *args)
    return wrapper
```

### 鎖的層次結構

```
GPU Semaphore（GPU 層）
    └── _inference_lock（model 層）
            └── 實際的 forward pass
```

取得順序永遠由外到內，釋放由內到外，不會 deadlock。

### 效果

```
Thread A：Whisper 想用 GPU 1 → 拿到 GPU 1 Semaphore → 推論中
Thread B：Qwen 想用 GPU 1   → 等 GPU 1 Semaphore ⏳

Thread A 推論完成（含 empty_cache）→ 釋放 GPU 1 Semaphore
Thread B：拿到 GPU 1 Semaphore → 開始推論 ✓
```

不同 GPU 的 Semaphore 互相獨立，GPU 0 的 Qwen 不受 GPU 1 的 Whisper 影響。

### 實作位置

修改 `model/base_model_manager.py`，在模組頂層加入 `GPU_SEMAPHORES` dict，並修改 `synchronized_inference` 裝飾器的邏輯。改動範圍小，不影響所有 model manager 的介面。

---

## 6. 動態 GPU 共用

### 目標

Stage 4（音訊分析）完成後，GPU 1 閒置。
讓 GPU 1 的 Qwen instance 接受 Stage 3 的任務，增加 Qwen 的整體吞吐量。

### 前提條件

1. **GPU-level Semaphore 已實作**（Section 5）
2. **Qwen 預先載入到兩張 GPU**（啟動時就做，不在 Stage 4 結束時才做）
3. **Qwen pool 包含兩張 GPU**

### 設計

```pseudocode
# 啟動時建立
qwen_pool    = ModelPool(QwenModelManager, gpu_ids=[0, 1])
audio_models = {
    "whisper": WhisperModelManager(device_id=1),
    "vad":     VadModelManager(device_id=1),
    "env":     AudioEnvModelManager(device_id=1),
}

# Stage 3 worker：從 pool 借用 Qwen，自動負載均衡
def stage3_worker(file):
    with qwen_pool.borrow() as qwen:
        return qwen.analyze_media(file)

# Stage 4 worker：使用固定在 GPU 1 的音訊 models
def stage4_worker(file):
    has_speech = audio_models["vad"].has_speech(file)   # 拿 GPU 1 Semaphore
    if has_speech:
        transcript = audio_models["whisper"].transcribe(file)  # 排隊等 GPU 1 Semaphore
    ...
```

### 執行時序（Stage 4 閒置時）

```
時間軸 →

GPU 0: [Qwen img1][Qwen img2][Qwen img3]...
GPU 1: [Whisper][VAD][  閒置  ][Qwen img4][Qwen img5]...
                      ↑
                Stage 4 結束，GPU 1 Semaphore 釋放
                Qwen pool 的 GPU 1 instance 被 Stage 3 借走
```

Stage 4 一結束，GPU 1 立刻轉投 Stage 3，不需要任何手動切換。

### 為什麼必須在啟動時預載 Qwen

Qwen-VL 8B 的模型載入需要 20–60 秒。若等 Stage 4 結束才開始載入，等待時間已超過大部分音訊的處理時間，完全沒有收益。

---

## 7. VRAM 預算試算

### 雙 GPU 配置（GPU 0 主視覺、GPU 1 音訊 + 補充視覺）

| GPU | 常駐 Models | 8-bit VRAM | 4-bit AWQ VRAM |
|---|---|---|---|
| GPU 0 | Qwen + MUSIQ + LAION + CLIP | ~13 GB | ~8 GB |
| GPU 1 | Qwen + Whisper + AudioEnv + VAD | ~14 GB | ~9 GB |

MUSIQ 和 LAION 各約 0.5–1 GB，Whisper large-v3 約 3 GB，AudioEnv (Whisper-tiny) 約 0.5 GB。

**結論：**
- 8-bit Qwen：需要 16GB+ GPU × 2
- 4-bit AWQ Qwen：12GB GPU 即可，24GB GPU 綽綽有餘

### 單 GPU 配置

| 常駐 Models | 8-bit VRAM | 4-bit AWQ VRAM |
|---|---|---|
| 全部 | ~17 GB | ~12 GB |

單 GPU 下 GPU-level Semaphore 會讓所有 model 序列化，但 Stage 1（CPU I/O）仍可並行，Stage 2 batch 仍有效益，Early rejection 仍節省 VLM 呼叫。

---

## 8. 建議實作順序

### Phase 1：低風險、立竿見影（不改架構）

1. **Qwen Flash Attention**：一行參數，需安裝 `flash-attn`
2. **Qwen 4-bit AWQ**：換 model_id，移除 BitsAndBytesConfig
3. **MUSIQ `score_batch()`**：新增方法，現有 `get_technical_score()` 保留向後相容
4. **LAION `score_batch()`**：同上

### Phase 2：加入 GPU-level Semaphore（安全基礎）

5. **`GPU_SEMAPHORES` + 修改 `synchronized_inference`**：改動在 `base_model_manager.py`，影響所有 model，需充分測試

### Phase 3：Pipeline 架構（最大改動）

6. **Stage 2 worker**：使用 batch API，Queue 出入
7. **Stage 3/4 worker**：包裝現有 processor 邏輯
8. **Pipeline 協調器**：建立 Queue、啟動 ThreadPoolExecutor、收集結果

### Phase 4：動態 GPU 共用（在 Phase 2, 3 完成後）

9. **雙 GPU Qwen Pool**：`ModelPool(QwenModelManager, gpu_ids=[0, 1])`
10. **測試 Stage 4 閒置時 GPU 1 能否自動接 Stage 3**

---

*文件最後更新：2026-05-15*
