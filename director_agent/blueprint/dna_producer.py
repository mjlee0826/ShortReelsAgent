"""藍圖準備分支的策略抽象(Strategy Pattern)。"""
from __future__ import annotations

from abc import ABC, abstractmethod

from media_processor.pipeline.progress import ProgressTracker
from director_agent.blueprint.prep_context import PrepContext


class DnaProducer(ABC):
    """藍圖準備的「DNA 生產者」抽象。

    每個生產者吃同一份 ``PrepContext``,獨立產出藍圖所需的一塊 DNA;彼此無資料相依,
    故可由 ``BlueprintPreparer`` 以 fork-join 並行。``tracker`` 為活的進度協作者(可為 ``None``),
    以獨立參數貫穿(不混入 frozen 的 ``PrepContext``,維持其並行唯讀語意)。
    """

    name: str  # 子類別提供;供日誌、進度、結果鍵

    @abstractmethod
    def produce(self, ctx: PrepContext, tracker: ProgressTracker | None = None) -> dict:
        """產出本分支的 DNA;不適用 / 取不到時回空 dict(呼叫端視為缺該段)。"""
