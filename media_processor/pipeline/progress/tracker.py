"""
進度廣播中樞：Subject 側 (Observer Pattern)。

``ProgressTracker`` 持有 observer 清單並廣播事件，
與「事件定義（``events``）」「觀察者實作（``observer``）」分離：
新增 observer 不動本檔，調整事件結構也不動本檔。
"""
import threading
from typing import Optional

from media_processor.pipeline.progress.events import ProgressEvent, ProgressEventType
from media_processor.pipeline.progress.observer import ProgressObserver


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

    # ── Week 3b：啟動期 warm up 與借出 VRAM 等待事件 ──────────────────────────
    def emit_model_warmup(
        self,
        model_name: str,
        device: str,
        payload: Optional[dict] = None,
    ) -> None:
        """送出 MODEL_WARMUP 事件（Eager Warm Up 預載熱門模型；stage_name 借用為模型名）。"""
        self.publish(ProgressEvent(
            event_type=ProgressEventType.MODEL_WARMUP,
            job_id=self._job_id,
            stage_name=model_name,
            payload={**(payload or {}), "device": device},
        ))

    def emit_resource_wait(
        self,
        asset_id: Optional[str],
        stage_name: Optional[str],
        payload: Optional[dict] = None,
    ) -> None:
        """送出 RESOURCE_WAIT 事件（borrow 因即時 free VRAM 不足而等待）。"""
        self.publish(ProgressEvent(
            event_type=ProgressEventType.RESOURCE_WAIT,
            job_id=self._job_id,
            asset_id=asset_id,
            stage_name=stage_name,
            payload=payload or {},
        ))

    def emit_resource_acquired(
        self,
        asset_id: Optional[str],
        stage_name: Optional[str],
        payload: Optional[dict] = None,
    ) -> None:
        """送出 RESOURCE_ACQUIRED 事件（等待後 VRAM 騰出、即將借出）。"""
        self.publish(ProgressEvent(
            event_type=ProgressEventType.RESOURCE_ACQUIRED,
            job_id=self._job_id,
            asset_id=asset_id,
            stage_name=stage_name,
            payload=payload or {},
        ))
