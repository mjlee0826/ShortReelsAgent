"""Pixabay 來源 adapter（影片 + 圖片）。

- ``PixabayVideoSource``：Videos API，挑寬度達門檻中解析度最高的 size。
- ``PixabayImageSource``：Images API（`image_type=photo`），下載 largeImageURL、用 previewURL 當縮圖；
  圖片 duration 以名目秒數填入。Pixabay 無 orientation 參數，直式與否由寬高自行判定。
"""
from __future__ import annotations

from ..constants import (
    MIN_CLIP_WIDTH,
    PIXABAY_IMAGE_SEARCH_URL,
    PIXABAY_IMAGE_TYPE_PHOTO,
    PIXABAY_LICENSE,
    PIXABAY_MAX_PER_PAGE,
    PIXABAY_SEARCH_URL,
)
from ..http_client import RetryingHttpClient
from ..logging_setup import get_logger
from ..models import ClipCandidate, MediaType, SourcePlatform
from .base import MediaSource

logger = get_logger(__name__)


def _build_author_url(hit: dict) -> str | None:
    """由 user 與 user_id 組出 Pixabay 使用者頁面 URL（缺值則回 None）。"""
    user = hit.get("user")
    user_id = hit.get("user_id")
    if user and user_id:
        return f"https://pixabay.com/users/{user}-{user_id}/"
    return None


class PixabayVideoSource(MediaSource):
    """Pixabay Videos API adapter。"""

    platform = SourcePlatform.PIXABAY
    media_type = MediaType.VIDEO

    def __init__(self, api_key: str, http: RetryingHttpClient) -> None:
        """以 API key 與共用 HTTP 客戶端建構。"""
        self._api_key = api_key
        self._http = http

    def search(self, keyword: str, *, page: int, page_size: int) -> list[ClipCandidate]:
        """呼叫 Pixabay 影片搜尋並正規化。"""
        params = {
            "key": self._api_key,
            "q": keyword,
            "per_page": min(page_size, PIXABAY_MAX_PER_PAGE),
            "page": page,
        }
        data = self._http.get_json(PIXABAY_SEARCH_URL, params=params)
        candidates = [self._to_candidate(h, keyword) for h in data.get("hits", [])]
        result = [c for c in candidates if c is not None]
        logger.debug("Pixabay 影片「%s」page=%d 取得 %d 筆", keyword, page, len(result))
        return result

    def _to_candidate(self, hit: dict, keyword: str) -> ClipCandidate | None:
        """把單一 Pixabay 影片 hit 轉成 ClipCandidate；無有效 size 則回 None。"""
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
            media_type=MediaType.VIDEO,
            video_id=str(hit.get("id")),
            page_url=hit.get("pageURL", ""),
            author_name=hit.get("user", "Unknown"),
            author_url=_build_author_url(hit),
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


class PixabayImageSource(MediaSource):
    """Pixabay Images API adapter（`image_type=photo`）。"""

    platform = SourcePlatform.PIXABAY
    media_type = MediaType.IMAGE

    def __init__(self, api_key: str, http: RetryingHttpClient, nominal_seconds: float) -> None:
        """以 API key、共用 HTTP 客戶端與圖片名目秒數建構。"""
        self._api_key = api_key
        self._http = http
        self._nominal_seconds = nominal_seconds

    def search(self, keyword: str, *, page: int, page_size: int) -> list[ClipCandidate]:
        """呼叫 Pixabay 圖片搜尋並正規化。"""
        params = {
            "key": self._api_key,
            "q": keyword,
            "image_type": PIXABAY_IMAGE_TYPE_PHOTO,
            "per_page": min(page_size, PIXABAY_MAX_PER_PAGE),
            "page": page,
        }
        data = self._http.get_json(PIXABAY_IMAGE_SEARCH_URL, params=params)
        candidates = [self._to_candidate(h, keyword) for h in data.get("hits", [])]
        result = [c for c in candidates if c is not None]
        logger.debug("Pixabay 圖片「%s」page=%d 取得 %d 筆", keyword, page, len(result))
        return result

    def _to_candidate(self, hit: dict, keyword: str) -> ClipCandidate | None:
        """把單一 Pixabay 圖片 hit 轉成 ClipCandidate；無有效下載連結則回 None。"""
        download_url = hit.get("largeImageURL") or hit.get("fullHDURL") or hit.get("webformatURL")
        thumbnail_url = hit.get("previewURL") or hit.get("webformatURL")
        # imageWidth/imageHeight 為原圖尺寸；largeImageURL 為等比例縮放（直式與否、長寬比一致）
        width = int(hit.get("imageWidth") or 0)
        height = int(hit.get("imageHeight") or 0)
        if not download_url or width <= 0 or height <= 0:
            return None

        return ClipCandidate(
            source_platform=SourcePlatform.PIXABAY,
            media_type=MediaType.IMAGE,
            video_id=str(hit.get("id")),
            page_url=hit.get("pageURL", ""),
            author_name=hit.get("user", "Unknown"),
            author_url=_build_author_url(hit),
            license=PIXABAY_LICENSE,
            width=width,
            height=height,
            duration_sec=self._nominal_seconds,
            download_url=download_url,
            thumbnail_url=thumbnail_url,
            keyword=keyword,
        )
