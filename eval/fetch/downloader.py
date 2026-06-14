"""素材（影片/圖片）與縮圖下載、快取索引（冪等、可重複執行）。

以 ``cache_key``（platform:media_type:id）為鍵維護索引；已下載且檔案仍在者跳過，達成「已抓過不重抓」。
下載走 ``RetryingHttpClient`` 的原子 streaming 寫入。
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from ..constants import (
    DEFAULT_IMAGE_EXT,
    DEFAULT_THUMBNAIL_EXT,
    DEFAULT_VIDEO_EXT,
)
from ..http_client import RetryingHttpClient
from ..logging_setup import get_logger
from ..models import ClipCandidate

logger = get_logger(__name__)

# 索引 JSON 縮排
_JSON_INDENT: int = 2


class FetchIndex:
    """已下載快取索引：cache_key → {asset, thumbnail} 本機路徑。"""

    def __init__(self, path: Path, entries: dict[str, dict[str, str]]) -> None:
        """以索引檔路徑與既有內容建構。"""
        self._path = path
        self._entries = entries

    @classmethod
    def load(cls, path: Path) -> "FetchIndex":
        """從檔載入索引；不存在則為空。"""
        entries = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        return cls(path, entries)

    def save(self) -> None:
        """寫回索引檔。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._entries, ensure_ascii=False, indent=_JSON_INDENT),
            encoding="utf-8",
        )

    def get(self, cache_key: str) -> dict[str, str] | None:
        """取得某鍵的本機路徑記錄。"""
        return self._entries.get(cache_key)

    def put(self, cache_key: str, asset_path: str, thumbnail_path: str | None) -> None:
        """寫入某鍵的本機路徑記錄。"""
        self._entries[cache_key] = {"asset": asset_path, "thumbnail": thumbnail_path or ""}


class ClipDownloader:
    """候選素材下載器（含縮圖），冪等。"""

    def __init__(self, http: RetryingHttpClient) -> None:
        """以共用 HTTP 客戶端建構。"""
        self._http = http

    def ensure_downloaded(
        self,
        candidate: ClipCandidate,
        *,
        candidates_dir: Path,
        thumbnails_dir: Path,
        index: FetchIndex,
    ) -> ClipCandidate:
        """確保候選的素材（與縮圖）已在本機；回傳補上本機路徑的候選。

        若索引已記錄且檔案仍存在 → 直接沿用（不重抓）；否則下載並更新索引。
        """
        cached = index.get(candidate.cache_key)
        if cached and Path(cached.get("asset", "")).is_file():
            # 快取命中：沿用既有檔案，補回路徑
            thumb = cached.get("thumbnail") or None
            return candidate.model_copy(update={"local_path": cached["asset"], "thumbnail_path": thumb})

        # 下載主素材（影片或圖片）
        default_ext = DEFAULT_IMAGE_EXT if candidate.is_image else DEFAULT_VIDEO_EXT
        asset_name = self._build_filename(candidate, candidate.download_url, default_ext)
        asset_path = candidates_dir / asset_name
        logger.debug("下載素材 %s → %s", candidate.cache_key, asset_path)
        self._http.download(candidate.download_url, asset_path)

        # 下載縮圖（失敗不致命：仍可成案，只是 preview 少一張圖）
        thumbnail_path: Path | None = None
        if candidate.thumbnail_url:
            thumb_name = self._build_filename(candidate, candidate.thumbnail_url, DEFAULT_THUMBNAIL_EXT)
            thumbnail_path = thumbnails_dir / thumb_name
            try:
                self._http.download(candidate.thumbnail_url, thumbnail_path)
            except Exception as exc:  # 縮圖失敗不阻斷流程
                logger.warning("縮圖下載失敗（%s）：%s", candidate.cache_key, exc)
                thumbnail_path = None

        index.put(candidate.cache_key, str(asset_path), str(thumbnail_path) if thumbnail_path else None)
        index.save()  # 增量持久化，部分中斷也能保住進度
        return candidate.model_copy(
            update={
                "local_path": str(asset_path),
                "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
            }
        )

    @staticmethod
    def _build_filename(candidate: ClipCandidate, url: str, default_ext: str) -> str:
        """以 platform_mediatype_id + URL 副檔名（或預設）組檔名。"""
        suffix = Path(urlparse(url).path).suffix
        ext = suffix if suffix else default_ext
        return f"{candidate.source_platform.value}_{candidate.media_type.value}_{candidate.video_id}{ext}"
