"""候選品質啟發式評分（Strategy）。

完全只用 API metadata（解析度、與 9:16 接近度、時長甜蜜區），不做像素級分析（本機亦無 ffmpeg）。
分數 0~1，供預覽排序與自動 fallback 取捨。
"""
from __future__ import annotations

import math

from ..constants import (
    QUALITY_DURATION_SPREAD_SEC,
    QUALITY_IDEAL_DURATION_SEC,
    QUALITY_REFERENCE_HEIGHT,
    QUALITY_WEIGHT_ASPECT,
    QUALITY_WEIGHT_DURATION,
    QUALITY_WEIGHT_RESOLUTION,
    TARGET_ASPECT_RATIO,
)
from ..models import ClipCandidate


class QualityScorer:
    """以加權方式綜合三項訊號的品質評分器。"""

    def __init__(
        self,
        *,
        weight_resolution: float = QUALITY_WEIGHT_RESOLUTION,
        weight_aspect: float = QUALITY_WEIGHT_ASPECT,
        weight_duration: float = QUALITY_WEIGHT_DURATION,
    ) -> None:
        """以三項權重建構（預設值相加為 1）。"""
        self._w_resolution = weight_resolution
        self._w_aspect = weight_aspect
        self._w_duration = weight_duration

    def score(self, candidate: ClipCandidate) -> float:
        """計算單一候選的品質分（0~1）。"""
        resolution_score = min(candidate.height / QUALITY_REFERENCE_HEIGHT, 1.0)

        aspect_deviation = abs(candidate.aspect_ratio - TARGET_ASPECT_RATIO)
        aspect_score = max(0.0, 1.0 - aspect_deviation / TARGET_ASPECT_RATIO)

        if candidate.is_image:
            # 圖片無時長概念：只用解析度 + aspect，權重重新正規化
            weight_sum = self._w_resolution + self._w_aspect
            return (self._w_resolution * resolution_score + self._w_aspect * aspect_score) / weight_sum

        # 影片：時長以高斯型在甜蜜區附近給高分，偏離越遠越低
        duration_score = math.exp(
            -(((candidate.duration_sec - QUALITY_IDEAL_DURATION_SEC) / QUALITY_DURATION_SPREAD_SEC) ** 2)
        )
        return (
            self._w_resolution * resolution_score
            + self._w_aspect * aspect_score
            + self._w_duration * duration_score
        )

    def annotate(self, candidates: list[ClipCandidate]) -> list[ClipCandidate]:
        """回傳補上 ``quality_score`` 的候選副本清單（不改原物件）。"""
        return [c.model_copy(update={"quality_score": self.score(c)}) for c in candidates]
