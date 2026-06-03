"""
Pipeline 排程層常數集中管理 (Configuration Object Pattern)。

media_processor/pipeline/ 底下所有模組從此處 import 併發度與 timeout 設定,
避免 magic number 散落各檔。數值先給 plan §10 的預設值,壓測後可依
nvidia-smi 與 CPU 利用率調整;併發度可由環境變數覆寫,方便實機調校與 rollback。

設計來源:integrated_acceleration_plan.md §10「Worker Pool 大小建議」。
"""
import os


def _read_int_env(env_name: str, default: int) -> int:
    """讀取 env var 並轉為 int;未設定或格式錯誤時回傳 default(不讓壞值炸掉啟動)。"""
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        # 壞字串視為未設定,回退預設值以保證啟動穩定
        return default


def _read_bool_env(env_name: str, default: bool) -> bool:
    """讀取 env var 並轉為 bool,接受 true/1/yes/on 等常見字串。"""
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


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
# API Pool(Gemini):Semaphore 控 RPS。Free tier 15 RPM → 1–2 並發;此處給保守預設 4。
API_POOL_MAX_WORKERS = 16

# ── Stage 提交逾時 ────────────────────────────────────────────────────────────
# 將 Stage 提交到 ResourceExecutor 後等待結果的最長秒數;None 表示無限等待。
# Week 2a 單 Stage 群組走 inline 不受此值影響,保留給 Week 2b/2c 多 Stage 群組。
STAGE_SUBMIT_TIMEOUT_SEC: float | None = None

# ── 模型載入策略 ──────────────────────────────────────────────────────────────
# Eager Warm Up 開關。Week 3b 起預設 True:啟動時依 GpuCapacityManager 的優先序 + check-before-load
# 預載熱門模型(Qwen 一定常駐、VRAM 不足的自動降級 lazy),讓第一個 asset 不再卡 20–60s 等載入
# (plan §5.2 對齊 vLLM/Triton 慣例)。開發 / 單卡迭代想啟動快可設 EAGER_MODELS=false 關閉。
EAGER_MODELS_DEFAULT = True
EAGER_MODELS = _read_bool_env("EAGER_MODELS", EAGER_MODELS_DEFAULT)

# ── 多 GPU ModelPool 借出開關 (Week 3b) ────────────────────────────────────────
# True(預設):semantic stage 與 GPU batch_fn 走 ModelPoolRegistry.instance().get_pool().borrow(),
#   把推論分散到 capacity 規劃的多張卡(Qwen 多卡、其餘最寬鬆卡),並享 borrow 即時 VRAM 重檢。
# False:緊急 rollback 回 Week 3a 行為 —— 直接用 device-0 singleton(不經 pool / 不重檢),
#   仍受 BudgetGate(L2)保護。供逐欄一致 A/B 與多 GPU 出問題時快速退回。
GPU_POOL_ENABLED = _read_bool_env("GPU_POOL_ENABLED", True)

# ── 圖片 Pipeline 拆 Stage 切換 (Week 2b) ──────────────────────────────────────
# False(預設):走 Week 2b 新拆的細粒度 Stage 編排(Decode → Tech → Reject → 平行群 → Assembly)。
# True：回退 Week 2a 的單一 LegacyImagePipelineStage,供 A/B 逐欄一致回歸與緊急 rollback。
# 人類同組素材各跑一次 true / false,diff phase1_assets_metadata.json 即完成驗收(roadmap §13)。
USE_LEGACY_IMAGE_PIPELINE_DEFAULT = False
USE_LEGACY_IMAGE_PIPELINE = _read_bool_env(
    "USE_LEGACY_IMAGE_PIPELINE", USE_LEGACY_IMAGE_PIPELINE_DEFAULT
)

# ── 影片 Pipeline 拆 Stage 切換 (Week 2c) ──────────────────────────────────────
# False(預設):走 Week 2c 新拆的細粒度 Stage 依賴圖(DAG):Decode → Tech → Reject → 大平行群 → Assembly
#   (Simple);Decode → (Timecode‖音訊‖場景‖視覺特徵) → Gemini → EventBbox → Assembly(Complex)。
# True：回退 Week 2a 的單一 LegacyVideoPipelineStage,供 A/B 逐欄一致回歸與緊急 rollback。
# 人類同組影片各跑一次 true / false,diff phase1_assets_metadata.json 即完成驗收(roadmap §13)。
USE_LEGACY_VIDEO_PIPELINE_DEFAULT = False
USE_LEGACY_VIDEO_PIPELINE = _read_bool_env(
    "USE_LEGACY_VIDEO_PIPELINE", USE_LEGACY_VIDEO_PIPELINE_DEFAULT
)

# ── Dynamic Batching 逐模型開關 (Week 3a) ──────────────────────────────────────
# 控制各 Stage 是否走 BatchCollector 合批;False 時該 Stage 回退原單張呼叫(對 driver 透明)。
# 與 USE_LEGACY_* 同屬操作開關,供逐欄一致 A/B 與緊急 rollback:
#   - LAION 因 CLIP 固定 resize 224²,單張/批次完全一致,預設安全可開。
#   - MUSIQ 批次走「保比例 + padding」(非裁切),與單張僅 padding 區有微差;實機量 drift 超過
#     ±0.01 時設 MUSIQ_BATCH_ENABLED=false 回到單張精確分數。
#   - Whisper / AudioEnv 批次對變長輸入做 padding,亦可能有微差,可逐一關閉比對。
MUSIQ_BATCH_ENABLED     = _read_bool_env("MUSIQ_BATCH_ENABLED", True)
LAION_BATCH_ENABLED     = _read_bool_env("LAION_BATCH_ENABLED", True)
WHISPER_BATCH_ENABLED   = _read_bool_env("WHISPER_BATCH_ENABLED", True)
AUDIO_ENV_BATCH_ENABLED = _read_bool_env("AUDIO_ENV_BATCH_ENABLED", True)

# ── 卡住偵測 Watchdog (Week 3b 觀測性) ─────────────────────────────────────────
# 背景 daemon 每隔 heartbeat 秒印出「目前進行中的 stage + 已執行秒數」，超過 stall_warn 秒標 ⚠。
# 只在「有進行中 stage」時才印（idle 不洗版）；processor 疑似卡住時用來看卡在哪個 stage、
# 是否在等 VRAM（borrow 的 RESOURCE_WAIT）。純觀測、不改流水線；要關閉設 WATCHDOG_ENABLED=false。
WATCHDOG_ENABLED        = _read_bool_env("WATCHDOG_ENABLED", True)
WATCHDOG_HEARTBEAT_SEC  = _read_int_env("WATCHDOG_HEARTBEAT_SEC", 30)
WATCHDOG_STALL_WARN_SEC = _read_int_env("WATCHDOG_STALL_WARN_SEC", 120)
# C 層 dead-man:心跳停止推進(GIL 被 C 擴充如 onnxruntime/CUDA 凍住)達此秒數 → 從 C 層 dump
# 全部 thread 堆疊到 stderr(Python watchdog 抓不到 GIL-holding hang,靠這個兜)。需 > heartbeat。
WATCHDOG_FREEZE_DUMP_SEC = _read_int_env("WATCHDOG_FREEZE_DUMP_SEC", 90)
