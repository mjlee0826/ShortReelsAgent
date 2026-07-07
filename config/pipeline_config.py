"""
Pipeline 排程層常數集中管理 (Configuration Object Pattern)。

media_processor/pipeline/ 底下所有模組從此處 import 併發度與 timeout 設定,
避免 magic number 散落各檔。數值為預設值,壓測後可依
nvidia-smi 與 CPU 利用率調整;併發度可由環境變數覆寫,方便實機調校與 rollback。
"""
import os

# env 讀取工具集中於 config.env_utils（DRY）；別名維持模組內既有呼叫寫法
from config.env_utils import (
    read_bool_env as _read_bool_env,
    read_int_env as _read_int_env,
)


# 系統 CPU 核心數(取不到時保守給 4),供 IO/CPU pool 預設值計算
_CPU_COUNT = os.cpu_count() or 4


# ── Asset 驅動層並行度 ────────────────────────────────────────────────────────
# HybridScheduler 同時推進幾個 asset driver 的「上限」;實際並行度 = min(asset 數, 本值)
# (見 HybridScheduler.run)。每 asset 解碼後 PIL/numpy 約 50–200MB,本值越大越吃 RAM
# (8 約 1.6GB、16 約 3.2GB)。
# 與 Dynamic Batching 的共調:inline 執行的 stage(圖片 tech)其有效合批量 ≤ 本值,
# 故要讓 MUSIQ batch 填得滿,本值需逼近 batch_size(預設 16);GPU-pool 類 stage 的批量則受
# GPU_POOL_MULTIPLIER 影響。預設 8 兼顧 RAM 與合批;壓測時可用 env 調到 16。
# 設為 1 等同序列化整條框架,可作為 rollback / 除錯安全閥。
MAX_ASSETS_PARALLEL = _read_int_env("MAX_ASSETS_PARALLEL", 16)

# ── 四種 Resource Pool 大小 (ExecutorRegistry) ────────────────────────────────
# IO Pool:FFmpeg subprocess、檔案讀寫、雲端上傳。FFmpeg 吃 CPU、上傳/讀寫偏 IO-bound,
# 封頂以 _CPU_COUNT 為準（你的機器 → 80;偏猛時看 CPU% 再回調）。
IO_POOL_MAX_WORKERS = min(128, _CPU_COUNT)
# CPU Pool:cv2、KMeans、MediaPipe、SceneDetect。numpy/cv2 釋放 GIL,thread 有效;但屬 compute-bound,
# 超過實體核報酬遞減,封頂 64（你的 80 緒機 → 64;原 max(128,..) 會強制 ≥128 反而 oversubscribe,已修正）。
CPU_POOL_MAX_WORKERS = min(64, _CPU_COUNT)
# GPU Pool:實際大小於 runtime 由 GPU 數動態算(gpu_count × multiplier);GPU Gate 仍限同卡單一 forward,
# multiplier 大只是讓 CPU 預處理重疊,效益遞減。
GPU_POOL_MULTIPLIER = 3
# 單卡環境(或無 GPU)時 GPU pool 的最低 worker 數,確保 pool 至少能運作
GPU_POOL_MIN_WORKERS = 2
# API Pool(Gemini):Semaphore 控 RPS。付費 tier 下預設 16 並發;free tier(15 RPM)建議降到 1–2。
API_POOL_MAX_WORKERS = 16

# ── Stage 提交逾時 ────────────────────────────────────────────────────────────
# 將 Stage 提交到 ResourceExecutor 後等待結果的最長秒數;None 表示無限等待。
# 單 Stage 群組走 inline 不受此值影響,保留給多 Stage 群組。
STAGE_SUBMIT_TIMEOUT_SEC: float | None = None

# ── 編輯頁 Phase 1 等待鎖逾時 ─────────────────────────────────────────────────
# 編輯頁完整生成時,若有前景 Phase 1(雲端同步 / 素材頁)正在跑同一專案,會阻塞等待其完成
# 再讀新鮮快取;此為等待上限(秒),逾時即回「分析進行中,請稍候再試」。設大以容納大專案在
# 共用 GPU 上跑完整 Phase 1,逾時應極少發生;可由 env EDITOR_PHASE1_LOCK_TIMEOUT_SEC 覆寫。
EDITOR_PHASE1_LOCK_TIMEOUT_SEC = _read_int_env("EDITOR_PHASE1_LOCK_TIMEOUT_SEC", 1200)

# ── 模型載入策略 ──────────────────────────────────────────────────────────────
# Eager Warm Up 開關。預設 True:啟動時依 GpuCapacityManager 的優先序 + check-before-load
# 預載熱門模型(Qwen 一定常駐、VRAM 不足的自動降級 lazy),讓第一個 asset 不再卡 20–60s 等載入
# (對齊 vLLM/Triton 慣例)。開發 / 單卡迭代想啟動快可設 EAGER_MODELS=false 關閉。
EAGER_MODELS_DEFAULT = True
EAGER_MODELS = _read_bool_env("EAGER_MODELS", EAGER_MODELS_DEFAULT)

