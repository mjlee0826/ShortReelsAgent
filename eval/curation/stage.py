"""階段 2 主流程：產預覽 + 選取範本，依人工選取或自動 fallback 策展。

流程：載入候選 → 評分排序 → 產 preview.html（影片可播放）與 selection 範本 → 讀人工選取；有則
人工策展，無則（allow_fallback 時）自動依品質與圖片佔比覆蓋秒數預算，並明確 warning 標示「非人工策展」。
"""
from __future__ import annotations

from ..jsonio import read_models, write_model
from ..logging_setup import get_logger
from ..models import ClipCandidate, CurationSummary, GroupSpec, MediaType
from ..pipeline import BuildContext, PipelineStage
from .curator import GroupCurator
from .preview import HtmlPreviewBuilder
from .quality import QualityScorer
from .selection import (
    AutoFallbackSelector,
    SelectAllSelector,
    SelectionReader,
    SelectionTemplateWriter,
)

logger = get_logger(__name__)

# 策展模式標記
_MODE_MANUAL: str = "manual"
_MODE_AUTO_FALLBACK: str = "auto_fallback"
_MODE_TAKE_ALL: str = "take_all"


class CurateStage(PipelineStage):
    """階段 2：半自動策展。"""

    name = "curate（階段 2：半自動策展）"

    def __init__(self) -> None:
        """建立評分、預覽、選取與策展元件。"""
        self._scorer = QualityScorer()
        self._preview = HtmlPreviewBuilder()
        self._template_writer = SelectionTemplateWriter()
        self._selection_reader = SelectionReader()
        self._fallback = AutoFallbackSelector()
        self._select_all = SelectAllSelector()
        self._curator = GroupCurator()

    def run(self, context: BuildContext) -> None:
        """對每組產預覽/範本並（在可行時）執行策展。"""
        context.selections_dir.mkdir(parents=True, exist_ok=True)
        for group in context.spec.groups:
            self._curate_group(context, group)

    def _curate_group(self, context: BuildContext, group: GroupSpec) -> None:
        """處理單一組。"""
        candidates = read_models(context.candidates_json(group), ClipCandidate)
        if not candidates:
            logger.warning("組 %s：找不到候選（請先執行 fetch），略過", group.group_id)
            return
        # 重建為當前機器的路徑：跨機器下載 _build 後，candidates.json 內的絕對路徑已失效
        candidates = context.localized_candidates(group, candidates)

        target_seconds = context.resolved_target_seconds(group)
        image_ratio = context.spec.resolved_image_ratio(group)
        scored = self._scorer.annotate(candidates)
        ordered = sorted(scored, key=lambda c: c.quality_score or 0.0, reverse=True)

        # 永遠（重新）產生預覽；選取範本只在不存在時建立
        self._preview.build(group, ordered, target_seconds, context.preview_html(group))
        self._template_writer.write_if_absent(
            context.selection_file(group), group, ordered, target_seconds
        )

        chosen, mode = self._resolve_selection(context, group, ordered, target_seconds, image_ratio)
        if chosen is None:
            return  # 尚未選取且不允許 fallback：等待人工編輯
        if not chosen:
            logger.warning("組 %s：選取結果為空，略過策展", group.group_id)
            return

        metadata, total_seconds = self._curator.curate(group, chosen, context.curated_dir(group))
        video_count = sum(1 for m in metadata if m.media_type is MediaType.VIDEO)
        image_count = sum(1 for m in metadata if m.media_type is MediaType.IMAGE)
        write_model(
            context.curation_summary_json(group),
            CurationSummary(
                curation_mode=mode,
                total_seconds=total_seconds,
                clip_count=len(metadata),
                video_count=video_count,
                image_count=image_count,
            ),
        )
        logger.info(
            "組 %s：策展完成，%d 件（影片 %d、圖片 %d）、總時長 %.0f s（模式=%s、預算 %.0f s）",
            group.group_id, len(metadata), video_count, image_count, total_seconds, mode, target_seconds,
        )

    def _resolve_selection(
        self,
        context: BuildContext,
        group: GroupSpec,
        ordered: list[ClipCandidate],
        target_seconds: float,
        image_ratio: float,
    ) -> tuple[list[ClipCandidate] | None, str]:
        """決定選取來源：全取(--take-all) > 人工 > 自動 fallback > 等待（回傳 (None, "")）。"""
        # 全取優先：明確要求跳過挑選、直接用全部素材
        if context.take_all:
            chosen = self._select_all.select(ordered)
            logger.info("組 %s：取用全部候選 %d 件（--take-all，跳過挑選）", group.group_id, len(chosen))
            return chosen, _MODE_TAKE_ALL

        selected_keys = self._selection_reader.read(context.selection_file(group))
        if selected_keys:
            chosen = [c for c in ordered if c.cache_key in selected_keys]
            logger.info("組 %s：採用人工選取 %d 件", group.group_id, len(chosen))
            return chosen, _MODE_MANUAL

        if context.allow_fallback:
            chosen = self._fallback.select(ordered, target_seconds, image_ratio)
            logger.warning(
                "組 %s：⚠️ 自動 fallback（非人工策展）——依品質與圖片佔比挑齊，選了 %d 件",
                group.group_id, len(chosen),
            )
            return chosen, _MODE_AUTO_FALLBACK

        logger.info(
            "組 %s：尚未選取，請編輯 %s 後重跑 curate（或用 `curate --fallback` / `all` 自動挑選）",
            group.group_id, context.selection_file(group),
        )
        return None, ""
