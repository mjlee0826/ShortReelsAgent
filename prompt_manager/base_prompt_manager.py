from abc import ABC, abstractmethod

class BasePromptManager(ABC):
    """
    Prompt 管理器的抽象介面。
    定義了 Agent 在各階段所需的提示詞；方法名稱以「產出什麼」命名，方便對照 TaskMode 與呼叫端。
    """

    @abstractmethod
    def get_basic_media_analysis_prompt(self) -> str:
        """基本媒體分析：圖片或簡單短影片的全局描述與語意標籤（Qwen 本地）"""
        pass

    @abstractmethod
    def get_deep_image_analysis_prompt(self) -> str:
        """深度圖片分析：靜態圖片的進階語意分析（Gemini 雲端，付費方案）"""
        pass

    @abstractmethod
    def get_video_event_index_prompt(self) -> str:
        """影片事件索引：複雜影片的逐時間段多模態事件 + 音訊轉錄（Gemini）"""
        pass

    @abstractmethod
    def get_template_analysis_prompt(self) -> str:
        """範本分析：範本影片的事件索引 + 音訊轉錄 + 配樂偵測（曲風 / 歌名猜測）"""
        pass

    @abstractmethod
    def get_director_blueprint_prompt(self, user_prompt: str, assets: list, audio_dna: dict, template_dna: dict = None, previous_timeline: list = None, error_prompt: str = "") -> str:
        """導演剪輯藍圖：將素材庫編排成 Remotion 可渲染的 JSON 剪輯藍圖"""
        pass

    @abstractmethod
    def get_music_search_query_prompt(self, user_prompt: str) -> str:
        """音樂搜尋關鍵字：把使用者的自然語言需求轉成精準的配樂搜尋詞"""
        pass
