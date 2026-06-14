"""人工選取機制 + 自動 fallback 選取（Strategy）。

- ``SelectionTemplateWriter``：產生 ``selections/<group_id>.txt`` 範本（全部候選預設註解掉），
  使用者把要保留的那行前面的 ``#`` 拿掉即可；已存在則不覆寫（保住人工編輯）。
- ``SelectionReader``：讀回未註解的行，取每行第一個 token 當 cache_key。
- ``AutoFallbackSelector``：無人工選取時，依品質由高到低挑到覆蓋秒數預算為止。
"""
from __future__ import annotations

from pathlib import Path

from ..constants import SELECTION_COMMENT_PREFIX
from ..logging_setup import get_logger
from ..models import ClipCandidate, GroupSpec

logger = get_logger(__name__)


class SelectionTemplateWriter:
    """選取檔範本產生器。"""

    def write_if_absent(
        self,
        path: Path,
        group: GroupSpec,
        candidates: list[ClipCandidate],
        target_seconds: float,
    ) -> None:
        """若選取檔不存在則建立範本（存在則不動，保留人工編輯）。"""
        if path.is_file():
            logger.debug("選取檔已存在，不覆寫：%s", path)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._render(group, candidates, target_seconds), encoding="utf-8")
        logger.info("已產生選取範本：%s（編輯後重跑 curate 套用）", path)

    def _render(
        self, group: GroupSpec, candidates: list[ClipCandidate], target_seconds: float
    ) -> str:
        """組出範本內容（含用法說明與每段提示）。"""
        c = SELECTION_COMMENT_PREFIX
        lines = [
            f"{c} 組 {group.group_id}（{group.theme}）選取檔",
            f"{c} 秒數預算：{target_seconds:.0f}s",
            f"{c} 用法：把要保留的片段那一行最前面的「{c} 」刪掉即可；可保留任意段數。",
            f"{c} 候選已依品質由高到低排序；行尾為各段資訊（dur=時長、cum=由上而下累計時長）。",
            f"{c} 若完全不編輯，使用 `curate --fallback` 或 `all` 會自動依品質挑到覆蓋秒數預算。",
            c,
        ]
        cumulative = 0.0
        for candidate in candidates:
            cumulative += candidate.duration_sec
            score = candidate.quality_score if candidate.quality_score is not None else 0.0
            lines.append(
                f"{c} {candidate.cache_key}    {c} dur={candidate.duration_sec:.0f}s "
                f"cum={cumulative:.0f}s {candidate.width}x{candidate.height} "
                f"{candidate.source_platform.value} q={score:.2f}"
            )
        return "\n".join(lines) + "\n"


class SelectionReader:
    """選取檔讀取器。"""

    def read(self, path: Path) -> set[str]:
        """讀回被保留（未註解）的 cache_key 集合；檔不存在則為空集合。"""
        if not path.is_file():
            return set()
        selected: set[str] = set()
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith(SELECTION_COMMENT_PREFIX):
                continue
            # 取第一個 token 當 cache_key（忽略行尾可能殘留的說明）
            selected.add(stripped.split()[0])
        return selected


class AutoFallbackSelector:
    """自動 fallback 選取：依品質由高到低挑到覆蓋秒數預算。"""

    def select(
        self, candidates: list[ClipCandidate], target_seconds: float
    ) -> list[ClipCandidate]:
        """挑選片段直到累計時長 ≥ 秒數預算（或候選用盡）。"""
        ordered = sorted(
            candidates, key=lambda c: c.quality_score or 0.0, reverse=True
        )
        chosen: list[ClipCandidate] = []
        total = 0.0
        for candidate in ordered:
            chosen.append(candidate)
            total += candidate.duration_sec
            if total >= target_seconds:
                break
        return chosen
