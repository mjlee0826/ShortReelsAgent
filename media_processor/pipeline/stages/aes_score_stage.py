"""AesScoreStage:LAION 美學評分(G3 平行群)。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.image_work import get_image_work

if TYPE_CHECKING:
    from model.laion_model_manager import LaionModelManager

_STAGE_NAME = "aes_score"


class AesScoreStage(Stage):
    """
    以 LAION Aesthetic Predictor 計算美學分數,寫入 ``ImageWork.aes_score``(原始值)。

    與 saliency / cv / face / exif / semantic 在同一平行群;只寫 ``aes_score`` 互斥欄位。
    GPU 資源;singleton manager 延遲載入。Assembly 才對分數 round。
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
        """計算美學分並寫入 ImageWork.aes_score。"""
        work = get_image_work(context)
        work.aes_score = self._engine().get_aesthetic_score(work.pil_image)
