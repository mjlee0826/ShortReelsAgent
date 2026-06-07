"""WhisperStage:有語音時做 Whisper 轉錄(GPU,經 BatchCollector 合批);依賴 VadStage。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from config.media_processor_config import BATCH_COLLECT_TIMEOUT_MS, WHISPER_BATCH_SIZE
from config.pipeline_config import WHISPER_BATCH_ENABLED
from media_processor.pipeline.batch_collector import BatchCollectorRegistry, BatchSpec
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.work.video_work import get_video_work

if TYPE_CHECKING:
    from model.whisper_model_manager import WhisperModelManager

_STAGE_NAME = "whisper"

# 本 Stage 的合批規格;key 跨 asset 共享同一個 collector
_WHISPER_SPEC = BatchSpec(
    key="whisper",
    batch_size=WHISPER_BATCH_SIZE,
    timeout_ms=BATCH_COLLECT_TIMEOUT_MS,
    enabled=WHISPER_BATCH_ENABLED,
)


def _whisper_batch(audio_paths: list[str]) -> list[dict]:
    """BatchCollector 合批函式:從多卡 pool 借出 Whisper(或 singleton)一次轉錄多檔(順序一致)。"""
    from model.whisper_model_manager import WhisperModelManager
    from media_processor.pipeline.executor.model_pool_registry import borrow_for_batch
    return borrow_for_batch(WhisperModelManager, _STAGE_NAME, lambda m: m.transcribe_batch(audio_paths))


class WhisperStage(Stage):
    """
    依賴 VadStage:``has_speech`` 為真才轉錄,寫入 ``audio_transcript`` / ``spoken_language``。

    無語音則 no-op(維持 VideoWork 預設空轉錄),逐欄對齊原 ``_analyze_audio``。啟用合批時走
    ``BatchCollector``(``transcribe_batch``),否則單張 ``transcribe``。GPU 資源;singleton 延遲載入。
    """

    def __init__(self):
        """設定 Stage 描述並預備 lazy manager 欄位。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.GPU)
        self._whisper: Optional["WhisperModelManager"] = None

    def _engine(self) -> "WhisperModelManager":
        """延遲取得 Whisper singleton(單張路徑用)。"""
        if self._whisper is None:
            from model.whisper_model_manager import WhisperModelManager
            self._whisper = WhisperModelManager()
        return self._whisper

    def run(self, context: AssetContext) -> None:
        """有語音才轉錄;啟用合批走 collector,否則單張。結果寫入 VideoWork。"""
        work = get_video_work(context)
        if not work.has_speech:
            # 無語音:保留 VideoWork 預設(spoken_language="" / audio_transcript={}),對齊原行為
            return
        if WHISPER_BATCH_ENABLED:
            collector = BatchCollectorRegistry.get(_WHISPER_SPEC, _whisper_batch)
            # submit_and_wait 把跨 thread 的合批等待計入本 stage 的「等資源」(供 compute/wait 拆分)
            transcript = collector.submit_and_wait(work.audio_path)
        else:
            transcript = self._engine().transcribe(work.audio_path)
        work.spoken_language = transcript.get("language", "")
        work.audio_transcript = transcript
