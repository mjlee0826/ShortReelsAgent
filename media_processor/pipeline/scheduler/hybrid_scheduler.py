"""
HybridScheduler:asset 間粗粒度並行的主力排程器 (plan §6.2)。

核心機制
--------
N 個 asset driver thread 同時推進(預設 ``MAX_ASSETS_PARALLEL``),每個 driver 在自己的 asset 上
跑一條 Pipeline。所有 driver 共享同一組 ``ExecutorRegistry``,於是:
``asset A 在跑 GPU forward、asset B 在抽音訊(IO)、asset C 在跑場景偵測(CPU)`` ── 不同資源永遠有事做。

Week 2a 的 Pipeline 是單一 LegacyStage(inline 執行),故並行紅利來自「driver 並行 + L2 GpuGate
只序列化 GPU forward,IO/CPU 自然重疊」。Week 2b/2c 拆 Stage 後再疊加「群組內並行」。
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from config.pipeline_config import MAX_ASSETS_PARALLEL
from media_processor.pipeline.builder import PipelineBuilder
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.executor.executor_registry import ExecutorRegistry
from media_processor.pipeline.progress import ProgressTracker

# asset driver 執行緒命名前綴,方便除錯時辨識
_DRIVER_THREAD_PREFIX = "pipe-driver"


class HybridScheduler:
    """
    以固定大小的 asset-driver 執行緒池並行推進多個 asset 的 Pipeline。
    """

    def __init__(
        self,
        registry: ExecutorRegistry,
        builder: PipelineBuilder,
        max_assets_parallel: int = MAX_ASSETS_PARALLEL,
    ):
        """注入共享的 ExecutorRegistry 與 PipelineBuilder,並設定 asset 並行度。"""
        self._registry = registry
        self._builder = builder
        # 至少 1,避免 env 設成 0 / 負數導致 ThreadPoolExecutor 報錯
        self._max_assets_parallel = max(1, max_assets_parallel)

    def run(
        self,
        contexts: list[AssetContext],
        tracker: ProgressTracker | None = None,
    ) -> list[AssetContext]:
        """
        平行跑完所有 asset 的 Pipeline,回傳**依輸入順序排序**的 context 列表。

        每個 asset 一個 driver task;driver 池大小即 asset 並行度。排序保證最終
        ``phase1_assets_metadata.json`` 與舊版序列輸出順序一致(輸出穩定性)。
        """
        if not contexts:
            return []

        # 實際並行度取「上限」與 asset 數的較小值:小批不浪費 thread、也讓 Dynamic Batching 的
        # inline stage(圖片 tech)有效合批量貼齊實際 asset 數;大批則受上限保護 RAM。
        effective_parallel = min(len(contexts), self._max_assets_parallel)
        # driver 池與單次 run 綁定,結束即回收;ResourceRegistry 則跨 run 長存
        with ThreadPoolExecutor(
            max_workers=effective_parallel,
            thread_name_prefix=_DRIVER_THREAD_PREFIX,
        ) as driver_pool:
            futures = [driver_pool.submit(self._drive_one, ctx, tracker) for ctx in contexts]
            # _drive_one 內部已隔離例外,future.result() 取回就地更新後的 context
            results = [future.result() for future in futures]

        # 平行完成順序不定 → 依輸入索引排序還原穩定順序
        results.sort(key=lambda ctx: ctx.index)
        return results

    def _drive_one(
        self,
        context: AssetContext,
        tracker: ProgressTracker | None,
    ) -> AssetContext:
        """單一 asset 的 driver:建 Pipeline → 執行 → 發 pipeline 起訖事件。"""
        # Week 3b:把本次 run 的 tracker 掛到 context,讓 GPU stage 的 borrow VRAM 等待能發帶 asset_id 的事件
        context.tracker = tracker
        if tracker is not None:
            tracker.emit_pipeline_start(asset_id=context.asset_id)

        start = time.perf_counter()
        pipeline = self._builder.build(context)
        # Pipeline.execute 永不拋例外(錯誤寫進 context),故此處無需 try/except
        pipeline.execute(context, self._registry, tracker)
        duration_ms = (time.perf_counter() - start) * 1000.0

        if tracker is not None:
            tracker.emit_pipeline_finish(
                asset_id=context.asset_id,
                duration_ms=duration_ms,
                payload={"status": context.status},
            )
        return context
