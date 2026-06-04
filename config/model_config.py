"""
模型層設定集中管理 (Configuration Object Pattern)。
model/ 底下所有 manager 的常數統一在此定義，對外是唯一的 import 來源。
"""
import os
from config.media_processor_config import (
    MUSIQ_MAX_INPUT_SIZE as MUSIQ_MAX_SHORT_SIDE,
    QWEN_USE_4BIT_DEFAULT,
)

# ── Gemini 影片上傳輪詢 ───────────────────────────────────────────────────────
# 影片上傳後台處理的最大輪詢次數（150 * 2s = 5 分鐘）
GEMINI_POLL_MAX_COUNT   = 150
GEMINI_POLL_INTERVAL_SEC = 2

# ── Whisper 幻覺防跳針 ────────────────────────────────────────────────────────
# 連續「停滯型重複」達到此次數，判定為 attention 鎖死並截斷後續輸出
WHISPER_HALLUCINATION_THRESHOLD = 3

# ── 確保 re-export 的名稱可被 from model_config import * 取用 ──────────────
__all__ = [
    # re-exports
    "GEMINI_POLL_MAX_COUNT",
    "GEMINI_POLL_INTERVAL_SEC",
    "WHISPER_HALLUCINATION_THRESHOLD",
    "MUSIQ_MAX_SHORT_SIDE",
    # Gemini
    "GEMINI_DEFAULT_MODEL",
    "GEMINI_STRONG_MODEL",
    # Qwen
    "QWEN_MODEL_ID",
    "QWEN_PROCESSOR_ID",
    "QWEN_BASE_MODEL_ID",
    "QWEN_USE_4BIT",
    "QWEN_USE_FLASH_ATTN",
    "QWEN_MAX_NEW_TOKENS",
    "QWEN_MAX_PIXELS",
    "QWEN_FPS_TIMECODED",
    "QWEN_FPS_DEFAULT",
    # Whisper (faster-whisper / CTranslate2)
    "WHISPER_MODEL_ID",
    "WHISPER_CUDA_COMPUTE_TYPE",
    "WHISPER_CPU_COMPUTE_TYPE",
    "WHISPER_BEAM_SIZE",
    "WHISPER_VAD_FILTER",
    # Audio Env
    "AUDIO_ENV_TOP_K",
    "AUDIO_SAMPLING_RATE",
    "AUDIO_ENV_MIN_SCORE",
    # MediaPipe
    "MEDIAPIPE_MIN_DETECTION_CONFIDENCE",
    "MEDIAPIPE_FACE_MODEL_FILENAME",
    "MEDIAPIPE_FACE_MODEL_URL",
    # LAION
    "LAION_CLIP_MODEL_ID",
    "LAION_MLP_INPUT_SIZE",
    "LAION_SCORE_MIN",
    "LAION_SCORE_MAX",
    "LAION_WEIGHT_FILENAME",
    "LAION_WEIGHT_URL",
    # MUSIQ
    "MUSIQ_METRIC_NAME",
    # VAD
    "VAD_REPO",
    "VAD_SAMPLING_RATE",
    # Saliency
    "SALIENCY_MODEL_NAME",
    # 共用
    "DEFAULT_FALLBACK_SCORE",
    "SCORE_MIN",
    "SCORE_MAX",
    # 本地模型權重目錄
    "MODEL_WEIGHTS_DIR",
]

# ── 本地模型權重目錄 ───────────────────────────────────────────────────────────
# LAION 與 MediaPipe 的 .pth / .tflite 權重存放於此；首次缺檔時 auto-download 到同路徑
MODEL_WEIGHTS_DIR = os.environ.get("MODEL_WEIGHTS_DIR", "/data1/cache/mjlee/models")

# ── Gemini ────────────────────────────────────────────────────────────────────
GEMINI_DEFAULT_MODEL = 'gemini-2.5-flash'
GEMINI_STRONG_MODEL  = 'gemini-3.1-pro-preview'

