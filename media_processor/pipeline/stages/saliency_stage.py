"""SaliencyStage:U2-Net 顯著性遮罩 → 主體 bbox(G3 平行群,CPU)。"""
from __future__ import annotations

from media_processor.media_strategy import MediaStrategy
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.work.image_work import get_image_work

_STAGE_NAME = "saliency"


class SaliencyStage(Stage):
    """
    以 U2-Net 取得顯著性遮罩,換算成主體必須保留的 bbox,寫入 ``ImageWork.saliency_bbox``。

    與 FaceDetectStage 在同一平行群並行;兩者分別寫 ``saliency_bbox`` / ``face_bbox`` 互斥欄位,
    最終由 AssemblyImageStage 決定「有臉用臉、否則用 saliency」,故此處不直接動 subject_bbox。
    CPU 資源(Option 3：U²-Net 改純 CPU onnxruntime，走獨立 CPU pool，不佔 GPU pool 槽)。
    """

    def __init__(self):
        """設定 Stage 描述。"""
        # Option 3：saliency 已改純 CPU（U²-Net via onnxruntime CPU EP），改走 cpu pool，
        # 不再佔用/阻塞較小的 GPU pool（16 緒），讓那些 slot 留給真正的 GPU stage。
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)

    def run(self, context: AssetContext) -> None:
        """取得遮罩並換算 bbox(共用既有 staticmethod,計算與原版一致)。"""
        work = get_image_work(context)
        # saliency 走多卡 pool（每卡一份 + 跨卡 failover）;GPU_POOL_ENABLED=false 自動回退最空卡 singleton
        from media_processor.pipeline.executor.model_pool_registry import run_saliency
        mask = run_saliency(lambda s: s.get_saliency_mask(work.frame.pil_image))
        work.saliency_bbox = MediaStrategy._compute_saliency_bbox(mask, work.width, work.height)
