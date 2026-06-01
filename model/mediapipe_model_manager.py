"""MediaPipe 臉部偵測引擎，提供輕量臉部偵測與 bbox 計算。

自 mediapipe 0.10.22 起，官方 linux wheel 不再包含 legacy ``mp.solutions``
（``python/`` 子套件遺失，import 時會出現 "has no attribute 'solutions'"），
改採官方主推、且在該批 wheel 中仍自包含可用的 **Tasks API**（``FaceDetector``）。
對外介面（:meth:`detect` 回傳 ``FaceInfo`` 與 ``SubjectBbox``）維持不變，
故上層 image / video processor 無須改動（Adapter Pattern 的好處）。
"""
from __future__ import annotations
import os
import urllib.request
from typing import Optional

import numpy as np
from PIL import Image
import mediapipe as mp
from mediapipe.tasks.python import vision as mp_vision
from mediapipe.tasks.python.core.base_options import BaseOptions

from model.base_model_manager import BaseModelManager, synchronized_inference
from media_processor.models import FaceInfo, SubjectBbox
from config.model_config import (
    MEDIAPIPE_MIN_DETECTION_CONFIDENCE,
    MEDIAPIPE_FACE_MODEL_FILENAME,
    MEDIAPIPE_FACE_MODEL_URL,
)

# 相對座標 → 百分比的換算係數與上下界（避免 magic number）
_RATIO_TO_PERCENT = 100.0
_PERCENT_MIN = 0.0
_PERCENT_MAX = 100.0
# 最大臉佔比的四捨五入位數
_FACE_RATIO_NDIGITS = 4


class MediaPipeModelManager(BaseModelManager):
    """
    配接器模式 (Adapter Pattern)：封裝 MediaPipe Tasks 的 FaceDetector。
    採用 BlazeFace short-range 模型，輕量、CPU 執行，
    偵測臉部數量、最大臉部佔比，並回傳最大臉部的 SubjectBbox 供裁切定位使用。
    """

    def _initialize(self, device_id: int = 0):
        """載入 MediaPipe Tasks FaceDetector，必要時自動下載 .tflite 模型檔。"""
        # FaceDetector 走 CPU；顯式標記 device 為 cpu，
        # 讓 BaseModelManager 的 L2 GpuGate 依 _uses_gpu 自動跳過
        self.device = "cpu"

        with self._log_load("MediaPipe"):
            # 模型檔固定存放在 model/ 目錄旁，避免 cwd 差異（與 LAION 權重作法一致）
            model_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                MEDIAPIPE_FACE_MODEL_FILENAME,
            )
            if not os.path.exists(model_path):
                print("[MediaPipe] 首次使用，正在下載臉部偵測模型...")
                urllib.request.urlretrieve(MEDIAPIPE_FACE_MODEL_URL, model_path)

            # Tasks API：以 IMAGE 模式（FaceDetectorOptions 預設）建立偵測器
            options = mp_vision.FaceDetectorOptions(
                base_options=BaseOptions(model_asset_path=model_path),
                min_detection_confidence=MEDIAPIPE_MIN_DETECTION_CONFIDENCE,
            )
            self._detector = mp_vision.FaceDetector.create_from_options(options)

    @synchronized_inference
    def detect(self, pil_image: Image.Image) -> tuple[FaceInfo, Optional[SubjectBbox]]:
        """
        對 PIL 圖片執行臉部偵測。
        回傳 (FaceInfo, 最大臉部的 SubjectBbox)；無臉時 SubjectBbox 為 None。
        """
        # Tasks 的 mp.Image 需要 SRGB 格式、且為連續記憶體的 numpy 陣列
        rgb_pil = pil_image if pil_image.mode == "RGB" else pil_image.convert("RGB")
        rgb_array = np.ascontiguousarray(np.array(rgb_pil))
        img_h, img_w = rgb_array.shape[:2]
        img_area = img_w * img_h

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_array)
        result = self._detector.detect(mp_image)

        if not result.detections:
            return FaceInfo(face_count=0, has_faces=False, largest_face_ratio=0.0), None

        face_count = len(result.detections)
        largest_bbox: Optional[SubjectBbox] = None
        largest_area = 0.0
        largest_ratio = 0.0

        for detection in result.detections:
            # Tasks 回傳「絕對像素」bbox（origin_x/origin_y/width/height），
            # 除以影像寬高換算回百分比，對齊舊 legacy relative_bounding_box × 100 的輸出
            bbox = detection.bounding_box
            x1 = max(_PERCENT_MIN, bbox.origin_x / img_w * _RATIO_TO_PERCENT)
            y1 = max(_PERCENT_MIN, bbox.origin_y / img_h * _RATIO_TO_PERCENT)
            x2 = min(_PERCENT_MAX, (bbox.origin_x + bbox.width) / img_w * _RATIO_TO_PERCENT)
            y2 = min(_PERCENT_MAX, (bbox.origin_y + bbox.height) / img_h * _RATIO_TO_PERCENT)
            face_area = bbox.width * bbox.height  # 絕對像素面積
            if face_area > largest_area:
                largest_area = face_area
                largest_ratio = round(face_area / img_area, _FACE_RATIO_NDIGITS)
                largest_bbox = SubjectBbox(x1=x1, y1=y1, x2=x2, y2=y2)

        face_info = FaceInfo(
            face_count=face_count,
            has_faces=True,
            largest_face_ratio=largest_ratio,
        )
        return face_info, largest_bbox
