"""
媒體處理器常數集中管理 (Configuration Object Pattern)。
media_processor/ 與 media_tools/ 所有模組從此處 import，避免 magic number 散落各檔。
"""
import os

# ── 畫質過濾 ───────────────────────────────────────────────────────────────
# MUSIQ 技術畫質分數低於此值即 reject。⚠️ 僅 legacy ImageProcessor（USE_LEGACY_IMAGE_PIPELINE）
# 仍沿用此硬性單訊號門檻；現行細粒度 pipeline 已移除硬 reject（評分與過濾解耦），改由
# ContextCompressor 做下方的「寬容雙訊號」非破壞性過濾，避免 MUSIQ 單訊號低估造成好素材誤刪。
TECHNICAL_SCORE_FILTER_THRESHOLD = 40.0

# ── 軟性畫質過濾 (ContextCompressor) ──────────────────────────────────────────
# 評分與過濾解耦後，tech/aes 一律由 Phase 1 算好存進 metadata（含 Complex）；導演端只做
# 「非破壞性 + 多訊號 + 寬容」的最終把關：唯有技術分「極低」AND 美學分「也低」雙重條件同時成立
# 才剔除。單一訊號偏低不再誤刪（MUSIQ 對動態模糊/低光素材常單邊低估）；缺分數的舊快取一律放行。
# 兩者皆為 0~100 分制。
TECHNICAL_SCORE_REJECT_THRESHOLD = 20.0   # 技術分低於此才視為「極可能是壞幀／嚴重模糊」
AESTHETIC_SCORE_REJECT_THRESHOLD = 30.0   # 美學分低於此才視為「構圖／內容也乏善可陳」

# ── MUSIQ 視覺評分模型 (MusiqModelManager) ────────────────────────────────────
# 推論前 PIL 圖片的最大短邊長度（過大會吃 VRAM 且分數震盪）
MUSIQ_MAX_INPUT_SIZE = 512

# ── 推論幀解析度上限 (pipeline/utils/video_frame_utils.cap_pil_resolution) ───────
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

# ── 素材標準化並行度 (MediaStandardizer.standardize_folder) ─────────────────────
# 標準化的重活都在 ffmpeg / PIL 子行程（subprocess 阻塞時釋放 GIL，故用 thread 即可真正並行，
# 不需 multiprocess 的 pickle / spawn 開銷）。並行度刻意設「上限」避免共用機（Leibniz）CPU/RAM
# 超賣：libx264 單檔本就吃滿多核，過高的並行只會互搶核心 + 墊高記憶體峰值。預設保守給 4，
# 可由 env STANDARDIZE_MAX_WORKERS 覆寫；壞字串視為未設定，回退預設值以保證啟動穩定。
_STANDARDIZE_MAX_WORKERS_DEFAULT = 4
try:
    STANDARDIZE_MAX_WORKERS = max(
        1, int(os.environ.get("STANDARDIZE_MAX_WORKERS", _STANDARDIZE_MAX_WORKERS_DEFAULT))
    )
except ValueError:
    STANDARDIZE_MAX_WORKERS = _STANDARDIZE_MAX_WORKERS_DEFAULT

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

# ── 主體框 top-N 候選選擇 (vlm_bbox_utils) ───────────────────────────────────
# VLM 每幀／每事件最多採信的候選主體數：要求模型「由信心高→低」排序，僅取前 N 個，
# 緩解「只逼模型一次定案而選錯主體」的失敗模式（mode A）。
SUBJECT_CANDIDATE_TOP_N              = 3
# 選框評分權重：score = 信心 * CONF_WEIGHT + 9:16 可裁性 * CROP_FIT_WEIGHT。
# 信心為主、可裁性為輔，讓「信心略低但能完整入直式框」的主體有機會勝出（貼合 reel 直式輸出）。
SUBJECT_SELECT_CONFIDENCE_WEIGHT    = 1.0
SUBJECT_SELECT_CROP_FIT_WEIGHT      = 0.5
# 候選缺 confidence 時的中性預設：讓未標信心的框仍能參與排序，不被當 0 永遠墊底。
SUBJECT_CANDIDATE_DEFAULT_CONFIDENCE = 0.5

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

