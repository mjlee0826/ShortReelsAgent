"""藍圖準備階段的唯讀輸入值物件。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrepContext:
    """藍圖準備階段的唯讀輸入(Value Object / Parameter Object)。

    兩分支共用同一份輸入、各取所需:template 分支用 ``template_url``;music 分支用
    ``music_strategy`` / ``user_music_file`` / ``user_prompt`` / ``regenerate_music``。
    ``frozen`` 確保並行讀取期間不被任一分支竄改(故 tracker 等「活協作者」刻意不放進來,
    以獨立參數貫穿,見 docs/blueprint_prep_design.md §10.5)。
    """

    template_url: str | None
    music_strategy: str
    user_music_file: str | None      # 已解析為絕對路徑
    user_prompt: str
    regenerate_music: bool
    # 素材整體氛圍摘要(主要情緒 + 常見場景);music 分支在使用者未指定配樂時據此推測搜尋詞
    asset_mood_summary: str = ""
