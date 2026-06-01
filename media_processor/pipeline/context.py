"""
AssetContext:單一 asset 流經 Pipeline 時的可變狀態容器 (Value Object / Blackboard Pattern)。

設計重點
--------
- **dataclass**:符合 CLAUDE.md「資料結構用 dataclass」要求,欄位皆有型別。
- **欄位全帶預設值**:Week 2a 只需 ``result`` 一個產出欄位;Week 2b/2c 拆 Stage 後,
  各 Stage 會把中間結果寫進 ``scratch``,新增欄位不需大改既有程式(plan 風險表「欄位設計遺漏」緩解)。
- **index 保序**:HybridScheduler 平行完成順序不定,``index`` 記錄輸入順序,
  讓最終 ``phase1_assets_metadata.json`` 與舊版序列輸出逐欄一致。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from media_processor.image_strategy import ImageStrategy
from media_processor.video_strategy import VideoStrategy


# ── 媒體類型 ──────────────────────────────────────────────────────────────────
# 圖片 / 影片副檔名白名單(與 MediaProcessorFactory 路由一致),作為 Pipeline 層
# 判斷 media_kind 的單一來源,避免在 Builder 內散落 magic string。
IMAGE_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif"})
VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mov"})


class MediaKind(str, Enum):
    """asset 的媒體大類,決定 PipelineBuilder 選圖片或影片 pipeline。"""

    IMAGE = "image"
    VIDEO = "video"


# ── 處理狀態 ──────────────────────────────────────────────────────────────────
# 與 media_processor.models.ProcessorResult 的 status 契約對齊,避免 magic string。
STATUS_PENDING = "pending"    # 尚未處理(初始值)
STATUS_SUCCESS = "success"    # 成功,result 內含 metadata
STATUS_REJECTED = "rejected"  # 畫質不足被短路
STATUS_ERROR = "error"        # 例外或解析失敗


def derive_media_kind(file_path: str) -> MediaKind:
    """
    依副檔名判斷 asset 屬於圖片或影片。

    Raises:
        ValueError: 副檔名不在圖片 / 影片白名單內(理論上呼叫端已先過濾)。
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        return MediaKind.IMAGE
    if ext in VIDEO_EXTENSIONS:
        return MediaKind.VIDEO
    raise ValueError(f"不支援的媒體副檔名: {ext}")


@dataclass
class AssetContext:
    """
    單一 asset 的處理上下文,在各 Stage 間傳遞並就地累積結果。

    Week 2a 的 LegacyStage 直接把整份 ``process()`` 輸出寫入 ``result``;
    Week 2b/2c 拆 Stage 後,細粒度 Stage 改寫 ``scratch`` 的中間欄位,最後由 AssemblyStage 組裝成 ``result``。
    """

    # ── 輸入(建構時給定)──────────────────────────────────────────────────
    asset_id: str               # 識別字串,通常為檔名(供進度事件與日誌標示)
    file_path: str              # 媒體檔案絕對路徑
    media_kind: MediaKind       # 圖片 / 影片
    index: int                  # 輸入順序索引,保證輸出排序穩定
    video_strategy: VideoStrategy = VideoStrategy.SIMPLE
    image_strategy: ImageStrategy = ImageStrategy.SIMPLE
    # Week 2a 恆為 0(LegacyStage 用 device-0 singleton);Week 3b 才依 Pool 借出實際裝置
    device_id: int = 0

    # ── 產出(Stage 執行後填入)────────────────────────────────────────────
    status: str = STATUS_PENDING
    result: Optional[dict] = None   # 與 ProcessorResult.to_dict() 相容的最終 metadata
    error: Optional[str] = None     # status==error 時的錯誤訊息
    # 拆 Stage 後各 Stage 的中間產物暫存區(Week 2a 暫不使用,預留擴充)
    scratch: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """是否成功處理(供 Runner 篩選最終要收集的 asset)。"""
        return self.status == STATUS_SUCCESS
