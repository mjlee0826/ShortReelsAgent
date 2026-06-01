"""
StageGroup:一組可並行執行的 Stage (Composite Pattern)。

設計語意
--------
**同一群組內的 Stage 並行,群組之間序列**。這是簡化版 DAG:把「只讀前一群組產出、彼此互不依賴」
的 Stage 塞進同一群組(群組內並行),把「依賴本群組結果」的 Stage 放下一群組(群組間序列)。

StageGroup 本身只是**容器**,不含執行邏輯;實際的「群組內並行 / 群組間序列」由
:class:`~media_processor.pipeline.pipeline.Pipeline` 搭配 ExecutorRegistry 實作,
符合「資料結構與執行策略分離」的設計。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from media_processor.pipeline.stage import Stage


@dataclass
class StageGroup:
    """
    一批可同時執行的 Stage。

    群組邊界由 PipelineBuilder 決定,並保證群組內各 Stage 寫入 ``AssetContext`` 的欄位互斥
    (plan 風險表「群組內 Stage 寫入 context 同欄位衝突」緩解)。
    """

    name: str
    stages: list[Stage] = field(default_factory=list)

    @property
    def is_single(self) -> bool:
        """是否只含單一 Stage(供 Pipeline 決定走 inline 或 executor 分派)。"""
        return len(self.stages) == 1