# ── Qwen3-VL ─────────────────────────────────────────────────────────────────
# 改用 4B-Instruct：semantic_stage 的 Qwen 只負責 SIMPLE / 全局分析（COMPLEX 與時間碼走 Gemini），
# 任務單純，4B 已足夠且推論更快、VRAM 更省；8B 的腦力在此用不到。
# 模型一律從官方 base 載入，再由 bitsandbytes 即時量化（4-bit 主、8-bit 後備）。
# 原社群 compressed-tensors AWQ（cyankiwi）在 transformers 推理時會解壓成 bf16、runtime 不省 VRAM，已棄用。
QWEN_BASE_MODEL_ID = "Qwen/Qwen3-VL-4B-Instruct"
# Processor (tokenizer + image preprocessor) 從官方 base model 載入
QWEN_PROCESSOR_ID  = QWEN_BASE_MODEL_ID


def _read_bool_env(env_name: str, default: bool) -> bool:
    """讀取 env var 並轉為 bool，接受 true/1/yes/on 等常見字串。"""
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


def _read_int_env(env_name: str, default: int) -> int:
    """讀取 env var 並轉為 int；未設定或格式錯誤時回 default（壞值不炸啟動）。"""
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _read_float_env(env_name: str, default: float) -> float:
    """讀取 env var 並轉為 float；未設定或格式錯誤時回 default（壞值不炸啟動）。"""
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


# 啟動時決定走哪條 Qwen 路徑（Feature Toggle）；rollback 時設 false
QWEN_USE_4BIT        = _read_bool_env("QWEN_USE_4BIT", QWEN_USE_4BIT_DEFAULT)
# Flash Attention 2 開關，安裝失敗時 QwenModelManager 內部會 fallback 到 sdpa
QWEN_USE_FLASH_ATTN = _read_bool_env("QWEN_USE_FLASH_ATTN", True)
# 量化改用 bitsandbytes（4-bit/8-bit 皆即時量化官方 base model），不再用 cyankiwi
# compressed-tensors AWQ —— 後者在 transformers 推理時會整包解壓成 bf16、runtime 不省 VRAM
# （真正的 4-bit kernel 僅 vLLM 有）。故 model id 一律指向官方 base，由 BitsAndBytesConfig 即時量化。
QWEN_MODEL_ID       = QWEN_BASE_MODEL_ID

# ── Qwen 單次 forward 成本旋鈕（皆可由 env 覆寫，便於不改碼 A/B 品質 vs 速度）─────────
# semantic（Qwen）是整條 pipeline 的長板：單次 forward 成本 ≈ 影格數 × 每格 token × 輸出 token，
# 三者都直接決定 GPU 佔用時間。共用卡序列化時，Qwen 拖多久、其餘 stage 就被卡多久，故這裡把
# 三個旋鈕都下修並開放 env 覆寫（品質回歸時用 env 調回 512 / 100352 / 1.0 比對）。
#
# 輸出 token 上限：512→384。GLOBAL_ANALYSIS 產的是結構化 JSON 描述，384 步通常已足夠，
# 但 autoregressive 每 token 一次 forward，省 25% 步數直接省 25% decode 時間（影響最大、品質風險最低）。
QWEN_MAX_NEW_TOKENS = _read_int_env("QWEN_MAX_NEW_TOKENS", 384)
# 每格影像 pixel 數上限：100352→81920（≈320×256）。對「多影格的影片」是 prefill token 的主要來源，
# 降 ~18% 直接省同比例的影片 token；對全局理解的細節影響有限（細節敏感任務可用 env 調回 100352）。
QWEN_MAX_PIXELS     = _read_int_env("QWEN_MAX_PIXELS", 81920)
# 時間碼模式採樣率（此模式走 Gemini，不影響本地 Qwen forward 成本）：保留 2.0，需要時 env 覆寫。
QWEN_FPS_TIMECODED  = _read_float_env("QWEN_FPS_TIMECODED", 2.0)
# 全局分析影片採樣率（Qwen 影片路徑實際用值）：影格數 = fps × 片長，是影片 forward 成本的關鍵旋鈕。
# 預設維持 1.0（已偏低）；影片偏長、想再降成本時設 QWEN_FPS_DEFAULT=0.5（每秒半格）。
QWEN_FPS_DEFAULT    = _read_float_env("QWEN_FPS_DEFAULT", 1.0)

