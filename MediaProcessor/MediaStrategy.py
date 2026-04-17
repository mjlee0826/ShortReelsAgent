from abc import ABC, abstractmethod
from BlipModelManager import BlipModelManager

class MediaStrategy(ABC):
    """
    策略模式 (Strategy): 定義素材處理器的標準介面
    """
    def __init__(self):
        self.vision_engine = BlipModelManager()

    @abstractmethod
    def process(self, file_path: str) -> dict:
        pass