# ── Dynamic Batching 參數 (BatchCollector) ──────────────────────
# 各支援 batch 推論的模型一次合批的最大樣本數（上限；實際批量受上游併發與 timeout 決定）。
# 開關（*_BATCH_ENABLED）與 asset 並行度（影響 inline stage 有效批量）放在 pipeline_config.py。
MUSIQ_BATCH_SIZE     = 16
LAION_BATCH_SIZE     = 16
WHISPER_BATCH_SIZE   = 4
AUDIO_ENV_BATCH_SIZE = 4
# 末尾未達 batch_size 時，等待多少毫秒就強制觸發 forward，避免最後幾張卡死
BATCH_COLLECT_TIMEOUT_MS = 50

# ── GPU 資源管理 (BudgetGate) ─────────────────────────────────────
# 預留給系統 / 共用 GPU 的其他使用者的 VRAM，不納入 BudgetGate 預算
GPU_SAFETY_BUFFER_GB = 1.5

# ── 各模型 VRAM 估值 (Capacity Manager / BudgetGate) ────────────────────
# ⚠️ 以下皆為「估值」，實機請以 torch.cuda.reset_peak_memory_stats() +
#    max_memory_allocated() 包一次 forward 校準。GpuCapacityManager 會組成
#    {ModelClass: ModelVramProfile} 對照表（對照表本身在 capacity manager，因需 import 模型類別）。
# - resident：模型常駐權重（載入後一直佔著，決定一張卡放得下幾份模型）。
# - transient：單次 forward 暫態峰值（activation/KV cache/workspace），即 INFERENCE_VRAM_COST_GB，
#   給 BudgetGate 記帳「在飛行中 forward 成本總和 ≤ 預算」。
# Qwen 量化策略 (Strategy 選擇器)：三種載入策略，預設 bf16（不量化）。
# 理由：bnb 4-bit/8-bit 在 transformers 推理時每個 matmul 都即時反量化、沒有真正的低位元 kernel
#   （真 4-bit kernel 僅 vLLM 有），單次 forward 慢 2~4 倍；本專案 Qwen 為端到端主瓶頸且 VRAM 充裕
#   （單卡 ~23GB、4B bf16 僅 ~8.5GB），故預設走最快的 bf16。nf4 / int8 保留供「VRAM 吃緊」或品質
#   回歸 A/B，以 env QWEN_QUANT_MODE 覆寫。
QWEN_QUANT_MODE_NF4  = "nf4"    # bitsandbytes 4-bit NF4：最省 VRAM、最慢
QWEN_QUANT_MODE_INT8 = "int8"   # bitsandbytes 8-bit：VRAM / 速度介於中間
QWEN_QUANT_MODE_BF16 = "bf16"   # 不量化、bf16 權重：最快、VRAM 最大（預設）
QWEN_QUANT_MODE_DEFAULT = QWEN_QUANT_MODE_BF16
QWEN_QUANT_MODE = os.environ.get("QWEN_QUANT_MODE", QWEN_QUANT_MODE_DEFAULT).strip().lower()

# 各量化模式的 VRAM profile：(resident 常駐權重, transient 單次 forward 暫態峰值)，單位 GB。
# bf16：Qwen3-VL-4B 權重 4B×2byte ≈ 8GB + 視覺編碼器 ≈ 8.5GB；nf4 ~3.5GB、int8 ~5.5GB。
# 未知 mode 退回 bf16 profile（過估 resident 只會少放幾份、安全；低估才會 OOM）。
_QWEN_VRAM_PROFILE_BY_MODE = {
    QWEN_QUANT_MODE_NF4:  (3.5, 2.5),
    QWEN_QUANT_MODE_INT8: (5.5, 2.5),
    QWEN_QUANT_MODE_BF16: (8.5, 3.0),
}
QWEN_RESIDENT_VRAM_GB, QWEN_TRANSIENT_VRAM_GB = _QWEN_VRAM_PROFILE_BY_MODE.get(
    QWEN_QUANT_MODE, _QWEN_VRAM_PROFILE_BY_MODE[QWEN_QUANT_MODE_BF16]
)
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
# saliency 納入 GpuCapacityManager（每卡一份的多卡）並走 pool，故需 resident（規劃放置）
# 與 transient（INFERENCE_VRAM_COST_GB，forward 經 L2 BudgetGate 記帳）。resident 為 onnxruntime
# CUDA session 常駐估值（含 context 開銷）。
SALIENCY_RESIDENT_VRAM_GB   = 0.5
SALIENCY_TRANSIENT_VRAM_GB  = 1.5

