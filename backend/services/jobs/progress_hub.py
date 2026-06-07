"""
進度事件連線中樞與 Observer (Mediator + Observer Pattern)。

把 pipeline 已就緒的 ``ProgressTracker`` 事件流橋接到 WebSocket 的核心機制(與 WS 端點解耦,
讓背景 job 子系統 ``backend.services.jobs`` 不需反向依賴 ``backend.api``):

- ``ProgressHub``:連線中樞,以 job_id 分流。worker thread 產生的事件 → 各 WS 連線的
  ``asyncio.Queue``,中間以 ``loop.call_soon_threadsafe`` 跨「執行緒 → event loop」邊界。
  另對每個 job 維護 bounded **replay buffer**,讓 WS 晚連時補播開頭事件(解 job_id 由後端產生、
  WS 連線稍晚的競態)。
- ``WebSocketProgressObserver``:訂閱 ``ProgressTracker`` 的 Observer,把事件委派給 Hub。

橋接要點:``ProgressObserver.on_event`` 在 pipeline 的 worker thread 被呼叫,而 WS ``send`` 是
event loop 上的 coroutine,故不能直接 await;一律經 queue + ``call_soon_threadsafe`` 轉交事件迴圈。
WS 端點(``backend.api.progress``)再從本中樞 attach / detach 連線並串流事件。
"""
from __future__ import annotations

import asyncio
import threading
from collections import deque
from typing import Optional

from config.app_config import PROGRESS_BUFFER_MAXLEN, PROGRESS_JOB_RETENTION_SEC
from media_processor.pipeline.progress import ProgressEvent, ProgressObserver


class ProgressHub:
    """
    進度事件連線中樞 (Mediator):以 job_id 把事件從 worker thread 分流到各 WS 連線。

    執行緒安全:``publish`` 在 pipeline worker thread 呼叫,``attach`` / ``detach`` / ``finish``
    在 event loop 執行緒呼叫,共享狀態全程以 ``threading.Lock`` 保護(臨界區極短、不在持鎖時 await)。
    """

    def __init__(self, buffer_maxlen: int = PROGRESS_BUFFER_MAXLEN):
        """初始化 replay buffer 表、訂閱者表與鎖;event loop 於首次 attach / ensure_loop 時捕捉。"""
        # 每個 job 的事件 replay buffer(序列化 JSON 字串),上限固定避免無限成長
        self._buffers: dict[str, deque[str]] = {}
        # 每個 job 目前連線的 WS 佇列集合
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._buffer_maxlen = buffer_maxlen
        # 跨執行緒排程用的事件迴圈;由 event loop 執行緒上的呼叫捕捉
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # 由 threading.Lock(非 asyncio)保護:publish 來自 worker thread
        self._lock = threading.Lock()

    # ── event loop 捕捉 ──────────────────────────────────────────────────────
    def ensure_loop(self) -> None:
        """在 event loop 執行緒上呼叫,記住目前 loop 供 worker thread 排程;須在 coroutine 內呼叫。"""
        self._loop = asyncio.get_running_loop()

    # ── worker thread 端:發布事件 ───────────────────────────────────────────
    def publish(self, event: ProgressEvent) -> None:
        """
        發布一個事件:存入該 job 的 replay buffer,並推給目前所有 WS 佇列。

        在 pipeline worker thread 被呼叫,故對每個佇列以 ``call_soon_threadsafe`` 排到 event loop。
        無 loop(尚無任何 WS 連過)或無訂閱者時,事件只進 buffer,待 WS attach 時補播。
        """
        job_id = event.job_id
        if job_id is None:
            return
        msg = event.model_dump_json()
        with self._lock:
            buffer = self._buffers.get(job_id)
            if buffer is None:
                buffer = deque(maxlen=self._buffer_maxlen)
                self._buffers[job_id] = buffer
            buffer.append(msg)
            queues = list(self._subscribers.get(job_id, ()))
            loop = self._loop
        if loop is None or not queues:
            return
        for queue in queues:
            loop.call_soon_threadsafe(queue.put_nowait, msg)

    # ── event loop 端:連線生命週期 ─────────────────────────────────────────
    def attach(self, job_id: str) -> tuple[list[str], asyncio.Queue]:
        """
        為一條 WS 連線註冊佇列,回傳 (replay 事件清單, 佇列)。

        在鎖內「snapshot buffer + 註冊佇列」原子完成:任一 publish 要嘛已在 snapshot 內、
        要嘛之後才進佇列,**不漏不重**。須在 event loop 的 coroutine 內呼叫。
        """
        self.ensure_loop()
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            buffer = self._buffers.get(job_id)
            replay = list(buffer) if buffer is not None else []
            self._subscribers.setdefault(job_id, set()).add(queue)
        return replay, queue

    def detach(self, job_id: str, queue: asyncio.Queue) -> None:
        """移除一條 WS 連線的佇列;該 job 無連線後清掉空集合。"""
        with self._lock:
            subscribers = self._subscribers.get(job_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    del self._subscribers[job_id]

    def finish(self, job_id: str) -> None:
        """
        標記一個 job 結束:對每條連線推哨兵(``None``)讓 WS 迴圈優雅收尾,
        並排程在保留期後清除其 replay buffer(讓晚到的 WS 仍可補播)。須在 event loop 執行緒呼叫。
        """
        loop = self._loop
        with self._lock:
            queues = list(self._subscribers.get(job_id, ()))
        if loop is None:
            # 理論上 job 啟動端點已 ensure_loop;保險起見直接清 buffer
            self._drop_buffer(job_id)
            return
        for queue in queues:
            loop.call_soon_threadsafe(queue.put_nowait, None)
        # 延遲清 buffer:WS 重連或晚連仍能在保留期內 replay
        loop.call_later(PROGRESS_JOB_RETENTION_SEC, self._drop_buffer, job_id)

    def finish_threadsafe(self, job_id: str) -> None:
        """
        從 worker thread 安全收尾一個 job:把 finish 排回 event loop 執行緒執行。

        finish 內部用 loop.call_later(非 thread-safe),只能在 event loop 執行緒呼叫;雲端同步的
        Phase 1 收尾發生在 worker thread,故一律經本方法以 call_soon_threadsafe 排回 loop。
        無 loop(理論上啟動端已 ensure_loop)時保守直接清 buffer。
        """
        loop = self._loop
        if loop is None:
            self._drop_buffer(job_id)
            return
        loop.call_soon_threadsafe(self.finish, job_id)

    def _drop_buffer(self, job_id: str) -> None:
        """清除某 job 的 replay buffer(保留期到期後由 loop 計時器觸發)。"""
        with self._lock:
            self._buffers.pop(job_id, None)


class WebSocketProgressObserver(ProgressObserver):
    """
    把 ``ProgressTracker`` 事件委派給 ``ProgressHub`` 的 Observer(無狀態,可被多個 tracker 共用)。
    """

    def __init__(self, hub: ProgressHub):
        """注入連線中樞。"""
        self._hub = hub

    def on_event(self, event: ProgressEvent) -> None:
        """收到事件即交給 Hub 依 job_id 分流;本方法在 worker thread 執行,不可阻塞。"""
        self._hub.publish(event)


# 模組層級單例:跨請求共享同一個中樞與 Observer
progress_hub = ProgressHub()
ws_progress_observer = WebSocketProgressObserver(progress_hub)
