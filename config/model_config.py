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
    "QWEN_LEGACY_MODEL_ID",
    "QWEN_USE_4BIT",
    "QWEN_USE_FLASH_ATTN",
    "QWEN_MAX_NEW_TOKENS",
    "QWEN_MAX_PIXELS",
    "QWEN_FPS_TIMECODED",
    "QWEN_FPS_DEFAULT",
    # Whisper
    "WHISPER_MODEL_ID",
    "WHISPER_CHUNK_LENGTH_SEC",
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
# 模型一律從官方 base 載入，再由 bitsandbytes 即時量化（4-bit 主、8-bit 後備）。
# 原社群 compressed-tensors AWQ（cyankiwi）在 transformers 推理時會解壓成 bf16、
# runtime 不省 VRAM，已棄用。
QWEN_LEGACY_MODEL_ID = "Qwen/Qwen3-VL-8B-Instruct"
# Processor (tokenizer + image preprocessor) 從官方 base model 載入
QWEN_PROCESSOR_ID    = QWEN_LEGACY_MODEL_ID


def _read_bool_env(env_name: str, default: bool) -> bool:
    """讀取 env var 並轉為 bool，接受 true/1/yes/on 等常見字串。"""
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


# 啟動時決定走哪條 Qwen 路徑（Feature Toggle）；rollback 時設 false
QWEN_USE_4BIT        = _read_bool_env("QWEN_USE_4BIT", QWEN_USE_4BIT_DEFAULT)
# Flash Attention 2 開關，安裝失敗時 QwenModelManager 內部會 fallback 到 sdpa
QWEN_USE_FLASH_ATTN = _read_bool_env("QWEN_USE_FLASH_ATTN", True)
# 量化改用 bitsandbytes（4-bit/8-bit 皆即時量化官方 base model），不再用 cyankiwi
# compressed-tensors AWQ —— 後者在 transformers 推理時會整包解壓成 bf16、runtime 不省
# VRAM（實測載入 7.5GB → 推理 18GB；真正的 4-bit kernel 僅 vLLM 有）。
# 故 model id 一律指向官方 base，由 BitsAndBytesConfig 即時量化。
QWEN_MODEL_ID       = QWEN_LEGACY_MODEL_ID

QWEN_MAX_NEW_TOKENS = 512
# 限制影像解析度以節省 VRAM（pixel 數上限）
QWEN_MAX_PIXELS     = 100352
# 時間碼模式需要較高採樣率以捕捉動作切換點
QWEN_FPS_TIMECODED  = 2.0
QWEN_FPS_DEFAULT    = 1.0

# ── Whisper ───────────────────────────────────────────────────────────────────
WHISPER_MODEL_ID        = "openai/whisper-large-v3"
WHISPER_CHUNK_LENGTH_SEC = 30

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
