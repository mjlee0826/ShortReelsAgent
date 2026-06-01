"""LegacyImagePipelineStage:圖片的 process() 整段包裝 Stage(Week 2a)。"""
from __future__ import annotations

from media_processor.pipeline.stages.legacy_base import LegacyProcessStage

# Stage 名稱常數,供進度事件與日誌標示,避免散落 magic string
_STAGE_NAME = "legacy_image"


class LegacyImagePipelineStage(LegacyProcessStage):
    """
    具體 Stage:把 ImageProcessor / ComplexImageProcessor 的整段 ``process()`` 包成單一 Stage。

    Week 2b 會把它展開成 Decode / Saliency / TechScore / Semantic 等細粒度 Stage,本類別屆時保留作 fallback。
    """

    def __init__(self):
        """以圖片 Stage 名稱初始化共用基底。"""
        super().__init__(name=_STAGE_NAME)
