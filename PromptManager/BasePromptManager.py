from abc import ABC, abstractmethod

class BasePromptManager(ABC):
    """
    Prompt 管理器的抽象介面。
    未來任何人想自訂 Prompt，都必須繼承這個類別並實作裡面的方法。
    """
    
    @abstractmethod
    def get_media_analysis_prompt(self) -> str:
        pass