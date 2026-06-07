"""
跨層共用的純 value object (Value Object Pattern)。

``SubjectBbox`` / ``FaceInfo`` 同時被 media_processor(消費端)與 model 的 MediaPipe
manager(生產端)使用。放在這個不依賴任何專案模組的中性葉節點,讓兩層都能 import 而不
產生反向依賴 ── 維持「media_processor → model」單向依賴規則。
"""
from __future__ import annotations

from pydantic import BaseModel


class SubjectBbox(BaseModel):
    """畫面主體必須保留的矩形區域,以百分比座標表示(0–100)。"""
    x1: float
    y1: float
    x2: float
    y2: float


class FaceInfo(BaseModel):
    """臉部偵測結果摘要。"""
    face_count: int
    has_faces: bool
    largest_face_ratio: float  # 最大臉部面積 / 畫面面積
