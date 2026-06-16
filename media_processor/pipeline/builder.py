"""
PipelineBuilder:依 asset 類型與策略組裝 Pipeline 依賴圖 (Builder Pattern)。

把「Pipeline 由哪些 Stage、彼此依賴關係如何」這個編排知識集中在這裡,呼叫端(Runner / Scheduler)
只拿成品 Pipeline,不需知道 Stage 細節。以 :class:`StageNode` 宣告**每個 Stage 的真依賴**,
由 Pipeline 以拓樸順序排程 —— 無依賴的 Stage 真正並行、不互相 block。

各 Pipeline 的依賴圖見對應的 build 方法;``USE_LEGACY_*_PIPELINE`` 旗標可回退單節點 Legacy 供 A/B 逐欄一致回歸。
"""
from __future__ import annotations

from config.pipeline_config import (
    COMPLEX_AUDIO_VIA_GEMINI,
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
from media_processor.pipeline.stages.semantic_image_stage import SemanticImageStage

# ── 影片專屬 Stage ────────────────────────────────────────────────────────────
from media_processor.pipeline.stages.assembly_video_stage import AssemblyVideoStage
from media_processor.pipeline.stages.audio_env_stage import AudioEnvStage
from media_processor.pipeline.stages.audio_extraction_stage import AudioExtractionStage
from media_processor.pipeline.stages.decode_video_stage import DecodeVideoStage
from media_processor.pipeline.stages.legacy.legacy_video_stage import LegacyVideoPipelineStage
from media_processor.pipeline.stages.motion_intensity_stage import MotionIntensityStage
from media_processor.pipeline.stages.scene_cut_stage import SceneCutStage
from media_processor.pipeline.stages.semantic_video_stage import SemanticVideoStage
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

        依賴圖:``decode → {tech, semantic, aes, cv, face, exif} → assembly``。主體框改由 semantic(Qwen)
        直接輸出,無效時退臉部 / 全畫面安全框,故已移除 U²-Net SaliencyStage。
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
        if context.video_strategy == VideoStrategy.TEMPLATE:
            return self._build_template_video_pipeline(context)
        return self._build_simple_video_pipeline(context)

    def _build_simple_video_pipeline(self, context: AssetContext) -> Pipeline:
        """
        Simple 影片依賴圖(Qwen 全局分析;音訊鏈全拆;不再有 reject 短路)。

        ``decode → {tech, semantic(Qwen), scene, motion, aes, cv, face}``;
        音訊鏈:``audio_extract``(只依賴 decode、便宜 IO)→ ``vad`` → ``whisper``;``audio_env`` 另只
        依賴 audio_extract,與語音鏈並行(全拆紅利)。主體框改由 semantic(Qwen)直接輸出、無效退全畫面安全框,
        故已移除 U²-Net SaliencyUnionStage。評分與過濾解耦後移除硬 reject(避免 MUSIQ 單訊號
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
        Complex 影片依賴圖(所有工作 decode 後全並行;Gemini 直接讀原始影片)。

        ``decode → {tech, aes, semantic(Gemini), scene, cv, face} → assembly``;音訊來源由
        ``COMPLEX_AUDIO_VIA_GEMINI`` 旗標決定:
          - 開啟(預設):**不建** audio_extract/vad/whisper/audio_env,音訊欄位改由 semantic(Gemini)
            一併輸出並寫回 VideoWork(省 GPU、消除與 Gemini「聆聽」的重複勞動)。
          - 關閉(回退):重建 ``audio_extract→vad→whisper`` + ``audio_env``,音訊由 Whisper/AudioEnv 產出。
        tech / aes 對代表幀算畫質 / 美學分(與 Simple/Image 同一條 Stage,只算分、不 gate)。逐 event
        主體框的正規化已併入 AssemblyVideoStage。
        """
        decode = DecodeVideoStage()
        # 代表幀畫質 / 美學評分 + 場景 / 視覺特徵 / 臉部(與音訊來源無關,恆建)
        tech = TechScoreStage()
        aes = AesScoreStage()
        scene = SceneCutStage()
        cv = CVFeaturesStage()
        face = FaceDetectStage()
        semantic = SemanticVideoStage(context.video_strategy)  # COMPLEX → Gemini(API)

        decode_name = decode.meta.name
        nodes = [
            StageNode(decode),
            StageNode(tech, (decode_name,)),
            StageNode(aes, (decode_name,)),
            StageNode(scene, (decode_name,)),
            StageNode(cv, (decode_name,)),
            StageNode(face, (decode_name,)),
            StageNode(semantic, (decode_name,)),              # Gemini 直接讀原始影片,decode 後即可上傳
        ]
        # Assembly 依賴:視覺 / 語意群恆含;音訊鏈(whisper/audio_env)只在旗標關閉時納入
        assembly_deps = [
            tech.meta.name, aes.meta.name, scene.meta.name,
            cv.meta.name, face.meta.name, semantic.meta.name,
        ]
        if not COMPLEX_AUDIO_VIA_GEMINI:
            # 回退路徑:重建原 Whisper 音訊鏈(全拆:vad→whisper 語音鏈;audio_env 獨立並行)
            audio_extract = AudioExtractionStage()
            vad = VadStage()
            whisper = WhisperStage()
            audio_env = AudioEnvStage()
            nodes += [
                StageNode(audio_extract, (decode_name,)),
                StageNode(vad, (audio_extract.meta.name,)),
                StageNode(whisper, (vad.meta.name,)),
                StageNode(audio_env, (audio_extract.meta.name,)),
            ]
            assembly_deps += [whisper.meta.name, audio_env.meta.name]

        nodes.append(StageNode(AssemblyVideoStage(), tuple(assembly_deps)))
        return Pipeline(nodes, name=_VIDEO_PIPELINE_NAME)

    def _build_template_video_pipeline(self, context: AssetContext) -> Pipeline:
        """
        Template 專屬精簡依賴圖:``decode → scene → assembly``(純訊號層,無 LLM)。

        範本的視覺理解改由導演 agentic loop 自己 ``view_template`` 親眼看原始幀(與看使用者素材的
        ``view_raw`` 同一機制),故這裡不再跑 Gemini ``TEMPLATE_ANALYSIS``——那層只是把畫面翻成文字
        再餵給同為多模態的導演,屬冗餘。只保留導演視覺還原不了的便宜訊號:decode(時長 / fps / 解析度 /
        代表幀)與 scene(PySceneDetect 物理切點=範本剪輯節奏)。節拍(librosa bpm)由 ``TemplateDnaProducer``
        於本 DAG 外補。assembly 以 ``_build_template`` 組精簡 ``TemplateVideoMetadata``。
        """
        decode = DecodeVideoStage()
        scene = SceneCutStage()

        decode_name = decode.meta.name
        nodes = [
            StageNode(decode),
            StageNode(scene, (decode_name,)),
            StageNode(AssemblyVideoStage(), (scene.meta.name,)),
        ]
        return Pipeline(nodes, name=_VIDEO_PIPELINE_NAME)
