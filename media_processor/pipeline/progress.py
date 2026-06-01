"""
ProgressTracker：Pipeline 進度事件廣播機制 (Observer Pattern)。

Week 1 範疇
-----------
本檔僅定義介面與一個 ``PrintProgressObserver``，**不接 WebSocket**。
Week 3c 才實作 ``WebSocketProgressObserver`` 推播給前端，
本檔提早建好讓 Stage 開發時即可埋事件，不需等到後期重構。

設計重點
--------
- **Subject (ProgressTracker)** 廣播給多個 **Observer**，
  任一 Observer 失敗 try/except 隔離，**絕對不阻斷主流水線**。
- **Pydantic BaseModel (ProgressEvent)**：Week 3c 接 WebSocket 時可
  直接 ``model_dump_json()`` 序列化，無需額外轉換層。
- **Enum (ProgressEventType)**：所有可能事件型態列舉，靜態檢查可發現未處理分支。
"""
import time
import threading
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ProgressEventType(str, Enum):
    """所有 Pipeline 階段可能產生的事件型態。"""

    # ── Stage 級別 ────────────────────────────────────────────────────────────
    STAGE_START  = "stage_start"
    STAGE_FINISH = "stage_finish"
    STAGE_ERROR  = "stage_error"

    # ── Pipeline 級別 ────────────────────────────────────────────────────────
    PIPELINE_START  = "pipeline_start"
    PIPELINE_FINISH = "pipeline_finish"

    # ── 啟動期 ────────────────────────────────────────────────────────────────
    # Eager warm up 模型載入事件，Week 2a 才實際發送，本檔提早定義
    MODEL_WARMUP = "model_warmup"


class ProgressEvent(BaseModel):
    """
    Pipeline 進度事件（不可變值物件）。

    序列化策略：Week 3c WebSocket 直接呼叫 ``event.model_dump_json()`` 推給前端。
    """

    event_type: ProgressEventType
    # 一次完整 generate 請求對應一個 job_id；Week 1 由 Tracker 建構時帶入
    job_id: Optional[str] = None
    # 多 asset 場景下 stage 事件需區分屬於哪個 asset；Pipeline 級別事件可空
    asset_id: Optional[str] = None
    # Stage 名稱（例如 "decode_image" / "semantic_image"）；非 stage 事件可空
    stage_name: Optional[str] = None
    # 事件發生時刻（unix 秒，預設取建立時當下）
    timestamp: float = Field(default_factory=time.time)
    # STAGE_FINISH / PIPELINE_FINISH 帶入該階段耗時（毫秒）
    duration_ms: Optional[float] = None
    # 任意額外資訊（例如 model 名稱、batch 大小、score 等）
    payload: dict[str, Any] = Field(default_factory=dict)
    # STAGE_ERROR 帶入錯誤訊息（保留 raw 字串，前端決定如何顯示）
    error: Optional[str] = None


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


