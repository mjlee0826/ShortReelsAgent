"""TechScoreStage:MUSIQ 技術畫質評分(image / video 共用),供 RejectFilter 短路。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.frame_analysis import get_frame_analysis

if TYPE_CHECKING:
    # 僅型別提示用;執行期改在 _engine() 內 lazy import,維持 EAGER_MODELS=false 語意
    from model.musiq_model_manager import MusiqModelManager

_STAGE_NAME = "tech_score"


class TechScoreStage(Stage):
    """
    以 MUSIQ 計算當前幀的技術畫質分數,寫入 ``FrameAnalysis.tech_score``(保留原始值供 reject 比較)。

    **image / video 共用**(media-agnostic,透過 ``get_frame_analysis`` 取幀):image 對整張圖、
    video 對中間代表幀。儘早執行讓 RejectFilter 能在跑昂貴的 saliency / aes / qwen 前就短路掉廢片。
    GPU 資源;singleton manager 延遲載入。代表幀缺失(video 抽幀失敗)時跳過、留預設 0.0。
    """

    def __init__(self):
        """設定 Stage 描述並預備 lazy manager 欄位。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.GPU)
        self._musiq: Optional["MusiqModelManager"] = None

    def _engine(self) -> "MusiqModelManager":
        """延遲取得 MUSIQ singleton(首次使用才載入權重)。"""
        if self._musiq is None:
            from model.musiq_model_manager import MusiqModelManager
            self._musiq = MusiqModelManager()
        return self._musiq

    def run(self, context: AssetContext) -> None:
        """計算技術分並寫入當前幀的 tech_score;代表幀缺失時跳過。"""
        frame = get_frame_analysis(context)
        if frame.pil_image is not None:
            frame.tech_score = self._engine().get_technical_score(frame.pil_image)
