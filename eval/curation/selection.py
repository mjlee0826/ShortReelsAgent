"""人工選取機制 + 自動 fallback 選取（Strategy）。

- ``SelectionTemplateWriter``：產生／覆寫 ``selections/<group_id>.txt``。
  - ``write_if_absent``：產生範本（全部候選預設註解掉），使用者把要保留的那行前面的 ``#`` 拿掉即可；
    已存在則不覆寫（保住人工編輯）。
  - ``write_selection``：依指定的選取集合覆寫（被選的行不註解、其餘註解），供互動 server 一鍵存檔用；
    輸出格式與範本完全相同，因此勾選與手動編輯兩種方式可互換。
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

    def write_selection(
        self,
        path: Path,
        group: GroupSpec,
        candidates: list[ClipCandidate],
        target_seconds: float,
        selected_keys: set[str],
    ) -> None:
        """依指定選取集合覆寫選取檔（被選的行不註解、其餘註解）；供互動 server 存檔用。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            self._render(group, candidates, target_seconds, selected_keys), encoding="utf-8"
        )
        logger.info("已寫入選取檔：%s（保留 %d 件）", path, len(selected_keys))

    def _render(
        self,
        group: GroupSpec,
        candidates: list[ClipCandidate],
        target_seconds: float,
        selected_keys: set[str] | None = None,
    ) -> str:
        """組出選取檔內容（含用法說明與每段提示）。

        ``selected_keys`` 為 None 或空集合時所有候選皆註解（純範本）；否則被選的 cache_key 那行不註解。
        """
        selected = selected_keys or set()
        c = SELECTION_COMMENT_PREFIX
        lines = [
            f"{c} 組 {group.group_id}（{group.theme}，scope={group.scope or '-'}）選取檔",
            f"{c} 秒數預算：{target_seconds:.0f}s（圖片以名目秒數計）",
            f"{c} 用法：把要保留的那一行最前面的「{c} 」刪掉即可；影片與圖片可混選，留任意件數。",
            f"{c} 候選已依品質由高到低排序；行尾為各件資訊（[類型] dur=名目/時長）。",
            f"{c} 若完全不編輯，`curate --fallback` 或 `all` 會自動依品質與圖片佔比挑齊。",
            c,
        ]
        for candidate in candidates:
            score = candidate.quality_score if candidate.quality_score is not None else 0.0
            # 被選的行不加註解前綴；其餘維持註解。行尾資訊一律以 {c} 標註，SelectionReader 取首 token 即可。
            prefix = "" if candidate.cache_key in selected else f"{c} "
            lines.append(
                f"{prefix}{candidate.cache_key}    {c} [{candidate.media_type.value}] "
                f"dur={candidate.duration_sec:.0f}s {candidate.width}x{candidate.height} "
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


class SelectAllSelector:
    """全取選取：直接取用全部候選（跳過人工挑選與品質 fallback）。"""

    def select(self, candidates: list[ClipCandidate]) -> list[ClipCandidate]:
        """回傳全部候選（順序不變；後續策展會自行以 group_id 決定性亂序）。"""
        return list(candidates)


class AutoFallbackSelector:
    """自動 fallback 選取：影片與圖片各依品質由高到低挑到覆蓋對應秒數預算。"""

    def select(
        self, candidates: list[ClipCandidate], target_seconds: float, image_ratio: float
    ) -> list[ClipCandidate]:
        """依圖片佔比把秒數預算拆成影片/圖片目標，各自挑到覆蓋目標後合併。"""
        video_target = target_seconds * (1.0 - image_ratio)
        image_target = target_seconds * image_ratio
        videos = [c for c in candidates if not c.is_image]
        images = [c for c in candidates if c.is_image]
        return self._take_until(videos, video_target) + self._take_until(images, image_target)

    @staticmethod
    def _take_until(items: list[ClipCandidate], target_seconds: float) -> list[ClipCandidate]:
        """依品質由高到低挑到累計時長覆蓋 target（target<=0 則不挑）。"""
        ordered = sorted(items, key=lambda c: c.quality_score or 0.0, reverse=True)
        chosen: list[ClipCandidate] = []
        total = 0.0
        for candidate in ordered:
            if total >= target_seconds:
                break
            chosen.append(candidate)
            total += candidate.duration_sec
        return chosen
