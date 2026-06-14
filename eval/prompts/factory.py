"""Prompt 生成器工廠（Factory）。

依策略名建立 ``PromptGenerator``。目前只有 template 策略；保留工廠以利日後擴充。
"""
from __future__ import annotations

from ..constants import PROMPT_GENERATOR_TEMPLATE
from .base import PromptGenerator
from .template_generator import TemplatePromptGenerator


class PromptGeneratorFactory:
    """建立 prompt 生成策略的工廠。"""

    @staticmethod
    def create(kind: str = PROMPT_GENERATOR_TEMPLATE) -> PromptGenerator:
        """依策略名建立生成器。

        例外
            ValueError: 未知的策略名。
        """
        if kind == PROMPT_GENERATOR_TEMPLATE:
            return TemplatePromptGenerator()
        raise ValueError(f"未知的 prompt 生成策略：{kind}")