# ── Whisper (faster-whisper / CTranslate2) ────────────────────────────────────
# 改用 faster-whisper（CTranslate2 後端）跑 large-v3-turbo：turbo decoder 僅 4 層（large-v3 為 32 層），
# 多語保留、速度數倍；CT2 再以量化 kernel（CUDA float16 / CPU int8）加速並降 VRAM。
# WHISPER_MODEL_ID 可為 faster-whisper 認得的尺寸名或 HF 上的 CT2 repo；turbo 由 faster-whisper 自官方
# CT2 轉檔下載，download_root 指到本地熱資料目錄（避免 NFS）。
WHISPER_MODEL_ID          = os.environ.get("WHISPER_MODEL_ID", "large-v3-turbo")
# CTranslate2 計算精度：CUDA 預設 float16（準度/速度平衡，要更快可改 int8_float16）；
# CPU 強制 int8（CPU 不支援 float16 推論）。
WHISPER_CUDA_COMPUTE_TYPE = os.environ.get("WHISPER_CUDA_COMPUTE_TYPE", "float16")
WHISPER_CPU_COMPUTE_TYPE  = "int8"
# beam search 寬度：5 為品質/速度平衡（要更快可降為 1=greedy）
WHISPER_BEAM_SIZE         = 5
# 是否以 faster-whisper 內建 Silero VAD 再修剪段內靜音以抑制幻覺；預設關——上游已有 VadStage 閘門
# 與 _filter_hallucination 後處理，關閉可省一次額外 onnxruntime VAD 載入/開銷。要更強過濾可設 True。
WHISPER_VAD_FILTER        = _read_bool_env("WHISPER_VAD_FILTER", False)

# ── Audio Env (PANNs CNN14) ───────────────────────────────────────────────────
# 回傳信心分數前 K 高的分類標籤（AudioSet 527 類）
AUDIO_ENV_TOP_K     = 5
# Whisper / VAD / PANNs 共同要求 16000Hz 採樣率
AUDIO_SAMPLING_RATE = 16000
# 低於此信心分數的分類視為無意義，過濾掉
AUDIO_ENV_MIN_SCORE = 0.01

# ── MediaPipe Face Detection (Tasks API) ──────────────────────────────────────
# 自 mediapipe 0.10.22 起官方 linux wheel 不再附 legacy mp.solutions（python/ 子套件遺失），
# 改用官方主推、在該批 wheel 仍自包含可用的 Tasks API FaceDetector，需指定 .tflite 模型檔。
MEDIAPIPE_MIN_DETECTION_CONFIDENCE = 0.5
# BlazeFace short-range（2m 內）官方預訓練權重，首次使用時自動下載至 model/ 旁
MEDIAPIPE_FACE_MODEL_FILENAME = "blaze_face_short_range.tflite"
MEDIAPIPE_FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector"
    "/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)

# ── LAION Aesthetic Predictor ─────────────────────────────────────────────────
LAION_CLIP_MODEL_ID  = "openai/clip-vit-large-patch14"
LAION_MLP_INPUT_SIZE = 768
LAION_SCORE_MIN      = 1.0   # LAION 原始評分下界
LAION_SCORE_MAX      = 10.0  # LAION 原始評分上界
LAION_WEIGHT_FILENAME = "sac+logos+ava1-l14-linearMSE.pth"
LAION_WEIGHT_URL = (
    "https://github.com/christophschuhmann/improved-aesthetic-predictor"
    "/raw/main/sac+logos+ava1-l14-linearMSE.pth"
)

# ── MUSIQ ─────────────────────────────────────────────────────────────────────
MUSIQ_METRIC_NAME = 'musiq'

# ── Silero VAD ────────────────────────────────────────────────────────────────
VAD_REPO        = 'snakers4/silero-vad'
VAD_SAMPLING_RATE = 16000  # Silero VAD 要求 16000Hz

# ── U²-Net Saliency ───────────────────────────────────────────────────────────
SALIENCY_MODEL_NAME = "u2net"

# ── 共用評分邊界 ───────────────────────────────────────────────────────────────
# 失敗時的保底分數：給予及格分，避免誤砍素材
DEFAULT_FALLBACK_SCORE = 60.0
SCORE_MIN = 0.0
SCORE_MAX = 100.0
