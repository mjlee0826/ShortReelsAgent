"""VadStage:對抽出的 wav 做語音活動偵測(VAD),寫入 has_speech(GPU,單張)。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.video_work import audio_file_ready, get_video_work

if TYPE_CHECKING:
    # 僅型別提示;執行期改在 _engine() 內 lazy import,維持 EAGER_MODELS=false 語意
    from model.vad_model_manager import VadModelManager

_STAGE_NAME = "vad"


class VadStage(Stage):
    """
    以 Silero VAD 偵測 wav 是否含人聲,寫入 ``VideoWork.has_speech``,作為 WhisperStage 的閘門。

    Week 3a 由 ``AudioInferenceStage`` 全拆而來:VAD 底層不支援 batch(plan §4.2),維持單張呼叫。
    音訊檔不存在 / 過小(靜音)時跳過、保留預設(無語音),對齊原 ``_analyze_audio`` 短路。
    Silero VAD 在 **CPU** 推論(模型極輕、ms 級;搬上 GPU 的 H2D/D2H 開銷反而更慢、又佔 VRAM 跟
    Qwen 搶),故標記為 **CPU 資源**(走 CPU pool、不佔 GPU 槽);singleton 由啟動 warmup 預載、否則延遲載入。
    """

    def __init__(self):
        """設定 Stage 描述並預備 lazy manager 欄位。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)
        self._vad: Optional["VadModelManager"] = None

    def _engine(self) -> "VadModelManager":
        """延遲取得 VAD singleton(首次使用才載入)。"""
        if self._vad is None:
            from model.vad_model_manager import VadModelManager
            self._vad = VadModelManager()
        return self._vad

    def run(self, context: AssetContext) -> None:
        """音訊有效才跑 VAD 並寫入 has_speech;無效則保留預設 False(維持無語音路徑)。"""
        work = get_video_work(context)
        if audio_file_ready(work.audio_path):
            work.has_speech = self._engine().has_speech(work.audio_path)
