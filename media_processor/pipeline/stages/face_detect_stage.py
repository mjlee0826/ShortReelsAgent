"""FaceDetectStage:MediaPipe 臉部偵測,產出 face_info 與 face_bbox(image / video 共用)。"""
from __future__ import annotations

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.executor.model_pool_registry import borrow_mediapipe
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.work.frame_analysis import get_frame_analysis

_STAGE_NAME = "face_detect"


class FaceDetectStage(Stage):
    """
    以 MediaPipe Tasks FaceDetector 偵測當前幀臉部,寫入 ``face_info`` 與 ``face_bbox``。

    **image / video 共用**。MediaPipe 走 CPU(manager.device="cpu",L2 GpuGate 自動跳過),標記為 CPU 資源。
    從 MEDIAPIPE_POOL_SIZE 個 instance 的 pool 借出，16 個 asset 可完全並行（zero-queue）。
    只寫 face 相關互斥欄位:image 由 AssemblyImageStage 決定是否以 face_bbox 覆蓋 saliency;
    video 代表幀的 face 僅供 ``faces`` 摘要(subject_bbox 另由 saliency 聯集 / event bbox 決定,不採此 face_bbox)。
    代表幀缺失時跳過、留預設 None(對齊原 video ``pil_mid is None`` 路徑)。
    """

    def __init__(self):
        """設定 Stage 描述。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)

    def run(self, context: AssetContext) -> None:
        """偵測臉部並寫入 face_info / face_bbox(無臉時 face_bbox 為 None;代表幀缺失時跳過)。"""
        frame = get_frame_analysis(context)
        if frame.pil_image is None:
            return
        with borrow_mediapipe() as mediapipe:
            face_info, face_bbox = mediapipe.detect(frame.pil_image)
        frame.face_info = face_info
        frame.face_bbox = face_bbox
