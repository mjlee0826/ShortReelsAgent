"""MotionIntensityStage:取樣多幀 frame diff 計算動態強度(CPU,Simple)。"""
from __future__ import annotations

from media_processor.media_strategy import MediaStrategy
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.work.video_work import get_video_work

_STAGE_NAME = "motion_intensity"


class MotionIntensityStage(Stage):
    """
    取樣多幀計算相鄰幀差均值,分類為 static / moderate / dynamic,寫入 ``VideoWork.motion_intensity``。

    僅 Simple 影片需要(Complex 以事件索引為單位、無此欄位)。共用既有 staticmethod,邏輯與原版一致。
    純 cv2 運算,標記為 CPU 資源。
    """

    def __init__(self):
        """設定 Stage 靜態描述。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)

    def run(self, context: AssetContext) -> None:
        """計算動態強度並寫入 VideoWork。"""
        work = get_video_work(context)
        work.motion_intensity = MediaStrategy._compute_motion_intensity(context.file_path)
