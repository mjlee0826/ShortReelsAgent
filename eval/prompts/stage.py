"""階段 4 主流程：為每組生成 prompt 並寫出 prompts.json。

此階段不需網路/金鑰，純離線決定性生成。
"""
from __future__ import annotations

from ..jsonio import write_models
from ..logging_setup import get_logger
from ..pipeline import BuildContext, PipelineStage
from .factory import PromptGeneratorFactory

logger = get_logger(__name__)


class PromptStage(PipelineStage):
    """階段 4：生成 user prompt 變異。"""

    name = "prompts（階段 4：生成 prompt）"

    def __init__(self) -> None:
        """建立 prompt 生成器（預設 template 策略）。"""
        self._generator = PromptGeneratorFactory.create()

    def run(self, context: BuildContext) -> None:
        """對每組生成單一 canonical prompt 並寫檔。"""
        for group in context.spec.groups:
            variants = self._generator.generate(group)
            write_models(context.prompts_json(group), variants)
            prompt = variants[0]  # 每組固定一個 canonical prompt
            logger.info(
                "組 %s：產生 %d 個 canonical prompt（目標 %d 秒、字幕=%s、scope=%s）",
                group.group_id, len(variants), prompt.target_duration_sec,
                prompt.caption_requirement, group.scope or "未分類",
            )
