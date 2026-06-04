"""
BatchCollector:Stage 內的動態合批器 (Producer–Consumer + Future/Promise)。

設計動機
--------
plan §4.3:多個 asset 的同一個 Stage 在執行期自動合批,攤平 GPU kernel 啟動成本
(MUSIQ/LAION 單張 200ms、batch 16 約 30ms/張),等同 Triton / vLLM 的 dynamic batching
縮小到 Stage 內部。對 driver thread 完全透明 —— Stage 只是把「單張呼叫」換成
``collector.submit(item).result()``,Stage 介面與依賴圖都不動。

為什麼不會 deadlock(關鍵)
--------------------------
每個 collector 有**自己的 daemon worker thread**,獨立於 ExecutorRegistry 的四個 pool。
送件方(driver / GPU-pool thread)只是阻塞在 ``future.result()``,**手上沒有握 GpuGate**
(還沒呼叫模型);worker 呼叫 ``batch_fn``(內部走 ``@synchronized_inference`` → L2 GpuGate)時,
沒有任何阻塞中的送件方握著 gate,故必能取得 → 跑完分發 Future → 解除所有阻塞。
即使 GPU pool 的 slot 全部阻塞在 future 上,獨立的 worker 仍能推進;timeout 保證即使只有 1 件
也會在 ``timeout_ms`` 後觸發。詳見 ``docs/lock_design.md`` 與整合計畫 §4.3。

跨 asset 共享
-------------
Stage 實例是「每個 asset 重新 new」,故 collector 不能存成 Stage 的 instance 屬性
(否則每 asset 一個、永遠合不了批)。改由 :class:`BatchCollectorRegistry` 以 process 級單例
(class-level + 雙重檢查鎖,對齊 ``BaseModelManager._GPU_GATES``)依 key 共享同一個 collector。
"""
from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from model.resource_wait_clock import ResourceWaitClock

# 合批項目型別 T、批次結果型別 R(供型別提示,讓 submit 的回傳 Future 型別清晰)
T = TypeVar("T")
R = TypeVar("R")

# 毫秒換算秒,避免裸 magic number
_MS_PER_SECOND = 1000.0

# 關閉訊號:放進 queue 讓 worker 收工(以唯一物件辨識,不與任何真實項目混淆)
_SHUTDOWN = object()


@dataclass(frozen=True)
class BatchSpec:
    """
    合批規格 (Value Object):描述一個 collector 的 key 與合批參數。

    - ``key``:跨 asset 共享的識別字串(同 key → 同一個 collector 單例)。
    - ``batch_size``:單次 forward 的最大樣本數(上限;實際批量受上游併發與 timeout 決定)。
    - ``timeout_ms``:收到第一件後等待補滿的視窗,逾時即以現有數量觸發,避免末尾項目卡死。
    - ``enabled``:是否啟用合批;False 時呼叫端應走原單張路徑(本旗標僅作為規格紀錄)。
    """

    key: str
    batch_size: int
    timeout_ms: int
    enabled: bool


@dataclass(frozen=True)
class _BatchRequest(Generic[T]):
    """單筆送件:待處理項目 + 對應的 Future(worker 算完後回填結果)。"""

    item: T
    future: Future


