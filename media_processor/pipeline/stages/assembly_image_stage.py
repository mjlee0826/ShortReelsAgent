"""AssemblyImageStage:彙整所有中間結果組成 ImageMetadata 與最終 result(G4,唯一 join)。"""
from __future__ import annotations

from media_processor.media_strategy import MediaStrategy
from media_processor.models import ImageMetadata, ProcessorResult
from media_processor.pipeline.context import AssetContext, STATUS_SUCCESS
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.image_work import get_image_work

_STAGE_NAME = "assembly_image"
# 品質分數輸出位數(逐字對齊原 process() 的 round(score, 2))
_SCORE_NDIGITS = 2
# 媒體類型標籤(對齊原 ProcessorResult(type="image"))
_RESULT_TYPE_IMAGE = "image"


class AssemblyImageStage(Stage):
    """
    平行群之後的唯一 join 點:讀齊 ImageWork 全部欄位,組裝成 ImageMetadata 與成功 result。

    在此完成兩件原本散在 process() 尾段、且依賴「saliency + face 兩個並行結果」的事:
    1. **主體 bbox 解析**:有臉時用 face_bbox 覆蓋 saliency_bbox(對齊原版覆蓋邏輯)。
    2. **crop_feasibility**:依解析後的 subject_bbox 與 aspect_ratio 計算。
    純組裝邏輯(CPU 資源);成功時設 ``context.status=SUCCESS`` 供 Runner 收集。
    本 Stage 只在前面群組皆未 reject / error 時才會執行(Pipeline 已自動短路)。
    """

    def __init__(self):
        """設定 Stage 靜態描述。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)

    def run(self, context: AssetContext) -> None:
        """解析 bbox → 算 crop → 組 ImageMetadata → 寫入成功 result 並標記狀態。"""
        work = get_image_work(context)
        frame = work.frame

        # 主體定位:有臉以臉部 bbox 覆蓋 saliency(與原 process() 一致)
        subject_bbox = frame.face_bbox if frame.face_bbox is not None else work.saliency_bbox
        crop_feasibility = MediaStrategy._compute_crop_feasibility(subject_bbox, work.aspect_ratio)

        # 語意欄位以 .get 取值並沿用原版預設,確保缺欄位時行為一致
        vlm = work.vlm_result
        metadata = ImageMetadata(
            width=work.width,
            height=work.height,
            aspect_ratio=work.aspect_ratio,
            creation_time=work.exif.get("datetime", ""),
            location_gps=work.exif.get("gps_info", ""),
            caption=vlm.get("caption"),
            cinematic_critique=vlm.get("cinematic_critique"),
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
            subject_bbox=subject_bbox,
            crop_feasibility=crop_feasibility,
            faces=frame.face_info,
        )

        # file 存素材身分(relpath),非絕對路徑:落地的 metadata 才能跨機器移植,且下游 clip_id 直接可用
        context.result = ProcessorResult(
            status=STATUS_SUCCESS,
            type=_RESULT_TYPE_IMAGE,
            file=context.asset_id,
            metadata=metadata,
        ).to_dict()
        context.status = STATUS_SUCCESS
