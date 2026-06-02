"""ExifStage:解析 EXIF 拍攝時間與 GPS(G3 平行群)。"""
from __future__ import annotations

from media_processor.media_strategy import MediaStrategy
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.image_work import get_image_work

_STAGE_NAME = "exif"


class ExifStage(Stage):
    """
    從 PIL 圖片解析 EXIF,取出 datetime 與 gps_info,寫入 ``ImageWork.exif``。

    純記憶體解析、不依賴模型(CPU 資源),解析失敗時原 staticmethod 已靜默回空字串。
    Assembly 再從 exif dict 取 creation_time / location_gps。
    """

    def __init__(self):
        """設定 Stage 靜態描述。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)

    def run(self, context: AssetContext) -> None:
        """解析 EXIF 並寫入 ImageWork.exif(共用既有 staticmethod)。"""
        work = get_image_work(context)
        work.exif = MediaStrategy._extract_exif_metadata(work.frame.pil_image)
