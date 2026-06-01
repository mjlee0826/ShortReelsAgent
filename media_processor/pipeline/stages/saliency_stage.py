"""SaliencyStage:U2-Net 顯著性遮罩 → 主體 bbox(G3 平行群)。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from media_processor.media_strategy import MediaStrategy
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.image_work import get_image_work

if TYPE_CHECKING:
    from model.saliency_model_manager import SaliencyModelManager

_STAGE_NAME = "saliency"


class SaliencyStage(Stage):
    """
    以 U2-Net 取得顯著性遮罩,換算成主體必須保留的 bbox,寫入 ``ImageWork.saliency_bbox``。

    與 FaceDetectStage 在同一平行群並行;兩者分別寫 ``saliency_bbox`` / ``face_bbox`` 互斥欄位,
    最終由 AssemblyImageStage 決定「有臉用臉、否則用 saliency」,故此處不直接動 subject_bbox。
    GPU 資源;singleton manager 延遲載入。
    """

    def __init__(self):
        """設定 Stage 描述並預備 lazy manager 欄位。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.GPU)
        self._saliency: Optional["SaliencyModelManager"] = None

    def _engine(self) -> "SaliencyModelManager":
        """延遲取得 Saliency singleton。"""
        if self._saliency is None:
            from model.saliency_model_manager import SaliencyModelManager
            self._saliency = SaliencyModelManager()
        return self._saliency

    def run(self, context: AssetContext) -> None:
        """取得遮罩並換算 bbox(共用既有 staticmethod,計算與原版一致)。"""
        work = get_image_work(context)
        mask = self._engine().get_saliency_mask(work.pil_image)
        work.saliency_bbox = MediaStrategy._compute_saliency_bbox(mask, work.width, work.height)