class ProgressTracker:
    """
    廣播中樞 (Subject in Observer Pattern)。

    執行緒安全：訂閱 / 取消訂閱與廣播全程持有 ``_lock``；
    廣播時對每個 Observer ``try/except``，任一失敗都不影響其他 Observer 與主流水線。

    用法（Week 2a 之後 Pipeline 內部）::

        tracker = ProgressTracker(job_id="abc-123")
        tracker.subscribe(PrintProgressObserver())
        tracker.emit_stage_start(asset_id="img1", stage_name="decode")
        # ... do work ...
        tracker.emit_stage_finish(asset_id="img1", stage_name="decode", duration_ms=42.5)
    """

    def __init__(self, job_id: Optional[str] = None):
        """初始化空 Observer 列表並繫結 job_id。"""
        self._job_id = job_id
        self._observers: list[ProgressObserver] = []
        # 訂閱 / 廣播共用同一把鎖，避免廣播途中 observer 列表變動
        self._lock = threading.Lock()

    # ── 訂閱管理 ─────────────────────────────────────────────────────────────
    def subscribe(self, observer: ProgressObserver) -> None:
        """訂閱事件流；重複訂閱會視為兩個獨立通道，由呼叫端負責去重。"""
        with self._lock:
            self._observers.append(observer)

    def unsubscribe(self, observer: ProgressObserver) -> None:
        """取消訂閱；若不在列表中靜默忽略，符合 Observer Pattern 慣例。"""
        with self._lock:
            try:
                self._observers.remove(observer)
            except ValueError:
                # 不在列表中視為已取消訂閱，靜默 swallow 即可
                pass

    # ── 核心廣播 ─────────────────────────────────────────────────────────────
    def publish(self, event: ProgressEvent) -> None:
        """
        廣播事件給所有 Observer。

        對每個 Observer 個別 ``try/except``，
        任一 Observer 失敗只印 warning，不阻斷其他 Observer 也不阻斷主流水線。
        """
        # 在鎖內 snapshot 一份 observer 列表，立即釋鎖以縮短臨界區
        with self._lock:
            snapshot = list(self._observers)

        for observer in snapshot:
            try:
                observer.on_event(event)
            except Exception as exc:
                # Observer 失敗隔離：印 warning 但繼續通知其他 Observer
                print(
                    f"[ProgressTracker Warning] observer={observer.__class__.__name__} "
                    f"raised {exc.__class__.__name__}: {exc}"
                )

    # ── 便利方法（語法糖，封裝常見事件型態的建構） ──────────────────────────
    def emit_stage_start(
        self,
        asset_id: Optional[str],
        stage_name: str,
        payload: Optional[dict] = None,
    ) -> None:
        """送出 STAGE_START 事件。"""
        self.publish(ProgressEvent(
            event_type=ProgressEventType.STAGE_START,
            job_id=self._job_id,
            asset_id=asset_id,
            stage_name=stage_name,
            payload=payload or {},
        ))

    def emit_stage_finish(
        self,
        asset_id: Optional[str],
        stage_name: str,
        duration_ms: float,
        payload: Optional[dict] = None,
    ) -> None:
        """送出 STAGE_FINISH 事件，必填耗時毫秒。"""
        self.publish(ProgressEvent(
            event_type=ProgressEventType.STAGE_FINISH,
            job_id=self._job_id,
            asset_id=asset_id,
            stage_name=stage_name,
            duration_ms=duration_ms,
            payload=payload or {},
        ))

    def emit_stage_error(
        self,
        asset_id: Optional[str],
        stage_name: str,
        error: str,
        payload: Optional[dict] = None,
    ) -> None:
        """送出 STAGE_ERROR 事件。"""
        self.publish(ProgressEvent(
            event_type=ProgressEventType.STAGE_ERROR,
            job_id=self._job_id,
            asset_id=asset_id,
            stage_name=stage_name,
            error=error,
            payload=payload or {},
        ))

    def emit_pipeline_start(
        self,
        asset_id: Optional[str],
        payload: Optional[dict] = None,
    ) -> None:
        """送出 PIPELINE_START 事件;帶 asset_id 以便觀察各 asset 流水線的起點(並行驗證)。"""
        self.publish(ProgressEvent(
            event_type=ProgressEventType.PIPELINE_START,
            job_id=self._job_id,
            asset_id=asset_id,
            payload=payload or {},
        ))

    def emit_pipeline_finish(
        self,
        asset_id: Optional[str],
        duration_ms: Optional[float] = None,
        payload: Optional[dict] = None,
    ) -> None:
        """送出 PIPELINE_FINISH 事件,帶該 asset 整條流水線耗時。"""
        self.publish(ProgressEvent(
            event_type=ProgressEventType.PIPELINE_FINISH,
            job_id=self._job_id,
            asset_id=asset_id,
            duration_ms=duration_ms,
            payload=payload or {},
        ))
