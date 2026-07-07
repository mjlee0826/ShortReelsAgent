"""WhisperStage:有語音時做 Whisper 轉錄(GPU,經共享 pool 借出);依賴 VadStage。"""
from __future__ import annotations

from config.pipeline_config import GPU_POOL_ENABLED
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.work.video_work import get_video_work

_STAGE_NAME = "whisper"


class WhisperStage(Stage):
    """
    依賴 VadStage:``has_speech`` 為真才轉錄,寫入 ``audio_transcript`` / ``spoken_language``。

    無語音則 no-op(維持 VideoWork 預設空轉錄),逐欄對齊原 ``_analyze_audio``。
    跨檔合批已移除（faster-whisper 無多檔 forward,舊路徑是循序假合批:無吞吐收益、純增隊頭延遲）;
    單檔內的分塊批次加速由 ``WhisperModelManager`` 的 ``BatchedInferencePipeline`` 承擔,本 Stage 透明。
    ``GPU_POOL_ENABLED`` 時從 capacity 規劃的 pool 借出(享多卡分散 + borrow 即時 VRAM 重檢事件與
    持續 OOM 換卡),否則回退 device-0 singleton(與 semantic stage 同構)。
    """

    def __init__(self):
        """設定 Stage 描述。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.GPU)

    def run(self, context: AssetContext) -> None:
        """有語音才轉錄;經 pool 借出 Whisper 執行,結果寫入 VideoWork。"""
        work = get_video_work(context)
        if not work.has_speech:
            # 無語音:保留 VideoWork 預設(spoken_language="" / audio_transcript={}),對齊原行為
            return
        transcript = self._transcribe_via_pool(work.audio_path, context)
        work.spoken_language = transcript.get("language", "")
        work.audio_transcript = transcript

    @staticmethod
    def _transcribe_via_pool(audio_path: str, context: AssetContext) -> dict:
        """``GPU_POOL_ENABLED`` 時走多卡 pool(含 failover 換卡),否則 device-0 singleton。"""
        from model.managers.whisper_model_manager import WhisperModelManager

        if not GPU_POOL_ENABLED:
            return WhisperModelManager().transcribe(audio_path)
        from media_processor.pipeline.executor.model_pool_registry import ModelPoolRegistry

        observer = ModelPoolRegistry.make_borrow_observer(
            context.tracker, context.asset_id, _STAGE_NAME
        )
        return ModelPoolRegistry.instance().get_pool(WhisperModelManager).run_with_failover(
            lambda whisper: whisper.transcribe(audio_path), observer=observer
        )
