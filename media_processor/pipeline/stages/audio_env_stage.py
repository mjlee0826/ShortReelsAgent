"""AudioEnvStage:環境音分類(GPU,經 BatchCollector 合批);獨立於 VAD/Whisper。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from config.media_processor_config import AUDIO_ENV_BATCH_SIZE, BATCH_COLLECT_TIMEOUT_MS
from config.pipeline_config import AUDIO_ENV_BATCH_ENABLED
from media_processor.pipeline.batch_collector import BatchCollectorRegistry, BatchSpec
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.work.video_work import audio_file_ready, get_video_work

if TYPE_CHECKING:
    from model.managers.audio_env_model_manager import AudioEnvModelManager

_STAGE_NAME = "audio_env"

# 本 Stage 的合批規格;key 跨 asset 共享同一個 collector
_AUDIO_ENV_SPEC = BatchSpec(
    key="audio_env",
    batch_size=AUDIO_ENV_BATCH_SIZE,
    timeout_ms=BATCH_COLLECT_TIMEOUT_MS,
    enabled=AUDIO_ENV_BATCH_ENABLED,
)


def _audio_env_batch(audio_paths: list[str]) -> list[list]:
    """BatchCollector 合批函式:從多卡 pool 借出 AudioEnv(或 singleton)一次分類多檔(順序一致)。"""
    from model.managers.audio_env_model_manager import AudioEnvModelManager
    from media_processor.pipeline.executor.model_pool_registry import borrow_for_batch
    return borrow_for_batch(AudioEnvModelManager, _STAGE_NAME, lambda m: m.classify_environment_batch(audio_paths))


class AudioEnvStage(Stage):
    """
    對 wav 做 PANNs CNN14 環境音分類,寫入 ``VideoWork.environmental_sounds``。

    本 Stage **只依賴 audio_extract**(與 VAD/Whisper 無依賴),DAG 中可與語音鏈並行,
    修正原 ``AudioInferenceStage`` 把環境音排在 Whisper 之後的過度序列化。音訊無效時跳過、保留空環境音。
    啟用合批時走 ``BatchCollector``,否則單張。GPU 資源;singleton 延遲載入。
    """

    def __init__(self):
        """設定 Stage 描述並預備 lazy manager 欄位。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.GPU)
        self._audio_env: Optional["AudioEnvModelManager"] = None

    def _engine(self) -> "AudioEnvModelManager":
        """延遲取得環境音(PANNs CNN14)singleton(單張路徑用)。"""
        if self._audio_env is None:
            from model.managers.audio_env_model_manager import AudioEnvModelManager
            self._audio_env = AudioEnvModelManager()
        return self._audio_env

    def run(self, context: AssetContext) -> None:
        """音訊有效才分類;啟用合批走 collector,否則單張。結果寫入 VideoWork。"""
        work = get_video_work(context)
        if not audio_file_ready(work.audio_path):
            return
        if AUDIO_ENV_BATCH_ENABLED:
            collector = BatchCollectorRegistry.get(_AUDIO_ENV_SPEC, _audio_env_batch)
            # submit_and_wait 把跨 thread 的合批等待計入本 stage 的「等資源」(供 compute/wait 拆分)
            work.environmental_sounds = collector.submit_and_wait(work.audio_path)
        else:
            work.environmental_sounds = self._engine().classify_environment(work.audio_path)
