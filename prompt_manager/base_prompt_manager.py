from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel


@dataclass(frozen=True)
class PromptSpec:
    """
    單支 prompt 的產出規格：給模型的指令文字 + （選填）結構化輸出 schema。

    ``schema`` 為 Gemini ``response_schema`` 用的 pydantic model；為 ``None`` 時代表走純文字
    路徑（如本地 Qwen 無 structured-output 能力），此時格式約束已由 ``schema_to_text`` 序列化
    進 ``text``。如此「格式交給 schema、文字專注心法」，且兩條路徑同源於 ``prompt_manager.schemas``。
    """
    text: str
    schema: Optional[type[BaseModel]] = None


class BasePromptManager(ABC):
    """
    Prompt 管理器的抽象介面。

    定義 Agent 在各階段所需的提示詞；方法名稱以「產出什麼」命名，方便對照 TaskMode 與呼叫端。
    每個方法回傳 :class:`PromptSpec`（指令文字 + 選填 schema），由 model manager 決定要不要
    把 schema 交給 ``response_schema``。
    """

    @abstractmethod
    def get_basic_media_analysis_prompt(self) -> PromptSpec:
        """基本媒體分析：圖片或簡單短影片的全局描述與語意標籤（Qwen 本地，純文字路徑）"""

    @abstractmethod
    def get_deep_image_analysis_prompt(self) -> PromptSpec:
        """深度圖片分析：靜態圖片的進階語意分析（Gemini 雲端，付費方案）"""

    @abstractmethod
    def get_video_event_index_prompt(self) -> PromptSpec:
        """影片事件索引：複雜影片的逐時間段多模態事件 + 音訊轉錄（Gemini）"""

    @abstractmethod
    def get_template_analysis_prompt(self) -> PromptSpec:
        """範本分析：範本影片的事件索引 + 音訊轉錄 + 配樂偵測（曲風 / 歌名猜測）"""

    @abstractmethod
    def get_director_agentic_system_prompt(self, has_template: bool = False,
                                           is_refinement: bool = False) -> str:
        """Agentic 導演系統提示（純心法、可快取）：角色 + 工作方式 + 剪輯 / 字幕心法 + 工具箱 + 物理鐵律"""

    @abstractmethod
    def build_director_agentic_user_message(self, user_prompt, catalog, manifest_text, creative_brief="",
                                            template_dna=None, previous_timeline=None) -> str:
        """組 agentic 導演首則 user 訊息：使用者指令 + 創意定錨 + 極輕素材目錄 + 欄位 manifest + 範本 DNA"""

    @abstractmethod
    def get_music_search_query_prompt(self, user_prompt: str, asset_mood_summary: str = "") -> PromptSpec:
        """音樂搜尋關鍵字：把使用者需求轉成配樂搜尋詞；asset_mood_summary 提供素材整體氛圍供推測"""

    @abstractmethod
    def get_music_brief_prompt(self, user_prompt: str, asset_mood_summary: str = "") -> PromptSpec:
        """Stage 1 創意 brief（Claude）：一次給配樂搜尋詞 search_query + 創意定錨 creative_brief"""
