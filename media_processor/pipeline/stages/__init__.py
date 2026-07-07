"""
media_processor.pipeline.stages 套件:具體 Stage 實作。

圖片細粒度 Stage(Decode / TechScore / 平行群 / Semantic / Assembly)
+ ``ImageWork`` 中間狀態容器。（Legacy 單節點包裝已於逐欄一致 A/B 驗收後移除。）
"""
from media_processor.pipeline.stages.aes_score_stage import AesScoreStage
from media_processor.pipeline.stages.assembly_image_stage import AssemblyImageStage
from media_processor.pipeline.stages.cv_features_stage import CVFeaturesStage
from media_processor.pipeline.stages.decode_image_stage import DecodeImageStage
from media_processor.pipeline.stages.exif_stage import ExifStage
from media_processor.pipeline.stages.face_detect_stage import FaceDetectStage
from media_processor.pipeline.work.image_work import IMAGE_WORK_KEY, ImageWork
from media_processor.pipeline.stages.semantic_image_stage import SemanticImageStage
from media_processor.pipeline.stages.tech_score_stage import TechScoreStage

__all__ = [
    # 中間狀態容器
    "ImageWork",
    "IMAGE_WORK_KEY",
    # 圖片細粒度 Stage
    "DecodeImageStage",
    "TechScoreStage",
    "AesScoreStage",
    "CVFeaturesStage",
    "FaceDetectStage",
    "ExifStage",
    "SemanticImageStage",
    "AssemblyImageStage",
]
