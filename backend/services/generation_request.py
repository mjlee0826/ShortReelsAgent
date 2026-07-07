"""
一次 blueprint 生成（初次 / 微調）的請求脈絡 (Parameter Object / Value Object)。

原本 ``prompt / folder_name / template / subtitles / filters / old_timeline / music_strategy /
user_music_file / regenerate_music / previous_bgm_track`` 這組參數原樣穿過 API 端點 →
``run_workflow`` → ``_run_workflow_inner`` → ``_suspend_for_clarification`` → ``AgentSession`` →
``resume_generation`` 共 6+ 處簽名，每加一個生成選項要同步改全部。收斂成單一 pydantic 值物件：
新選項只加一個欄位，各層簽名不再變動；B2 暫停時整包內嵌進 ``AgentSession`` 直接 JSON 落地。

``user_id``（認證身分）與 ``tracker``（執行期基礎設施）刻意**不**入本物件：前者是授權脈絡、
後者不可序列化，兩者皆維持獨立參數。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# 預設配樂策略（與 director_agent.music_director.MUSIC_STRATEGY_SEARCH_COPYRIGHT 同值；
# 刻意不 import 該模組——它拉起 Gemini SDK 等重依賴，本值物件須保持可被 store 層輕量載入）
_DEFAULT_MUSIC_STRATEGY = "search_copyright"


class GenerationRequest(BaseModel):
    """一次 blueprint 生成的完整請求內容（可 JSON 落地 / 載回，供 B2 session 內嵌）。"""

    # 使用者指令與目標專案
    prompt: str
    folder_name: str
    # 範本影片來源 URL（無範本為 None）
    template: Optional[str] = None
    # 字幕 / 調色開關（後端 post-LLM 雙保險用）
    subtitles: bool = True
    filters: bool = True
    # 微調模式：前端送回的上一版完整藍圖（None = 初次生成）
    old_timeline: Optional[dict] = None
    # 配樂策略（search_copyright | search_free | none）與自訂上傳檔名
    music_strategy: str = _DEFAULT_MUSIC_STRATEGY
    user_music_file: Optional[str] = None
    # 是否重挑配樂；False 時沿用 previous_bgm_track（音樂保護）
    regenerate_music: bool = True
    previous_bgm_track: Optional[dict] = Field(default=None)

    @property
    def is_refinement(self) -> bool:
        """是否為微調（帶上一版藍圖）；單一判定來源，取代散落的 ``old_timeline is not None``。"""
        return self.old_timeline is not None
