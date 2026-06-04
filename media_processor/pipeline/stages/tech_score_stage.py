"""TechScoreStage:MUSIQ 技術畫質評分(image / video 共用),供 RejectFilter 短路。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from config.media_processor_config import BATCH_COLLECT_TIMEOUT_MS, MUSIQ_BATCH_SIZE
from config.pipeline_config import MUSIQ_BATCH_ENABLED
from media_processor.pipeline.batch_collector import BatchCollectorRegistry, BatchSpec
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.frame_analysis import get_frame_analysis

if TYPE_CHECKING:
    # 僅型別提示用;執行期改在 _engine() / batch fn 內 lazy import,維持 EAGER_MODELS=false 語意
    from model.musiq_model_manager import MusiqModelManager

_STAGE_NAME = "tech_score"

# 跨 asset 共享的 MUSIQ 合批規格(key 唯一 → 同一個 collector 單例)
_MUSIQ_SPEC = BatchSpec(
    key="musiq",
    batch_size=MUSIQ_BATCH_SIZE,
    timeout_ms=BATCH_COLLECT_TIMEOUT_MS,
    enabled=MUSIQ_BATCH_ENABLED,
)


def _musiq_batch(images: list) -> list:
    """BatchCollector 合批函式:從多卡 pool 借出 MUSIQ(或 singleton)一次評分多張(順序一致)。"""
    from model.musiq_model_manager import MusiqModelManager
    from media_processor.pipeline.executor.model_pool_registry import borrow_for_batch
    return borrow_for_batch(MusiqModelManager, _STAGE_NAME, lambda m: m.score_batch(images))


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
        """計算技術分並寫入當前幀的 tech_score;代表幀缺失時跳過。啟用合批走 collector,否則單張。"""
        frame = get_frame_analysis(context)
        if frame.pil_image is None:
            return
        if MUSIQ_BATCH_ENABLED:
            collector = BatchCollectorRegistry.get(_MUSIQ_SPEC, _musiq_batch)
            # submit_and_wait 把跨 thread 的合批等待計入本 stage 的「等資源」(供 compute/wait 拆分)
            frame.tech_score = collector.submit_and_wait(frame.pil_image)
        else:
            frame.tech_score = self._engine().get_technical_score(frame.pil_image)
