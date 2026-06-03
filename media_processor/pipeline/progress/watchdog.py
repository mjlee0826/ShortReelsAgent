"""
StallWatchdog：偵測「卡住」的觀測工具 (Observer Pattern + 背景 daemon + C 層故障處理)。

processor 疑似卡住時最想知道:現在卡在哪個 stage、卡多久、是不是在等 VRAM。本元件:

1. **Python 層心跳**:訂閱 :class:`ProgressTracker` stage 事件，維護「已開始未結束」清單，
   背景 daemon 每隔心跳秒印出進行中清單，超過警示秒數標 ⚠。
2. **C 層 dead-man dump**(關鍵):用 ``faulthandler.dump_traceback_later`` 設一個 C 層計時器，
   每次心跳「重新武裝」往後推。**只要 Python 還活著就一直推、永不觸發**；一旦某個 C 擴充
   (如 onnxruntime / CUDA)在持有 GIL 下 hang 住,連這條心跳 thread 都凍住 → 推不動 → 計時器
   在 ``freeze_dump_sec`` 後**從 C 層 dump 全部 thread 堆疊到 stderr**。這正補上「Python watchdog
   抓不到 GIL-holding C hang」的盲區。
3. **手動 dump**:註冊 ``SIGUSR1`` → ``kill -USR1 <pid>`` 即時 dump 全部堆疊(免 py-spy / root 權限)。

純觀測,不改流水線行為。
"""
from __future__ import annotations

import faulthandler
import signal
import threading
import time
from typing import Callable, Optional

from media_processor.pipeline.progress.events import ProgressEvent, ProgressEventType
from media_processor.pipeline.progress.observer import ProgressObserver

# stop() 等待背景執行緒結束的上限(秒),避免收工時卡住主流程
_THREAD_JOIN_TIMEOUT_SEC = 2.0

# 進行中 stage 的索引鍵:(asset_id, stage_name)
_StageKey = tuple[Optional[str], Optional[str]]


