"""候選片段硬篩條件（Composite of Strategy）。

硬條件只保留：直式（height > width）、時長落在 3–20 秒、寬度 ≥ 720。
「接近 9:16」屬偏好，不在此剔除，改由策展階段的 QualityScorer 評分。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..constants import (
    MAX_CLIP_DURATION_SEC,
    MIN_CLIP_DURATION_SEC,
    MIN_CLIP_WIDTH,
)
from ..logging_setup import get_logger
from ..models import ClipCandidate

logger = get_logger(__name__)


class ClipPredicate(ABC):
    """單一篩選條件。"""

    #: 被剔除時用於 log 統計的原因標籤
    reason: str = "unknown"

    @abstractmethod
    def accepts(self, candidate: ClipCandidate) -> bool:
        """是否通過此條件。"""
        raise NotImplementedError


class VerticalPredicate(ClipPredicate):
    """只保留直式（height > width）。"""

    reason = "非直式"

    def accepts(self, candidate: ClipCandidate) -> bool:
        """直式判定。"""
        return candidate.is_vertical


class DurationRangePredicate(ClipPredicate):
    """時長須落在 [MIN, MAX]。"""

    reason = "時長超出範圍"

    def accepts(self, candidate: ClipCandidate) -> bool:
        """時長範圍判定。"""
        return MIN_CLIP_DURATION_SEC <= candidate.duration_sec <= MAX_CLIP_DURATION_SEC


class MinWidthPredicate(ClipPredicate):
    """寬度須 ≥ 門檻。"""

    reason = "解析度不足"

    def accepts(self, candidate: ClipCandidate) -> bool:
        """最小寬度判定。"""
        return candidate.width >= MIN_CLIP_WIDTH


class ClipFilter:
    """以多個 predicate 組合的複合篩選器（Composite）。"""

    def __init__(self, predicates: list[ClipPredicate]) -> None:
        """以 predicate 清單建構。"""
        self._predicates = predicates

    @classmethod
    def default(cls) -> "ClipFilter":
        """預設硬篩：直式 + 時長 + 最小寬度。"""
        return cls([VerticalPredicate(), DurationRangePredicate(), MinWidthPredicate()])

    def accepts(self, candidate: ClipCandidate) -> bool:
        """全部 predicate 都通過才算通過。"""
        return all(p.accepts(candidate) for p in self._predicates)

    def filter(self, candidates: list[ClipCandidate]) -> list[ClipCandidate]:
        """回傳通過的候選；被剔除者依原因彙整成 debug log。"""
        accepted: list[ClipCandidate] = []
        reject_counts: dict[str, int] = {}
        for candidate in candidates:
            first_fail = next((p for p in self._predicates if not p.accepts(candidate)), None)
            if first_fail is None:
                accepted.append(candidate)
            else:
                reject_counts[first_fail.reason] = reject_counts.get(first_fail.reason, 0) + 1
        if reject_counts:
            logger.debug("篩選剔除統計：%s", reject_counts)
        return accepted
