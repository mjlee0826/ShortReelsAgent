"""AudioExtractionStage:用 ffmpeg 抽出 AI 分析用單聲道 wav(IO)。"""
from __future__ import annotations

import tempfile

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.video_work import get_video_work
from media_tools.ffmpeg_adapter import FFmpegAdapter

_STAGE_NAME = "audio_extraction"
# 暫存音訊副檔名(對齊原 process() 的 NamedTemporaryFile(suffix=".wav"))
_AUDIO_SUFFIX = ".wav"


class AudioExtractionStage(Stage):
    """
    以 FFmpeg 抽出 AI 分析專用的單聲道 wav 暫存檔,路徑寫入 ``VideoWork.audio_path``。

    暫存檔登記到 ``context.temp_paths``,由 Pipeline 結束時統一刪除(取代原 process() 的 finally)。
    標記為 IO 資源(ffmpeg 子程序);後續 VadStage / WhisperStage / AudioEnvStage 對此檔做 VAD / Whisper / 環境音分析。
    """

    def __init__(self):
        """設定 Stage 描述並建立 FFmpeg 配接器。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.IO)
        self._ffmpeg = FFmpegAdapter()

    def run(self, context: AssetContext) -> None:
        """建立 wav 暫存檔 → ffmpeg 抽音 → 記錄路徑並登記待清除。"""
        work = get_video_work(context)
        temp_audio = tempfile.NamedTemporaryFile(suffix=_AUDIO_SUFFIX, delete=False)
        audio_path = temp_audio.name
        temp_audio.close()
        # 先登記待清除,確保即使 extract 後續出錯,Pipeline finally 仍會刪掉此檔
        context.temp_paths.append(audio_path)
        self._ffmpeg.extract_ai_audio(context.file_path, audio_path)
        work.audio_path = audio_path
