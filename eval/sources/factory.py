"""來源 adapter 工廠（Factory）。

依平台 enum 從環境變數讀對應 API key 並建立 adapter；金鑰缺失時拋出清楚錯誤。
"""
from __future__ import annotations

import os

from ..constants import ENV_PEXELS_API_KEY, ENV_PIXABAY_API_KEY
from ..http_client import RetryingHttpClient
from ..models import SourcePlatform
from .base import VideoSource
from .pexels import PexelsSource
from .pixabay import PixabaySource

# 平台 → (adapter 類別, 金鑰環境變數名)
_PLATFORM_REGISTRY: dict[SourcePlatform, tuple[type[VideoSource], str]] = {
    SourcePlatform.PEXELS: (PexelsSource, ENV_PEXELS_API_KEY),
    SourcePlatform.PIXABAY: (PixabaySource, ENV_PIXABAY_API_KEY),
}


class VideoSourceFactory:
    """依平台建立 ``VideoSource`` 的工廠。"""

    @staticmethod
    def create(platform: SourcePlatform, http: RetryingHttpClient) -> VideoSource:
        """建立單一平台的 adapter。

        例外
            ValueError: 平台不支援。
            EnvironmentError: 對應的 API key 環境變數未設定。
        """
        entry = _PLATFORM_REGISTRY.get(platform)
        if entry is None:
            raise ValueError(f"不支援的來源平台：{platform}")
        source_cls, env_name = entry

        api_key = os.environ.get(env_name)
        if not api_key:
            raise EnvironmentError(
                f"找不到 {platform.value} 的 API key，請設定環境變數 {env_name}"
            )
        return source_cls(api_key, http)

    @staticmethod
    def create_all(
        platforms: list[SourcePlatform], http: RetryingHttpClient
    ) -> list[VideoSource]:
        """依序建立多個平台的 adapter。"""
        return [VideoSourceFactory.create(p, http) for p in platforms]
