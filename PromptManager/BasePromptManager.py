from abc import ABC, abstractmethod

class BasePromptManager(ABC):
    """
    Prompt 管理器的抽象介面。
    定義了 Agent 在不同階段所需的視覺推理任務。
    """
    
    @abstractmethod
    def get_media_analysis_prompt(self) -> str:
        """適用於 StandardVideoProcessor: 進行全局的攝影評論與描述"""
        pass

    @abstractmethod
    def get_action_index_prompt(self) -> str:
        """適用於 DenseSequenceVideoProcessor: 針對 2-3 秒切片描述具體動作"""
        pass

    @abstractmethod
    def get_cinematic_style_prompt(self) -> str:
        """適用於 Phase 2 TemplateAnalyzer: 萃取導演的運鏡與視覺 DNA"""
        pass