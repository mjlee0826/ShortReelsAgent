"""SaliencyUnionStage:頭/中/尾三幀 saliency bbox 取聯集(GPU,Simple)。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from config.media_processor_config import SALIENCY_SAMPLE_POSITIONS
from media_processor.media_strategy import MediaStrategy
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.video_frame_utils import compute_saliency_bbox_at_time
from media_processor.pipeline.stages.video_work import get_video_work

if TYPE_CHECKING:
    from model.mediapipe_model_manager import MediaPipeModelManager
    from model.saliency_model_manager import SaliencyModelManager

_STAGE_NAME = "saliency_union"


class SaliencyUnionStage(Stage):
    """
    取影片頭(10%)/ 中(50%)/ 尾(90%)三幀的 saliency bbox 取聯集,寫入 ``VideoWork.subject_bbox``。

    聯集 bbox 代表整段影片主體曾出現的最大安全區域,確保 9:16 裁切不截斷主體(對齊原 ``_get_saliency_bbox_union``)。
    僅 Simple 影片需要(Complex 以逐 event bbox 取代)。每幀內部「saliency mask → bbox → 有臉覆蓋」由
    ``compute_saliency_bbox_at_time`` 處理。GPU 資源(U2-Net);saliency / mediapipe singleton 延遲載入並注入工具函式。
    """

    def __init__(self):
        """設定 Stage 描述並預備 saliency / mediapipe 兩個 lazy manager。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.GPU)
        self._saliency: Optional["SaliencyModelManager"] = None
        self._mediapipe: Optional["MediaPipeModelManager"] = None

    def _saliency_engine(self) -> "SaliencyModelManager":
        """延遲取得 U2-Net saliency singleton。"""
        if self._saliency is None:
            from model.saliency_model_manager import SaliencyModelManager
            self._saliency = SaliencyModelManager()
        return self._saliency

    def _mediapipe_engine(self) -> "MediaPipeModelManager":
        """延遲取得 MediaPipe singleton。"""
        if self._mediapipe is None:
            from model.mediapipe_model_manager import MediaPipeModelManager
            self._mediapipe = MediaPipeModelManager()
        return self._mediapipe

    def run(self, context: AssetContext) -> None:
        """頭/中/尾三幀各算 bbox,取聯集寫入 VideoWork.subject_bbox。"""
        work = get_video_work(context)
        saliency = self._saliency_engine()
        mediapipe = self._mediapipe_engine()
        sample_times = [work.duration * position for position in SALIENCY_SAMPLE_POSITIONS]
        bboxes = [
            compute_saliency_bbox_at_time(context.file_path, t, saliency, mediapipe)
            for t in sample_times
        ]
        work.subject_bbox = MediaStrategy._union_bboxes(bboxes)
