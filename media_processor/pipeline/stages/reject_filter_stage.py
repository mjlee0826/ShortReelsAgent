"""RejectFilterStage:技術分過低即短路 reject(image / video Simple 共用),省下後續昂貴 Stage。"""
from __future__ import annotations

from config.media_processor_config import TECHNICAL_SCORE_FILTER_THRESHOLD
from media_processor.models import ProcessorResult
from media_processor.pipeline.context import AssetContext, STATUS_REJECTED
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.frame_analysis import get_frame_analysis

_STAGE_NAME = "reject_filter"


class RejectFilterStage(Stage):
    """
    Early Rejection 短路點:當前幀 ``tech_score`` 低於門檻時把 asset 標記為 rejected。

    **image / video(Simple)共用**。設定 ``context.status=REJECTED`` 後,Pipeline 會讓後續才解除依賴的
    Stage(Qwen / saliency / aes / 音訊推論等)全部跳過 —— 這就是 plan §4.4 的「白送加速」。
    純比較邏輯,標記為 CPU 資源。reason 字串與原 processor 逐字對齊。
    """

    def __init__(self):
        """設定 Stage 靜態描述。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)

    def run(self, context: AssetContext) -> None:
        """技術分不足則寫入 rejected 結果並標記狀態(reason 逐字對齊原 process())。"""
        frame = get_frame_analysis(context)
        if frame.tech_score < TECHNICAL_SCORE_FILTER_THRESHOLD:
            context.result = ProcessorResult(
                status=STATUS_REJECTED,
                file=context.file_path,
                reason=f"Technical Score too low (Blur/Noise): {frame.tech_score:.1f}",
            ).to_dict()
            context.status = STATUS_REJECTED
