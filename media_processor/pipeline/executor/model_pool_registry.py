"""
ModelPoolRegistry:集中管理各模型的 ModelPool (Registry + Singleton Pattern)。

職責 (Week 3b 起正式啟用)
-------------------------
- 啟動時用 :class:`GpuCapacityManager` 掃描 free VRAM,決定每個模型鋪在哪些 ``(device, slot)``、
  每卡 BudgetGate 預算,並 eager 預載熱門模型(Qwen 等)。
- ``get_pool(model_class)`` 延遲建立並快取「依 capacity 規劃槽位」的 :class:`ModelPool`,
  多個 asset / batch worker 共享同一份模型,不會每 asset 載一份。
- **process 級共享單例**(:meth:`instance`):stage 與 batch_fn 不必穿參數即可取得同一個 registry
  (對齊 ``BatchCollectorRegistry`` 的 class-level 單例做法),由 ``PipelineRunner`` 建構時自動註冊。

Week 3b 之前
------------
Week 2a–3a 期間本 Registry 建好但 stage 仍直接用 device-0 singleton;Week 3b 起 semantic stage 與
GPU batch_fn 改走 ``ModelPoolRegistry.instance().get_pool(...).borrow()``,真正分散到多卡。
"""
from __future__ import annotations

import threading
from typing import Callable, Optional, TypeVar

from config.media_processor_config import GPU_SAFETY_BUFFER_GB
from config.pipeline_config import GPU_POOL_ENABLED
from media_processor.pipeline.executor.gpu_detect import detect_gpu_ids
from media_processor.pipeline.progress import ProgressObserver, ProgressTracker
from model.base_model_manager import BaseModelManager
from model.gpu_capacity_manager import GpuCapacityManager
from model.model_pool import ModelPool, PoolBorrowObserver

# borrow_for_batch 的 Manager / 回傳型別提示
_M = TypeVar("_M", bound=BaseModelManager)
_R = TypeVar("_R")

# 無 GPU 時 ModelPool 仍需至少一個 slot;device 0 經 get_device_str 會對應到 'cpu'
_CPU_FALLBACK_DEVICE_ID = 0
# 啟動期(warm up / 跨 asset batch borrow)事件用的 job_id,與單次 generate 的 job_id 區隔
_STARTUP_JOB_ID = "startup"


class _TrackerBorrowObserver:
    """
    把 :class:`PoolBorrowObserver` 的 wait / ready 轉成 ProgressEvent (Adapter Pattern)。

    讓 model 層的 ``ModelPool.borrow`` 完全不依賴 pipeline 的 ProgressTracker:
    pipeline 側注入本 adapter,model 層只認 ``PoolBorrowObserver`` Protocol。
    """

    def __init__(
        self,
        tracker: ProgressTracker,
        asset_id: Optional[str],
        stage_name: Optional[str],
    ):
        """綁定要廣播到的 tracker 與事件歸屬(asset / stage;跨 asset 的 batch 借出可為 None)。"""
        self._tracker = tracker
        self._asset_id = asset_id
        self._stage_name = stage_name

    def on_vram_wait(self, device_id: int, slot_id: int, free_gb: float, need_gb: float) -> None:
        """borrow 因即時 free VRAM 不足開始等待 → RESOURCE_WAIT。"""
        self._tracker.emit_resource_wait(
            asset_id=self._asset_id,
            stage_name=self._stage_name,
            payload={
                "device": f"cuda:{device_id}",
                "slot_id": slot_id,
                "free_gb": round(free_gb, 2),
                "need_gb": round(need_gb, 2),
            },
        )

    def on_vram_ready(self, device_id: int, slot_id: int, free_gb: float) -> None:
        """等待後 VRAM 騰出(或逾時放行)、即將借出 → RESOURCE_ACQUIRED。"""
        self._tracker.emit_resource_acquired(
            asset_id=self._asset_id,
            stage_name=self._stage_name,
            payload={
                "device": f"cuda:{device_id}",
                "slot_id": slot_id,
                "free_gb": round(free_gb, 2),
            },
        )


