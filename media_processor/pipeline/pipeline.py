"""
Pipeline:一條 asset 處理流水線,以依賴圖 (DAG) 排程 (Template Method + Dependency Graph)。

由多個 :class:`StageNode` 組成,執行語意:
- **每個 Stage 只等自己宣告的上游依賴**(``StageNode.deps``)全部完成,即可執行;
  彼此無依賴的 Stage 真正並行,不被「整個前群組」barrier 卡住。
- **依資源型別分派**:多個同時可執行的 Stage 各自送到 ExecutorRegistry 對應的 Worker Pool(IO/CPU/GPU/API);
  **單一可執行且無併發時直接在 driver thread inline 跑**(省一次 thread 跳轉,也讓單節點 / Legacy
  Pipeline 不被較小的 GPU pool 限流 —— N 個 asset driver 仍能滿並行)。
- **短路**:任一 Stage 把 ``context.status`` 設為 rejected / error 後,後續才解除依賴的 Stage 一律跳過。
- **暫存檔清理**:execute 結束(無論成功 / 短路 / 例外)在 finally 統一清掉 ``context.temp_paths``。

橫切關注點(進度事件、錯誤隔離)集中在本類別的 ``_run_stage`` 處理,Stage 子類別保持單純。
排程順序只影響「時機」、不影響「輸出值」(輸出與執行順序無關,只要依賴正確)→ 與 Legacy 逐欄一致。
"""
from __future__ import annotations

import os
import time
from concurrent.futures import FIRST_COMPLETED, Future, wait
from typing import TYPE_CHECKING

from media_processor.pipeline.context import (
    AssetContext,
    STATUS_ERROR,
    STATUS_REJECTED,
)
from media_processor.pipeline.node import StageNode
from media_processor.pipeline.progress import ProgressTracker
from media_processor.pipeline.stage import Stage
from model.resource_wait_clock import ResourceWaitClock

if TYPE_CHECKING:
    # 僅型別檢查時 import,執行期不依賴,避免不必要的耦合與 import 順序問題
    from media_processor.pipeline.executor.executor_registry import ExecutorRegistry

# 終止狀態:asset 一旦進入這些狀態,後續才解除依賴的 Stage 一律跳過(短路)
_TERMINAL_STATUSES = frozenset({STATUS_ERROR, STATUS_REJECTED})


