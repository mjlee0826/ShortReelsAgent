"""
LegacyProcessStage:把整個既有 ``processor.process()`` 包成單一 Stage (Adapter Pattern)。

Week 2a 的核心妥協 ── **框架就緒但先不拆 Stage**。本 Stage 直接委派給既有的
``MediaProcessorFactory`` + ``MediaStrategy.process()``,完全不改動 model 路徑,
因此輸出與 Week 1 序列版逐欄一致、風險最低。Week 2b/2c 才會把 process() 內部展開成
DecodeStage / TechScoreStage / SemanticStage 等細粒度 Stage,屆時本 Stage 退居 fallback 與 regression 比對。
"""
from __future__ import annotations

from media_processor.media_processor_factory import MediaProcessorFactory
from media_processor.pipeline.context import AssetContext, STATUS_ERROR
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta


class LegacyProcessStage(Stage):
    """
    共用基底:建立對應 processor 並執行整段 ``process()``,結果寫回 AssetContext。

    圖片 / 影片子類別只差 ``meta.name``,行為完全一致(由 factory 依副檔名與策略路由)。
    標記為 GPU 資源僅為語意說明 ── 單 Stage 群組由 Pipeline 直接 inline 執行,
    實際 GPU 安全由各 model manager 的 ``@synchronized_inference``(L2 GpuGate + L3 鎖)保證。
    """

    def __init__(self, name: str):
        """以指定 Stage 名稱建構;資源型別固定為 GPU(本地 Qwen 為主要成本)。"""
        self.meta = StageMeta(name=name, resource_type=ResourceType.GPU)

    def run(self, context: AssetContext) -> None:
        """
        委派既有 process() 流程,並把回傳 dict 的 status / metadata 攤平到 context。

        ``process()`` 內部已自行 try/except 並回傳帶 status 的 dict(success / rejected / error),
        故此處正常情況不會拋例外;真有意外例外時,由 Pipeline 的 ``_run_stage`` 統一隔離。
        """
        # 沿用既有工廠路由:圖片恆走 ImageStrategy 預設、影片套用 context.video_strategy
        processor = MediaProcessorFactory.create_processor(
            context.file_path, video_strategy=context.video_strategy
        )
        result = processor.process(context.file_path)

        context.result = result
        context.status = result.get("status", STATUS_ERROR)
        # error 狀態時保留訊息到 context.error,方便上層觀測
        if context.status == STATUS_ERROR:
            context.error = result.get("message")
