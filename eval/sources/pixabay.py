"""Pixabay 影片搜尋 adapter。

把 Pixabay Videos API 回應正規化成 ``ClipCandidate``。Pixabay 無 orientation 參數，故直式與否
由各 rendition（videos.large/medium/...）的寬高自行判定；這裡挑「寬度達門檻中解析度最高」的 size
作為下載來源。
"""
from __future__ import annotations

from ..constants import (
    MIN_CLIP_WIDTH,
    PIXABAY_LICENSE,
    PIXABAY_MAX_PER_PAGE,
    PIXABAY_SEARCH_URL,
)
from ..http_client import RetryingHttpClient
from ..logging_setup import get_logger
from ..models import ClipCandidate, SourcePlatform
from .base import VideoSource

logger = get_logger(__name__)


class PixabaySource(VideoSource):
    """Pixabay Videos API adapter。"""

    platform = SourcePlatform.PIXABAY

    def __init__(self, api_key: str, http: RetryingHttpClient) -> None:
        """以 API key 與共用 HTTP 客戶端建構。"""
        self._api_key = api_key
        self._http = http

    def search(self, keyword: str, *, page: int, page_size: int) -> list[ClipCandidate]:
        """呼叫 Pixabay 搜尋並正規化。"""
        params = {
            "key": self._api_key,
            "q": keyword,
            "per_page": min(page_size, PIXABAY_MAX_PER_PAGE),
            "page": page,
        }
        data = self._http.get_json(PIXABAY_SEARCH_URL, params=params)

        candidates: list[ClipCandidate] = []
        for hit in data.get("hits", []):
            candidate = self._to_candidate(hit, keyword)
            if candidate is not None:
                candidates.append(candidate)
        logger.debug("Pixabay「%s」page=%d 取得 %d 筆候選", keyword, page, len(candidates))
        return candidates

    def _to_candidate(self, hit: dict, keyword: str) -> ClipCandidate | None:
        """把單一 Pixabay hit 轉成 ClipCandidate；無有效 size 則回 None。"""
        best_size = self._select_best_size(hit.get("videos", {}))
        if best_size is None:
            return None

        width = int(best_size.get("width") or 0)
        height = int(best_size.get("height") or 0)
        download_url = best_size.get("url")
        if not download_url or width <= 0 or height <= 0:
            return None

        return ClipCandidate(
            source_platform=SourcePlatform.PIXABAY,
            video_id=str(hit.get("id")),
            page_url=hit.get("pageURL", ""),
            author_name=hit.get("user", "Unknown"),
            author_url=self._build_author_url(hit),
            license=PIXABAY_LICENSE,
            width=width,
            height=height,
            duration_sec=float(hit.get("duration") or 0.0),
            download_url=download_url,
            thumbnail_url=best_size.get("thumbnail"),
            keyword=keyword,
        )

    @staticmethod
    def _select_best_size(videos: dict) -> dict | None:
        """從 size 字典挑「寬度達門檻中解析度最高」的 size；都不達門檻則挑最大者。"""
        sizes = [
            s
            for s in videos.values()
            if isinstance(s, dict) and (s.get("width") or 0) > 0 and (s.get("height") or 0) > 0 and s.get("url")
        ]
        if not sizes:
            return None

        def area(size: dict) -> int:
            return int(size.get("width") or 0) * int(size.get("height") or 0)

        qualified = [s for s in sizes if int(s.get("width") or 0) >= MIN_CLIP_WIDTH]
        pool = qualified or sizes
        return max(pool, key=area)

    @staticmethod
    def _build_author_url(hit: dict) -> str | None:
        """由 user 與 user_id 組出 Pixabay 使用者頁面 URL（缺值則回 None）。"""
        user = hit.get("user")
        user_id = hit.get("user_id")
        if user and user_id:
            return f"https://pixabay.com/users/{user}-{user_id}/"
        return None
