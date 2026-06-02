"""FaceDetectStage:MediaPipe 臉部偵測,產出 face_info 與 face_bbox(image / video 共用)。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.frame_analysis import get_frame_analysis

if TYPE_CHECKING:
    from model.mediapipe_model_manager import MediaPipeModelManager

_STAGE_NAME = "face_detect"


class FaceDetectStage(Stage):
    """
    以 MediaPipe Tasks FaceDetector 偵測當前幀臉部,寫入 ``face_info`` 與 ``face_bbox``。

    **image / video 共用**。MediaPipe 走 CPU(manager.device="cpu",L2 GpuGate 自動跳過),標記為 CPU 資源。
    只寫 face 相關互斥欄位:image 由 AssemblyImageStage 決定是否以 face_bbox 覆蓋 saliency;
    video 代表幀的 face 僅供 ``faces`` 摘要(subject_bbox 另由 saliency 聯集 / event bbox 決定,不採此 face_bbox)。
    代表幀缺失時跳過、留預設 None(對齊原 video ``pil_mid is None`` 路徑)。
    """

    def __init__(self):
        """設定 Stage 描述並預備 lazy manager 欄位。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)
        self._mediapipe: Optional["MediaPipeModelManager"] = None

    def _engine(self) -> "MediaPipeModelManager":
        """延遲取得 MediaPipe singleton。"""
        if self._mediapipe is None:
            from model.mediapipe_model_manager import MediaPipeModelManager
            self._mediapipe = MediaPipeModelManager()
        return self._mediapipe

    def run(self, context: AssetContext) -> None:
        """偵測臉部並寫入 face_info / face_bbox(無臉時 face_bbox 為 None;代表幀缺失時跳過)。"""
        frame = get_frame_analysis(context)
        if frame.pil_image is None:
            return
        face_info, face_bbox = self._engine().detect(frame.pil_image)
        frame.face_info = face_info
        frame.face_bbox = face_bbox
