"""TechScoreStage:MUSIQ 技術畫質評分(G1),供緊接的 RejectFilter 短路。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.image_work import get_image_work

if TYPE_CHECKING:
    # 僅型別提示用;執行期改在 _engine() 內 lazy import,維持 EAGER_MODELS=false 語意
    from model.musiq_model_manager import MusiqModelManager

_STAGE_NAME = "tech_score"


class TechScoreStage(Stage):
    """
    以 MUSIQ 計算技術畫質分數,寫入 ``ImageWork.tech_score``(保留原始值供 reject 比較)。

    單獨成 G1 群並儘早執行,讓 RejectFilter 能在跑昂貴的 saliency/aes/qwen 前就短路掉廢片。
    GPU 資源;singleton manager 延遲載入,與 ``AbstractImageProcessor`` 的 lazy 引擎等價。
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
        """計算技術分並寫入 ImageWork.tech_score。"""
        work = get_image_work(context)
        work.tech_score = self._engine().get_technical_score(work.pil_image)
