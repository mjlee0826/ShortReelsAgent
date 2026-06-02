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

# K-means 主色計算參數
DOMINANT_COLORS_K      = 3    # 取幾個主色
KMEANS_N_INIT          = 3    # KMeans 初始化次數（穩定性 vs 速度）
DOMINANT_COLORS_RESIZE = 100  # 縮圖尺寸（像素）加速 k-means 計算

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

# ── Qwen VLM 量化切換 ─────────────────────────────────────────────────────────
# 啟動時 env var QWEN_USE_4BIT 未設定時的預設值
# True： bitsandbytes 4-bit(NF4) 量化（主路徑，runtime ~6.4GB）
# False：bitsandbytes 8-bit 量化（品質回歸 A/B，runtime ~10GB）
QWEN_USE_4BIT_DEFAULT = True
