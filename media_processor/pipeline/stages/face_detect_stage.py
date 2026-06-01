"""FaceDetectStage:MediaPipe 臉部偵測,產出 face_info 與 face_bbox(G3 平行群)。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.image_work import get_image_work

if TYPE_CHECKING:
    from model.mediapipe_model_manager import MediaPipeModelManager

_STAGE_NAME = "face_detect"


class FaceDetectStage(Stage):
    """
    以 MediaPipe Tasks FaceDetector 偵測臉部,寫入 ``face_info`` 與 ``face_bbox``。

    MediaPipe 走 CPU(manager.device="cpu",L2 GpuGate 自動跳過),標記為 CPU 資源。
    只寫 face 相關互斥欄位;是否用 face_bbox 覆蓋 saliency_bbox 留給 AssemblyImageStage 決定。
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
        """偵測臉部並寫入 face_info / face_bbox(無臉時 face_bbox 為 None)。"""
        work = get_image_work(context)
        face_info, face_bbox = self._engine().detect(work.pil_image)
        work.face_info = face_info
        work.face_bbox = face_bbox
