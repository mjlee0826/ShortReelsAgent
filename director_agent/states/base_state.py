from abc import ABC, abstractmethod

class BaseState(ABC):
    @abstractmethod
    def run(self, context: dict):
        pass