# Qwen 推論優先序（>0）：BudgetGate 在「有 Qwen 在等」時讓低優先（其餘模型恆 0）讓路，
# 避免 MUSIQ/LAION 等小模型串流把主瓶頸 Qwen 的大塊 VRAM 請求無限延後（餓死）。
QWEN_INFERENCE_PRIORITY = 10

# BudgetGate「低優先保留車道」比例（反餓死軟化）：
# 舊規則「只要有高優先(Qwen)在等，同卡低優先一律全擋」會在 Qwen forward 長達數十秒~數分鐘時，
# 把同卡小模型(MUSIQ/LAION/AudioEnv/Whisper)餓死整場（log 裡 aes 實算 ~50ms 卻被卡到 91s）。
# 改為保留一條「低優先車道」：即使有 Qwen 在等，只要低優先「在飛成本總和 ≤ budget × 本比例」就放行
# （且整體不超預算以防 OOM），讓小模型細水長流不被餓死；Qwen 仍對其餘大部分預算保有優先權。
# 0.0 = 回到舊的硬餓死規則；1.0 = 等於取消優先序。預設 0.5 折衷（Qwen 仍拿一半，小模型不致全停）。
BUDGET_GATE_LOW_PRIORITY_RESERVE_RATIO = 0.5

# 同卡 Qwen instance 份數上限（同卡多 slot ⇒ 同卡可並行多條 Qwen forward；需 VRAM 充裕）。
#   0（= QWEN_SLOTS_AUTO）：自動 —— GpuCapacityManager 依該卡 free VRAM 算「能真正並行的份數」：
#     floor((free − 單卡模型常駐總和 − GPU_SAFETY_BUFFER_GB) / (QWEN_RESIDENT + QWEN_TRANSIENT))。
#   >0：手動上限 —— 取 min(本值, 自動值)；例如 1 = 強制每卡單份、2 = 上限每卡 2 份。
# 設為 1 的理由：實測 Qwen 為 compute-bound（單卡 SM/頻寬已飽和），同卡疊多份 forward 只是互相
#   時間分片、總吞吐不變（報酬遞減 ~1.2–1.5x），徒增 VRAM；且 bf16 權重 ~8.5GB，單張 23GB 卡本就
#   只放得下 1 份。要回到「依 VRAM 自動鋪滿」改回 QWEN_SLOTS_AUTO。
QWEN_SLOTS_AUTO = 0
QWEN_MAX_SLOTS_PER_GPU = 1

# ── OOM 容錯重試 (oom_resilient) ───────────────────────────────────────
# 推論遇 CUDA OOM 時釋放 VRAM + backoff 後重試的最大次數；耗盡仍 OOM 則 re-raise 標 asset error。
OOM_RETRY_MAX_ATTEMPTS = 3
# 線性 backoff 基數（秒）：第 k 次重試前睡 OOM_RETRY_BACKOFF_SEC * k，給鄰居 / 同卡 forward 排空時間。
OOM_RETRY_BACKOFF_SEC = 1.0

# ── borrow 即時 VRAM 重檢 (ModelPool.borrow) ───────────────────────────
# 借出 GPU 模型前以 mem_get_info 重檢真實 free VRAM（含鄰居 process）；不足時每隔本秒數輪詢一次。
BORROW_VRAM_POLL_INTERVAL_SEC = 0.5
# 等待 VRAM 的上限秒數；逾時仍不足則「盡力放行」（讓 forward 去試，OOM 由 oom_resilient 兜底），
# 避免鄰居長期佔用造成 driver thread 永久卡死（優先等待，但不可無限等）。
BORROW_VRAM_MAX_WAIT_SEC = 30.0
