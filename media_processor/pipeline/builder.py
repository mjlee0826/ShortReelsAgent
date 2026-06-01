"""
PipelineBuilder:依 asset 類型組裝 Pipeline (Builder Pattern)。

把「Pipeline 由哪些 StageGroup 組成」這個編排知識集中在這裡,呼叫端(Runner / Scheduler)
只拿成品 Pipeline,不需知道 Stage 細節。Week 2b/2c 會在 ``_build_image_pipeline`` /
``_build_video_pipeline`` 內把單一 LegacyStage 展開成多個 StageGroup,**呼叫端零改動**。
"""
from __future__ import annotations

from config.pipeline_config import USE_LEGACY_IMAGE_PIPELINE
from media_processor.pipeline.context import AssetContext, MediaKind
from media_processor.pipeline.pipeline import Pipeline
from media_processor.pipeline.stage_group import StageGroup
from media_processor.pipeline.stages.aes_score_stage import AesScoreStage
from media_processor.pipeline.stages.assembly_image_stage import AssemblyImageStage
from media_processor.pipeline.stages.cv_features_stage import CVFeaturesStage
from media_processor.pipeline.stages.decode_image_stage import DecodeImageStage
from media_processor.pipeline.stages.exif_stage import ExifStage
from media_processor.pipeline.stages.face_detect_stage import FaceDetectStage
from media_processor.pipeline.stages.legacy_image_stage import LegacyImagePipelineStage
from media_processor.pipeline.stages.legacy_video_stage import LegacyVideoPipelineStage
from media_processor.pipeline.stages.reject_filter_stage import RejectFilterStage
from media_processor.pipeline.stages.saliency_stage import SaliencyStage
from media_processor.pipeline.stages.semantic_image_stage import SemanticImageStage
from media_processor.pipeline.stages.tech_score_stage import TechScoreStage

# Week 2a Legacy 單一群組名稱;Week 2b 圖片改用下方多群組編排
_LEGACY_GROUP_NAME = "legacy"
# 圖片 Pipeline 名稱(legacy 與細粒度兩種編排共用同一識別,下游無感)
_IMAGE_PIPELINE_NAME = "image_pipeline"
# Week 2b 圖片各 StageGroup 名稱(供日誌 / ProgressTracker 觀察群組邊界)
_G0_DECODE = "g0_decode"
_G1_TECH_SCORE = "g1_tech_score"
_G2_REJECT_FILTER = "g2_reject_filter"
_G3_PARALLEL = "g3_parallel"
_G4_ASSEMBLY = "g4_assembly"


class PipelineBuilder:
    """依 ``AssetContext.media_kind`` 選擇並建構對應的 Pipeline。"""

    def build(self, context: AssetContext) -> Pipeline:
        """為單一 asset 建立 Pipeline(圖片或影片)。"""
        if context.media_kind == MediaKind.IMAGE:
            return self._build_image_pipeline(context)
        return self._build_video_pipeline(context)

    def _build_image_pipeline(self, context: AssetContext) -> Pipeline:
        """
        圖片 Pipeline(Week 2b 細粒度編排,可旗標回退 Legacy)。

        ``USE_LEGACY_IMAGE_PIPELINE=true``:回退 Week 2a 單一 ``[LegacyImagePipelineStage]``,
        供 A/B 逐欄一致回歸與緊急 rollback。

        預設(false):五群編排 ──
          - G0 ``[DecodeImage]``           開圖、建 ImageWork
          - G1 ``[TechScore]``             MUSIQ 技術分(供儘早 reject)
          - G2 ``[RejectFilter]``          畫質不足即短路,後續群組自動跳過(Early Rejection)
          - G3 ``[Semantic, Saliency, Aes, CVFeatures, FaceDetect, Exif]`` 大平行群
          - G4 ``[AssemblyImage]``         唯一 join,組裝 metadata

        **semantic 併入 G3 並放 list 第一個提交**:圖片語意只依賴解碼後的圖,與其他 G3 stage 無依賴,
        故不必排在它們之後(避免 qwen 空等 CPU stage);放第一個提交可最早搶到 GpuGate,做到軟性 qwen 優先。
        詳見 plan 設計決策 8/9。
        """
        if USE_LEGACY_IMAGE_PIPELINE:
            group = StageGroup(name=_LEGACY_GROUP_NAME, stages=[LegacyImagePipelineStage()])
            return Pipeline(groups=[group], name=_IMAGE_PIPELINE_NAME)

        groups = [
            StageGroup(name=_G0_DECODE, stages=[DecodeImageStage()]),
            StageGroup(name=_G1_TECH_SCORE, stages=[TechScoreStage()]),
            StageGroup(name=_G2_REJECT_FILTER, stages=[RejectFilterStage()]),
            StageGroup(
                name=_G3_PARALLEL,
                stages=[
                    # semantic 放第一個提交 → 最早搶 GpuGate(軟性 qwen 優先);依 strategy 走 Qwen/Gemini
                    SemanticImageStage(context.image_strategy),
                    SaliencyStage(),
                    AesScoreStage(),
                    CVFeaturesStage(),
                    FaceDetectStage(),
                    ExifStage(),
                ],
            ),
            StageGroup(name=_G4_ASSEMBLY, stages=[AssemblyImageStage()]),
        ]
        return Pipeline(groups=groups, name=_IMAGE_PIPELINE_NAME)

    def _build_video_pipeline(self, context: AssetContext) -> Pipeline:
        """
        影片 Pipeline。

        Week 2a:單一群組 ``[LegacyVideoPipelineStage]``。
        Week 2c 展開為 G0 Decode → G1 大平行(音訊鏈 / 場景 / 動態)→ G2 ... → Semantic → Assembly。
        """
        group = StageGroup(name=_LEGACY_GROUP_NAME, stages=[LegacyVideoPipelineStage()])
        return Pipeline(groups=[group], name="video_pipeline")
