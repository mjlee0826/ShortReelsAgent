"""
導演 agentic loop 的共享上下文 (Context Object Pattern)。

一個 :class:`AgentContext` 實例貫穿整輪 loop，傳給每個工具的 ``execute``：工具讀它取素材 dossier、
記錄「已親看的時間範圍」（供必讀強制驗證）、就地套用 metadata 修正。刻意為可變 dataclass（非
frozen），因 ``viewed`` / ``corrections`` / ``asset_index`` 會在 loop 過程被工具更新。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from config.director_config import DIRECTOR_VIEWED_OVERLAP_TOLERANCE_SECONDS
from media_processor.pipeline.progress.tracker import ProgressTracker


@dataclass
class AgentContext:
    """貫穿整輪 agentic loop 的共享可變上下文（工具的執行環境）。"""

    # id → 完整 dossier（``ContextCompressor.compress`` 產出）；correct_metadata 就地改寫語意欄位
    asset_index: dict[str, dict]
    # 專案絕對路徑（view_raw 解析素材實體檔用）
    project_dir: str
    # 進度追蹤器（串流 thinking / 工具旁白 / 提問到 WS）；可為 None（離線測試）
    tracker: Optional[ProgressTracker] = None
    # asset_id → 已 view_raw 的時間範圍清單 [(start, end), ...]；圖片以 (0.0, 0.0) 記一次
    viewed: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    # metadata 修正紀錄（供落地 session / 觀測）：[{asset_id, field, before, after, reason}, ...]
    corrections: list[dict] = field(default_factory=list)
    # 背景配樂 future（B 設計：music ∥ loop 重疊）；get_music_beats join 它取 beats。resume 時為 None
    music_future: Optional[object] = None
    # 已解析的配樂 audio_dna；get_music_beats join future 後快取於此，resume 時由 facade 直接設入
    audio_dna: Optional[dict] = None

    def record_view(self, asset_id: str, start: float = 0.0, end: float = 0.0) -> None:
        """記錄某素材已被親看的一段時間範圍（圖片用 (0.0, 0.0)）。"""
        self.viewed.setdefault(asset_id, []).append((start, end))

    def was_viewed(self, asset_id: str, start: float = 0.0, end: float = 0.0) -> bool:
        """
        判斷某素材的 ``[start, end]`` 區間是否已被親看過（供必讀強制驗證）。

        圖片（記為 (0,0)）只要看過一次即視為涵蓋；影片要求請求區間落在某一段已看範圍內
        （含 ``DIRECTOR_VIEWED_OVERLAP_TOLERANCE_SECONDS`` 容差，避免邊界捨入誤判）。
        """
        ranges = self.viewed.get(asset_id)
        if not ranges:
            return False
        tol = DIRECTOR_VIEWED_OVERLAP_TOLERANCE_SECONDS
        for (viewed_start, viewed_end) in ranges:
            # 圖片或無區間（start==end==0）：看過即算涵蓋
            if viewed_end <= viewed_start:
                return True
            if start >= viewed_start - tol and end <= viewed_end + tol:
                return True
        return False

    def apply_correction(
        self, asset_id: str, field_name: str, value: Any, reason: str
    ) -> tuple[bool, str]:
        """
        就地套用一筆語意欄位修正到 in-session dossier，回 ``(是否成功, 訊息)``。

        身分不存在 → 失敗；成功則改寫 ``dossier[field_name]`` 並記錄 before/after/reason。
        物理欄位的攔阻在 ``correct_metadata`` 工具層（白名單）處理，本方法只負責落地與記錄。
        """
        dossier = self.asset_index.get(asset_id)
        if dossier is None:
            return False, f"素材 id 不存在：{asset_id}"
        before = dossier.get(field_name)
        dossier[field_name] = value
        self.corrections.append({
            "asset_id": asset_id, "field": field_name,
            "before": before, "after": value, "reason": reason,
        })
        return True, f"已修正 {asset_id}.{field_name}"
