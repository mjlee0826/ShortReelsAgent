"""素材來源抽象介面（Adapter + Strategy）。

各平台 adapter 把自家 REST API 的回應正規化成統一的 ``ClipCandidate``（影片或圖片），上層 fetch
階段便不需知道平台與媒體類型差異。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import ClipCandidate, MediaType, SourcePlatform


class MediaSource(ABC):
    """單一（平台 × 媒體類型）的統一查詢介面。"""

    #: 此來源對應的平台
    platform: SourcePlatform
    #: 此來源產出的媒體類型（影片或圖片）
    media_type: MediaType

    @abstractmethod
    def search(self, keyword: str, *, page: int, page_size: int) -> list[ClipCandidate]:
        """以關鍵字搜尋，回傳正規化後的候選清單（單頁）。

        參數
            keyword: 搜尋關鍵字。
            page: 第幾頁（1-based）。
            page_size: 期望單頁筆數（adapter 會 clamp 到平台上限）。
        回傳
            ``ClipCandidate`` 清單；解析不出有效下載連結的項目會被略過。
        """
        raise NotImplementedError
