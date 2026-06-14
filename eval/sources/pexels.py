"""Pexels 影片搜尋 adapter。

把 Pexels Videos API 回應正規化成 ``ClipCandidate``。Pexels 支援 ``orientation=portrait``
直接要直式結果；單一影片有多個 rendition（video_files），這裡挑解析度最高的 mp4 作為下載來源，
並以該 rendition 的寬高作為篩選/評分依據（即實際會下載到的畫面）。
"""
from __future__ import annotations

from ..constants import (
    PEXELS_LICENSE,
    PEXELS_MAX_PER_PAGE,
    PEXELS_PORTRAIT_ORIENTATION,
    PEXELS_SEARCH_URL,
)
from ..http_client import RetryingHttpClient
from ..logging_setup import get_logger
from ..models import ClipCandidate, SourcePlatform
from .base import VideoSource

logger = get_logger(__name__)

# Pexels rendition 的 mp4 判斷字串
_MP4_FILE_TYPE_HINT: str = "mp4"


class PexelsSource(VideoSource):
    """Pexels Videos API adapter。"""

    platform = SourcePlatform.PEXELS

    def __init__(self, api_key: str, http: RetryingHttpClient) -> None:
        """以 API key 與共用 HTTP 客戶端建構。"""
        self._api_key = api_key
        self._http = http

    def search(self, keyword: str, *, page: int, page_size: int) -> list[ClipCandidate]:
        """呼叫 Pexels 搜尋並正規化（只要直式結果）。"""
        params = {
            "query": keyword,
            "orientation": PEXELS_PORTRAIT_ORIENTATION,
            "per_page": min(page_size, PEXELS_MAX_PER_PAGE),
            "page": page,
        }
        # Pexels 以 Authorization header 帶 API key（非 Bearer）
        headers = {"Authorization": self._api_key}
        data = self._http.get_json(PEXELS_SEARCH_URL, params=params, headers=headers)

        candidates: list[ClipCandidate] = []
        for video in data.get("videos", []):
            candidate = self._to_candidate(video, keyword)
            if candidate is not None:
                candidates.append(candidate)
        logger.debug("Pexels「%s」page=%d 取得 %d 筆候選", keyword, page, len(candidates))
        return candidates

    def _to_candidate(self, video: dict, keyword: str) -> ClipCandidate | None:
        """把單一 Pexels video 物件轉成 ClipCandidate；無有效 mp4 則回 None。"""
        best_file = self._select_best_mp4(video.get("video_files", []))
        if best_file is None:
            return None

        width = int(best_file.get("width") or 0)
        height = int(best_file.get("height") or 0)
        download_url = best_file.get("link")
        if not download_url or width <= 0 or height <= 0:
            return None

        user = video.get("user") or {}
        return ClipCandidate(
            source_platform=SourcePlatform.PEXELS,
            video_id=str(video.get("id")),
            page_url=video.get("url", ""),
            author_name=user.get("name", "Unknown"),
            author_url=user.get("url"),
            license=PEXELS_LICENSE,
            width=width,
            height=height,
            duration_sec=float(video.get("duration") or 0.0),
            download_url=download_url,
            thumbnail_url=video.get("image"),
            keyword=keyword,
        )

    @staticmethod
    def _select_best_mp4(video_files: list[dict]) -> dict | None:
        """從 rendition 清單挑解析度最高（以高度為準）的 mp4；無則回 None。"""
        mp4_files = [
            f
            for f in video_files
            if _MP4_FILE_TYPE_HINT in str(f.get("file_type", "")).lower()
            and (f.get("height") or 0) > 0
        ]
        if not mp4_files:
            return None
        return max(mp4_files, key=lambda f: int(f.get("height") or 0))
