"""複雜圖片處理器，使用 Gemini API 進行深度語意分析（付費方案）。"""

import pillow_heif
from PIL import Image

from media_processor.abstract_image_processor import AbstractImageProcessor
from model.gemini_model_manager import GeminiModelManager
from prompt_manager.task_mode import TaskMode

pillow_heif.register_heif_opener()


class ComplexImageProcessor(AbstractImageProcessor):
    """
    具體策略 (Concrete Strategy)：靜態圖片的深度感知處理器（付費方案）。
    以 Gemini API 取代本地 Qwen，提供更豐富的語意標籤與更精準的情緒/場景判斷。
    流水線繼承自 AbstractImageProcessor，此類只注入差異化的視覺語意引擎。
    """

    def __init__(self):
        super().__init__()
        # 雲端語意分析引擎（付費）
        self.vision_engine = GeminiModelManager()

    def analyze_visual_semantics(
        self, pil_image: Image.Image, exif_data: dict
    ) -> dict:
        """以 Gemini API 執行圖片深度語意分析，回傳含 caption / mood 等欄位的 dict。"""
        return self.vision_engine.analyze_media(
            pil_image, media_type="image", mode=TaskMode.COMPLEX_IMAGE_ANALYSIS
        )
