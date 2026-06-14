"""Prompt 生成策略介面（Strategy）。

保留抽象介面，未來若要新增「呼叫 LLM 生成」的策略也不會破壞既有架構；本次只實作範本版。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import GroupSpec, PromptVariant


class PromptGenerator(ABC):
    """為單一素材組生成多個 user prompt 的策略介面。"""

    @abstractmethod
    def generate(self, group: GroupSpec) -> list[PromptVariant]:
        """回傳 ``group.prompt_count`` 個多樣化的 ``PromptVariant``。"""
        raise NotImplementedError
