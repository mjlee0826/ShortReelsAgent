"""
StallWatchdog：偵測「卡住」的觀測工具 (Observer Pattern + 背景 daemon thread)。

processor 疑似卡住時，最想知道的是「現在到底卡在哪個 stage、卡多久了、是不是在等 VRAM」。
本元件訂閱 :class:`ProgressTracker` 的 stage 事件，維護「已開始未結束」的 stage 清單，並由一條
背景 daemon 執行緒每隔心跳秒印出進行中清單；超過警示秒數的標 ⚠（疑似卡住），同時標示正在
等 VRAM 的 stage（借出時的 ``RESOURCE_WAIT``）。

設計重點
--------
- **純觀測**：只讀事件、印 log，不碰流水線狀態，掛掉也不影響主流程。
- **不洗版**：idle（無進行中 stage）時不輸出；只在有工作在跑時才印心跳。
- **clock 可注入**：用 ``time.monotonic`` 算 elapsed（免受系統時鐘調整影響），測試可注入假時鐘。
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from media_processor.pipeline.progress.events import ProgressEvent, ProgressEventType
from media_processor.pipeline.progress.observer import ProgressObserver

# stop() 等待背景執行緒結束的上限（秒），避免收工時卡住主流程
_THREAD_JOIN_TIMEOUT_SEC = 2.0

# 進行中 stage 的索引鍵：(asset_id, stage_name)
_StageKey = tuple[Optional[str], Optional[str]]


class StallWatchdog(ProgressObserver):
    """
    訂閱進度事件、定期回報進行中 stage 的卡住偵測器。

    心跳輸出範例::

        [Watchdog +30s] 進行中 2 個 stage：
          asset=clip_07.mp4 stage=semantic_video 已 18s
          asset=clip_12.jpg stage=semantic_image 已 95s  ⚠ 疑似卡住  [等 VRAM: cuda:0 free 1.2GB < 需 5.5GB]
    """

    def __init__(
        self,
        heartbeat_sec: float,
        stall_warn_sec: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        """設定心跳間隔、卡住警示門檻與時鐘（clock 可注入供測試）。"""
        self._heartbeat_sec = heartbeat_sec
        self._stall_warn_sec = stall_warn_sec
        self._clock = clock
        # (asset_id, stage_name) -> 開始時刻（monotonic）；只保留進行中的
        self._inflight: dict[_StageKey, float] = {}
        # (asset_id, stage_name) -> 正在等待的資源說明（borrow 等 VRAM）
        self._waiting: dict[_StageKey, str] = {}
        # 同時保護 _inflight / _waiting（事件執行緒寫、心跳執行緒讀）
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── Observer 介面 ─────────────────────────────────────────────────────────
    def on_event(self, event: ProgressEvent) -> None:
        """依事件型態維護進行中 / 等待中清單（持鎖極短，符合 observer 要快的要求）。"""
        key: _StageKey = (event.asset_id, event.stage_name)
        event_type = event.event_type
        with self._lock:
            if event_type == ProgressEventType.STAGE_START:
                self._inflight[key] = self._clock()
            elif event_type in (ProgressEventType.STAGE_FINISH, ProgressEventType.STAGE_ERROR):
                # 結束（成功或錯誤）即移出進行中與等待中
                self._inflight.pop(key, None)
                self._waiting.pop(key, None)
            elif event_type == ProgressEventType.RESOURCE_WAIT:
                self._waiting[key] = self._format_wait(event.payload)
            elif event_type == ProgressEventType.RESOURCE_ACQUIRED:
                self._waiting.pop(key, None)

    # ── 生命週期 ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        """啟動背景心跳 daemon 執行緒（已啟動則無效，可安全重複呼叫）。"""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="StallWatchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """通知背景執行緒收工並等待其結束（最多 _THREAD_JOIN_TIMEOUT_SEC 秒）。"""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=_THREAD_JOIN_TIMEOUT_SEC)

    # ── 背景輪詢 ──────────────────────────────────────────────────────────────
    def _loop(self) -> None:
        """每隔心跳秒回報一次；用 Event.wait 兼顧定時與「被 set 立即收工」。"""
        # wait 回 True = 被 set（收工）；False = 逾時（到下一個心跳）
        while not self._stop.wait(self._heartbeat_sec):
            self._report()

    def _report(self) -> None:
        """印出目前進行中的 stage（依已執行時間由久到新排序），超時者標 ⚠。"""
        now = self._clock()
        with self._lock:
            # 依開始時刻升冪排序 → 跑最久的排最前面
            items = sorted(self._inflight.items(), key=lambda kv: kv[1])
            waiting = dict(self._waiting)
        if not items:
            return  # idle：無進行中 stage 就不輸出，避免洗版
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
