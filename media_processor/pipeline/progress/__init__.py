"""
ProgressTracker：Pipeline 進度事件廣播機制 (Observer Pattern)。

Week 1 範疇
-----------
本套件僅定義介面與一個 ``PrintProgressObserver``，**不接 WebSocket**。
Week 3c 才實作 ``WebSocketProgressObserver`` 推播給前端，
本套件提早建好讓 Stage 開發時即可埋事件，不需等到後期重構。

模組切分（Observer Pattern 的三個角色各自一檔）
-----------------------------------------------
- ``events``   ── 事件資料：``ProgressEventType`` + ``ProgressEvent``（pydantic，可直接 ``model_dump_json()``）。
- ``observer`` ── Observer 側：``ProgressObserver`` 介面 + ``PrintProgressObserver``（Week 3c 在此加 WebSocket）。
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

__all__ = [
    "ProgressEventType",
    "ProgressEvent",
    "ProgressObserver",
    "PrintProgressObserver",
    "ProgressTracker",
]