class BatchCollector(Generic[T, R]):
    """
    動態合批器:``submit`` 回傳 Future,背景 worker 收集成批後一次 ``batch_fn`` 並分發結果。

    ``batch_fn`` 由呼叫端注入(通常 lazy 綁定某模型單例的 ``score_batch``),
    必須回傳「與輸入等長、順序一致」的結果列表;collector 會強制檢查長度,不符即整批
    ``set_exception``(視為框架級 bug,避免 driver 永久卡死)。
    """

    def __init__(self, batch_fn: Callable[[list[T]], list[R]], spec: BatchSpec):
        """記錄合批函式與規格,預備(但尚未啟動)背景 worker thread。"""
        self._batch_fn = batch_fn
        self._spec = spec
        self._timeout_s = spec.timeout_ms / _MS_PER_SECOND
        self._queue: "queue.Queue" = queue.Queue()
        # worker 延遲到第一次 submit 才啟動,避免「建了 collector 卻沒用」也佔一條 thread
        self._worker: threading.Thread | None = None
        self._start_lock = threading.Lock()

    def submit(self, item: T) -> Future:
        """送入一個待處理項目,立刻回傳 Future;呼叫端 ``.result()`` 阻塞到該批算完。"""
        future: Future = Future()
        self._ensure_worker()
        self._queue.put(_BatchRequest(item=item, future=future))
        return future

    def submit_and_wait(self, item: T) -> R:
        """
        送件並阻塞等結果,且把等待時間計入「呼叫者 thread」的等資源累加 (ResourceWaitClock)。

        合批的真正運算發生在 collector 自己的 daemon worker thread;送件方(stage thread)只是阻塞在
        ``future.result()``。因 ResourceWaitClock 是 thread-local,worker thread 上的 borrow / GpuGate
        等待無法歸給送件 stage,故在此把整段 ``result()`` 計為送件方的「等資源」(其本身 compute≈0)。
        所有走合批的 stage(tech / aes / whisper / audio_env)統一呼叫本方法,等待歸因才一致,
        不必各自在 stage 內 sprinkle ``measure()``。
        """
        future = self.submit(item)
        with ResourceWaitClock.measure():
            return future.result()

    def shutdown(self) -> None:
        """送出關閉訊號讓 worker 收工(daemon thread,程序結束本也會自動回收)。"""
        if self._worker is None:
            return
        self._queue.put(_SHUTDOWN)
        # 給 worker 一點時間把手上的批跑完;逾時不強制,交給 daemon 隨程序回收
        self._worker.join(timeout=self._timeout_s + 1.0)

    # ── 內部 ──────────────────────────────────────────────────────────────────

    def _ensure_worker(self) -> None:
        """雙重檢查鎖延遲啟動單一背景 worker thread。"""
        if self._worker is not None:
            return
        with self._start_lock:
            if self._worker is None:
                worker = threading.Thread(
                    target=self._worker_loop,
                    name=f"batch-{self._spec.key}",
                    daemon=True,
                )
                worker.start()
                self._worker = worker

    def _worker_loop(self) -> None:
        """
        背景收集迴圈:阻塞等第一件 → 在 timeout 視窗內補到 batch_size 或逾時 → 分發。

        阻塞等第一件(無逾時)讓 idle 時不空轉 CPU;且批量恆 ≥1,天然滿足「batch < 1 則跳過」。
        """
        while True:
            first = self._queue.get()  # 阻塞:沒工作就睡,有第一件才醒
            if first is _SHUTDOWN:
                return

            batch: list[_BatchRequest] = [first]
            deadline = time.monotonic() + self._timeout_s
            stop_after_dispatch = False

            # timeout 視窗內持續收件,直到滿批或逾時
            while len(batch) < self._spec.batch_size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    nxt = self._queue.get(timeout=remaining)
                except queue.Empty:
                    break
                if nxt is _SHUTDOWN:
                    # 關閉訊號:先把已收集的批跑完再收工,不丟棄在飛行中的請求
                    stop_after_dispatch = True
                    break
                batch.append(nxt)

            self._dispatch(batch)
            if stop_after_dispatch:
                return

    def _dispatch(self, batch: list[_BatchRequest]) -> None:
        """對一批請求呼叫 ``batch_fn`` 並把結果(或例外)回填到各自的 Future。"""
        futures = [req.future for req in batch]
        try:
            results = self._batch_fn([req.item for req in batch])
        except Exception as exc:  # noqa: BLE001 - 合批函式任何失敗都要傳遞給送件方,不可吞掉
            self._fail_all(futures, exc)
            return

        # 長度防呆:回傳數量與輸入不符代表框架級 bug,整批拋例外,避免部分 Future 永遠無人回填
        if len(results) != len(futures):
            self._fail_all(
                futures,
                RuntimeError(
                    f"BatchCollector '{self._spec.key}' batch_fn 回傳 {len(results)} 筆 "
                    f"≠ 輸入 {len(futures)} 筆"
                ),
            )
            return

        for future, result in zip(futures, results):
            if not future.done():
                future.set_result(result)

    @staticmethod
    def _fail_all(futures: list[Future], exc: Exception) -> None:
        """把同一個例外設給整批 Future(送件方 ``.result()`` 會重新拋出,由 Pipeline 隔離成 error)。"""
        for future in futures:
            if not future.done():
                future.set_exception(exc)


class BatchCollectorRegistry:
    """
    跨 asset 共享的 BatchCollector 單例倉儲 (Registry + Singleton)。

    Stage 實例每個 asset 重新建立,但同一 key 的 collector 必須唯一才會真的合批,
    故以 class-level dict + 雙重檢查鎖管理(對齊 ``BaseModelManager._GPU_GATES`` 的做法)。
    """

    _collectors: dict[str, BatchCollector] = {}
    _lock = threading.Lock()

    @classmethod
    def get(cls, spec: BatchSpec, batch_fn: Callable[[list], list]) -> BatchCollector:
        """
        取得(或延遲建立並快取)指定 key 的 collector。

        ``batch_fn`` 僅在「首次建立」時使用,之後同 key 的呼叫一律回傳既有單例
        (故呼叫端每次傳同義的 batch_fn 無妨)。
        """
        collector = cls._collectors.get(spec.key)
        if collector is not None:
            return collector
        with cls._lock:
            collector = cls._collectors.get(spec.key)
            if collector is None:
                collector = BatchCollector(batch_fn, spec)
                cls._collectors[spec.key] = collector
            return collector

    @classmethod
    def shutdown_all(cls) -> None:
        """關閉並清空所有 collector(由 ``PipelineRunner.shutdown`` 呼叫)。"""
        with cls._lock:
            for collector in cls._collectors.values():
                collector.shutdown()
            cls._collectors.clear()
