"""
PipelineBuilder:依 asset 類型組裝 Pipeline (Builder Pattern)。

把「Pipeline 由哪些 StageGroup 組成」這個編排知識集中在這裡,呼叫端(Runner / Scheduler)
只拿成品 Pipeline,不需知道 Stage 細節。Week 2b/2c 會在 ``_build_image_pipeline`` /
``_build_video_pipeline`` 內把單一 LegacyStage 展開成多個 StageGroup,**呼叫端零改動**。
"""
from __future__ import annotations

from media_processor.pipeline.context import AssetContext, MediaKind
from media_processor.pipeline.pipeline import Pipeline
from media_processor.pipeline.stage_group import StageGroup
from media_processor.pipeline.stages.legacy_image_stage import LegacyImagePipelineStage
from media_processor.pipeline.stages.legacy_video_stage import LegacyVideoPipelineStage

# Week 2a 唯一群組的名稱;Week 2b/2c 會換成 G0/G1/... 多群組編排
_LEGACY_GROUP_NAME = "legacy"


class PipelineBuilder:
    """依 ``AssetContext.media_kind`` 選擇並建構對應的 Pipeline。"""

    def build(self, context: AssetContext) -> Pipeline:
        """為單一 asset 建立 Pipeline(圖片或影片)。"""
        if context.media_kind == MediaKind.IMAGE:
            return self._build_image_pipeline(context)
        return self._build_video_pipeline(context)

    def _build_image_pipeline(self, context: AssetContext) -> Pipeline:
        """
        圖片 Pipeline。

        Week 2a:單一群組 ``[LegacyImagePipelineStage]``。
        Week 2b 展開為 G0 Decode → G1 TechScore → G2 RejectFilter → G3 大平行 → G4 Semantic → G5 Assembly。
        """
        group = StageGroup(name=_LEGACY_GROUP_NAME, stages=[LegacyImagePipelineStage()])
        return Pipeline(groups=[group], name="image_pipeline")

    def _build_video_pipeline(self, context: AssetContext) -> Pipeline:
        """
        影片 Pipeline。

        Week 2a:單一群組 ``[LegacyVideoPipelineStage]``。
        Week 2c 展開為 G0 Decode → G1 大平行(音訊鏈 / 場景 / 動態)→ G2 ... → Semantic → Assembly。
        """
        group = StageGroup(name=_LEGACY_GROUP_NAME, stages=[LegacyVideoPipelineStage()])
        return Pipeline(groups=[group], name="video_pipeline")
