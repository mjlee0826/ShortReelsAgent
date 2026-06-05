"""
media_processor.pipeline.stages 套件:具體 Stage 實作。

- Legacy 包裝 Stage(整段 process() 包成單一 Stage)。
- 圖片細粒度 Stage(Decode / TechScore / Reject / 平行群 / Semantic / Assembly)
  + ``ImageWork`` 中間狀態容器。
"""
from media_processor.pipeline.stages.aes_score_stage import AesScoreStage
from media_processor.pipeline.stages.assembly_image_stage import AssemblyImageStage
from media_processor.pipeline.stages.cv_features_stage import CVFeaturesStage
from media_processor.pipeline.stages.decode_image_stage import DecodeImageStage
from media_processor.pipeline.stages.exif_stage import ExifStage
from media_processor.pipeline.stages.face_detect_stage import FaceDetectStage
from media_processor.pipeline.stages.image_work import IMAGE_WORK_KEY, ImageWork
from media_processor.pipeline.stages.legacy_base import LegacyProcessStage
from media_processor.pipeline.stages.legacy_image_stage import LegacyImagePipelineStage
from media_processor.pipeline.stages.legacy_video_stage import LegacyVideoPipelineStage
from media_processor.pipeline.stages.reject_filter_stage import RejectFilterStage
from media_processor.pipeline.stages.saliency_stage import SaliencyStage
from media_processor.pipeline.stages.semantic_image_stage import SemanticImageStage
from media_processor.pipeline.stages.tech_score_stage import TechScoreStage

__all__ = [
    # Legacy 包裝
    "LegacyProcessStage",
    "LegacyImagePipelineStage",
    "LegacyVideoPipelineStage",
    # 中間狀態容器
    "ImageWork",
    "IMAGE_WORK_KEY",
    # 圖片細粒度 Stage
    "DecodeImageStage",
    "TechScoreStage",
    "RejectFilterStage",
    "SaliencyStage",
    "AesScoreStage",
    "CVFeaturesStage",
    "FaceDetectStage",
    "ExifStage",
    "SemanticImageStage",
    "AssemblyImageStage",
]
