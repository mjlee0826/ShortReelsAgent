"""
PipelineBuilder:依 asset 類型與策略組裝 Pipeline 依賴圖 (Builder Pattern)。

把「Pipeline 由哪些 Stage、彼此依賴關係如何」這個編排知識集中在這裡,呼叫端(Runner / Scheduler)
只拿成品 Pipeline,不需知道 Stage 細節。Week 2c 起改用 :class:`StageNode` 宣告**每個 Stage 的真依賴**
(取代 StageGroup barrier),由 Pipeline 以拓樸順序排程 —— 無依賴的 Stage 真正並行、不互相 block。

各依賴圖見 plan Week 2c D3;``USE_LEGACY_*_PIPELINE`` 旗標可回退單節點 Legacy 供 A/B 逐欄一致回歸。
"""
from __future__ import annotations

from config.pipeline_config import (
    USE_LEGACY_IMAGE_PIPELINE,
    USE_LEGACY_VIDEO_PIPELINE,
)
from media_processor.pipeline.context import AssetContext, MediaKind
from media_processor.pipeline.node import StageNode
from media_processor.pipeline.pipeline import Pipeline
from media_processor.video_strategy import VideoStrategy

# ── 共用 per-frame Stage(image / video 皆用)──────────────────────────────────
from media_processor.pipeline.stages.aes_score_stage import AesScoreStage
from media_processor.pipeline.stages.cv_features_stage import CVFeaturesStage
from media_processor.pipeline.stages.face_detect_stage import FaceDetectStage
from media_processor.pipeline.stages.reject_filter_stage import RejectFilterStage
from media_processor.pipeline.stages.tech_score_stage import TechScoreStage

# ── 圖片專屬 Stage ────────────────────────────────────────────────────────────
from media_processor.pipeline.stages.assembly_image_stage import AssemblyImageStage
from media_processor.pipeline.stages.decode_image_stage import DecodeImageStage
from media_processor.pipeline.stages.exif_stage import ExifStage
from media_processor.pipeline.stages.legacy_image_stage import LegacyImagePipelineStage
from media_processor.pipeline.stages.saliency_stage import SaliencyStage
from media_processor.pipeline.stages.semantic_image_stage import SemanticImageStage

# ── 影片專屬 Stage ────────────────────────────────────────────────────────────
from media_processor.pipeline.stages.assembly_video_stage import AssemblyVideoStage
from media_processor.pipeline.stages.audio_extraction_stage import AudioExtractionStage
from media_processor.pipeline.stages.audio_inference_stage import AudioInferenceStage
from media_processor.pipeline.stages.decode_video_stage import DecodeVideoStage
from media_processor.pipeline.stages.event_bbox_stage import EventBboxStage
from media_processor.pipeline.stages.legacy_video_stage import LegacyVideoPipelineStage
from media_processor.pipeline.stages.motion_intensity_stage import MotionIntensityStage
from media_processor.pipeline.stages.saliency_union_stage import SaliencyUnionStage
from media_processor.pipeline.stages.scene_cut_stage import SceneCutStage
from media_processor.pipeline.stages.semantic_video_stage import SemanticVideoStage
from media_processor.pipeline.stages.timecode_stage import TimecodeStage

# Pipeline 名稱(legacy 與細粒度兩種編排共用同一識別,下游無感)
_IMAGE_PIPELINE_NAME = "image_pipeline"
_VIDEO_PIPELINE_NAME = "video_pipeline"


