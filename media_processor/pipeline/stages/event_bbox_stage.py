"""EventBboxStage:為 Gemini 每個多模態事件算精準畫面 bbox(GPU,Complex)。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.video_frame_utils import compute_saliency_bbox_at_time
from media_processor.pipeline.stages.video_work import get_video_work

if TYPE_CHECKING:
    from model.mediapipe_model_manager import MediaPipeModelManager

_STAGE_NAME = "event_bbox"
# 多模態事件清單在 Gemini 結果中的鍵(對齊 ComplexVideoMetadata.multimodal_event_index)
_EVENT_INDEX_KEY = "multimodal_event_index"


class EventBboxStage(Stage):
    """
    為 SemanticVideo(Gemini)產出的每個多模態事件,於其視聽高潮秒數計算精準畫面 bbox(就地補進事件)。

    僅 Complex 影片需要。key_timestamp 優先採模型指定的高潮秒數;缺失或超出區段範圍時退回區間中點
    (逐字對齊原 ComplexVideoProcessor 後處理)。每個事件的 bbox 以 ``compute_saliency_bbox_at_time`` 對
    **原始**影片抓幀計算,結果 ``model_dump()`` 寫回 ``event["subject_bbox"]``。GPU 資源(U2-Net)。
    """

    def __init__(self):
        """設定 Stage 描述並預備 saliency / mediapipe 兩個 lazy manager。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.GPU)
        self._mediapipe: Optional["MediaPipeModelManager"] = None

    def _mediapipe_engine(self) -> "MediaPipeModelManager":
        """延遲取得 MediaPipe singleton。"""
        if self._mediapipe is None:
            from model.mediapipe_model_manager import MediaPipeModelManager
            self._mediapipe = MediaPipeModelManager()
        return self._mediapipe

    def run(self, context: AssetContext) -> None:
        """逐事件決定高潮秒數 → 算 bbox → 就地寫回 event["subject_bbox"]。"""
        work = get_video_work(context)
        events = work.vlm_result.get(_EVENT_INDEX_KEY, [])
        if not events:
            return
        mediapipe = self._mediapipe_engine()
        # 借一個 saliency（多卡 pool + 跨卡 failover）跑完整批 event 的 bbox
        from media_processor.pipeline.executor.model_pool_registry import run_saliency
        run_saliency(
            lambda s: self._fill_event_bboxes(events, context.file_path, work.duration, s, mediapipe)
        )

    def _fill_event_bboxes(self, events, file_path, duration, saliency, mediapipe) -> None:
        """逐 event 決定高潮秒數 → 算 bbox → 就地寫回 ``event["subject_bbox"]``（借出的 saliency 跑完整批）。"""
        for event in events:
            start_t = float(event.get("start_time", 0.0))
            end_t = float(event.get("end_time", duration))
            # 優先採模型指定的高潮秒數;缺失或超出區段則退回區間中點(防呆,對齊原版)
            key_t = event.get("key_timestamp")
            if key_t is None or not (start_t <= float(key_t) <= end_t):
                key_t = start_t + (end_t - start_t) / 2.0
            else:
                key_t = float(key_t)
            bbox = compute_saliency_bbox_at_time(file_path, key_t, saliency, mediapipe)
            event["subject_bbox"] = bbox.model_dump()
