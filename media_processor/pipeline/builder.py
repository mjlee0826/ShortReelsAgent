"""
PipelineBuilder:依 asset 類型與策略組裝 Pipeline 依賴圖 (Builder Pattern)。

把「Pipeline 由哪些 Stage、彼此依賴關係如何」這個編排知識集中在這裡,呼叫端(Runner / Scheduler)
只拿成品 Pipeline,不需知道 Stage 細節。以 :class:`StageNode` 宣告**每個 Stage 的真依賴**,
由 Pipeline 以拓樸順序排程 —— 無依賴的 Stage 真正並行、不互相 block。

各 Pipeline 的依賴圖見對應的 build 方法;``USE_LEGACY_*_PIPELINE`` 旗標可回退單節點 Legacy 供 A/B 逐欄一致回歸。
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
from media_processor.pipeline.stages.tech_score_stage import TechScoreStage

# ── 圖片專屬 Stage ────────────────────────────────────────────────────────────
from media_processor.pipeline.stages.assembly_image_stage import AssemblyImageStage
from media_processor.pipeline.stages.decode_image_stage import DecodeImageStage
from media_processor.pipeline.stages.exif_stage import ExifStage
from media_processor.pipeline.stages.legacy.legacy_image_stage import LegacyImagePipelineStage
from media_processor.pipeline.stages.saliency_stage import SaliencyStage
from media_processor.pipeline.stages.semantic_image_stage import SemanticImageStage

# ── 影片專屬 Stage ────────────────────────────────────────────────────────────
from media_processor.pipeline.stages.assembly_video_stage import AssemblyVideoStage
from media_processor.pipeline.stages.audio_env_stage import AudioEnvStage
from media_processor.pipeline.stages.audio_extraction_stage import AudioExtractionStage
from media_processor.pipeline.stages.decode_video_stage import DecodeVideoStage
from media_processor.pipeline.stages.event_bbox_stage import EventBboxStage
from media_processor.pipeline.stages.legacy.legacy_video_stage import LegacyVideoPipelineStage
from media_processor.pipeline.stages.motion_intensity_stage import MotionIntensityStage
from media_processor.pipeline.stages.saliency_union_stage import SaliencyUnionStage
from media_processor.pipeline.stages.scene_cut_stage import SceneCutStage
from media_processor.pipeline.stages.semantic_video_stage import SemanticVideoStage
from media_processor.pipeline.stages.timecode_stage import TimecodeStage
from media_processor.pipeline.stages.vad_stage import VadStage
from media_processor.pipeline.stages.whisper_stage import WhisperStage

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
        圖片 Pipeline(DAG 表達,可旗標回退 Legacy)。

        依賴圖:``decode → {tech, semantic, saliency, aes, cv, face, exif} → assembly``。
        評分與過濾已解耦:不再有硬性 reject 短路(避免 MUSIQ 單訊號低估誤刪好素材),tech 退為
        decode 後的平行 Stage 之一,只負責算分寫入 metadata;畫質取捨改由 ContextCompressor 寬容把關。
        """
        if USE_LEGACY_IMAGE_PIPELINE:
            return Pipeline([StageNode(LegacyImagePipelineStage())], name=_IMAGE_PIPELINE_NAME)

        decode = DecodeImageStage()
        # decode 之後全部並行(各只依賴代表幀);semantic 依策略走 Qwen / Gemini
        parallel = [
            TechScoreStage(),
            SemanticImageStage(context.image_strategy),
            SaliencyStage(),
            AesScoreStage(),
            CVFeaturesStage(),
            FaceDetectStage(),
            ExifStage(),
        ]
        nodes = [
            StageNode(decode),
            *[StageNode(stage, (decode.meta.name,)) for stage in parallel],
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
        Simple 影片依賴圖(Qwen 全局分析;音訊鏈全拆;不再有 reject 短路)。

        ``decode → {tech, semantic(Qwen), scene, motion, saliency_union, aes, cv, face}``;
        音訊鏈:``audio_extract``(只依賴 decode、便宜 IO)→ ``vad`` → ``whisper``;``audio_env`` 另只
        依賴 audio_extract,與語音鏈並行(全拆紅利)。評分與過濾解耦後移除硬 reject(避免 MUSIQ 單訊號
        低估誤刪),tech 退為 decode 後的平行 Stage 之一;assembly 等齊視覺群 + whisper + audio_env。
        """
        decode = DecodeVideoStage()
        audio_extract = AudioExtractionStage()
        # decode 後才解除依賴的視覺 / 語意工作(tech 併入此平行群,只算分不再 gate 後續)
        visual = [
            TechScoreStage(),
            SemanticVideoStage(context.video_strategy),  # SIMPLE → Qwen(GPU)
            SceneCutStage(),
            MotionIntensityStage(),
            SaliencyUnionStage(),
            AesScoreStage(),
            CVFeaturesStage(),
            FaceDetectStage(),
        ]
        # 音訊鏈全拆:vad → whisper 為語音鏈;audio_env 獨立並行(皆只依賴 audio_extract)
        vad = VadStage()
        whisper = WhisperStage()
        audio_env = AudioEnvStage()
        nodes = [
            StageNode(decode),
            StageNode(audio_extract, (decode.meta.name,)),
            StageNode(vad, (audio_extract.meta.name,)),
            StageNode(whisper, (vad.meta.name,)),
            StageNode(audio_env, (audio_extract.meta.name,)),
            *[StageNode(stage, (decode.meta.name,)) for stage in visual],
            StageNode(
                AssemblyVideoStage(),
                # 視覺 / 語意群 + 音訊輸出(whisper / audio_env)湊齊所有 metadata 來源
                tuple(stage.meta.name for stage in visual) + (whisper.meta.name, audio_env.meta.name),
            ),
        ]
        return Pipeline(nodes, name=_VIDEO_PIPELINE_NAME)

    def _build_complex_video_pipeline(self, context: AssetContext) -> Pipeline:
        """
        Complex 影片依賴圖(Timecode 與所有非-Gemini 工作並行;Gemini 只等 Timecode)。

        ``decode → {tech, aes, audio_extract→audio_infer, timecode→semantic(Gemini)→event_bbox, scene, cv, face}
        → assembly``。tech / aes 對代表幀(中間幀)算畫質 / 美學分,與 Simple/Image 同一條 Stage(只算分、
        不 gate,故 Complex 無 reject 短路);timecode(最耗時的燒碼)只被 semantic 依賴,與音訊鏈 / 場景 /
        視覺特徵 / 評分自然重疊。
        """
        decode = DecodeVideoStage()
        audio_extract = AudioExtractionStage()
        # 音訊鏈全拆:vad → whisper 為語音鏈;audio_env 獨立並行(皆只依賴 audio_extract)
        vad = VadStage()
        whisper = WhisperStage()
        audio_env = AudioEnvStage()
        # 代表幀畫質 / 美學評分(與 Simple/Image 共用 Stage,只依賴代表幀)
        tech = TechScoreStage()
        aes = AesScoreStage()
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
            StageNode(vad, (audio_extract.meta.name,)),
            StageNode(whisper, (vad.meta.name,)),
            StageNode(audio_env, (audio_extract.meta.name,)),
            StageNode(tech, (decode_name,)),
            StageNode(aes, (decode_name,)),
            StageNode(timecode, (decode_name,)),
            StageNode(scene, (decode_name,)),
            StageNode(cv, (decode_name,)),
            StageNode(face, (decode_name,)),
            StageNode(semantic, (timecode.meta.name,)),       # Gemini 只等 timecode
            StageNode(event_bbox, (semantic.meta.name,)),     # 逐 event bbox 需 Gemini 事件清單
            StageNode(
                AssemblyVideoStage(),
                # event_bbox 已涵蓋 semantic(vlm_result);加 tech/aes/whisper/audio_env/scene/cv/face 湊齊所有 metadata 來源
                (
                    tech.meta.name,
                    aes.meta.name,
                    whisper.meta.name,
                    audio_env.meta.name,
                    scene.meta.name,
                    cv.meta.name,
                    face.meta.name,
                    event_bbox.meta.name,
                ),
            ),
        ]
        return Pipeline(nodes, name=_VIDEO_PIPELINE_NAME)
