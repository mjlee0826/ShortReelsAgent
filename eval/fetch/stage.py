"""階段 1 主流程：以「秒數預算 + 圖片佔比」有意識地抓影片與圖片。

對每組：把秒數預算 S 依 image_ratio 拆成影片預算與圖片預算，分別用影片來源與圖片來源把兩個候選池
各自湊到「對應預算 × candidate_multiplier」才停（仍有翻頁上限保護）。可重複執行：已下載者不重抓，
某池已滿足預算則跳過該池的 API 呼叫。
"""
from __future__ import annotations

from pathlib import Path

from ..constants import MAX_SEARCH_PAGES_PER_KEYWORD, SEARCH_PAGE_SIZE
from ..http_client import RetryingHttpClient
from ..jsonio import read_models, write_models
from ..logging_setup import get_logger
from ..models import ClipCandidate, GroupSpec, MediaType
from ..pipeline import BuildContext, PipelineStage
from ..sources.base import MediaSource
from ..sources.factory import MediaSourceFactory
from .downloader import ClipDownloader, FetchIndex
from .filters import ClipFilter

logger = get_logger(__name__)

# log 用的中文類型標籤
_LABEL_VIDEO: str = "影片"
_LABEL_IMAGE: str = "圖片"


class FetchStage(PipelineStage):
    """階段 1：抓素材（影片 + 圖片）。"""

    name = "fetch（階段 1：抓素材）"

    def __init__(self) -> None:
        """建立共用 HTTP 客戶端、硬篩器與下載器。"""
        self._http = RetryingHttpClient()
        self._filter = ClipFilter.default()
        self._downloader = ClipDownloader(self._http)

    def run(self, context: BuildContext) -> None:
        """為每組分別抓影片與圖片到各自預算。"""
        nominal = context.spec.image_nominal_seconds
        video_sources = MediaSourceFactory.create_for(
            context.spec.sources, [MediaType.VIDEO], self._http, image_nominal_seconds=nominal
        )
        image_sources = MediaSourceFactory.create_for(
            context.spec.sources, [MediaType.IMAGE], self._http, image_nominal_seconds=nominal
        )
        for group in context.spec.groups:
            self._fetch_group(context, group, video_sources, image_sources)

    def _fetch_group(
        self,
        context: BuildContext,
        group: GroupSpec,
        video_sources: list[MediaSource],
        image_sources: list[MediaSource],
    ) -> None:
        """抓單一組：影片池 + 圖片池各湊到預算。"""
        target = context.resolved_target_seconds(group)
        ratio = context.spec.resolved_image_ratio(group)
        multiplier = context.spec.candidate_multiplier
        video_budget = target * (1.0 - ratio) * multiplier
        image_budget = target * ratio * multiplier

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

        logger.info(
            "組 %s（scope=%s）：影片預算 %.0f s、圖片預算 %.0f s（秒數預算 %.0f × 倍數 %.1f，圖片佔比 %.0f%%）",
            group.group_id, group.scope or "-", video_budget, image_budget, target, multiplier, ratio * 100,
        )

        self._collect_pool(
            group, _LABEL_VIDEO, video_sources, MediaType.VIDEO,
            accumulated, video_budget, candidates_dir, thumbnails_dir, index,
        )
        self._collect_pool(
            group, _LABEL_IMAGE, image_sources, MediaType.IMAGE,
            accumulated, image_budget, candidates_dir, thumbnails_dir, index,
        )

        write_models(context.candidates_json(group), list(accumulated.values()))

        video_seconds = self._pool_seconds(accumulated, MediaType.VIDEO)
        image_seconds = self._pool_seconds(accumulated, MediaType.IMAGE)
        logger.info(
            "組 %s：抓取完成，影片 %.0f/%.0f s、圖片 %.0f/%.0f s，共 %d 件",
            group.group_id, video_seconds, video_budget, image_seconds, image_budget, len(accumulated),
        )

    def _collect_pool(
        self,
        group: GroupSpec,
        label: str,
        sources: list[MediaSource],
        media_type: MediaType,
        accumulated: dict[str, ClipCandidate],
        budget: float,
        candidates_dir: Path,
        thumbnails_dir: Path,
        index: FetchIndex,
    ) -> None:
        """把某一媒體類型的候選池湊到 budget（跨來源/關鍵字/分頁）。"""
        if budget <= 0 or not sources:
            return
        seconds = self._pool_seconds(accumulated, media_type)
        if seconds >= budget:
            logger.info("組 %s：%s池已滿足（%.0f/%.0f s），跳過", group.group_id, label, seconds, budget)
            return

        for page in range(1, MAX_SEARCH_PAGES_PER_KEYWORD + 1):
            for source in sources:
                for keyword in group.keywords:
                    if seconds >= budget:
                        return
                    try:
                        results = source.search(keyword, page=page, page_size=SEARCH_PAGE_SIZE)
                    except Exception as exc:  # 單一來源/關鍵字失敗不阻斷其他
                        logger.warning(
                            "搜尋失敗（%s／%s／page=%d）：%s",
                            source.platform.value, keyword, page, exc,
                        )
                        continue
                    seconds = self._download_accepted(
                        group, label, results, accumulated, seconds, budget,
                        candidates_dir, thumbnails_dir, index,
                    )
        if seconds < budget:
            logger.warning(
                "組 %s：%s池未湊滿（%.0f/%.0f s）；關鍵字或 API 結果可能不足",
                group.group_id, label, seconds, budget,
            )

    def _download_accepted(
        self,
        group: GroupSpec,
        label: str,
        results: list[ClipCandidate],
        accumulated: dict[str, ClipCandidate],
        seconds: float,
        budget: float,
        candidates_dir: Path,
        thumbnails_dir: Path,
        index: FetchIndex,
    ) -> float:
        """對單頁結果做硬篩、去重、下載並累積秒數；回傳更新後秒數。"""
        for candidate in self._filter.filter(results):
            if candidate.cache_key in accumulated:
                continue
            try:
                downloaded = self._downloader.ensure_downloaded(
                    candidate, candidates_dir=candidates_dir, thumbnails_dir=thumbnails_dir, index=index
                )
            except Exception as exc:  # 單件下載失敗就跳過
                logger.warning("下載失敗，略過 %s：%s", candidate.cache_key, exc)
                continue
            accumulated[downloaded.cache_key] = downloaded
            seconds += downloaded.duration_sec
            logger.info(
                "組 %s：%s候選 %.0f/%.0f s（+%.0fs %s）",
                group.group_id, label, seconds, budget, downloaded.duration_sec, downloaded.cache_key,
            )
            if seconds >= budget:
                break
        return seconds

    @staticmethod
    def _pool_seconds(accumulated: dict[str, ClipCandidate], media_type: MediaType) -> float:
        """統計累積候選中某媒體類型的總秒數（圖片以名目秒數計）。"""
        return sum(c.duration_sec for c in accumulated.values() if c.media_type is media_type)
