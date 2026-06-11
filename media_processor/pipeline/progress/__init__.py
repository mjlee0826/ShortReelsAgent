"""
ProgressTracker：Pipeline 進度事件廣播機制 (Observer Pattern)。

範疇
----
本套件僅定義介面與一個 ``PrintProgressObserver``，**不接 WebSocket**。

模組切分（Observer Pattern 的三個角色各自一檔）
-----------------------------------------------
- ``events``   ── 事件資料：``ProgressEventType`` + ``ProgressEvent``（pydantic，可直接 ``model_dump_json()``）。
- ``observer`` ── Observer 側：``ProgressObserver`` 介面 + ``PrintProgressObserver``。
- ``tracker``  ── Subject 側：``ProgressTracker`` 廣播中樞，對每個 Observer try/except 隔離，絕不阻斷主流水線。

對外維持單一 import 路徑 ``media_processor.pipeline.progress``：
原本就是一個檔，拆成套件後在此 re-export 全部公開名稱，呼叫端零改動。
"""
from media_processor.pipeline.progress.events import (
    ProgressEvent,
    ProgressEventType,
)
from media_processor.pipeline.progress.observer import (
    PrintProgressObserver,
    ProgressObserver,
)
from media_processor.pipeline.progress.tracker import ProgressTracker
from media_processor.pipeline.progress.stage_span import stage_span

__all__ = [
    "ProgressEventType",
    "ProgressEvent",
    "ProgressObserver",
    "PrintProgressObserver",
    "ProgressTracker",
    "stage_span",
]
