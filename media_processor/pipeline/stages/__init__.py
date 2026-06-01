"""
media_processor.pipeline.stages 套件:具體 Stage 實作。

Week 2a 只有 Legacy 包裝 Stage;Week 2b/2c 會在此新增細粒度 Stage(Decode / TechScore / Semantic ...)。
"""
from media_processor.pipeline.stages.legacy_base import LegacyProcessStage
from media_processor.pipeline.stages.legacy_image_stage import LegacyImagePipelineStage
from media_processor.pipeline.stages.legacy_video_stage import LegacyVideoPipelineStage

__all__ = [
    "LegacyProcessStage",
    "LegacyImagePipelineStage",
    "LegacyVideoPipelineStage",
]
