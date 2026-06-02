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
# HybridScheduler 同時推進幾個 asset driver。每 asset 解碼後 PIL/numpy 約 50–200MB,
# 預設 4 約佔 1GB RAM。設為 1 等同序列化整條框架,可作為 rollback / 除錯安全閥。
MAX_ASSETS_PARALLEL = _read_int_env("MAX_ASSETS_PARALLEL", 4)

# ── 四種 Resource Pool 大小 (ExecutorRegistry) ────────────────────────────────
# IO Pool:FFmpeg subprocess、檔案讀寫、雲端上傳。高併發可大量,但 FFmpeg 也吃 CPU,封頂 8。
IO_POOL_MAX_WORKERS = min(8, _CPU_COUNT)
# CPU Pool:cv2、KMeans、MediaPipe、SceneDetect。numpy/cv2 釋放 GIL,thread 有效,取半數核心。
CPU_POOL_MAX_WORKERS = max(1, _CPU_COUNT // 2)
# GPU Pool:實際大小於 runtime 由 GPU 數動態算(gpu_count × multiplier);GPU Gate 仍限同卡單一 forward,
# multiplier 大只是讓 CPU 預處理重疊,效益遞減。
GPU_POOL_MULTIPLIER = 2
# 單卡環境(或無 GPU)時 GPU pool 的最低 worker 數,確保 pool 至少能運作
GPU_POOL_MIN_WORKERS = 2
# API Pool(Gemini):Semaphore 控 RPS。Free tier 15 RPM → 1–2 並發;此處給保守預設 4。
API_POOL_MAX_WORKERS = 4

# ── Stage 提交逾時 ────────────────────────────────────────────────────────────
# 將 Stage 提交到 ResourceExecutor 後等待結果的最長秒數;None 表示無限等待。
# Week 2a 單 Stage 群組走 inline 不受此值影響,保留給 Week 2b/2c 多 Stage 群組。
STAGE_SUBMIT_TIMEOUT_SEC: float | None = None

# ── 模型載入策略 ──────────────────────────────────────────────────────────────
# Eager Warm Up 開關。Week 2a 預設 False(維持既有 lazy 載入,行為與 Week 1 一致、啟動快);
# 真正的啟動期預載 + VRAM 不足自動降級 lazy,留待 Week 3b GPU Capacity Manager 實作。
EAGER_MODELS_DEFAULT = False
EAGER_MODELS = _read_bool_env("EAGER_MODELS", EAGER_MODELS_DEFAULT)

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
