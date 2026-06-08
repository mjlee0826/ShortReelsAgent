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
from media_processor.pipeline.utils.vlm_bbox_utils import (
    full_frame_bbox,
    parse_gemini_candidates,
    parse_qwen_candidates,
    select_best_candidate,
)
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

    - SIMPLE → ``VideoMetadata``(含畫質 / 美學 / 動態 / Qwen subject_bbox / crop_feasibility / faces)。
    - COMPLEX → ``ComplexVideoMetadata``(以 multimodal_event_index 為主;**逐 event 主體框於此就地正規化**
      ——原 EventBboxStage 簡化為純資料整形後併入本 join 點,不再獨立成 Stage;含代表幀畫質 / 美學分供導演
      選材;**無 faces 欄位** —— 與原版「dict 經 Pydantic coercion 丟棄多餘 faces 鍵」一致)。
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
        # 主體框優先序:Qwen top-N 候選中選最佳框 → 全畫面安全框(已移除 U²-Net 三幀聯集 fallback)
        # 相容舊鍵:新 prompt 輸出 subject_candidates,缺漏時退回舊單框 subject_bbox
        candidates = parse_qwen_candidates(vlm.get("subject_candidates", vlm.get("subject_bbox")))
        vlm_bbox = select_best_candidate(candidates, work.aspect_ratio)
        subject_bbox = vlm_bbox if vlm_bbox is not None else full_frame_bbox()
        crop_feasibility = MediaStrategy._compute_crop_feasibility(
            subject_bbox, work.aspect_ratio
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
            subject_bbox=subject_bbox,
            subject_candidates=candidates,
            crop_feasibility=crop_feasibility,
            faces=frame.face_info,
            scene_cuts=work.scene_cuts,
        )

    @staticmethod
    def _normalize_event_bboxes(events: list, aspect_ratio: float) -> list:
        """
        把 Gemini 逐 event 的 top-N 候選主體正規化、選最佳框(原 EventBboxStage 的工作)。

        逐事件解析 ``subject_candidates``(缺漏時退回舊單框 ``subject_bbox``),依「信心 + 9:16 可裁性」
        選最佳框寫回 ``subject_bbox``;同時就地寫回排序後的 ``subject_candidates``(dict 清單),供下游
        前端逐 event 動態框 / 導演按使用者意圖改選。缺失 / 格式不符 / 退化即退回全畫面安全框。
        """
        for event in events:
            candidates = parse_gemini_candidates(
                event.get("subject_candidates", event.get("subject_bbox"))
            )
            best = select_best_candidate(candidates, aspect_ratio) or full_frame_bbox()
            event["subject_bbox"] = best.model_dump()
            event["subject_candidates"] = [candidate.model_dump() for candidate in candidates]
        return events

    @staticmethod
    def _build_complex(work: VideoWork, vlm: dict) -> ComplexVideoMetadata:
        """組 Complex 影片 metadata(逐 event 主體框就地正規化;無 faces,但保留代表幀畫質/美學分)。"""
        frame = work.frame
        events = AssemblyVideoStage._normalize_event_bboxes(
            vlm.get(_EVENT_INDEX_KEY, []), work.aspect_ratio
        )
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
            # 代表幀(中間幀)畫質/美學分,與 Simple/Image 同一條 TechScore/AesScore Stage 產出
            technical_score=round(frame.tech_score, _SCORE_NDIGITS),
            aesthetic_score=round(frame.aes_score, _SCORE_NDIGITS),
            brightness=frame.brightness,
            color_temperature=frame.color_temperature,
            dominant_colors=frame.dominant_colors,
            is_dense_indexed=True,
            scene_cuts=work.scene_cuts,
            multimodal_event_index=events,
        )
