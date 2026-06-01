"""DecodeImageStage:開圖、轉 RGB、算尺寸,建立 ImageWork(G0)。"""
from __future__ import annotations

import pillow_heif
from PIL import Image

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.image_work import IMAGE_WORK_KEY, ImageWork

# HEIC/HEIF 支援:與既有 processor 一致,在模組載入時註冊(idempotent)
pillow_heif.register_heif_opener()

_STAGE_NAME = "decode_image"
# aspect_ratio 四捨五入位數(逐字對齊原 AbstractImageProcessor,確保輸出一致)
_ASPECT_RATIO_NDIGITS = 4


class DecodeImageStage(Stage):
    """
    Pipeline 起點:讀檔解碼成 RGB PIL 圖,算出 width/height/aspect_ratio 並建立 ImageWork。

    標記為 IO 資源(以檔案讀取為主);單 Stage 群組由 Pipeline inline 執行。
    後續所有圖片 Stage 都讀取本 Stage 寫入的 ``ImageWork.pil_image``。
    """

    def __init__(self):
        """設定 Stage 靜態描述。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.IO)

    def run(self, context: AssetContext) -> None:
        """開圖 → 轉 RGB → 算尺寸 → 建立並存入 ImageWork。"""
        pil_image = Image.open(context.file_path).convert("RGB")
        width, height = pil_image.size
        # 與原版一致:height 為 0 時 aspect_ratio 退 0.0,避免除零
        aspect_ratio = round(width / height, _ASPECT_RATIO_NDIGITS) if height > 0 else 0.0

        context.scratch[IMAGE_WORK_KEY] = ImageWork(
            pil_image=pil_image,
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
        )