# ── 多 GPU ModelPool 借出開關 ────────────────────────────────────────
# True(預設):semantic stage 與 GPU batch_fn 走 ModelPoolRegistry.instance().get_pool().borrow(),
#   把推論分散到 capacity 規劃的多張卡(Qwen 多卡、其餘最寬鬆卡),並享 borrow 即時 VRAM 重檢。
# False:緊急 rollback —— 直接用 device-0 singleton(不經 pool / 不重檢),
#   仍受 BudgetGate(L2)保護。供逐欄一致 A/B 與多 GPU 出問題時快速退回。
GPU_POOL_ENABLED = _read_bool_env("GPU_POOL_ENABLED", True)

# （USE_LEGACY_IMAGE/VIDEO_PIPELINE 與 COMPLEX_AUDIO_VIA_GEMINI 旗標已移除：
#   細粒度 DAG 與「Complex 音訊由 Gemini 一併輸出」皆已完成逐欄一致 / 品質驗收並轉正,
#   legacy 單節點路徑與 Whisper 回退鏈一併刪除。）

# ── Dynamic Batching 逐模型開關 ──────────────────────────────────────
# 控制各 Stage 是否走 BatchCollector 合批;False 時該 Stage 回退原單張呼叫(對 driver 透明)。
# 屬操作開關,供逐欄一致 A/B 與緊急 rollback:
#   - LAION 因 CLIP 固定 resize 224²,單張/批次完全一致,預設安全可開。
#   - MUSIQ 批次走「保比例 + padding」(非裁切),與單張僅 padding 區有微差;實機量 drift 超過
#     ±0.01 時設 MUSIQ_BATCH_ENABLED=false 回到單張精確分數。
#   - AudioEnv 批次對變長輸入做 padding,亦可能有微差,可關閉比對。
# （Whisper 的跨檔合批開關已移除:faster-whisper 無多檔 forward,舊路徑是循序假合批;
#   其單檔內分塊批次開關見 model_config 的 WHISPER_USE_BATCHED_PIPELINE。）
MUSIQ_BATCH_ENABLED     = _read_bool_env("MUSIQ_BATCH_ENABLED", True)
LAION_BATCH_ENABLED     = _read_bool_env("LAION_BATCH_ENABLED", True)
AUDIO_ENV_BATCH_ENABLED = _read_bool_env("AUDIO_ENV_BATCH_ENABLED", True)

# ── MediaPipe Face Detect Pool ────────────────────────────────────────────────
# 每個 asset 可獨立借出一個 FaceDetector instance → 上限取 MAX_ASSETS_PARALLEL（zero-queue）。
# 超過 MAX_ASSETS_PARALLEL 個 instance 不會帶來額外並行收益，故以此為上限避免浪費記憶體。
MEDIAPIPE_POOL_SIZE: int = MAX_ASSETS_PARALLEL

# ── VAD pool（Silero）────────────────────────────────────────────────────────
# VAD 改為獨立 CPU pool（與 MediaPipe / Saliency 同構）：放 VAD_POOL_SIZE 個「不同 slot_id」的 Silero
# instance，各有獨立 L3 lock，讓多支影片的 VAD 真平行（修正單例序列化：實測 3 片 VAD 排隊到 250s+）。
# Silero 極輕（權重 ~MB、ms 級推論），但每多一份 warmup 多一次 torch.hub 載入（~0.2–0.6s），
# 故預設保守給 4（覆蓋常見並行影片數）；批量更大時用 env VAD_POOL_SIZE 調高。
VAD_POOL_SIZE: int = _read_int_env("VAD_POOL_SIZE", 4)

# ── 卡住偵測 Watchdog (觀測性) ─────────────────────────────────────────
# 背景 daemon 每隔 heartbeat 秒印出「目前進行中的 stage + 已執行秒數」，超過 stall_warn 秒標 ⚠。
# 只在「有進行中 stage」時才印（idle 不洗版）；processor 疑似卡住時用來看卡在哪個 stage、
# 是否在等 VRAM（borrow 的 RESOURCE_WAIT）。純觀測、不改流水線；要關閉設 WATCHDOG_ENABLED=false。
WATCHDOG_ENABLED        = _read_bool_env("WATCHDOG_ENABLED", True)
WATCHDOG_HEARTBEAT_SEC  = _read_int_env("WATCHDOG_HEARTBEAT_SEC", 30)
WATCHDOG_STALL_WARN_SEC = _read_int_env("WATCHDOG_STALL_WARN_SEC", 120)
# C 層 dead-man:心跳停止推進(GIL 被 C 擴充如 onnxruntime/CUDA 凍住)達此秒數 → 從 C 層 dump
# 全部 thread 堆疊到 stderr(Python watchdog 抓不到 GIL-holding hang,靠這個兜)。需 > heartbeat。
WATCHDOG_FREEZE_DUMP_SEC = _read_int_env("WATCHDOG_FREEZE_DUMP_SEC", 90)
