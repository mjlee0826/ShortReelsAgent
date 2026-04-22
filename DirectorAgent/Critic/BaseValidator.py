from abc import ABC, abstractmethod

class BaseValidator(ABC):
    def __init__(self, next_validator=None):
        self.next = next_validator

    @abstractmethod
    def validate(self, timeline: list, assets: list) -> list:
        """回傳錯誤訊息清單，若無錯誤則傳給下一個驗證器"""
        pass