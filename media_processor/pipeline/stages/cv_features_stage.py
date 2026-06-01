"""CVFeaturesStage:亮度 / 色溫 / 主色調等純 cv2 視覺特徵(G3 平行群)。"""
from __future__ import annotations

from media_processor.media_strategy import MediaStrategy
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.image_work import get_image_work

_STAGE_NAME = "cv_features"


class CVFeaturesStage(Stage):
    """
    計算純 cv2/PIL/KMeans 視覺特徵:brightness、color_temperature、dominant_colors。

    不依賴任何模型(CPU 資源),與 GPU stage 同群並行即達成「GPU 與 CPU 重疊」紅利。
    三個欄位都寫進 ImageWork,與其他平行 Stage 互斥。共用既有 staticmethod,邏輯與原版一致。
    """

    def __init__(self):
        """設定 Stage 靜態描述。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)

    def run(self, context: AssetContext) -> None:
        """依序算亮度 / 色溫 / 主色,寫入 ImageWork。"""
        work = get_image_work(context)
        pil_image = work.pil_image
        work.brightness = MediaStrategy._compute_brightness(pil_image)
        work.color_temperature = MediaStrategy._compute_color_temperature(pil_image)
        work.dominant_colors = MediaStrategy._compute_dominant_colors(pil_image)