class Pipeline:
    """
    一條由 :class:`StageNode` 組成的 asset 處理依賴圖。

    本身不持有並行資源;``execute`` 時由呼叫端(HybridScheduler 的 driver)注入
    ``ExecutorRegistry`` 與 ``ProgressTracker``,使同一條 Pipeline 定義可被多個 driver 重複使用。
    建構時即驗證依賴圖合法(名稱存在、無環),不合法直接 fail fast。
    """

    def __init__(self, nodes: list[StageNode], name: str = "pipeline"):
        """以一組 StageNode 建構 Pipeline,並在建構期驗證依賴圖。"""
        self._nodes = nodes
        self._name = name
        self._validate()

    @property
    def nodes(self) -> list[StageNode]:
        """組成本 Pipeline 的節點清單(供測試 / 觀察)。"""
        return self._nodes

    # ── 建構期驗證 ───────────────────────────────────────────────────────────

    def _validate(self) -> None:
        """
        驗證依賴圖:Stage 名稱不可重複、依賴必須指向存在的 Stage、整圖不可成環。

        任一不符立即拋 ValueError —— 避免 typo 造成「永遠不 ready」的死迴圈或漏跑 Stage。
        """
        names = [node.name for node in self._nodes]
        name_set = set(names)
        if len(name_set) != len(names):
            duplicated = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"Pipeline '{self._name}' 有重複的 Stage 名稱: {duplicated}")

        for node in self._nodes:
            for dep in node.deps:
                if dep not in name_set:
                    raise ValueError(
                        f"Pipeline '{self._name}' 的 Stage '{node.name}' 依賴不存在的 Stage '{dep}'"
                    )

        # Kahn 拓樸排序偵測環:可拜訪節點數 != 全部 → 含環
        indegree = {node.name: len(node.deps) for node in self._nodes}
        dependents: dict[str, list[str]] = {node.name: [] for node in self._nodes}
        for node in self._nodes:
            for dep in node.deps:
                dependents[dep].append(node.name)
        queue = [name for name, deg in indegree.items() if deg == 0]
        visited = 0
        while queue:
            current = queue.pop()
            visited += 1
            for nxt in dependents[current]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        if visited != len(self._nodes):
            raise ValueError(f"Pipeline '{self._name}' 的 Stage 依賴圖含環(cycle)")

    # ── 執行 ─────────────────────────────────────────────────────────────────

    def execute(
        self,
        context: AssetContext,
        registry: "ExecutorRegistry",  # noqa: F821 - 避免循環 import,僅型別提示
        tracker: ProgressTracker | None = None,
    ) -> AssetContext:
        """
        依依賴圖排程執行所有 Stage,就地更新並回傳 ``context``。

        以拓樸波次推進:每輪找出「依賴全部完成」的 Stage,單一則 inline、多個則分派到各資源池並行,
        等任一完成後再評估下一批。任一 Stage 失敗或 asset 進入終止狀態即短路後續,
        但**絕不拋出例外**——錯誤一律寫入 ``context``,確保單一 asset 失敗不影響其他 asset。
        無論結束路徑為何,finally 一律清除登記的暫存檔。
        """
        name_to_node = {node.name: node for node in self._nodes}
        pending = dict(name_to_node)        # 尚未開始的節點
        in_flight: dict[str, Future] = {}   # 已提交、執行中的節點
        done: set[str] = set()              # 已完成(實際執行或被短路跳過)

        try:
            while pending or in_flight:
                terminal = context.status in _TERMINAL_STATUSES
                # 依賴全部完成的可執行節點
                ready = [
                    name for name, node in pending.items()
                    if all(dep in done for dep in node.deps)
                ]

                if terminal:
                    # 短路:已 reject / error,後續可執行節點全部跳過(標 done 不實際執行)
                    for name in ready:
                        del pending[name]
                        done.add(name)
                elif len(ready) == 1 and not in_flight:
                    # 單一可執行且無併發 → inline 在 driver thread 跑
                    # (省 thread 跳轉;單節點 / Legacy Pipeline 不被 GPU pool size 限流)
                    name = ready[0]
                    del pending[name]
                    self._run_stage(name_to_node[name].stage, context, tracker)
                    done.add(name)
                    continue
                else:
                    # 多個可執行 → 各自依 ResourceType 提交到對應 Worker Pool 並行
                    for name in ready:
                        node = pending.pop(name)
                        in_flight[name] = registry.submit(
                            node.stage.meta.resource_type,
                            self._run_stage,
                            node.stage,
                            context,
                            tracker,
                        )

                if in_flight:
                    # 等任一完成 → 標 done → 回圈重新評估哪些節點解除依賴
                    completed, _ = wait(set(in_flight.values()), return_when=FIRST_COMPLETED)
                    for name, future in list(in_flight.items()):
                        if future in completed:
                            del in_flight[name]
                            # _run_stage 已隔離 Stage 例外;此處 result() 僅會傳遞框架級錯誤
                            future.result()
                            done.add(name)
                elif not ready:
                    # 無在飛行、本輪也無可執行 → 收尾(理論上 pending 已空;建構期已保證無環)
                    break

            return context
        finally:
            self._cleanup_temp_files(context)

    @staticmethod
    def _cleanup_temp_files(context: AssetContext) -> None:
        """清除本 asset 登記的所有暫存檔(逐字對齊原 process() finally:存在才刪、吞 OSError)。"""
        for path in context.temp_paths:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    # 刪不掉(權限 / 已被刪)不致命,忽略以免影響其他 asset
                    pass

    @staticmethod
    def _run_stage(
        stage: Stage,
        context: AssetContext,
        tracker: ProgressTracker | None,
    ) -> None:
        """
        執行單一 Stage 並包覆進度事件與錯誤隔離(Decorator 式橫切處理)。

        Stage 內拋出的任何例外都在此被捕捉、寫入 ``context.error`` 並標記為 error,
        再發 STAGE_ERROR 事件;**不向上拋出**,以免中斷其他並行 Stage 或其他 asset。
        """
        stage_name = stage.meta.name
        if tracker is not None:
            tracker.emit_stage_start(asset_id=context.asset_id, stage_name=stage_name)

        # 每個 stage 開跑前歸零本 thread 的「等資源」累加器，結束時讀回以把等待從總耗時拆出
        ResourceWaitClock.reset()
        start = time.perf_counter()
        try:
            stage.run(context)
            duration_ms = (time.perf_counter() - start) * 1000.0
            if tracker is not None:
                # wait = 卡在 borrow / GpuGate / 合批 等資源關卡的時間；compute = 總耗時 − wait（夾非負）
                waited_ms = min(ResourceWaitClock.waited_ms(), duration_ms)
                compute_ms = max(0.0, duration_ms - waited_ms)
                tracker.emit_stage_finish(
                    asset_id=context.asset_id,
                    stage_name=stage_name,
                    duration_ms=duration_ms,
                    payload={"wait_ms": round(waited_ms, 1), "compute_ms": round(compute_ms, 1)},
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
