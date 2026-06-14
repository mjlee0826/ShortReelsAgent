"""Pexels 來源 adapter（影片 + 圖片）。

- ``PexelsVideoSource``：Videos API，挑解析度最高的 mp4 rendition 下載。
- ``PexelsPhotoSource``：Photos API（`/v1/search`），下載較大尺寸、用小尺寸當縮圖；圖片的 duration
  以名目秒數填入（計入秒數預算）。兩者都用 ``orientation=portrait`` 直接取直式。
"""
from __future__ import annotations

from ..constants import (
    PEXELS_LICENSE,
    PEXELS_MAX_PER_PAGE,
    PEXELS_PHOTO_SEARCH_URL,
    PEXELS_PORTRAIT_ORIENTATION,
    PEXELS_SEARCH_URL,
)
from ..http_client import RetryingHttpClient
from ..logging_setup import get_logger
from ..models import ClipCandidate, MediaType, SourcePlatform
from .base import MediaSource

logger = get_logger(__name__)

# Pexels rendition 的 mp4 判斷字串
_MP4_FILE_TYPE_HINT: str = "mp4"


def _pexels_headers(api_key: str) -> dict:
    """Pexels 以 Authorization header 帶 API key（非 Bearer）。"""
    return {"Authorization": api_key}


class PexelsVideoSource(MediaSource):
    """Pexels Videos API adapter。"""

    platform = SourcePlatform.PEXELS
    media_type = MediaType.VIDEO

    def __init__(self, api_key: str, http: RetryingHttpClient) -> None:
        """以 API key 與共用 HTTP 客戶端建構。"""
        self._api_key = api_key
        self._http = http

    def search(self, keyword: str, *, page: int, page_size: int) -> list[ClipCandidate]:
        """呼叫 Pexels 影片搜尋並正規化（只要直式結果）。"""
        params = {
            "query": keyword,
            "orientation": PEXELS_PORTRAIT_ORIENTATION,
            "per_page": min(page_size, PEXELS_MAX_PER_PAGE),
            "page": page,
        }
        data = self._http.get_json(PEXELS_SEARCH_URL, params=params, headers=_pexels_headers(self._api_key))
        candidates = [self._to_candidate(v, keyword) for v in data.get("videos", [])]
        result = [c for c in candidates if c is not None]
        logger.debug("Pexels 影片「%s」page=%d 取得 %d 筆", keyword, page, len(result))
        return result

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
            media_type=MediaType.VIDEO,
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


class PexelsPhotoSource(MediaSource):
    """Pexels Photos API adapter（`/v1/search`）。"""

    platform = SourcePlatform.PEXELS
    media_type = MediaType.IMAGE

    def __init__(self, api_key: str, http: RetryingHttpClient, nominal_seconds: float) -> None:
        """以 API key、共用 HTTP 客戶端與圖片名目秒數建構。"""
        self._api_key = api_key
        self._http = http
        self._nominal_seconds = nominal_seconds

    def search(self, keyword: str, *, page: int, page_size: int) -> list[ClipCandidate]:
        """呼叫 Pexels 圖片搜尋並正規化（只要直式結果）。"""
        params = {
            "query": keyword,
            "orientation": PEXELS_PORTRAIT_ORIENTATION,
            "per_page": min(page_size, PEXELS_MAX_PER_PAGE),
            "page": page,
        }
        data = self._http.get_json(PEXELS_PHOTO_SEARCH_URL, params=params, headers=_pexels_headers(self._api_key))
        candidates = [self._to_candidate(p, keyword) for p in data.get("photos", [])]
        result = [c for c in candidates if c is not None]
        logger.debug("Pexels 圖片「%s」page=%d 取得 %d 筆", keyword, page, len(result))
        return result

    def _to_candidate(self, photo: dict, keyword: str) -> ClipCandidate | None:
        """把單一 Pexels photo 物件轉成 ClipCandidate；無有效下載連結則回 None。"""
        src = photo.get("src") or {}
        download_url = src.get("large2x") or src.get("large") or src.get("original")
        thumbnail_url = src.get("tiny") or src.get("small") or src.get("medium")
        width = int(photo.get("width") or 0)
        height = int(photo.get("height") or 0)
        if not download_url or width <= 0 or height <= 0:
            return None

        return ClipCandidate(
            source_platform=SourcePlatform.PEXELS,
            media_type=MediaType.IMAGE,
            video_id=str(photo.get("id")),
            page_url=photo.get("url", ""),
            author_name=photo.get("photographer", "Unknown"),
            author_url=photo.get("photographer_url"),
            license=PEXELS_LICENSE,
            width=width,
            height=height,
            duration_sec=self._nominal_seconds,
            download_url=download_url,
            thumbnail_url=thumbnail_url,
            keyword=keyword,
        )
