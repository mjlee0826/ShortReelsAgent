"""藍圖準備階段的唯讀輸入值物件。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrepContext:
    """Template DNA 生產者的唯讀輸入 (Value Object)。

    Phase 4 agentic 改造後,配樂改由 ``director_service`` 直接呼叫 ``MusicDirector``(不再經本物件),
    故原 music 分支欄位(music_strategy / user_music_file / regenerate_music / user_prompt /
    asset_mood_summary)已移除;現只剩 template 分支需要的 ``template_url``。``frozen`` 維持唯讀語意。
    """

    template_url: str | None
