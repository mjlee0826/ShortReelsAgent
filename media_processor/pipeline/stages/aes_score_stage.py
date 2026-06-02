"""AesScoreStage:LAION 美學評分(image / video 共用)。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.frame_analysis import get_frame_analysis

if TYPE_CHECKING:
    from model.laion_model_manager import LaionModelManager

_STAGE_NAME = "aes_score"


class AesScoreStage(Stage):
    """
    以 LAION Aesthetic Predictor 計算當前幀的美學分數,寫入 ``FrameAnalysis.aes_score``(原始值)。

    **image / video 共用**(media-agnostic);只寫 ``aes_score`` 互斥欄位。GPU 資源;singleton 延遲載入。
    Assembly 才對分數 round。代表幀缺失時跳過、留預設 0.0。
    """

    def __init__(self):
        """設定 Stage 描述並預備 lazy manager 欄位。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.GPU)
        self._laion: Optional["LaionModelManager"] = None

    def _engine(self) -> "LaionModelManager":
        """延遲取得 LAION singleton。"""
        if self._laion is None:
            from model.laion_model_manager import LaionModelManager
            self._laion = LaionModelManager()
        return self._laion

    def run(self, context: AssetContext) -> None:
        """計算美學分並寫入當前幀的 aes_score;代表幀缺失時跳過。"""
        frame = get_frame_analysis(context)
        if frame.pil_image is not None:
            frame.aes_score = self._engine().get_aesthetic_score(frame.pil_image)
