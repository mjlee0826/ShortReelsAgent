"""
進度觀察者：Observer 側（介面 + 具體實作）。

把「誰來消費事件」獨立成一檔。Week 3c 新增 ``WebSocketProgressObserver`` 時
只在此檔追加，不需動到 Subject（``ProgressTracker``）與事件定義（``events``），
符合 Open/Closed Principle。
"""
from abc import ABC, abstractmethod

from media_processor.pipeline.progress.events import ProgressEvent


class ProgressObserver(ABC):
    """
    進度觀察者介面 (Observer Pattern)。

    具體實作可以是：
    - 印到 stdout（``PrintProgressObserver``，Week 1）
    - 推到 WebSocket client（Week 3c）
    - 寫進結構化 log / 上報 metrics（未來擴展）
    """

    @abstractmethod
    def on_event(self, event: ProgressEvent) -> None:
        """處理一個事件；本方法應 **盡量快速** 且不拋出例外。"""


class PrintProgressObserver(ProgressObserver):
    """
    最小可用 Observer：將事件以可讀格式印到 stdout。

    主要用於 Week 1/2 開發期，無需架設 WebSocket 即可肉眼觀察事件流。
    """

    def on_event(self, event: ProgressEvent) -> None:
        """以「[type] asset/stage – duration」格式印出事件。"""
        # 將 None 欄位以「-」顯示，避免訊息中出現「None」混淆
        asset    = event.asset_id  or "-"
        stage    = event.stage_name or "-"
        duration = f"{event.duration_ms:.1f}ms" if event.duration_ms is not None else "-"
        suffix   = f" err={event.error}" if event.error else ""
        print(
            f"[Progress] {event.event_type.value:<16} "
            f"asset={asset:<24} stage={stage:<24} dur={duration}{suffix}"
        )
