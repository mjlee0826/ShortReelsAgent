"""圖片素材處理器，使用本地 Qwen 進行全局語意分析（免費方案）。"""

import pillow_heif
from PIL import Image

from media_processor.processors.abstract_image_processor import AbstractImageProcessor
from model.qwen_model_manager import QwenModelManager
from prompt_manager.task_mode import TaskMode

pillow_heif.register_heif_opener()


class ImageProcessor(AbstractImageProcessor):
    """
    具體策略 (Concrete Strategy)：靜態圖片的標準感知處理器（免費方案）。
    以本地端 Qwen3-VL 進行全局語意描述（GLOBAL_ANALYSIS），
    適用於不需要付費 API 的一般圖片素材。
    流水線繼承自 AbstractImageProcessor，此類只注入差異化的視覺語意引擎。
    """

    def __init__(self):
        super().__init__()
        # 主視覺語意引擎（非延遲：為此類的核心差異點）
        self.vision_engine = QwenModelManager()

    def analyze_visual_semantics(
        self, pil_image: Image.Image, exif_data: dict
    ) -> dict:
        """以 Qwen3-VL 執行圖片全局語意分析，回傳含 caption / mood 等欄位的 dict。"""
        return self.vision_engine.analyze_media(
            pil_image, media_type="image", mode=TaskMode.GLOBAL_ANALYSIS
        )
