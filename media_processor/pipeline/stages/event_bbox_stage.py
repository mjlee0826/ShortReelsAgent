"""EventBboxStage:為 Gemini 每個多模態事件決定主體 bbox(優先採 Gemini 直接給的框,無效才退 CV;Complex)。"""
from __future__ import annotations

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.executor.model_pool_registry import borrow_mediapipe, run_saliency
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.utils.video_frame_utils import compute_saliency_bbox_at_time
from media_processor.pipeline.utils.vlm_bbox_utils import parse_gemini_bbox
from media_processor.pipeline.work.video_work import get_video_work

_STAGE_NAME = "event_bbox"
# 多模態事件清單在 Gemini 結果中的鍵(對齊 ComplexVideoMetadata.multimodal_event_index)
_EVENT_INDEX_KEY = "multimodal_event_index"


class EventBboxStage(Stage):
    """
    為 SemanticVideo(Gemini)產出的每個多模態事件決定主體 bbox(就地寫回 ``event["subject_bbox"]``)。

    僅 Complex 影片需要。**優先採 Gemini 在 prompt 直接給的逐 event 主體框**(語意更準、且免逐幀解碼);
    僅當該框缺失 / 格式不符 / 退化時,才退回原 CV 路徑:於 key_timestamp 精確幀以 ``compute_saliency_bbox_at_time``
    抓 U²-Net saliency + 臉部覆蓋。若**全部** event 都由 Gemini 提供框,則完全不借 saliency / mediapipe(省資源)。

    key_timestamp 優先採模型指定的高潮秒數;缺失或超出區段範圍時退回區間中點(防呆,對齊原版)。
    CPU 資源(Option 3：U²-Net 改純 CPU onnxruntime)；MediaPipe 從 pool 借出（borrow_mediapipe）。
    """

    def __init__(self):
        """設定 Stage 描述。"""
        # Option 3：saliency 已改純 CPU，改走 cpu pool（不再佔用較小的 GPU pool）
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)

    def run(self, context: AssetContext) -> None:
        """先以 Gemini 直接給的框填掉能填的;剩餘無框 event 才借引擎走 CV fallback。"""
        work = get_video_work(context)
        events = work.vlm_result.get(_EVENT_INDEX_KEY, [])
        if not events:
            return
        # 第一輪:採用 Gemini 直接給的主體框,收集仍需 CV fallback 的 event
        pending = self._apply_vlm_bboxes(events)
        if not pending:
            # 全部由 Gemini 提供 → 不借 saliency / mediapipe(免去無謂的解碼與推論)
            return
        # 第二輪:僅對沒有有效 VLM 框的 event 借引擎,於精確幀算 CV bbox
        with borrow_mediapipe() as mediapipe:
            run_saliency(
                lambda s: self._fill_cv_bboxes(pending, context.file_path, work.duration, s, mediapipe)
            )

    @staticmethod
    def _apply_vlm_bboxes(events) -> list:
        """逐 event 嘗試採用 Gemini 直接給的框;成功就地寫回 dict,否則收集進待 CV 清單回傳。"""
        pending = []
        for event in events:
            vlm_bbox = parse_gemini_bbox(event.get("subject_bbox"))
            if vlm_bbox is not None:
                event["subject_bbox"] = vlm_bbox.model_dump()
            else:
                pending.append(event)
        return pending

    def _fill_cv_bboxes(self, events, file_path, duration, saliency, mediapipe) -> None:
        """對沒有有效 VLM 框的 event:決定高潮秒數 → CV 算 bbox → 就地寫回(借出的 saliency 跑完整批)。"""
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
