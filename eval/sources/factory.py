"""來源 adapter 工廠（Factory）。

依（平台 × 媒體類型）從環境變數讀對應 API key 並建立 adapter；金鑰缺失時拋出清楚錯誤。
圖片來源需要圖片名目秒數，建立時一併注入。
"""
from __future__ import annotations

import os

from ..constants import ENV_PEXELS_API_KEY, ENV_PIXABAY_API_KEY
from ..http_client import RetryingHttpClient
from ..models import MediaType, SourcePlatform
from .base import MediaSource
from .pexels import PexelsPhotoSource, PexelsVideoSource
from .pixabay import PixabayImageSource, PixabayVideoSource

# (平台, 媒體類型) → (adapter 類別, 金鑰環境變數名)
_REGISTRY: dict[tuple[SourcePlatform, MediaType], tuple[type[MediaSource], str]] = {
    (SourcePlatform.PEXELS, MediaType.VIDEO): (PexelsVideoSource, ENV_PEXELS_API_KEY),
    (SourcePlatform.PEXELS, MediaType.IMAGE): (PexelsPhotoSource, ENV_PEXELS_API_KEY),
    (SourcePlatform.PIXABAY, MediaType.VIDEO): (PixabayVideoSource, ENV_PIXABAY_API_KEY),
    (SourcePlatform.PIXABAY, MediaType.IMAGE): (PixabayImageSource, ENV_PIXABAY_API_KEY),
}


class MediaSourceFactory:
    """依（平台 × 媒體類型）建立 ``MediaSource`` 的工廠。"""

    @staticmethod
    def create(
        platform: SourcePlatform,
        media_type: MediaType,
        http: RetryingHttpClient,
        *,
        image_nominal_seconds: float,
    ) -> MediaSource:
        """建立單一（平台 × 類型）的 adapter。

        例外
            ValueError: 平台/類型組合不支援。
            EnvironmentError: 對應的 API key 環境變數未設定。
        """
        entry = _REGISTRY.get((platform, media_type))
        if entry is None:
            raise ValueError(f"不支援的來源組合：{platform.value} / {media_type.value}")
        source_cls, env_name = entry

        api_key = os.environ.get(env_name)
        if not api_key:
            raise EnvironmentError(
                f"找不到 {platform.value} 的 API key，請設定環境變數 {env_name}"
            )

        # 圖片來源多吃一個名目秒數參數
        if media_type is MediaType.IMAGE:
            return source_cls(api_key, http, image_nominal_seconds)
        return source_cls(api_key, http)

    @staticmethod
    def create_for(
        platforms: list[SourcePlatform],
        media_types: list[MediaType],
        http: RetryingHttpClient,
        *,
        image_nominal_seconds: float,
    ) -> list[MediaSource]:
        """為每個（平台 × 類型）組合建立 adapter（不支援的組合自動略過）。"""
        sources: list[MediaSource] = []
        for platform in platforms:
            for media_type in media_types:
                if (platform, media_type) in _REGISTRY:
                    sources.append(
                        MediaSourceFactory.create(
                            platform, media_type, http, image_nominal_seconds=image_nominal_seconds
                        )
                    )
        return sources
