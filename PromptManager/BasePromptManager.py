from abc import ABC, abstractmethod

class BasePromptManager(ABC):
    """
    Prompt 管理器的抽象介面。
    定義了 Agent 在不同階段所需的視覺推理任務。
    """
    
    @abstractmethod
    def get_media_analysis_prompt(self) -> str:
        """適用於靜態圖片或簡單影片的全局描述與評價"""
        pass

    @abstractmethod
    def get_timecoded_action_index_prompt(self) -> str:
        """適用於 Omni 架構：要求模型讀取畫面左上角的時間碼並進行多模態分段"""
        pass

    @abstractmethod
    def get_director_prompt(self, user_prompt: str, assets: list, audio_dna: dict, template_dna: dict = None, previous_timeline: list = None, error_prompt: str = "") -> str:
        pass