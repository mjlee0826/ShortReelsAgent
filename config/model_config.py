"""
模型層設定集中管理 (Configuration Object Pattern)。
model/ 底下所有 manager 的常數統一在此定義，對外是唯一的 import 來源。
constants.py 中已有的 model 相關常數，在此處 re-export，
讓 model 層只需 import model_config，不需知道值的實際出處。
"""
from config.constants import (
    GEMINI_VIDEO_PROCESSING_MAX_POLL as GEMINI_POLL_MAX_COUNT,
    GEMINI_VIDEO_POLL_INTERVAL_SEC   as GEMINI_POLL_INTERVAL_SEC,
    HALLUCINATION_REPEAT_THRESHOLD   as WHISPER_HALLUCINATION_THRESHOLD,
    MUSIQ_MAX_INPUT_SIZE             as MUSIQ_MAX_SHORT_SIDE,
)

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
    "QWEN_MAX_NEW_TOKENS",
    "QWEN_MAX_PIXELS",
    "QWEN_FPS_TIMECODED",
    "QWEN_FPS_DEFAULT",
    # Whisper
    "WHISPER_MODEL_ID",
    "WHISPER_CHUNK_LENGTH_SEC",
    # Audio Env
    "AUDIO_ENV_MODEL_ID",
    "AUDIO_ENV_MAX_NEW_TOKENS",
    "AUDIO_ENV_NUM_BEAMS",
    "AUDIO_SAMPLING_RATE",
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
]

# ── Gemini ────────────────────────────────────────────────────────────────────
GEMINI_DEFAULT_MODEL = 'gemini-2.5-flash'
GEMINI_STRONG_MODEL  = 'gemini-3.1-pro-preview'

# ── Qwen3-VL ─────────────────────────────────────────────────────────────────
QWEN_MODEL_ID       = "Qwen/Qwen3-VL-8B-Instruct"
QWEN_MAX_NEW_TOKENS = 512
# 限制影像解析度以節省 VRAM（pixel 數上限）
QWEN_MAX_PIXELS     = 100352
# 時間碼模式需要較高採樣率以捕捉動作切換點
QWEN_FPS_TIMECODED  = 2.0
QWEN_FPS_DEFAULT    = 1.0

# ── Whisper ───────────────────────────────────────────────────────────────────
WHISPER_MODEL_ID        = "openai/whisper-large-v3"
WHISPER_CHUNK_LENGTH_SEC = 30

# ── Audio Env (Whisper-tiny audio captioning) ─────────────────────────────────
AUDIO_ENV_MODEL_ID      = "MU-NLPC/whisper-tiny-audio-captioning"
# 環境音描述通常很短，限制長度以加速推論
AUDIO_ENV_MAX_NEW_TOKENS = 64
AUDIO_ENV_NUM_BEAMS      = 3
# Whisper 架構嚴格要求 16000Hz 採樣率
AUDIO_SAMPLING_RATE      = 16000

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
