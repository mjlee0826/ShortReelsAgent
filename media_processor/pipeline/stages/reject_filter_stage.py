"""RejectFilterStage:技術分過低即短路 reject(G2),省下後續昂貴 Stage。"""
from __future__ import annotations

from config.media_processor_config import TECHNICAL_SCORE_FILTER_THRESHOLD
from media_processor.models import ProcessorResult
from media_processor.pipeline.context import AssetContext, STATUS_REJECTED
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.image_work import get_image_work

_STAGE_NAME = "reject_filter"


class RejectFilterStage(Stage):
    """
    Early Rejection 短路點:``tech_score`` 低於門檻時把 asset 標記為 rejected。

    設定 ``context.status=REJECTED`` 後,Pipeline 會在本群組結束時自動 break,
    G3 平行群(含 Qwen)與 Assembly 全部跳過 —— 這就是 plan §4.4 要拿的「白送加速」。
    純比較邏輯,標記為 CPU 資源。
    """

    def __init__(self):
        """設定 Stage 靜態描述。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)

    def run(self, context: AssetContext) -> None:
        """技術分不足則寫入 rejected 結果並標記狀態(reason 逐字對齊原 process())。"""
        work = get_image_work(context)
        if work.tech_score < TECHNICAL_SCORE_FILTER_THRESHOLD:
            context.result = ProcessorResult(
                status=STATUS_REJECTED,
                file=context.file_path,
                reason=f"Technical Score too low (Blur/Noise): {work.tech_score:.1f}",
            ).to_dict()
            context.status = STATUS_REJECTED
