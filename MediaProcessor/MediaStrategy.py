from abc import ABC, abstractmethod

class MediaStrategy(ABC):
    """
    策略模式 (Strategy): 定義素材處理器的標準介面。
    重構：移除在父類別強制初始化 BlipModelManager 的邏輯，
    將依賴注入 (Dependency Injection) 的責任交給具體實作的子類別。
    """
    @abstractmethod
    def process(self, file_path: str) -> dict:
        pass