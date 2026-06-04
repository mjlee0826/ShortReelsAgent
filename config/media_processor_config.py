"""
媒體處理器常數集中管理 (Configuration Object Pattern)。
media_processor/ 與 media_tools/ 所有模組從此處 import，避免 magic number 散落各檔。
"""

# ── 畫質過濾 (ImageProcessor / ContextCompressor) ─────────────────────────────
# MUSIQ 技術畫質分數低於此值的圖片直接 reject，避免模糊/噪點素材進入導演決策
TECHNICAL_SCORE_FILTER_THRESHOLD = 40.0

# ── MUSIQ 視覺評分模型 (MusiqModelManager) ────────────────────────────────────
# 推論前 PIL 圖片的最大短邊長度（過大會吃 VRAM 且分數震盪）
MUSIQ_MAX_INPUT_SIZE = 512

# ── 推論幀解析度上限 (video_frame_utils.cap_pil_resolution) ─────────────────────
# 所有模型推論幀在送入模型前，短邊超過此值即等比縮放（純記憶體 PIL 物件，不回寫檔案）。
# 主要修復 4K 幀的 GIL-freeze：MediaPipe tflite / Saliency ONNX 在 ~8M px 幀推論時不釋放 GIL，
# 會凍住 Python watchdog 心跳與 faulthandler re-arm。720 保留足夠細節讓人臉/主體偵測準確。
INFERENCE_MAX_SHORT_SIDE = 720

# ── 媒體標準化 (MediaStandardizer / FFmpegAdapter._convert_to_h264) ─────────────
# 影片標準化的長邊上限：超過此值（4K 等）才轉檔縮放。同時作為 _convert_to_h264 的 scale 目標
# 與 .mp4 是否需轉檔的閘控門檻（已合規的 1080p 不重編碼，避免世代品質損失與上傳延遲）。
STANDARDIZE_MAX_LONG_SIDE = 1920

# ── 音訊暫存檔驗證 (AbstractVideoProcessor) ──────────────────────────────────
# ffmpeg 對靜音影片輸出幾乎空的 wav，小於此 bytes 視為無效音訊
MINIMUM_AUDIO_FILE_BYTES = 1000

# ── 時間碼燒錄 (FFmpegAdapter.burn_timecode) ─────────────────────────────────
# drawtext filter 的字體大小表達式（相對影片高度）
TIMECODE_FONT_SIZE_EXPR = "h/15"
# 時間碼文字左上角像素偏移
TIMECODE_POSITION_X = 20
TIMECODE_POSITION_Y = 20

# ── 視覺特徵計算 (MediaStrategy) ─────────────────────────────────────────────
# motion_intensity 分類（frame diff 均值）
MOTION_STATIC_THRESHOLD        = 10.0  # 低於此為 "static"
MOTION_DYNAMIC_THRESHOLD       = 30.0  # 高於此為 "dynamic"
# color_temperature 判斷（R–B channel 均值差）
COLOR_TEMP_THRESHOLD           = 10.0  # 超過此值判定 warm/cool
# crop_feasibility 判斷（bbox 寬度佔畫面百分比）
CROP_PARTIAL_THRESHOLD         = 56.0  # >56%（9:16 裁切橫向邊界）→ "partial"
CROP_NOT_RECOMMENDED_THRESHOLD = 75.0  # >75% → "not_recommended"

# K-means 主色計算參數（改用 cv2.kmeans：不經 sklearn/threadpoolctl 的 dl_iterate_phdr 掃描，
# 避免首呼叫持有動態連結器鎖、與其他執行緒原生擴充 dlopen 形成鎖序倒置死結）
DOMINANT_COLORS_K      = 3    # 取幾個主色
DOMINANT_COLORS_RESIZE = 100  # 縮圖尺寸（像素）加速 k-means 計算
# cv2.kmeans 收斂條件與重試次數（取代 sklearn 的 n_init / max_iter / tol，全部具名避免 magic number）
KMEANS_ATTEMPTS        = 3    # 不同初始中心的嘗試次數，取 compactness 最佳者（穩定性 vs 速度）
KMEANS_MAX_ITER        = 100  # 單次嘗試的最大迭代次數（達上限即停）
KMEANS_EPSILON         = 0.2  # 中心位移小於此值（像素 0–255 尺度）即視為收斂提早停

