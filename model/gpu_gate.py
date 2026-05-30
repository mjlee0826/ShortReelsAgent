"""
GpuGate：GPU 容量門抽象與預設實作 (Strategy Pattern)。

設計動機
--------
原本 ``@synchronized_inference`` 只鎖住「同一個 Manager instance 的 forward」，
跨 instance 的多模型同卡時會撞 VRAM OOM（例如同卡 Qwen + Whisper 兩條 thread）。
GpuGate 補上「同卡所有 forward 互斥」這層 (L2)，並設計成可替換策略：

- Week 1: ``BinaryGate`` ── Semaphore(1)，粗粒度互斥，序列化同卡所有 forward。
- Week 3b: ``BudgetGate`` ── 依 per-model VRAM cost 預算控制，VRAM 夠可同卡併發。

整體鎖層級與升級路徑詳見 ``docs/lock_design.md``。
"""
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Iterator


class GpuGate(ABC):
    """
    GPU 容量門抽象 (Strategy Pattern)。

    所有具體 Gate 必須提供 :meth:`acquire` 作為 context manager，
    呼叫端取得門票後執行 forward，結束時自動歸還。

    ``cost_gb`` 參數給 ``BudgetGate`` 計算 VRAM 預算用，
    ``BinaryGate`` 等粗粒度實作可忽略。
    """

    @abstractmethod
    @contextmanager
    def acquire(self, cost_gb: float = 0.0) -> Iterator[None]:
        """取得門票（context manager）。離開 context 時自動釋放。"""


class BinaryGate(GpuGate):
    """
    粗粒度 Gate：同卡同時最多一條 forward。

    用法等同 ``threading.Semaphore(1)``，是 Week 1 修補同卡多模型 OOM bug 的最小成本實作。
    後續 Week 3b 由 GPU Capacity Manager 透過
    ``BaseModelManager.register_gate_factory`` 替換為 ``BudgetGate`` 即可拿到同卡併發紅利。
    """

    def __init__(self) -> None:
        """初始化內部 Semaphore，容量固定為 1。"""
        # 內部僅一名持票人，達到「同卡單一 forward」的不變式
        self._semaphore = threading.Semaphore(1)

    @contextmanager
    def acquire(self, cost_gb: float = 0.0) -> Iterator[None]:
        """阻塞取得門票；cost_gb 在 BinaryGate 無意義，僅保留簽名給未來 BudgetGate。"""
        # cost_gb 刻意保留，避免日後切換 BudgetGate 時呼叫端要改
        with self._semaphore:
            yield
