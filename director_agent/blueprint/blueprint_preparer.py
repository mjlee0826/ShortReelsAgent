"""藍圖準備階段的 fork-join 協調器(縮小版 HybridScheduler)。"""
from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor, as_completed

from media_processor.pipeline.progress import ProgressTracker
from director_agent.blueprint.dna_producer import DnaProducer
from director_agent.blueprint.prep_context import PrepContext

# driver thread 命名前綴,方便除錯辨識(對齊 HybridScheduler 慣例)
_PREP_THREAD_PREFIX = "blueprint-prep"


class BlueprintPreparer:
    """藍圖準備階段的 fork-join 協調器。

    結構上即「少數 driver thread + 共享 Tier A 資源」的縮小版 HybridScheduler:把彼此獨立的
    ``DnaProducer`` 並行跑,join 後回傳 ``{name: dna}``。GPU 工作各自 borrow ``ModelPoolRegistry``
    → 共用 GpuGate,故並行不會 VRAM 翻倍;不需要 asset-DAG 機械。
    """

    def __init__(self, producers: list[DnaProducer]):
        """注入分支生產者清單(順序不影響結果,鍵以 ``producer.name`` 為準)。"""
        self._producers = producers

    def prepare(self, ctx: PrepContext, tracker: ProgressTracker | None = None) -> dict[str, dict]:
        """並行跑完所有分支,回傳以 ``producer.name`` 為鍵的 DNA 字典。

        driver 數 = 分支數;皆 I/O 密集(下載 / 雲端),thread 足以重疊(GIL 在 I/O 釋放)。
        ``tracker`` 以獨立參數透傳給每個分支(刻意不入 frozen 的 ``PrepContext``)。
        """
        with ThreadPoolExecutor(
            max_workers=len(self._producers),
            thread_name_prefix=_PREP_THREAD_PREFIX,
        ) as pool:
            # copy_context:把 run_workflow 的成本帳本帶進每個 producer 緒,
            # 否則 Phase 2/3 的 Gemini 呼叫在 producer 緒上讀不到帳本 → 金額記不到
            futures = {
                pool.submit(contextvars.copy_context().run, self._safe_produce, p, ctx, tracker): p
                for p in self._producers
            }
            return {futures[f].name: f.result() for f in as_completed(futures)}

    @staticmethod
    def _safe_produce(producer: DnaProducer, ctx: PrepContext,
                      tracker: ProgressTracker | None) -> dict:
        """單一分支例外不拖垮另一分支:吞例外回空 dict(對齊既有『取不到配樂視為無配樂』)。"""
        try:
            return producer.produce(ctx, tracker)
        except Exception as exc:  # noqa: BLE001 - 刻意隔離分支例外
            print(f"[BlueprintPreparer] 分支 {producer.name} 失敗: {exc}")
            return {}
