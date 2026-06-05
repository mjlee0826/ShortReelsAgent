"""
素材縮圖服務 (Service Pattern)。

為 Asset Management 網格產生並快取縮圖:圖片用 PIL 等比縮放、影片取中間代表幀。
縮圖落在 ``TEMP_TEMPLATES_DIR/thumbnails/{user_id}/{project}/{檔名}.jpg``,沿用既有 ``/cache``
靜態路由對外服務(與 /static、/cache 同為免授權靜態,前端 ``<img>`` 可直接讀)。

採 lazy 產生:已存在即略過,只在缺檔時產一次,之後命中快取。任何產生失敗都回傳 None
(由前端顯示佔位),不讓縮圖問題影響素材列表本身。
"""
from __future__ import annotations

import os
from typing import Optional

import cv2
from PIL import Image

from config.app_config import (
    TEMP_TEMPLATES_DIR,
    THUMBNAIL_EXT,
    THUMBNAIL_JPEG_QUALITY,
    THUMBNAIL_MAX_PX,
    THUMBNAIL_SUBDIR,
)
from config.media_processor_config import MIDDLE_FRAME_POSITION
from media_processor.pipeline.context import MediaKind
from media_processor.pipeline.stages.video_frame_utils import grab_frame_at_time

# 後端對外位址預設值(與 director_service 一致):用來組 /cache 縮圖的完整 URL
_DEFAULT_BACKEND_URL = "http://localhost:5174"


class ThumbnailService:
    """產生 / 快取素材縮圖,並回傳可直接給前端 ``<img src>`` 的 /cache URL。"""

    def __init__(
        self,
        cache_root: str = TEMP_TEMPLATES_DIR,
        backend_url: Optional[str] = None,
        max_px: int = THUMBNAIL_MAX_PX,
        subdir: str = THUMBNAIL_SUBDIR,
    ):
        """
        設定縮圖快取根目錄與後端對外位址(URL 組裝用)。

        max_px / subdir 可覆寫,讓不同版位(如較大的專案封面)用各自的尺寸與獨立快取目錄、
        彼此不覆蓋;預設沿用素材網格的 320px 與 thumbnails/,行為向後相容。
        """
        self._cache_root = cache_root
        self._thumb_root = os.path.join(cache_root, subdir)
        self._backend_url = backend_url or os.getenv("BACKEND_URL", _DEFAULT_BACKEND_URL)
        self._max_px = max_px

    def ensure_url(
        self,
        user_id: str,
        project: str,
        filename: str,
        src_path: str,
        media_kind: MediaKind,
    ) -> Optional[str]:
        """
        確保某素材的縮圖存在(缺檔才產),回傳其 /cache 完整 URL;產生失敗回 None。
        """
        out_path = os.path.join(self._thumb_root, user_id, project, filename + THUMBNAIL_EXT)
        if not os.path.exists(out_path):
            if not self._generate(src_path, media_kind, out_path):
                return None
        # 相對於 cache 根目錄的路徑即 /cache 之後的 URL 片段(統一以正斜線輸出)
        rel_path = os.path.relpath(out_path, self._cache_root).replace(os.sep, "/")
        return f"{self._backend_url}/cache/{rel_path}"

    def _generate(self, src_path: str, media_kind: MediaKind, out_path: str) -> bool:
        """依媒體類型取一張代表圖、等比縮放後存成 JPEG;任何失敗回 False(不拋例外)。"""
        try:
            image = (
                self._load_image_thumbnail(src_path)
                if media_kind == MediaKind.IMAGE
                else self._load_video_thumbnail(src_path)
            )
            if image is None:
                return False
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            # 等比縮到長邊不超過上限(依本 instance 的 max_px);RGB 轉換確保可存 JPEG(去除 alpha / palette)
            image.thumbnail((self._max_px, self._max_px), Image.LANCZOS)
            image.convert("RGB").save(out_path, format="JPEG", quality=THUMBNAIL_JPEG_QUALITY)
            return True
        except Exception as exc:  # noqa: BLE001 - 縮圖非關鍵路徑,任何失敗都退佔位
            print(f"[ThumbnailService Warning] 產生縮圖失敗 ({os.path.basename(src_path)}): {exc}")
            return False

    @staticmethod
    def _load_image_thumbnail(src_path: str) -> Optional[Image.Image]:
        """開啟圖片素材為 PIL Image(HEIC 等 PIL 無法解碼者回 None,退佔位)。"""
        return Image.open(src_path)

    @staticmethod
    def _load_video_thumbnail(src_path: str) -> Optional[Image.Image]:
        """取影片中間代表幀為 PIL Image;以 cv2 算片長後重用既有的取幀工具。"""
        cap = cv2.VideoCapture(src_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        duration = float(frame_count) / float(fps) if fps > 0 else 0.0
        return grab_frame_at_time(src_path, duration * MIDDLE_FRAME_POSITION)