# 影片取樣
MOTION_SAMPLE_FRAMES      = 10               # 動態強度 frame diff 取樣幀數
SALIENCY_SAMPLE_POSITIONS = (0.1, 0.5, 0.9)  # 三幀 saliency 取樣位置（影片長度 %）
MIDDLE_FRAME_POSITION     = 0.5              # 代表幀位置（對應 SALIENCY_SAMPLE_POSITIONS 中點）

# ComplexVideo / ContextCompressor 強制放行分數
# ComplexVideo 無 technical_score 欄位，ContextCompressor 以此值強制通過畫質篩選
TECHNICAL_SCORE_FORCE_PASS = 100.0

# ── Dynamic Batching 參數 (Week 3a BatchCollector 已接入) ──────────────────────
# 各支援 batch 推論的模型一次合批的最大樣本數（上限；實際批量受上游併發與 timeout 決定）。
# 開關（*_BATCH_ENABLED）與 asset 並行度（影響 inline stage 有效批量）放在 pipeline_config.py。
MUSIQ_BATCH_SIZE     = 16
LAION_BATCH_SIZE     = 16
WHISPER_BATCH_SIZE   = 4
AUDIO_ENV_BATCH_SIZE = 4
# 末尾未達 batch_size 時，等待多少毫秒就強制觸發 forward，避免最後幾張卡死
BATCH_COLLECT_TIMEOUT_MS = 50

# ── GPU 資源管理 (Week 3b BudgetGate 啟用) ─────────────────────────────────────
# 預留給系統 / 共用 GPU 的其他使用者的 VRAM，不納入 BudgetGate 預算
GPU_SAFETY_BUFFER_GB = 1.5

# ── 各模型 VRAM 估值 (Week 3b Capacity Manager / BudgetGate) ────────────────────
# ⚠️ 以下皆為「估值」，實機請以 torch.cuda.reset_peak_memory_stats() +
#    max_memory_allocated() 包一次 forward 校準。GpuCapacityManager 會組成
#    {ModelClass: ModelVramProfile} 對照表（對照表本身在 capacity manager，因需 import 模型類別）。
# - resident：模型常駐權重（載入後一直佔著，決定一張卡放得下幾份模型）。
# - transient：單次 forward 暫態峰值（activation/KV cache/workspace），即 INFERENCE_VRAM_COST_GB，
#   給 BudgetGate 記帳「在飛行中 forward 成本總和 ≤ 預算」。
# Qwen3-VL-4B 4-bit NF4 常駐估值 ~3.5GB（8B 時實測 ~6.4GB，4B 約其半；待實機 reset_peak_memory 校準）；
# transient 為含影像 token 的 generate 暫態估值（4B 層數/隱藏維較小，較 8B 低）。
QWEN_RESIDENT_VRAM_GB       = 3.5
QWEN_TRANSIENT_VRAM_GB      = 2.5
# Whisper 改 faster-whisper(CTranslate2) large-v3-turbo：CT2 float16 常駐遠小於 HF large-v3（~3GB → ~1.6GB）
WHISPER_RESIDENT_VRAM_GB    = 1.6
WHISPER_TRANSIENT_VRAM_GB   = 1.0
MUSIQ_RESIDENT_VRAM_GB      = 0.5
MUSIQ_TRANSIENT_VRAM_GB     = 1.5
LAION_RESIDENT_VRAM_GB      = 1.7
LAION_TRANSIENT_VRAM_GB     = 1.0
AUDIO_ENV_RESIDENT_VRAM_GB  = 0.3
AUDIO_ENV_TRANSIENT_VRAM_GB = 0.5
# Saliency（U²-Net via rembg/onnxruntime）：常駐 + 單次推論暫態。
# Week 3b 起 saliency 納入 GpuCapacityManager（每卡一份的多卡）並走 pool，故需 resident（規劃放置）
# 與 transient（INFERENCE_VRAM_COST_GB，forward 經 L2 BudgetGate 記帳）。resident 為 onnxruntime
# CUDA session 常駐估值（含 context 開銷）。
SALIENCY_RESIDENT_VRAM_GB   = 0.5
SALIENCY_TRANSIENT_VRAM_GB  = 1.5

