"""
media_processor.pipeline.stages.legacy 套件:legacy fallback 包裝 Stage。

這些不是細粒度 Stage,而是把整段舊版 ``processor.process()`` 包成單一 Stage 的 fallback
(由 config flag 切換),與 23 個真正的細粒度 Stage 區隔,避免混在同一層難以辨識。
"""
from media_processor.pipeline.stages.legacy.legacy_base import LegacyProcessStage
from media_processor.pipeline.stages.legacy.legacy_image_stage import LegacyImagePipelineStage
from media_processor.pipeline.stages.legacy.legacy_video_stage import LegacyVideoPipelineStage

__all__ = [
    "LegacyProcessStage",
    "LegacyImagePipelineStage",
    "LegacyVideoPipelineStage",
]
