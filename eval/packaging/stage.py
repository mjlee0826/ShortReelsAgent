"""階段 5 主流程：呼叫 DatasetPackager 打包並凍結。"""
from __future__ import annotations

from ..logging_setup import get_logger
from ..pipeline import BuildContext, PipelineStage
from .packager import DatasetPackager

logger = get_logger(__name__)


class PackageStage(PipelineStage):
    """階段 5：打包與凍結。"""

    name = "package（階段 5：打包凍結）"

    def __init__(self) -> None:
        """建立打包器。"""
        self._packager = DatasetPackager()

    def run(self, context: BuildContext) -> None:
        """執行打包。"""
        self._packager.package(context)
