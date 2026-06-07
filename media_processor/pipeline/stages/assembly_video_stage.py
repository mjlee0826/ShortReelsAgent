"""AssemblyVideoStage:彙整中間結果組成 VideoMetadata / ComplexVideoMetadata 與最終 result。"""
from __future__ import annotations

from media_processor.media_strategy import MediaStrategy
from media_processor.models import (
    ComplexVideoMetadata,
    ProcessorResult,
    VideoMetadata,
)
from media_processor.pipeline.context import AssetContext, STATUS_SUCCESS
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.work.video_work import VideoWork, get_video_work
from media_processor.video_strategy import VideoStrategy

_STAGE_NAME = "assembly_video"
# 品質分數輸出位數(逐字對齊原 round(score, 2))
_SCORE_NDIGITS = 2
# 媒體類型標籤(對齊原 ProcessorResult(type="video"))
_RESULT_TYPE_VIDEO = "video"
# Complex 多模態事件清單鍵
_EVENT_INDEX_KEY = "multimodal_event_index"


class AssemblyVideoStage(Stage):
    """
    依 strategy 把 VideoWork 組裝成最終 metadata 與成功 result(DAG 的唯一 join 點)。

    - SIMPLE → ``VideoMetadata``(含畫質 / 美學 / 動態 / 三幀聯集 subject_bbox / crop_feasibility / faces)。
    - COMPLEX → ``ComplexVideoMetadata``(以 multimodal_event_index 為主,不含整體畫質 / subject_bbox;
      **亦無 faces 欄位** —— 與原版「dict 經 Pydantic 模型 coercion 丟棄多餘 faces 鍵」逐欄一致)。
    純組裝(CPU 資源);只在前面 Stage 皆未 reject / error 時才執行(Pipeline 已自動短路)。
    """

    def __init__(self):
        """設定 Stage 靜態描述。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)

    def run(self, context: AssetContext) -> None:
        """依 strategy 組 metadata → 寫入成功 result 並標記狀態。"""
        work = get_video_work(context)
        vlm = work.vlm_result
        if context.video_strategy == VideoStrategy.COMPLEX:
            metadata = self._build_complex(work, vlm)
        else:
            metadata = self._build_simple(work, vlm)

        # file 存素材身分(relpath),非絕對路徑:落地的 metadata 才能跨機器移植,且下游 clip_id 直接可用
        context.result = ProcessorResult(
            status=STATUS_SUCCESS,
            type=_RESULT_TYPE_VIDEO,
            file=context.asset_id,
            metadata=metadata,
        ).to_dict()
        context.status = STATUS_SUCCESS

    @staticmethod
    def _build_simple(work: VideoWork, vlm: dict) -> VideoMetadata:
        """組 Simple 影片 metadata(逐欄對齊原 VideoProcessor.analyze_visual_semantics)。"""
        frame = work.frame
        crop_feasibility = MediaStrategy._compute_crop_feasibility(
            work.subject_bbox, work.aspect_ratio
        )
        return VideoMetadata(
            width=work.width,
            height=work.height,
            aspect_ratio=work.aspect_ratio,
            duration=work.duration,
            fps=work.fps,
            creation_time=work.creation_time,
            location_gps=work.location_gps,
            has_speech=work.has_speech,
            spoken_language=work.spoken_language,
            audio_transcript=work.audio_transcript,
            environmental_sounds=work.environmental_sounds,
            caption=vlm.get("caption"),
            cinematic_critique=vlm.get("cinematic_critique", ""),
            mood=vlm.get("mood", ""),
            scene_tags=vlm.get("scene_tags", []),
            camera_angle=vlm.get("camera_angle", ""),
            action_tags=vlm.get("action_tags", []),
            time_of_day=vlm.get("time_of_day", ""),
            technical_score=round(frame.tech_score, _SCORE_NDIGITS),
            aesthetic_score=round(frame.aes_score, _SCORE_NDIGITS),
            brightness=frame.brightness,
            color_temperature=frame.color_temperature,
            dominant_colors=frame.dominant_colors,
            motion_intensity=work.motion_intensity,
            subject_bbox=work.subject_bbox,
            crop_feasibility=crop_feasibility,
            faces=frame.face_info,
            scene_cuts=work.scene_cuts,
        )

    @staticmethod
    def _build_complex(work: VideoWork, vlm: dict) -> ComplexVideoMetadata:
        """組 Complex 影片 metadata(逐欄對齊原 ComplexVideoProcessor.analyze_visual_semantics;無 faces)。"""
        frame = work.frame
        return ComplexVideoMetadata(
            width=work.width,
            height=work.height,
            aspect_ratio=work.aspect_ratio,
            duration=work.duration,
            fps=work.fps,
            creation_time=work.creation_time,
            location_gps=work.location_gps,
            has_speech=work.has_speech,
            spoken_language=work.spoken_language,
            audio_transcript=work.audio_transcript,
            environmental_sounds=work.environmental_sounds,
            cinematic_critique=vlm.get("cinematic_critique", ""),
            mood=vlm.get("mood", ""),
            scene_tags=vlm.get("scene_tags", []),
            camera_angle=vlm.get("camera_angle", ""),
            action_tags=vlm.get("action_tags", []),
            time_of_day=vlm.get("time_of_day", ""),
            brightness=frame.brightness,
            color_temperature=frame.color_temperature,
            dominant_colors=frame.dominant_colors,
            is_dense_indexed=True,
            scene_cuts=work.scene_cuts,
            multimodal_event_index=vlm.get(_EVENT_INDEX_KEY, []),
        )
