"""
GpuGate：GPU 容量門抽象與預設實作 (Strategy Pattern)。

設計動機
--------
原本 ``@synchronized_inference`` 只鎖住「同一個 Manager instance 的 forward」，
跨 instance 的多模型同卡時會撞 VRAM OOM（例如同卡 Qwen + Whisper 兩條 thread）。
GpuGate 補上「同卡所有 forward 互斥」這層 (L2)，並設計成可替換策略：

- Week 1: ``BinaryGate`` ── Semaphore(1)，粗粒度互斥，序列化同卡所有 forward。
- Week 3b: ``BudgetGate`` ── 依 per-model VRAM cost 預算控制，VRAM 夠可同卡併發；
  並以 ``priority`` 讓主瓶頸（Qwen）優先取得 VRAM，不被小模型串流餓死。

整體鎖層級與升級路徑詳見 ``docs/lock_design.md``。
"""
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Iterator

# 無優先權的預設等級：數值越大優先序越高（Qwen 等主瓶頸設正值，其餘維持 0）
NO_PRIORITY = 0


class GpuGate(ABC):
    """
    GPU 容量門抽象 (Strategy Pattern)。

    所有具體 Gate 必須提供 :meth:`acquire` 作為 context manager，
    呼叫端取得門票後執行 forward，結束時自動歸還。

    - ``cost_gb``：給 ``BudgetGate`` 計算 VRAM 預算用，``BinaryGate`` 等粗粒度實作可忽略。
    - ``priority``：給 ``BudgetGate`` 做反餓死排序用（高優先在等時低優先讓路），粗粒度實作可忽略。
    """

    @abstractmethod
    @contextmanager
    def acquire(self, cost_gb: float = 0.0, priority: int = NO_PRIORITY) -> Iterator[None]:
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
    def acquire(self, cost_gb: float = 0.0, priority: int = NO_PRIORITY) -> Iterator[None]:
        """阻塞取得門票；cost_gb / priority 在 BinaryGate 無意義，僅保留簽名供策略替換。"""
        # cost_gb / priority 刻意保留，避免日後切換 BudgetGate 時呼叫端要改
        with self._semaphore:
            yield


class BudgetGate(GpuGate):
    """
    細粒度 Gate：以 per-model VRAM cost 做預算記帳，VRAM 夠就同卡併發 (Week 3b)。

    預算語意
    --------
    ``total_gb`` 應已是「該卡 free VRAM − 已常駐權重總和」（由 GPU Capacity Manager 算出），
    本類別再扣掉 ``safety_buffer_gb`` 得到可分配給「在飛行中 forward 暫態峰值總和」的預算。
    放行條件：``in_flight + cost ≤ budget``。

    Qwen 反餓死 (priority)
    ----------------------
    小模型（MUSIQ inline 可多條、LAION/Whisper/AudioEnv）會與 Qwen 搶同卡預算；
    若貪婪放行，Qwen 的大塊 cost 會一直被小請求插隊而餓死。故規則：
    **只要有高優先請求在等，低優先請求一律不放行** —— 讓在飛的小 forward 自然排空、
    預算騰給 Qwen，Qwen 進場後小模型再恢復。

    過大請求保險
    ------------
    若單一 forward 的 cost 大於整卡預算，``in_flight == 0`` 時仍無條件放行（單獨跑），
    避免「cost > budget」造成永久阻塞。
    """

    def __init__(self, total_gb: float, safety_buffer_gb: float = 0.0) -> None:
        """以「free − 常駐權重」總額扣掉安全緩衝得到可分配預算，並初始化記帳狀態。"""
        # 預算下限為 0，避免 free 被鄰居吃光時算出負值
        self._budget = max(0.0, total_gb - safety_buffer_gb)
        # 在飛行中的 forward 暫態成本總和（GB）
        self._in_flight = 0.0
        # 正在等待的高優先（priority>0）請求數；>0 時低優先讓路
        self._waiting_priority = 0
        # 單一 Condition 同時保護記帳狀態與作為等待/喚醒通道
        self._cond = threading.Condition()

    @contextmanager
    def acquire(self, cost_gb: float = 0.0, priority: int = NO_PRIORITY) -> Iterator[None]:
        """阻塞到預算可容納本次 forward 才放行；離開 context 時歸還預算並喚醒等待者。"""
        # 負成本無意義，夾到 0；確保記帳不會因壞值倒退
        cost = max(0.0, cost_gb)
        with self._cond:
            # 標記「有高優先在等」必須在進入 wait 迴圈前，低優先才看得到並讓路
            if priority > NO_PRIORITY:
                self._waiting_priority += 1
            try:
                while not self._can_admit(cost, priority):
                    self._cond.wait()
            finally:
                # 無論正常取得或例外，等待計數都要還原，避免永久壓住低優先
                if priority > NO_PRIORITY:
                    self._waiting_priority -= 1
            # 取得門票：在鎖內累加 in_flight，狀態一致後才離開臨界區
            self._in_flight += cost
        try:
            yield
        finally:
            with self._cond:
                self._in_flight -= cost
                # 預算釋出，喚醒所有等待者重新評估（含被讓路的低優先）
                self._cond.notify_all()

    def _can_admit(self, cost: float, priority: int) -> bool:
        """判定當前是否可放行本次請求（須在持有 _cond 時呼叫）。"""
        # 反餓死：低優先請求在「有高優先等待」時一律讓路
        if priority == NO_PRIORITY and self._waiting_priority > 0:
            return False
        # 無人在飛 → 無條件放行（涵蓋 cost > budget 的過大請求單獨跑，避免永久阻塞）
        if self._in_flight == 0:
            return True
        # 一般情況：在飛成本加上本次成本不超過預算才放行
        return self._in_flight + cost <= self._budget
