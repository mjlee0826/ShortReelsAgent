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


class SubjectCandidate(BaseModel):
    """
    VLM 排序輸出的單一候選主體(top-N 選框用)。

    由 prompt 要求模型「由信心高→低」列出畫面前幾名主體;下游 ``select_best_candidate``
    依「信心 + 9:16 可裁性」聰明挑框,緩解「逼模型一次定案而選錯主體」的失敗模式。
    """
    bbox: SubjectBbox
    label: str = ""          # 主體語意描述(如「紅衣女子」「衝浪板」),供導演按使用者意圖挑選
    confidence: float = 0.0  # 模型對「此為畫面最主要主體」的信心(0–1)


class FaceInfo(BaseModel):
    """臉部偵測結果摘要。"""
    face_count: int
    has_faces: bool
    largest_face_ratio: float  # 最大臉部面積 / 畫面面積
