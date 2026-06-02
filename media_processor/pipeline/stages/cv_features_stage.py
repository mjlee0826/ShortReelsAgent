"""CVFeaturesStage:亮度 / 色溫 / 主色調等純 cv2 視覺特徵(image / video 共用)。"""
from __future__ import annotations

from media_processor.media_strategy import MediaStrategy
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.frame_analysis import get_frame_analysis

_STAGE_NAME = "cv_features"


class CVFeaturesStage(Stage):
    """
    計算純 cv2/PIL/KMeans 視覺特徵:brightness、color_temperature、dominant_colors,寫入當前幀。

    **image / video 共用**(media-agnostic);不依賴任何模型(CPU 資源),與 GPU stage 同時推進即達成
    「GPU 與 CPU 重疊」紅利。三個欄位都寫進 FrameAnalysis,與其他平行 Stage 互斥。共用既有 staticmethod,
    邏輯與原版一致。代表幀缺失時跳過、留預設。
    """

    def __init__(self):
        """設定 Stage 靜態描述。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)

    def run(self, context: AssetContext) -> None:
        """依序算亮度 / 色溫 / 主色,寫入當前幀;代表幀缺失時跳過。"""
        frame = get_frame_analysis(context)
        pil_image = frame.pil_image
        if pil_image is None:
            return
        frame.brightness = MediaStrategy._compute_brightness(pil_image)
        frame.color_temperature = MediaStrategy._compute_color_temperature(pil_image)
        frame.dominant_colors = MediaStrategy._compute_dominant_colors(pil_image)