class ModelPoolRegistry:
    """
    每個模型類別一個 ModelPool 的集中管理器(執行緒安全、延遲建立、process 級共享)。
    """

    # process 級共享實例:stage / batch_fn 經 instance() 取用,由 PipelineRunner 建構時設定
    _shared: Optional["ModelPoolRegistry"] = None
    _shared_lock = threading.Lock()

    def __init__(
        self,
        gpu_ids: Optional[list[int]] = None,
        capacity_manager: Optional[GpuCapacityManager] = None,
        observers: Optional[list[ProgressObserver]] = None,
    ):
        """
        以 GpuCapacityManager 規劃模型放置與每卡預算,並把自己註冊為 process 級共享實例。

        Args:
            gpu_ids: 明示裝置列表(主要供測試);``None`` 時自動偵測,無 GPU 則退回 ``[0]``(cpu)。
            capacity_manager: 容量規劃器;``None`` 時以「真正偵測到的 GPU」自動建立。
            observers: 啟動期(warm up / 跨 asset batch borrow)事件要廣播到的 Observer。
        """
        detected = detect_gpu_ids()
        # _gpu_ids 含 CPU 後備(供 log);capacity 用「真實偵測」(空=無 CUDA → apply no-op)
        self._gpu_ids = list(gpu_ids) if gpu_ids is not None else (detected or [_CPU_FALLBACK_DEVICE_ID])
        self._capacity = capacity_manager or GpuCapacityManager(gpu_ids=detected)
        self._pools: dict[type, ModelPool] = {}
        # 延遲建立 Pool 時的互斥鎖,避免多 driver 同時建同一個 Pool
        self._lock = threading.Lock()
        # 啟動期事件 tracker(warm up + 無 asset 歸屬的 batch borrow 等待)
        self._startup_tracker = ProgressTracker(job_id=_STARTUP_JOB_ID)
        for observer in (observers or []):
            self._startup_tracker.subscribe(observer)

        print(f"[ModelPoolRegistry] 偵測到模型可用裝置: {self._device_strs()}")
        print(f"[ModelPoolRegistry] {self._capacity.describe()}")

        # 註冊為 process 級共享實例(最後建立者勝出;單一 PipelineRunner 場景即唯一)
        ModelPoolRegistry._shared = self

    # ── process 級共享存取 ─────────────────────────────────────────────────────
    @classmethod
    def instance(cls) -> "ModelPoolRegistry":
        """
        取得 process 級共享 registry;尚未建立時 lazy 建一個預設的(自動偵測 GPU)。

        讓 stage / batch_fn 在沒有 PipelineRunner 的測試 / CLI 場景也能借到模型。
        """
        if cls._shared is not None:
            return cls._shared
        with cls._shared_lock:
            if cls._shared is None:
                # 建構子會把自己設為 _shared
                cls()
        return cls._shared

    # ── Pool 取得 / 容量套用 / warm up ────────────────────────────────────────
    def get_pool(self, model_class: type[BaseModelManager]) -> ModelPool:
        """
        取得(或延遲建立並快取)指定模型類別的 ModelPool。

        Pool 槽位由 :class:`GpuCapacityManager` 規劃(Qwen 多卡、其餘最寬鬆卡單份);
        並帶入該模型的 forward 暫態成本作為 borrow 即時 VRAM 重檢門檻。
        """
        pool = self._pools.get(model_class)
        if pool is not None:
            return pool

        with self._lock:
            pool = self._pools.get(model_class)
            if pool is None:
                slots = self._capacity.plan_slots(model_class)
                pool = ModelPool(
                    model_class,
                    slots=slots,
                    vram_need_gb=self._capacity.transient_gb(model_class),
                    safety_buffer_gb=GPU_SAFETY_BUFFER_GB,
                )
                self._pools[model_class] = pool
                placement = [f"cuda:{s.device_id}#{s.slot_id}" for s in slots]
                print(f"[ModelPoolRegistry] 建立 {model_class.__name__} pool → slots={placement}")
            return pool

    def apply_capacity_policy(self) -> None:
        """套用 capacity 規劃的 per-device BudgetGate(委派 GpuCapacityManager.apply,無 CUDA 時 no-op)。"""
        self._capacity.apply()

    def warm_up(self) -> None:
        """
        依 capacity 規劃的優先序預載 eager 模型(觸發各槽位 singleton 載入),逐一發 MODEL_WARMUP。

        無 CUDA 時 ``eager_models()`` 為空 → no-op(維持 lazy,開發 / CPU 環境啟動快)。
        """
        eager = self._capacity.eager_models()
        if not eager:
            print("[ModelPoolRegistry] 無 eager 模型可預載(無 CUDA 或 VRAM 不足),維持 lazy 載入")
            return
        for model_class in eager:
            slots = self._capacity.plan_slots(model_class)
            device = ",".join(f"cuda:{s.device_id}" for s in slots)
            name = model_class.__name__
            self._startup_tracker.emit_model_warmup(name, device, payload={"status": "loading"})
            # 建立 pool 即觸發各槽位 Manager singleton 的 _initialize(載入權重)
            self.get_pool(model_class)
            self._startup_tracker.emit_model_warmup(name, device, payload={"status": "ready"})

    def startup_borrow_observer(self, stage_name: Optional[str] = None) -> PoolBorrowObserver:
        """
        回傳綁定啟動期 tracker 的 borrow 觀察者(給跨 asset 的 batch_fn 借出用,無 asset 歸屬)。
        """
        return _TrackerBorrowObserver(self._startup_tracker, asset_id=None, stage_name=stage_name)

    @staticmethod
    def make_borrow_observer(
        tracker: Optional[ProgressTracker],
        asset_id: Optional[str],
        stage_name: Optional[str],
    ) -> Optional[PoolBorrowObserver]:
        """
        由 per-asset 的 tracker 組 borrow 觀察者(給 semantic stage 用);tracker 為 None 時回 None。
        """
        if tracker is None:
            return None
        return _TrackerBorrowObserver(tracker, asset_id=asset_id, stage_name=stage_name)

    # ── 屬性 / 工具 ───────────────────────────────────────────────────────────
    @property
    def capacity(self) -> GpuCapacityManager:
        """底層容量規劃器(供 Runner / 測試觀察規劃結果)。"""
        return self._capacity

    @property
    def gpu_ids(self) -> list[int]:
        """Pool 鋪設的裝置 id 列表(含 CPU 後備)。"""
        return list(self._gpu_ids)

    def _device_strs(self) -> list[str]:
        """把 device id 轉成可讀裝置字串(例如 ['cuda:0', 'cuda:1'] 或 ['cpu'])。"""
        return [BaseModelManager.get_device_str(i) for i in self._gpu_ids]


def borrow_for_batch(
    model_class: type[_M],
    stage_name: str,
    fn: Callable[[_M], _R],
) -> _R:
    """
    供 GPU batch_fn 使用:依 ``GPU_POOL_ENABLED`` 走多卡 pool 借出或 device-0 singleton (Week 3b)。

    batch_fn 在 ``BatchCollector`` 的 worker thread 上跨多 asset 執行、無單一 asset 歸屬,
    故 borrow 即時 VRAM 等待事件走 registry 啟動期 tracker(asset_id=None)。
    ``GPU_POOL_ENABLED=false`` 時直接用 ``model_class()`` device-0 singleton(Week 3a 行為)。
    """
    if not GPU_POOL_ENABLED:
        return fn(model_class())
    registry = ModelPoolRegistry.instance()
    observer = registry.startup_borrow_observer(stage_name)
    # run_with_failover:多卡 pool 在某卡持續 OOM 時自動換卡;單卡 pool 退化為單次借出(無回歸)
    return registry.get_pool(model_class).run_with_failover(fn, observer=observer)