class PipelineBuilder:
    """依 ``AssetContext.media_kind`` 與策略選擇並建構對應的 Pipeline 依賴圖。"""

    def build(self, context: AssetContext) -> Pipeline:
        """為單一 asset 建立 Pipeline(圖片或影片)。"""
        if context.media_kind == MediaKind.IMAGE:
            return self._build_image_pipeline(context)
        return self._build_video_pipeline(context)

    # ── 圖片 ─────────────────────────────────────────────────────────────────

    def _build_image_pipeline(self, context: AssetContext) -> Pipeline:
        """
        圖片 Pipeline(Week 2c DAG 表達,可旗標回退 Legacy)。

        依賴圖:``decode → tech → reject → {semantic, saliency, aes, cv, face, exif} → assembly``。
        reject 之後的六個 Stage 並行(各只依賴 reject);reject 觸發時它們與 assembly 全被短路跳過。
        輸出與 Week 2b 逐欄一致(只改排程,不改值)。
        """
        if USE_LEGACY_IMAGE_PIPELINE:
            return Pipeline([StageNode(LegacyImagePipelineStage())], name=_IMAGE_PIPELINE_NAME)

        decode = DecodeImageStage()
        tech = TechScoreStage()
        reject = RejectFilterStage()
        # reject 之後的平行群:semantic 依策略走 Qwen / Gemini
        parallel = [
            SemanticImageStage(context.image_strategy),
            SaliencyStage(),
            AesScoreStage(),
            CVFeaturesStage(),
            FaceDetectStage(),
            ExifStage(),
        ]
        nodes = [
            StageNode(decode),
            StageNode(tech, (decode.meta.name,)),
            StageNode(reject, (tech.meta.name,)),
            *[StageNode(stage, (reject.meta.name,)) for stage in parallel],
            StageNode(AssemblyImageStage(), tuple(stage.meta.name for stage in parallel)),
        ]
        return Pipeline(nodes, name=_IMAGE_PIPELINE_NAME)

    # ── 影片 ─────────────────────────────────────────────────────────────────

    def _build_video_pipeline(self, context: AssetContext) -> Pipeline:
        """影片 Pipeline:旗標回退 Legacy,否則依 strategy 建 Simple / Complex 依賴圖。"""
        if USE_LEGACY_VIDEO_PIPELINE:
            return Pipeline([StageNode(LegacyVideoPipelineStage())], name=_VIDEO_PIPELINE_NAME)
        if context.video_strategy == VideoStrategy.COMPLEX:
            return self._build_complex_video_pipeline(context)
        return self._build_simple_video_pipeline(context)

    def _build_simple_video_pipeline(self, context: AssetContext) -> Pipeline:
        """
        Simple 影片依賴圖(鏡像圖片的早 reject;Qwen 全局分析)。

        ``decode → tech → reject → {semantic(Qwen), audio_infer, scene, motion, saliency_union,
        aes, cv, face} → assembly``。audio_extract 只依賴 decode(與 tech 重疊、不被 reject gate;便宜 IO),
        audio_infer 另依賴 audio_extract;reject 之後的工作在 reject 觸發時全被短路(連 whisper / qwen 都省)。
        """
        decode = DecodeVideoStage()
        tech = TechScoreStage()
        audio_extract = AudioExtractionStage()
        reject = RejectFilterStage()
        # reject 之後才解除依賴的工作(reject 觸發時全部跳過)
        semantic = SemanticVideoStage(context.video_strategy)  # SIMPLE → Qwen(GPU)
        audio_infer = AudioInferenceStage()
        gated = [
            semantic,
            audio_infer,
            SceneCutStage(),
            MotionIntensityStage(),
            SaliencyUnionStage(),
            AesScoreStage(),
            CVFeaturesStage(),
            FaceDetectStage(),
        ]
        reject_name = reject.meta.name
        nodes = [
            StageNode(decode),
            StageNode(tech, (decode.meta.name,)),
            StageNode(audio_extract, (decode.meta.name,)),
            StageNode(reject, (tech.meta.name,)),
            # audio_infer 需「音訊已抽出」且「未被 reject」雙重前提
            StageNode(audio_infer, (audio_extract.meta.name, reject_name)),
            *[StageNode(stage, (reject_name,)) for stage in gated if stage is not audio_infer],
            StageNode(AssemblyVideoStage(), tuple(stage.meta.name for stage in gated)),
        ]
        return Pipeline(nodes, name=_VIDEO_PIPELINE_NAME)

    def _build_complex_video_pipeline(self, context: AssetContext) -> Pipeline:
        """
        Complex 影片依賴圖(Timecode 與所有非-Gemini 工作並行;Gemini 只等 Timecode)。

        ``decode → {audio_extract→audio_infer, timecode→semantic(Gemini)→event_bbox, scene, cv, face}
        → assembly``。timecode(最耗時的燒碼)只被 semantic 依賴,故與音訊鏈 / 場景 / 視覺特徵自然重疊;
        semantic 不再被同群的 audio/cv/face 卡住(修正 StageGroup 時代的過度約束)。
        """
        decode = DecodeVideoStage()
        audio_extract = AudioExtractionStage()
        audio_infer = AudioInferenceStage()
        timecode = TimecodeStage()
        scene = SceneCutStage()
        cv = CVFeaturesStage()
        face = FaceDetectStage()
        semantic = SemanticVideoStage(context.video_strategy)  # COMPLEX → Gemini(API)
        event_bbox = EventBboxStage()

        decode_name = decode.meta.name
        nodes = [
            StageNode(decode),
            StageNode(audio_extract, (decode_name,)),
            StageNode(audio_infer, (audio_extract.meta.name,)),
            StageNode(timecode, (decode_name,)),
            StageNode(scene, (decode_name,)),
            StageNode(cv, (decode_name,)),
            StageNode(face, (decode_name,)),
            StageNode(semantic, (timecode.meta.name,)),       # Gemini 只等 timecode
            StageNode(event_bbox, (semantic.meta.name,)),     # 逐 event bbox 需 Gemini 事件清單
            StageNode(
                AssemblyVideoStage(),
                # event_bbox 已涵蓋 semantic(vlm_result);加 audio/scene/cv/face 湊齊所有 metadata 來源
                (
                    audio_infer.meta.name,
                    scene.meta.name,
                    cv.meta.name,
                    face.meta.name,
                    event_bbox.meta.name,
                ),
            ),
        ]
        return Pipeline(nodes, name=_VIDEO_PIPELINE_NAME)
