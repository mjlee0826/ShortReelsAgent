"""階段 1 主流程：以「秒數預算」有意識地抓素材。

對每組：跨來源 × 關鍵字 × 分頁持續累積通過硬篩的候選並下載，直到候選池總時長達
``秒數預算 × candidate_multiplier`` 才停（仍有翻頁上限保護）。可重複執行：已下載者不重抓，
若候選池已滿足預算則整組跳過 API 呼叫。
"""
from __future__ import annotations

from pathlib import Path

from ..constants import MAX_SEARCH_PAGES_PER_KEYWORD, SEARCH_PAGE_SIZE
from ..http_client import RetryingHttpClient
from ..jsonio import read_models, write_models
from ..logging_setup import get_logger
from ..models import ClipCandidate, GroupSpec
from ..pipeline import BuildContext, PipelineStage
from ..sources.base import VideoSource
from ..sources.factory import VideoSourceFactory
from .downloader import ClipDownloader, FetchIndex
from .filters import ClipFilter

logger = get_logger(__name__)


class FetchStage(PipelineStage):
    """階段 1：抓素材。"""

    name = "fetch（階段 1：抓素材）"

    def __init__(self) -> None:
        """建立共用 HTTP 客戶端、硬篩器與下載器。"""
        self._http = RetryingHttpClient()
        self._filter = ClipFilter.default()
        self._downloader = ClipDownloader(self._http)

    def run(self, context: BuildContext) -> None:
        """對每組執行秒數預算驅動的抓取。"""
        sources = VideoSourceFactory.create_all(context.spec.sources, self._http)
        for group in context.spec.groups:
            self._fetch_group(context, group, sources)

    def _fetch_group(
        self, context: BuildContext, group: GroupSpec, sources: list[VideoSource]
    ) -> None:
        """抓單一組到秒數預算。"""
        target_seconds = context.resolved_target_seconds(group)
        budget = target_seconds * context.spec.candidate_multiplier

        candidates_dir = context.candidates_dir(group)
        thumbnails_dir = context.thumbnails_dir(group)
        candidates_dir.mkdir(parents=True, exist_ok=True)
        thumbnails_dir.mkdir(parents=True, exist_ok=True)

        index = FetchIndex.load(context.fetch_index_json(group))

        # 載入既有候選（可重複執行：保留先前已下載且檔案仍在者）
        accumulated: dict[str, ClipCandidate] = {}
        for candidate in read_models(context.candidates_json(group), ClipCandidate):
            if candidate.local_path and Path(candidate.local_path).is_file():
                accumulated[candidate.cache_key] = candidate
        current_seconds = sum(c.duration_sec for c in accumulated.values())

        if current_seconds >= budget:
            logger.info(
                "組 %s：候選池已滿足秒數預算（%.0f/%.0f s），跳過抓取",
                group.group_id, current_seconds, budget,
            )
            return

        logger.info(
            "組 %s：開始抓取，目標候選秒數 %.0f s（預算 %.0f s × %.1f；起始 %.0f s）",
            group.group_id, budget, target_seconds, context.spec.candidate_multiplier, current_seconds,
        )

        current_seconds = self._collect_until_budget(
            group, sources, accumulated, current_seconds, budget, candidates_dir, thumbnails_dir, index
        )

        write_models(context.candidates_json(group), list(accumulated.values()))

        if current_seconds < budget:
            logger.warning(
                "組 %s：未湊滿候選秒數預算（%.0f/%.0f s）；關鍵字或 API 結果可能不足，"
                "策展時仍會盡量覆蓋秒數預算 %.0f s",
                group.group_id, current_seconds, budget, target_seconds,
            )
        logger.info(
            "組 %s：抓取完成，候選 %d 段、總時長 %.0f s",
            group.group_id, len(accumulated), current_seconds,
        )

    def _collect_until_budget(
        self,
        group: GroupSpec,
        sources: list[VideoSource],
        accumulated: dict[str, ClipCandidate],
        current_seconds: float,
        budget: float,
        candidates_dir: Path,
        thumbnails_dir: Path,
        index: FetchIndex,
    ) -> float:
        """跨來源/關鍵字/分頁累積候選並下載，達預算即停；回傳最終累積秒數。"""
        # 可選的片段數上限（若 spec 有設）
        max_clips = group.target_clip_count
        for page in range(1, MAX_SEARCH_PAGES_PER_KEYWORD + 1):
            for source in sources:
                for keyword in group.keywords:
                    if current_seconds >= budget:
                        return current_seconds
                    if max_clips is not None and len(accumulated) >= max_clips:
                        return current_seconds
                    try:
                        results = source.search(keyword, page=page, page_size=SEARCH_PAGE_SIZE)
                    except Exception as exc:  # 單一來源/關鍵字失敗不阻斷其他
                        logger.warning(
                            "搜尋失敗（%s／%s／page=%d）：%s",
                            source.platform.value, keyword, page, exc,
                        )
                        continue
                    current_seconds = self._download_accepted(
                        results, accumulated, current_seconds, budget,
                        candidates_dir, thumbnails_dir, index, group,
                    )
        return current_seconds

    def _download_accepted(
        self,
        results: list[ClipCandidate],
        accumulated: dict[str, ClipCandidate],
        current_seconds: float,
        budget: float,
        candidates_dir: Path,
        thumbnails_dir: Path,
        index: FetchIndex,
        group: GroupSpec,
    ) -> float:
        """對單頁結果做硬篩、去重、下載並累積秒數；回傳更新後秒數。"""
        for candidate in self._filter.filter(results):
            if candidate.cache_key in accumulated:
                continue
            if group.target_clip_count is not None and len(accumulated) >= group.target_clip_count:
                break
            try:
                downloaded = self._downloader.ensure_downloaded(
                    candidate, candidates_dir=candidates_dir, thumbnails_dir=thumbnails_dir, index=index
                )
            except Exception as exc:  # 單段下載失敗就跳過
                logger.warning("下載失敗，略過 %s：%s", candidate.cache_key, exc)
                continue
            accumulated[downloaded.cache_key] = downloaded
            current_seconds += downloaded.duration_sec
            logger.info(
                "組 %s：候選秒數 %.0f/%.0f s（+%.0fs %s）",
                group.group_id, current_seconds, budget, downloaded.duration_sec, downloaded.cache_key,
            )
            if current_seconds >= budget:
                break
        return current_seconds
