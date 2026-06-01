"""
Pipeline:一條 asset 處理流水線 (Template Method Pattern)。

由多個 :class:`StageGroup` 組成,執行語意:
- **群組之間序列**:前一群組全部完成才進入下一群組。
- **群組之內並行**:多 Stage 群組把各 Stage 分派到 ExecutorRegistry 對應的 Worker Pool 並行執行;
  **單 Stage 群組直接在 driver thread inline 執行**(避免單一 Stage 還多一次 thread 跳轉,
  也讓 Week 2a 的 N 個 asset driver 拿到滿並行,不被小 GPU pool 限流)。

橫切關注點(進度事件、錯誤隔離)集中在本類別處理,Stage 子類別保持單純。
"""
from __future__ import annotations

import time
from concurrent.futures import Future
from typing import TYPE_CHECKING

from config.pipeline_config import STAGE_SUBMIT_TIMEOUT_SEC
from media_processor.pipeline.context import (
    AssetContext,
    STATUS_ERROR,
    STATUS_REJECTED,
)
from media_processor.pipeline.progress import ProgressTracker
from media_processor.pipeline.stage import Stage
from media_processor.pipeline.stage_group import StageGroup

if TYPE_CHECKING:
    # 僅型別檢查時 import,執行期不依賴,避免不必要的耦合與 import 順序問題
    from media_processor.pipeline.executor.executor_registry import ExecutorRegistry

# 終止狀態:asset 一旦進入這些狀態就不再往後續群組推進(短路)
_TERMINAL_STATUSES = frozenset({STATUS_ERROR, STATUS_REJECTED})


class Pipeline:
    """
    一條由 StageGroup 串成的 asset 處理流水線。

    本身不持有並行資源;``execute`` 時由呼叫端(HybridScheduler 的 driver)注入
    ``ExecutorRegistry`` 與 ``ProgressTracker``,使同一條 Pipeline 定義可被多個 driver 重複使用。
    """

    def __init__(self, groups: list[StageGroup], name: str = "pipeline"):
        """以一組有序的 StageGroup 建構 Pipeline。"""
        self._groups = groups
        self._name = name

    @property
    def groups(self) -> list[StageGroup]:
        """組成本 Pipeline 的有序群組清單(供測試 / 觀察)。"""
        return self._groups

    def execute(
        self,
        context: AssetContext,
        registry: "ExecutorRegistry",  # noqa: F821 - 避免循環 import,僅型別提示
        tracker: ProgressTracker | None = None,
    ) -> AssetContext:
        """
        依序執行所有群組,就地更新並回傳 ``context``。

        任一 Stage 失敗或 asset 進入終止狀態(error / rejected)即短路,不再推進後續群組,
        但**絕不拋出例外**——錯誤一律寫入 ``context``,確保單一 asset 失敗不影響其他 asset。
        """
        for group in self._groups:
            if group.is_single:
                # 單 Stage 群組:直接在當前 driver thread 執行,省去 executor 分派開銷
                self._run_stage(group.stages[0], context, tracker)
            else:
                # 多 Stage 群組:分派到各自 ResourceType 的 Worker Pool 並行,再 await 全部
                self._run_group_parallel(group, context, registry, tracker)

            # 短路:asset 已被 reject 或出錯,後續群組無意義
            if context.status in _TERMINAL_STATUSES:
                break

        return context

    def _run_group_parallel(
        self,
        group: StageGroup,
        context: AssetContext,
        registry: "ExecutorRegistry",  # noqa: F821
        tracker: ProgressTracker | None,
    ) -> None:
        """把群組內每個 Stage 提交到對應 Worker Pool,並等待全部完成。"""
        futures: list[Future] = [
            registry.submit(stage.meta.resource_type, self._run_stage, stage, context, tracker)
            for stage in group.stages
        ]
        # 逐一等待;_run_stage 內部已隔離例外,故 future 不會拋出,僅等待完成
        for future in futures:
            future.result(timeout=STAGE_SUBMIT_TIMEOUT_SEC)

    @staticmethod
    def _run_stage(
        stage: Stage,
        context: AssetContext,
        tracker: ProgressTracker | None,
    ) -> None:
        """
        執行單一 Stage 並包覆進度事件與錯誤隔離(Decorator 式橫切處理)。

        Stage 內拋出的任何例外都在此被捕捉、寫入 ``context.error`` 並標記為 error,
        再發 STAGE_ERROR 事件;**不向上拋出**,以免中斷同群組其他 Stage 或其他 asset。
        """
        stage_name = stage.meta.name
        if tracker is not None:
            tracker.emit_stage_start(asset_id=context.asset_id, stage_name=stage_name)

        start = time.perf_counter()
        try:
            stage.run(context)
            duration_ms = (time.perf_counter() - start) * 1000.0
            if tracker is not None:
                tracker.emit_stage_finish(
                    asset_id=context.asset_id,
                    stage_name=stage_name,
                    duration_ms=duration_ms,
                )
        except Exception as exc:  # noqa: BLE001 - 刻意攔截所有例外做隔離
            # 錯誤寫進 context,asset 標記 error,流水線其他部分照常運作
            context.status = STATUS_ERROR
            context.error = f"{exc.__class__.__name__}: {exc}"
            if tracker is not None:
                tracker.emit_stage_error(
                    asset_id=context.asset_id,
                    stage_name=stage_name,
                    error=context.error,
                )
