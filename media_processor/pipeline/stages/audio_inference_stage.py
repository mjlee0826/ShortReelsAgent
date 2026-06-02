"""AudioInferenceStage:對抽出的 wav 做 VAD → Whisper → 環境音分類(GPU)。"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

from config.media_processor_config import MINIMUM_AUDIO_FILE_BYTES
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.video_work import get_video_work

if TYPE_CHECKING:
    from model.audio_env_model_manager import AudioEnvModelManager
    from model.vad_model_manager import VadModelManager
    from model.whisper_model_manager import WhisperModelManager

_STAGE_NAME = "audio_inference"


class AudioInferenceStage(Stage):
    """
    對 AudioExtractionStage 抽出的 wav 做三段音訊分析:VAD 偵測語音 → (有語音才)Whisper 轉錄 → 環境音分類。

    對齊原 ``_analyze_audio``:音訊檔不存在或過小(靜音影片)時直接保留 VideoWork 預設(無語音 / 空轉錄)。
    三個模型皆 GPU 推論(各自 @synchronized_inference 經 L2 GpuGate 保護),標記為 GPU 資源;singleton 延遲載入。
    """

    def __init__(self):
        """設定 Stage 描述並預備三個 lazy manager 欄位。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.GPU)
        self._vad: Optional["VadModelManager"] = None
        self._whisper: Optional["WhisperModelManager"] = None
        self._audio_env: Optional["AudioEnvModelManager"] = None

    def _vad_engine(self) -> "VadModelManager":
        """延遲取得 VAD singleton。"""
        if self._vad is None:
            from model.vad_model_manager import VadModelManager
            self._vad = VadModelManager()
        return self._vad

    def _whisper_engine(self) -> "WhisperModelManager":
        """延遲取得 Whisper singleton。"""
        if self._whisper is None:
            from model.whisper_model_manager import WhisperModelManager
            self._whisper = WhisperModelManager()
        return self._whisper

    def _audio_env_engine(self) -> "AudioEnvModelManager":
        """延遲取得環境音(PANNs CNN14)singleton。"""
        if self._audio_env is None:
            from model.audio_env_model_manager import AudioEnvModelManager
            self._audio_env = AudioEnvModelManager()
        return self._audio_env

    def run(self, context: AssetContext) -> None:
        """小檔短路 → VAD → (有語音)Whisper → 環境音,結果寫入 VideoWork。"""
        work = get_video_work(context)
        audio_path = work.audio_path
        # 靜音 / 無音軌:ffmpeg 產出近乎空的 wav,小於門檻直接視為無效並保留預設(對齊原 _analyze_audio)
        if (
            not audio_path
            or not os.path.exists(audio_path)
            or os.path.getsize(audio_path) <= MINIMUM_AUDIO_FILE_BYTES
        ):
            return

        has_speech = self._vad_engine().has_speech(audio_path)
        transcript: dict = {}
        if has_speech:
            transcript = self._whisper_engine().transcribe(audio_path)
        work.has_speech = has_speech
        work.spoken_language = transcript.get("language", "")
        work.audio_transcript = transcript
        work.environmental_sounds = self._audio_env_engine().classify_environment(audio_path)
