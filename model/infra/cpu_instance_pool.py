"""
CpuInstancePool：本地 CPU 模型的固定大小 instance 池 (Object Pool Pattern)。

VAD(Silero)與 MediaPipe 兩個 CPU 池原本是兩份近乎相同的模組級樣板（Queue + initialized 旗標 +
雙重檢查鎖 + warm/borrow 函式，各 ~45 行），收斂成本類別：以 ``manager_class`` + ``size`` 參數化，
新增 CPU 池（未來若有）只需一行實例化。

真平行關鍵（沿用原設計，不可退化）
--------------------------------
池內放的是「``size`` 個 *不同 slot_id* 的 Manager instance」——每個是彼此獨立的 singleton、
各有自己的 L3 ``_inference_lock``，借出後才能真正多路 CPU 併發（Silero 推論與 MediaPipe 的
C++ graph 執行都釋放 GIL）。⚠️ 不可改成 N 個無參數 ``manager_class()``：那會全部命中同一
(0,0) singleton、共用單一 L3 鎖，被 ``@synchronized_inference`` 序列化 → 池形同虛設退回單路。

warmup 合約：建池時逐 instance 呼叫 ``warmup()``（單執行緒），把「首呼叫才 dlopen 原生擴充」
收斂到啟動期，杜絕執行期多 thread 並發 dlopen 撞動態連結器鎖的死結（見 BaseModelManager.warmup）。
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from queue import Queue
from typing import Callable, Generic, Iterator, TypeVar

from model.infra.base_model_manager import BaseModelManager
from model.infra.resource_wait_clock import ResourceWaitClock

_M = TypeVar("_M", bound=BaseModelManager)
_R = TypeVar("_R")


class CpuInstancePool(Generic[_M]):
    """固定大小的 CPU Manager instance 池：懶初始化（雙重檢查鎖）+ 借還自動歸位。"""

    def __init__(self, manager_class: type[_M], size: int):
        """記錄要建池的 Manager 類別與份數；instance 延遲到 warm() / 首次 borrow 才建。"""
        self._manager_class = manager_class
        self._size = size
        self._queue: Queue = Queue()
        self._initialized = False
        self._init_lock = threading.Lock()

    def warm(self) -> None:
        """
        建滿整池（``size`` 個不同 slot_id 的 instance）並逐一 ``warmup()``（單執行緒預載原生擴充）。

        啟動期由 registry 顯式呼叫；失敗往上拋交由呼叫端記錄並降級 lazy（首次 borrow 會再試）。
        冪等：已初始化則直接返回。
        """
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            for slot_id in range(self._size):
                manager = self._manager_class(slot_id=slot_id)
                # warmup 為 best-effort（內部吞例外）：預載首呼叫的 lazy import / 原生 dlopen
                manager.warmup()
                self._queue.put(manager)
            self._initialized = True

    @contextmanager
    def borrow(self) -> Iterator[_M]:
        """
        借出一個 instance（blocking queue），用完自動歸還。

        池未預熱（warmup 失敗 / 未呼叫）時就地 lazy 建滿整池，避免永久阻塞。
        借出阻塞（池全借出時）計入 ResourceWaitClock，供 stage 拆分 compute/wait。
        """
        if not self._initialized:
            self.warm()
        with ResourceWaitClock.measure():
            manager = self._queue.get()
        try:
            yield manager
        finally:
            # finally 確保異常路徑也歸還 instance，避免池被慢慢耗盡
            self._queue.put(manager)

    def run(self, fn: Callable[[_M], _R]) -> _R:
        """借出一個 instance 執行 ``fn`` 後歸還（borrow 的函式式便捷包裝）。"""
        with self.borrow() as manager:
            return fn(manager)

    @property
    def size(self) -> int:
        """池的常駐 instance 份數（供啟動報表顯示）。"""
        return self._size