class StallWatchdog(ProgressObserver):
    """
    訂閱進度事件、定期回報進行中 stage,並以 C 層 dead-man dump 兜住 GIL 凍結的卡住偵測器。
    """

    def __init__(
        self,
        heartbeat_sec: float,
        stall_warn_sec: float,
        freeze_dump_sec: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        """
        Args:
            heartbeat_sec:   心跳間隔(每隔多久印一次進行中 stage)。
            stall_warn_sec:  單一 stage 執行超過此秒數標 ⚠ 疑似卡住。
            freeze_dump_sec: C 層 dead-man:心跳停止推進(GIL 凍住)達此秒數 → dump 全部堆疊。
                             應 > heartbeat_sec(預留數次心跳的容錯)。
            clock:           時鐘函式(可注入供測試)。
        """
        self._heartbeat_sec = heartbeat_sec
        self._stall_warn_sec = stall_warn_sec
        self._freeze_dump_sec = freeze_dump_sec
        self._clock = clock
        # (asset_id, stage_name) -> 開始時刻(monotonic);只保留進行中的
        self._inflight: dict[_StageKey, float] = {}
        # (asset_id, stage_name) -> 正在等待的資源說明(borrow 等 VRAM)
        self._waiting: dict[_StageKey, str] = {}
        # 同時保護 _inflight / _waiting(事件執行緒寫、心跳執行緒讀)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # 啟用 C 層故障處理 + 手動 SIGUSR1 dump(GIL 凍住也有效)
        self._enable_fault_dump()

    # ── C 層故障處理(GIL 凍住也能 dump) ──────────────────────────────────────
    def _enable_fault_dump(self) -> None:
        """啟用 faulthandler,並註冊 SIGUSR1 手動 dump(best-effort;失敗不影響其餘功能)。"""
        if not faulthandler.is_enabled():
            faulthandler.enable()
        # SIGUSR1:kill -USR1 <pid> 即時 dump 全部 thread 堆疊(不需 py-spy / ptrace 權限)
        if hasattr(signal, "SIGUSR1"):
            try:
                faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)
            except (ValueError, RuntimeError) as exc:
                # 非主執行緒等情況可能註冊失敗;dead-man timer 仍生效,故僅告警
                print(f"[StallWatchdog] SIGUSR1 手動 dump 註冊失敗({exc});dead-man timer 仍有效")

    def _rearm_freeze_dump(self) -> None:
        """
        重新武裝 C 層 dead-man 計時器:本心跳 thread 活著就一直往後推。

        ``dump_traceback_later`` 每次呼叫會取消前一個計時器、重設新的;只要這行還跑得到,
        就永遠在 ``freeze_dump_sec`` 之外、不會觸發。一旦 GIL 被 C hang 凍住、這行跑不到,
        計時器就會在 C 層自行 dump 全部堆疊(這是 Python watchdog 做不到的)。
        """
        faulthandler.dump_traceback_later(self._freeze_dump_sec, repeat=False)

    # ── Observer 介面 ─────────────────────────────────────────────────────────
    def on_event(self, event: ProgressEvent) -> None:
        """依事件型態維護進行中 / 等待中清單(持鎖極短,符合 observer 要快的要求)。"""
        key: _StageKey = (event.asset_id, event.stage_name)
        event_type = event.event_type
        with self._lock:
            if event_type == ProgressEventType.STAGE_START:
                self._inflight[key] = self._clock()
            elif event_type in (ProgressEventType.STAGE_FINISH, ProgressEventType.STAGE_ERROR):
                # 結束(成功或錯誤)即移出進行中與等待中
                self._inflight.pop(key, None)
                self._waiting.pop(key, None)
            elif event_type == ProgressEventType.RESOURCE_WAIT:
                self._waiting[key] = self._format_wait(event.payload)
            elif event_type == ProgressEventType.RESOURCE_ACQUIRED:
                self._waiting.pop(key, None)

    # ── 生命週期 ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        """啟動背景心跳 daemon 執行緒(已啟動則無效,可安全重複呼叫)。"""
        if self._thread is not None:
            return
        self._stop.clear()
        # 先武裝一次,涵蓋「第一個心跳前就凍住」的情況
        self._rearm_freeze_dump()
        self._thread = threading.Thread(target=self._loop, name="StallWatchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """通知背景執行緒收工、取消 dead-man 計時器,並等待其結束(最多 _THREAD_JOIN_TIMEOUT_SEC 秒)。"""
        self._stop.set()
        # 正常收工 → 取消 dead-man,避免閒置期誤觸發
        faulthandler.cancel_dump_traceback_later()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=_THREAD_JOIN_TIMEOUT_SEC)

    # ── 背景輪詢 ──────────────────────────────────────────────────────────────
    def _loop(self) -> None:
        """每隔心跳秒:重新武裝 dead-man timer + 回報進行中 stage。"""
        # wait 回 True = 被 set(收工);False = 逾時(到下一個心跳)
        while not self._stop.wait(self._heartbeat_sec):
            self._rearm_freeze_dump()
            self._report()

    def _report(self) -> None:
        """印出目前進行中的 stage(依已執行時間由久到新排序),超時者標 ⚠。"""
        now = self._clock()
        with self._lock:
            # 依開始時刻升冪排序 → 跑最久的排最前面
            items = sorted(self._inflight.items(), key=lambda kv: kv[1])
            waiting = dict(self._waiting)
        if not items:
            return  # idle:無進行中 stage 就不輸出,避免洗版
        lines = [f"[Watchdog +{self._heartbeat_sec:.0f}s] 進行中 {len(items)} 個 stage："]
        for (asset_id, stage_name), started_at in items:
            elapsed = now - started_at
            warn = "  ⚠ 疑似卡住" if elapsed >= self._stall_warn_sec else ""
            wait_note = waiting.get((asset_id, stage_name), "")
            wait_str = f"  [{wait_note}]" if wait_note else ""
            lines.append(
                f"  asset={asset_id or '-'} stage={stage_name or '-'} "
                f"已 {elapsed:.0f}s{warn}{wait_str}"
            )
        print("\n".join(lines))

    @staticmethod
    def _format_wait(payload: dict) -> str:
        """把 RESOURCE_WAIT payload 整理成「等 VRAM: cuda:0 free X < 需 Y」。"""
        device = payload.get("device", "?")
        free_gb = payload.get("free_gb")
        need_gb = payload.get("need_gb")
        if free_gb is not None and need_gb is not None:
            return f"等 VRAM: {device} free {free_gb}GB < 需 {need_gb}GB"
        return f"等 VRAM: {device}"
