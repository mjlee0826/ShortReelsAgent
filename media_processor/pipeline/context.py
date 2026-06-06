"""
AssetContext:單一 asset 流經 Pipeline 時的可變狀態容器 (Value Object / Blackboard Pattern)。

設計重點
--------
- **dataclass**:符合 CLAUDE.md「資料結構用 dataclass」要求,欄位皆有型別。
- **欄位全帶預設值**:細粒度 Stage 把中間結果寫進 ``scratch``,
  新增欄位不需大改既有程式。
- **index 保序**:HybridScheduler 平行完成順序不定,``index`` 記錄輸入順序,
  讓最終 ``phase1_assets_metadata.json`` 與舊版序列輸出逐欄一致。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from config.media_formats import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from media_processor.image_strategy import ImageStrategy
from media_processor.video_strategy import VideoStrategy

if TYPE_CHECKING:
    # 僅型別檢查時 import,執行期不依賴(配合 from __future__ import annotations),避免低階模組耦合
    from media_processor.pipeline.progress import ProgressTracker


# ── 媒體類型 ──────────────────────────────────────────────────────────────────
# 圖片 / 影片副檔名白名單改由 config.media_formats 單一來源提供(見頂部 import),於此 re-export
# 供 derive_media_kind 與既有 `from context import IMAGE/VIDEO_EXTENSIONS` 的下游沿用。


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

    LegacyStage 直接把整份 ``process()`` 輸出寫入 ``result``;
    細粒度 Stage 則改寫 ``scratch`` 的中間欄位,最後由 AssemblyStage 組裝成 ``result``。
    """

    # ── 輸入(建構時給定)──────────────────────────────────────────────────
    # 素材身分:相對 project root 的 relpath(如 raw/photo.jpg);作為 status / metadata / 策略 meta
    # 的鍵、blueprint clip_id 與進度事件標示。與 file_path(絕對路徑,供讀檔)分離。
    asset_id: str
    file_path: str              # 媒體檔案絕對路徑(供各 Stage 實際讀檔)
    media_kind: MediaKind       # 圖片 / 影片
    index: int                  # 輸入順序索引,保證輸出排序穩定
    video_strategy: VideoStrategy = VideoStrategy.SIMPLE
    image_strategy: ImageStrategy = ImageStrategy.SIMPLE
    # GPU stage 使用的裝置 id;預設 device-0,啟用多卡 Pool 時依借出的實際裝置覆寫
    device_id: int = 0
    # driver 注入本次 run 的 ProgressTracker,讓 GPU stage 的 borrow 即時 VRAM 等待
    # 能發出帶 asset_id 的 RESOURCE_WAIT / RESOURCE_ACQUIRED 事件(無 tracker 時為 None,事件略過)
    tracker: Optional["ProgressTracker"] = None

    # ── 產出(Stage 執行後填入)────────────────────────────────────────────
    status: str = STATUS_PENDING
    result: Optional[dict] = None   # 與 ProcessorResult.to_dict() 相容的最終 metadata
    error: Optional[str] = None     # status==error 時的錯誤訊息
    # 各 Stage 的中間產物暫存區(細粒度 Stage 間傳遞用)
    scratch: dict[str, Any] = field(default_factory=dict)
    # 本 asset 處理期間產生、結束時需刪除的暫存檔絕對路徑(例:影片 audio wav / timecode mp4)。
    # 建檔 Stage 以 append 登記(GIL 下 list.append 為原子操作,平行 Stage 併發登記安全);
    # Pipeline.execute 在 finally 統一清除,success / rejected / error 三條路徑都會清(取代原 process() 的 finally)。
    temp_paths: list[str] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        """是否成功處理(供 Runner 篩選最終要收集的 asset)。"""
        return self.status == STATUS_SUCCESS
