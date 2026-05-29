"""MediaPipe 臉部偵測引擎，提供輕量臉部偵測與 bbox 計算。"""

from __future__ import annotations
from typing import Optional
from PIL import Image

from model.base_model_manager import BaseModelManager, synchronized_inference
from media_processor.models import FaceInfo, SubjectBbox
from config.model_config import MEDIAPIPE_MODEL_SELECTION, MEDIAPIPE_MIN_DETECTION_CONFIDENCE


class MediaPipeModelManager(BaseModelManager):
    """
    配接器模式 (Adapter Pattern)：封裝 MediaPipe Face Detection。
    採用 BlazeFace short-range 模型，輕量（~1MB）、CPU 執行，
    偵測臉部數量、最大臉部佔比，並回傳最大臉部的 SubjectBbox 供裁切定位使用。
    """

    def _initialize(self, device_id: int = 0):
        """初始化 MediaPipe Face Detection。"""
        import mediapipe as mp
        self._face_detection = mp.solutions.face_detection.FaceDetection(
            model_selection=MEDIAPIPE_MODEL_SELECTION,
            min_detection_confidence=MEDIAPIPE_MIN_DETECTION_CONFIDENCE,
        )

    @synchronized_inference
    def detect(self, pil_image: Image.Image) -> tuple[FaceInfo, Optional[SubjectBbox]]:
        """
        對 PIL 圖片執行臉部偵測。
        回傳 (FaceInfo, 最大臉部的 SubjectBbox)；無臉時 SubjectBbox 為 None。
        """
        import numpy as np
        import cv2

        arr = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        img_h, img_w = arr.shape[:2]
        img_area = img_w * img_h

        results = self._face_detection.process(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))

        if not results.detections:
            return FaceInfo(face_count=0, has_faces=False, largest_face_ratio=0.0), None

        face_count = len(results.detections)
        largest_bbox: Optional[SubjectBbox] = None
        largest_area = 0.0
        largest_ratio = 0.0

        for detection in results.detections:
            bb = detection.location_data.relative_bounding_box
            # 將相對座標轉換為像素，再轉百分比
            x1 = max(0.0, bb.xmin * 100)
            y1 = max(0.0, bb.ymin * 100)
            x2 = min(100.0, (bb.xmin + bb.width) * 100)
            y2 = min(100.0, (bb.ymin + bb.height) * 100)
            face_area = (bb.width * img_w) * (bb.height * img_h)
            if face_area > largest_area:
                largest_area = face_area
                largest_ratio = round(face_area / img_area, 4)
                largest_bbox = SubjectBbox(x1=x1, y1=y1, x2=x2, y2=y2)

        face_info = FaceInfo(
            face_count=face_count,
            has_faces=True,
            largest_face_ratio=largest_ratio,
        )
        return face_info, largest_bbox
