"""
VideoWork:影片各細粒度 Stage 之間傳遞的中間狀態容器 (Blackboard / Value Object Pattern)。

``AbstractVideoProcessor.process()`` 拆成多個 Stage 後,中間結果需在 Stage 間流動,
集中存放於 ``AssetContext.scratch[VIDEO_WORK_KEY]``。與 ImageWork 比照:把「對中間代表幀的 per-frame
分析」抽到共用的 :class:`FrameAnalysis`(``VideoWork.frame``),讓 TechScore / AesScore / CVFeatures /
FaceDetect / RejectFilter 五個 Stage 與圖片共用;VideoWork 自身保留影片**專有**欄位(metadata、
音訊鏈、場景切點、動態強度、三幀聯集 bbox、暫存檔路徑、影片級語意結果)。

並行安全:平行群的各 Stage 只寫入**不同 attribute**(audio 寫音訊欄位、scene 寫 scene_cuts…),
CPython GIL 下單一 attribute 賦值為原子操作,無 torn write。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from config.media_processor_config import MINIMUM_AUDIO_FILE_BYTES
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.work.frame_analysis import FrameAnalysis

# AssetContext.scratch 中存放 VideoWork 的唯一鍵;集中為常數避免 magic string 散落各 Stage
VIDEO_WORK_KEY = "video"


@dataclass
class VideoWork:
    """
    單部影片流經各 Stage 時的中間產物集合。

    DecodeVideoStage 建立並填入影片 metadata 與代表幀;後續 Stage 各自補上對應 attribute,
    AssemblyVideoStage 讀齊組成 ``VideoMetadata``(Simple)或 ``ComplexVideoMetadata``(Complex)。
    所有欄位帶預設值,對齊原 processor 的「代表幀 None / 無音訊」等降級路徑。
    """

    # ── DecodeVideoStage 產出:影片 metadata ─────────────────────────────────
    width: int = 0
    height: int = 0
    aspect_ratio: float = 0.0
    fps: float = 0.0
    duration: float = 0.0
    creation_time: str = ""
    location_gps: str = ""
    # 中間代表幀的 per-frame 分析(tech/aes/色彩/臉);與圖片共用的 per-frame Stage 寫入
    frame: FrameAnalysis = field(default_factory=FrameAnalysis)

    # ── 暫存檔路徑(由對應 Stage 建立並登記到 context.temp_paths,結束時統一清除)──
    audio_path: Optional[str] = None     # AudioExtractionStage 抽出的 wav

    # ── 音訊分析(VadStage / WhisperStage / AudioEnvStage 產出)──────────────
    has_speech: bool = False
    spoken_language: str = ""
    audio_transcript: dict[str, Any] = field(default_factory=dict)
    environmental_sounds: list[Any] = field(default_factory=list)

    # ── 影片結構與視覺(各對應 Stage 產出)──────────────────────────────────
    scene_cuts: list[float] = field(default_factory=list)   # SceneCutStage
    motion_intensity: str = ""                              # MotionIntensityStage(Simple)

    # ── 語意(SemanticVideoStage 產出;Qwen 全局 / Gemini 時間碼事件索引)──────
    vlm_result: dict[str, Any] = field(default_factory=dict)


def get_video_work(context: AssetContext) -> VideoWork:
    """
    從 ``context.scratch`` 取出本 asset 的 VideoWork(DecodeVideoStage 已建立)。

    缺少時拋出明確錯誤而非 KeyError,方便定位「Decode 未先執行」的編排錯誤;
    此例外會被 Pipeline 的 ``_run_stage`` 統一隔離成該 asset 的 error 狀態。
    """
    work = context.scratch.get(VIDEO_WORK_KEY)
    if work is None:
        raise RuntimeError(
            f"VideoWork 尚未建立(asset={context.asset_id});DecodeVideoStage 必須先於其他影片 Stage 執行"
        )
    return work


def audio_file_ready(audio_path: Optional[str]) -> bool:
    """
    判斷 AudioExtractionStage 抽出的 wav 是否為有效音訊(VAD / AudioEnv 共用守門)。

    靜音 / 無音軌時 ffmpeg 會產出近乎空的 wav,小於 ``MINIMUM_AUDIO_FILE_BYTES`` 視為無效;
    無效時音訊類 Stage 直接保留 VideoWork 預設(無語音 / 空轉錄 / 空環境音),對齊原 ``_analyze_audio`` 短路。
    """
    return bool(
        audio_path
        and os.path.exists(audio_path)
        and os.path.getsize(audio_path) > MINIMUM_AUDIO_FILE_BYTES
    )
