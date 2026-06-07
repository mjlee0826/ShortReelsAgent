"""SaliencyUnionStage:頭/中/尾三幀 saliency bbox 取聯集(CPU,Simple)。"""
from __future__ import annotations

from config.media_processor_config import SALIENCY_SAMPLE_POSITIONS
from media_processor.media_strategy import MediaStrategy
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.executor.model_pool_registry import borrow_mediapipe, run_saliency
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.utils.video_frame_utils import compute_saliency_bbox_at_time
from media_processor.pipeline.work.video_work import get_video_work

_STAGE_NAME = "saliency_union"


class SaliencyUnionStage(Stage):
    """
    取影片頭(10%)/ 中(50%)/ 尾(90%)三幀的 saliency bbox 取聯集,寫入 ``VideoWork.subject_bbox``。

    聯集 bbox 代表整段影片主體曾出現的最大安全區域,確保 9:16 裁切不截斷主體(對齊原 ``_get_saliency_bbox_union``)。
    僅 Simple 影片需要(Complex 以逐 event bbox 取代)。每幀內部「saliency mask → bbox → 有臉覆蓋」由
    ``compute_saliency_bbox_at_time`` 處理。CPU 資源(Option 3：U²-Net 改純 CPU onnxruntime)；MediaPipe 從 pool 借出（borrow_mediapipe）。
    """

    def __init__(self):
        """設定 Stage 描述。"""
        # Option 3：saliency 已改純 CPU，改走 cpu pool（不再佔用較小的 GPU pool）
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)

    def run(self, context: AssetContext) -> None:
        """頭/中/尾三幀各算 bbox,取聯集寫入 VideoWork.subject_bbox。"""
        work = get_video_work(context)
        sample_times = [work.duration * position for position in SALIENCY_SAMPLE_POSITIONS]
        # MediaPipe 從 pool 借出（MEDIAPIPE_POOL_SIZE 個 instance，zero-queue 並行）
        with borrow_mediapipe() as mediapipe:
            # 借一個 saliency（多卡 pool + 跨卡 failover）跑完頭/中/尾三幀
            bboxes = run_saliency(
                lambda s: [
                    compute_saliency_bbox_at_time(context.file_path, t, s, mediapipe)
                    for t in sample_times
                ]
            )
        work.subject_bbox = MediaStrategy._union_bboxes(bboxes)
