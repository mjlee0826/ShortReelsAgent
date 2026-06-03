# 推論解析度優化 + Startup Log 補強

> 本文件記錄 Week 3b 後續強化：全熱資料本地化後仍出現的 4K 幀 GIL-freeze 問題的根因分析，
> 以及三層解析度截斷策略與 MediaPipe Pool 補強的實作說明。
> 設計日期：2026-06-04。

---

## 目錄

- [1. 問題背景](#1-問題背景)
- [2. Task 1：StartupReporter 補 CPU aux 模型](#2-task-1startupReporter-補-cpu-aux-模型)
- [3. Task 2：三層推論解析度優化](#3-task-2三層推論解析度優化)
  - [3A. Layer 1 — PIL 720p Cap（所有模型推論幀）](#3a-layer-1--pil-720p-cap所有模型推論幀)
  - [3B. Layer 0 — MediaStandardizer 補 .mp4（上傳時一次性）](#3b-layer-0--mediastandardizer-補-mp4上傳時一次性)
  - [3C. Layer 0.5 — SceneDetect 固定目標解析度](#3c-layer-05--scenedetect-固定目標解析度)
- [4. 三層優化關係總覽](#4-三層優化關係總覽)
- [5. 常見問答](#5-常見問答)

---

## 1. 問題背景

### 1.1 NFS hang（已解決）

Week 3b 期間 faulthandler dead-man（`WATCHDOG_FREEZE_DUMP_SEC=90`）在 90s 抓到：
`SceneDetect cv2.VideoCapture.read()` 卡在 NFS（`/nfs/nas/...`）逐幀讀取。
NFS `hard` mount 下 `cv2.read()` 不釋放 GIL → 整個 Python process 凍住。

**修復**：把所有熱資料（assets / temp_templates / temp_workspaces / model weights）遷移到
本地 `/data1/cache/mjlee/`（詳見程式碼中 `config/app_config.py`）。

### 1.2 4K GIL-freeze（本文件的處理對象）

素材遷到本地後 cv2 不再 hang，但仍出現 90s faulthandler 觸發。根因：
- **4K 原生 `.mp4`（如 iPhone 拍攝）**：media_standardizer 只處理 `.mov/.avi/.mkv/.webm`，
  `.mp4` 以原始 4K（3840×2160）直接進 pipeline。
- **MediaPipe tflite / Saliency ONNX Runtime** 在 4K 幀（~8M pixels）推論期間
  **不釋放 GIL**，導致 Python watchdog 心跳和 faulthandler re-arm 全部暫停，90s 後 dead-man 觸發。
- 相比之下，PyTorch CUDA 推論（Qwen、MUSIQ、LAION）**會釋放 GIL**，所以 Qwen 即使跑 200s 也不會觸發。

### 1.3 為什麼不降 FPS / 不降音訊

| 優化項 | 決策 | 理由 |
|---|---|---|
| FPS 降低 | **不做** | SceneDetect 需要完整 FPS 才不漏短切點；其他 stage 用 POS_MSEC seek，FPS 無關 |
| 音訊降質 | **不做** | AudioExtraction 已 ffmpeg 抽出 16kHz mono WAV；視訊音訊 track 對 pipeline 無影響 |
| `_infer.mp4` 推論副本 | **不做** | 架構複雜（context.file_path 需兩條路徑）；三層截斷已足夠 |

---

## 2. Task 1：StartupReporter 補 CPU aux 模型

### 問題

`StartupReporter._model_section()` 僅讀 `GpuCapacityManager.placement_rows()`，
只含 GPU pool 模型（Qwen / Saliency / MUSIQ / LAION / Whisper / AudioEnv）。
VAD 與 MediaPipe 是 CPU-only aux 模型，warmup 後 pool 已建好但 table 不顯示。

### 解法

在 `media_processor/pipeline/startup_report.py` 的 `_model_section()` 最後追加 CPU 區塊：

```python
from config.pipeline_config import MEDIAPIPE_POOL_SIZE

# GPU 區塊後加虛線分隔，追加 CPU aux 模型
out.append(f"  {'-'*(_W_MODEL+_W_RESIDENT+_W_STATUS+10)}")
out.append(f"  {'VadModelManager':<{_W_MODEL}}{'1':<{_W_RESIDENT}}{'eager':<{_W_STATUS}}cpu")
out.append(
    f"  {'MediaPipeModelManager':<{_W_MODEL}}"
    f"{str(MEDIAPIPE_POOL_SIZE):<{_W_RESIDENT}}"
    f"{'eager':<{_W_STATUS}}cpu×{MEDIAPIPE_POOL_SIZE}"
)
```

> `resident` 欄對 CPU 模型顯示 **instance 數量**（不是 VRAM GB），
> MediaPipe pool 有 `MEDIAPIPE_POOL_SIZE`（= `MAX_ASSETS_PARALLEL` = 16）個 instance。

---

## 3. Task 2：三層推論解析度優化

### 3A. Layer 1 — PIL 720p Cap（所有模型推論幀）

**最核心的一層**：在幀被轉成 PIL Image 後、傳給任何模型前，限制短邊 ≤ 720px。

#### 新常數（`config/media_processor_config.py`）

```python
# 推論用幀解析度上限：短邊超過此值則等比縮放（保留足夠細節讓人臉/主體偵測準確）
INFERENCE_MAX_SHORT_SIDE: int = 720
```

#### 新工具函式（`media_processor/pipeline/stages/video_frame_utils.py`）

```python
def cap_pil_resolution(img: Image.Image, max_short_side: int = INFERENCE_MAX_SHORT_SIDE) -> Image.Image:
    """短邊超過 max_short_side 時等比縮放（推論用，不影響輸出品質）。"""
    w, h = img.size
    short = min(w, h)
    if short <= max_short_side:
        return img
    scale = max_short_side / short
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
```

#### 套用位置（兩個解碼入口，覆蓋所有下游 stage）

| 素材類型 | 改動位置 | cap 發生時機 | metadata 來源（不受影響）|
|---|---|---|---|
| 視訊代表幀 | `grab_frame_at_time()` 回傳前 | cv2→PIL 轉換後立即 cap | `cv2.CAP_PROP_FRAME_WIDTH/HEIGHT` |
| 視訊 saliency 幀 × N | 同上（同一函式） | 同上 | — |
| 圖片 | `decode_image_stage.py:run()` | `Image.open()` 後、存入 Work 前 | `pil.size`（在 cap **前**取） |

`grab_frame_at_time()` 是所有視訊幀的唯一出口——DecodeVideoStage 的代表幀、
SaliencyUnion 的頭/中/尾三幀、EventBbox 的 N 個事件幀全走此函式，改一處全部受益。

`decode_image_stage.py` 中，`width/height` 取自 cap 前的原始 PIL，不受 resize 影響，
確保 `ImageWork.width/height` 仍反映原始解析度。

---

### 3B. Layer 0 — MediaStandardizer 補 `.mp4`（上傳時一次性）

**問題**：目前只轉 `.mov/.avi/.mkv/.webm`；原生 `.mp4`（4K iPhone 等）完全不經縮放直接進 pipeline。

**改 `media_tools/media_standardizer.py`**：

```python
# 舊：if ext in [".mov", ".avi", ".mkv", ".webm"]:
# 新（排除已有 _std 的檔案，避免 _std_std）：
if ext in [".mov", ".avi", ".mkv", ".webm"] or (ext == ".mp4" and "_std." not in filename):
```

沿用完全相同的 ffmpeg 指令（含 `scale=1920:1920:force_original_aspect_ratio=decrease`）：
- 所有視訊進 pipeline 前長邊已壓到 ≤ 1920px
- `director_service._collect_asset_files()` 的「有 `_std` 就跳原檔」邏輯自動生效

> 這一層是「上傳時做一次」：後續重跑 pipeline 不需要再 transcode（`_std.mp4` 已存在則跳過）。

---

### 3C. Layer 0.5 — SceneDetect 固定目標解析度

SceneDetect 是 pipeline 中**唯一逐幀掃描整部影片**的元件（其他 stage 只 seek 特定幀），
需要獨立的降解析度處理。

`detect()` API 支援 `downscale_factor`（整數倍），但固定倍數在低解析度輸入時可能降到太小。
改為從 VideoWork 的已知 `width/height` 動態計算 factor，確保 SceneDetect 總在目標短邊附近運行。

#### 新常數（`config/media_processor_config.py`）

```python
# SceneDetect 內部處理短邊目標（360px 足夠偵測 content diff；小於此的影片 factor=1 不縮）
SCENE_DETECT_TARGET_SHORT_SIDE: int = 360
```

#### 改 `template_engine/scene_cut_extractor.py`

```python
def get_cuts(self, video_path: str, downscale_factor: int = 1) -> list:
    scene_list = detect(video_path, ContentDetector(threshold=27.0),
                        downscale_factor=downscale_factor)
    cuts = [float(scene[1].get_seconds()) for scene in scene_list]
    return sorted(list(set(cuts)))
```

#### 改 `media_processor/pipeline/stages/scene_cut_stage.py`

從 VideoWork 的 `width/height`（已有，無需重讀 metadata）算出 factor：

```python
from config.media_processor_config import SCENE_DETECT_TARGET_SHORT_SIDE

def run(self, context: AssetContext) -> None:
    work = get_video_work(context)
    short_side = min(work.width, work.height)
    factor = max(1, short_side // SCENE_DETECT_TARGET_SHORT_SIDE)
    try:
        work.scene_cuts = SceneCutExtractor().get_cuts(context.file_path,
                                                        downscale_factor=factor)
    except Exception as e:
        print(f"[SceneCutStage Warning] ...")
        work.scene_cuts = []
```

**效果**：
- 1920×1080 → factor=3 → 360p
- 1280×720 → factor=2 → 360p
- 640×480 → factor=1（不縮，已在目標範圍內）

---

## 4. 三層優化關係總覽

```
上傳
  │
  ▼
[Layer 0] MediaStandardizer
  .mp4/.mov/.avi → _std.mp4（scale=1920 long side cap）
  一次性，後續重跑跳過
  │
  ▼ pipeline reads _std.mp4（≤ 1920px）
  │
  ├─→ [Layer 0.5] SceneDetect
  │     downscale_factor = short_side // 360
  │     內部以 360p 掃全幀（不影響切點時間精度）
  │
  └─→ [Layer 1] grab_frame_at_time / Image.open
        cap_pil_resolution(720p)
        PIL 短邊 ≤ 720px 後送進所有模型
        （MediaPipe tflite / Saliency ONNX / Qwen / MUSIQ / LAION）
```

| Layer | 機制 | 何時生效 | 受益範圍 |
|---|---|---|---|
| 0 | Standardizer 處理 `.mp4` | 上傳時（一次性） | 全部 cv2 讀取、Audio extraction |
| 0.5 | SceneDetect downscale | 每次執行 | SceneCutStage（逐幀掃描） |
| 1 | PIL `cap_pil_resolution(720p)` | 每次執行 | 所有模型推論幀（GIL-freeze 主要修復） |

---

## 5. 常見問答

**Q: resize 後原始檔案會改變嗎？前端畫質會降低嗎？**

不會。Layer 1 的 resize 發生在記憶體裡的 PIL 物件上，不回寫任何檔案。
Layer 0 的 Standardizer 建立新的 `_std.mp4`，原始 `.mp4` 保留不動。
前端透過 `/static` URL serve 的包含原始和 `_std` 兩個版本，都在 ASSETS_DIR 下。

**Q: Qwen inference 跑 200s 會觸發 90s dead-man 嗎？**

不會。PyTorch CUDA 推論在 GPU compute 期間**釋放 GIL**，Python watchdog 心跳每 30s 繼續執行並 re-arm faulthandler dead-man。
你會看到心跳輸出「semantic_video ⚠ 200s」（超過 `STALL_WARN_SEC=120` 標 ⚠），那只是觀察性警告，不影響流程。
只有 `cv2.read on NFS`、`MediaPipe tflite on 4K 幀`、`Saliency ONNX on 4K 幀` 等 C 層不釋放 GIL 的情況才觸發 dead-man。

**Q: SceneDetect 為何不直接用固定倍數（如 downscale_factor=2）？**

固定倍數在高解析度輸入有效但在低解析度反而過度縮小（720p / 2 = 360p 剛好；480p / 2 = 240p 偏小）。
動態計算 `factor = short_side // 360` 確保所有輸入都在 360p 附近，精度一致。

**Q: 為什麼不建立 `_infer.mp4`（720p 推論副本）？**

需要 `context.file_path` 同時持有兩條路徑（render 用高清版、inference 用小版），架構改動較大。
現有三層已覆蓋同等效果：Standardizer 保證進 pipeline 的檔案 ≤ 1920px，PIL cap 保證推論幀 ≤ 720p。