# Qwen 推論優先序（>0）：BudgetGate 在「有 Qwen 在等」時讓低優先（其餘模型恆 0）讓路，
# 避免 MUSIQ/LAION 等小模型串流把主瓶頸 Qwen 的大塊 VRAM 請求無限延後（餓死）。
QWEN_INFERENCE_PRIORITY = 10

# 同卡 Qwen instance 份數上限（同卡多 slot ⇒ 同卡可並行多條 Qwen forward；需 VRAM 充裕）。
#   0（預設，= QWEN_SLOTS_AUTO）：自動 —— GpuCapacityManager 依該卡 free VRAM 算「能真正並行的份數」：
#     floor((free − 單卡模型常駐總和 − GPU_SAFETY_BUFFER_GB) / (QWEN_RESIDENT + QWEN_TRANSIENT))，
#     常駐放得下至少 1 份。會預留其餘單卡模型常駐，故雙卡環境通常仍每卡 1 份（安全），單張大卡才放到多份。
#   >0：手動上限 —— 取 min(本值, 自動值)；例如 1 = 強制每卡單份（Week 3b 原行為）、2 = 上限每卡 2 份。
# 代價：每多 1 份多吃 ~QWEN_RESIDENT_VRAM_GB 常駐權重；同卡多條 forward 共用 SM，報酬遞減（約 1.2–1.5x）。
QWEN_SLOTS_AUTO = 0
QWEN_MAX_SLOTS_PER_GPU = QWEN_SLOTS_AUTO

# ── OOM 容錯重試 (Week 3b oom_resilient) ───────────────────────────────────────
# 推論遇 CUDA OOM 時釋放 VRAM + backoff 後重試的最大次數；耗盡仍 OOM 則 re-raise 標 asset error。
OOM_RETRY_MAX_ATTEMPTS = 3
# 線性 backoff 基數（秒）：第 k 次重試前睡 OOM_RETRY_BACKOFF_SEC * k，給鄰居 / 同卡 forward 排空時間。
OOM_RETRY_BACKOFF_SEC = 1.0

# ── borrow 即時 VRAM 重檢 (Week 3b ModelPool.borrow) ───────────────────────────
# 借出 GPU 模型前以 mem_get_info 重檢真實 free VRAM（含鄰居 process）；不足時每隔本秒數輪詢一次。
BORROW_VRAM_POLL_INTERVAL_SEC = 0.5
# 等待 VRAM 的上限秒數；逾時仍不足則「盡力放行」（讓 forward 去試，OOM 由 oom_resilient 兜底），
# 避免鄰居長期佔用造成 driver thread 永久卡死（plan §5.3 note 1：優先等待，但不可無限等）。
BORROW_VRAM_MAX_WAIT_SEC = 30.0

# ── Qwen VLM 量化切換 ─────────────────────────────────────────────────────────
# 啟動時 env var QWEN_USE_4BIT 未設定時的預設值
# True： bitsandbytes 4-bit(NF4) 量化（主路徑，runtime ~6.4GB）
# False：bitsandbytes 8-bit 量化（品質回歸 A/B，runtime ~10GB）
QWEN_USE_4BIT_DEFAULT = True
