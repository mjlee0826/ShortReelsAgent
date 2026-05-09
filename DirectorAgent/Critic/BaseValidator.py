from abc import ABC, abstractmethod

class BaseValidator(ABC):
    @abstractmethod
    def validate(self, timeline: list, assets: list) -> list:
        """回傳此驗證器發現的所有錯誤訊息清單"""
        pass