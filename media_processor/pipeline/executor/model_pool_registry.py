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
from contextlib import contextmanager
from dataclasses import dataclass
from queue import Queue
from typing import Callable, Iterator, Optional, TypeVar

from config.media_processor_config import GPU_SAFETY_BUFFER_GB
from config.pipeline_config import (
    GPU_POOL_ENABLED,
    MEDIAPIPE_POOL_SIZE,
    SALIENCY_POOL_SIZE,
    VAD_POOL_SIZE,
)
from media_processor.pipeline.executor.gpu_detect import detect_gpu_ids
from media_processor.pipeline.progress import ProgressObserver, ProgressTracker
from model.base_model_manager import BaseModelManager
from model.gpu_capacity_manager import GpuCapacityManager
from model.model_pool import ModelPool, PoolBorrowObserver
from model.resource_wait_clock import ResourceWaitClock

# borrow_for_batch 的 Manager / 回傳型別提示
_M = TypeVar("_M", bound=BaseModelManager)
_R = TypeVar("_R")

# ── MediaPipe pool（模組級，CPU；真平行）──────────────────────────────────────────
# 與 saliency pool 同構：放「MEDIAPIPE_POOL_SIZE 個 *不同 slot_id* 的 instance」，每個是獨立的
# FaceDetector singleton、各有自己的 L3 _inference_lock，借出後才能真正多路 CPU 併發
# （MediaPipe Tasks 的 detect() 在 C++ graph 內執行會釋放 GIL，與 saliency 的 onnxruntime
# CPU EP 同理）。borrow_mediapipe() 從此借出。
# ⚠️ 不可改回 N 個無參數 MediaPipeModelManager()：那會全部命中同一 (0,0) singleton、共用單一
#    L3 lock，被 @synchronized_inference 序列化 → pool 形同虛設、退回單路。
_mediapipe_pool: Queue = Queue()
_mediapipe_pool_initialized = False
_mediapipe_pool_init_lock = threading.Lock()

# ── Saliency pool（模組級，CPU；Option 3）─────────────────────────────────────────
# U²-Net 已移出 GPU capacity、改純 CPU（見 model.saliency_model_manager），由此獨立 pool 管併發。
# 與 mediapipe pool 同構：放「SALIENCY_POOL_SIZE 個 *不同 slot_id* 的 instance」，每個有獨立的
# onnxruntime CPU session 與 L3 _inference_lock，才能真正多路 CPU 併發（saliency CPU 推論較重，
# 需要真平行）。run_saliency() 從此借出。
_saliency_pool: Queue = Queue()
_saliency_pool_initialized = False
_saliency_pool_init_lock = threading.Lock()

# ── VAD pool（模組級，CPU；真平行）─────────────────────────────────────────────
# 與 mediapipe / saliency pool 同構：放「VAD_POOL_SIZE 個 *不同 slot_id* 的 Silero instance」，
# 每個有獨立的 model 與 L3 _inference_lock，借出後多支影片的 VAD 才能真正多路 CPU 併發
# （read_audio 解碼與 Silero 推論皆釋放 GIL）。run_vad() 從此借出。
# ⚠️ 不可改回單一 VadModelManager()：那會全部命中同一 (0,0) singleton、共用單一 L3 lock，
#    被 @synchronized_inference 序列化 → 多影片 VAD 排隊（log 裡卡到 250s+）。
_vad_pool: Queue = Queue()
_vad_pool_initialized = False
_vad_pool_init_lock = threading.Lock()

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


@dataclass(frozen=True)
class AuxPoolRow:
    """
    未納入 GPU capacity 規劃的本地 CPU 模型佈局列(VAD / MediaPipe / Saliency),供 StartupReporter 顯示。

    這些模型不佔 GPU 預算、不在 ``GpuCapacityManager.placement_rows()`` 內,故需獨立一份描述。
    ``instances`` 為常駐 instance 份數(非 VRAM GB);``status`` 預設 ``eager``(三者皆於
    ``_warm_up_auxiliary`` 啟動期預熱)。
    """

    name: str
    instances: int
    placement: str
    status: str = "eager"


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
        預載 capacity 規劃的 eager pool 模型(Qwen / Saliency 多卡、其餘小模型),並一併預載未走 pool 的
        本地 CPU singleton(VAD / MediaPipe),逐一發 MODEL_WARMUP。

        pool 模型無 CUDA 時為空 → 跳過;aux(CPU)模型則不論有無 CUDA 都預載。Gemini 不預載(見 _warm_up_auxiliary)。
        """
        eager = self._capacity.eager_models()
        if eager:
            for model_class in eager:
                slots = self._capacity.plan_slots(model_class)
                device = ",".join(f"cuda:{s.device_id}#{s.slot_id}" for s in slots)
                name = model_class.__name__
                self._startup_tracker.emit_model_warmup(name, device, payload={"status": "loading"})
                # 建立 pool 即觸發各槽位 Manager singleton 的 _initialize(載入權重)
                pool = self.get_pool(model_class)
                # 啟動單執行緒預熱各 instance 的首呼叫 lazy import / 原生 dlopen（多數模型 no-op；
                # AudioEnv 等延遲載原生解碼後端者藉此避免執行期撞動態連結器鎖死結）
                pool.warmup_all()
                self._startup_tracker.emit_model_warmup(name, device, payload={"status": "ready"})
        else:
            print("[ModelPoolRegistry] 無 eager pool 模型(無 CUDA 或 VRAM 不足),pool 模型維持 lazy")
        # 不論 pool 模型有無,都預載「沒走 capacity/pool」的本地 CPU singleton(VAD / MediaPipe)
        self._warm_up_auxiliary()

    def aux_pool_rows(self) -> list[AuxPoolRow]:
        """
        回傳未納入 GPU capacity 的本地 CPU 模型(VAD / MediaPipe / Saliency)佈局列,供 StartupReporter 顯示。

        份數取自 config 常數(單一資料來源、無 magic number);三者皆於 _warm_up_auxiliary 啟動期 eager 預熱,
        故 status 統一為 AuxPoolRow 預設的 ``eager``(個別載入失敗的降級已由 _warm_up_auxiliary 另行 log)。
        """
        return [
            AuxPoolRow(
                name="VadModelManager",
                instances=VAD_POOL_SIZE,
                placement=f"cpu×{VAD_POOL_SIZE}",
            ),
            AuxPoolRow(
                name="MediaPipeModelManager",
                instances=MEDIAPIPE_POOL_SIZE,
                placement=f"cpu×{MEDIAPIPE_POOL_SIZE}",
            ),
            AuxPoolRow(
                name="SaliencyModelManager",
                instances=SALIENCY_POOL_SIZE,
                placement=f"cpu×{SALIENCY_POOL_SIZE}",
            ),
        ]

    def _warm_up_auxiliary(self) -> None:
        """
        預載未納入 GPU capacity 的本地 CPU pool：VAD(Silero) / MediaPipe / Saliency，三者皆為獨立 CPU pool。

        三池同構（各放 N 個「不同 slot_id」instance、各有獨立 L3 lock → 借出後真平行），故用統一的
        ``_warm_up_cpu_pool`` 預熱（DRY，取代原本三段近乎相同的樣板）。每池 warmup 失敗只降級 lazy、
        不中斷其餘（stage 首次用到會 lazy 再試）。VAD 改 pool 後，其 torchcodec 預載改在
        ``_warm_up_vad_pool`` 內逐 instance 觸發（仍是單執行緒、避免執行期並發 dlopen 死結）。
        Gemini **刻意不預載**：雲端 API client、無本地權重，且未設金鑰時 ``_initialize`` 會 raise。
        """
        self._warm_up_cpu_pool("VadModelManager", VAD_POOL_SIZE, _warm_up_vad_pool)
        self._warm_up_cpu_pool("MediaPipeModelManager", MEDIAPIPE_POOL_SIZE, _warm_up_mediapipe_pool)
        self._warm_up_cpu_pool("SaliencyModelManager", SALIENCY_POOL_SIZE, _warm_up_saliency_pool)

    def _warm_up_cpu_pool(self, name: str, size: int, warm_fn: Callable[[], None]) -> None:
        """
        通用 CPU pool 預熱：發 loading→ready 事件;整池失敗則降級 lazy(個別 instance 的容錯在 warm_fn 內)。

        三個 aux CPU pool(VAD / MediaPipe / Saliency)共用本入口,消除原本三段幾乎相同的樣板。
        """
        label = f"cpu×{size}"
        self._startup_tracker.emit_model_warmup(name, label, payload={"status": "loading"})
        try:
            warm_fn()
            self._startup_tracker.emit_model_warmup(name, label, payload={"status": "ready"})
        except Exception as exc:
            print(f"[ModelPoolRegistry] {name} pool warmup 失敗({exc});改為 lazy 載入")
            self._startup_tracker.emit_model_warmup(name, "cpu×1", payload={"status": "lazy_fallback"})

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


def _warm_up_mediapipe_pool() -> None:
    """
    warmup 時建立 MEDIAPIPE_POOL_SIZE 個「不同 slot_id」的 MediaPipeModelManager instance 放進 pool。

    與 _warm_up_saliency_pool 同構：用不同 slot_id（(0,0)、(0,1)…）取得彼此獨立的 singleton，
    每個各有自己的 FaceDetector 與 L3 _inference_lock → 借出後可真正多路 CPU 併發（不像共用單一
    (0,0) instance 會被 @synchronized_inference 的 L3 lock 序列化成單路）。
    pool 預熱後 _mediapipe_pool_initialized 置 True，borrow_mediapipe 不再 lazy 初始化。
    """
    global _mediapipe_pool_initialized
    from model.mediapipe_model_manager import MediaPipeModelManager
    for slot_id in range(MEDIAPIPE_POOL_SIZE):
        _mediapipe_pool.put(MediaPipeModelManager(slot_id=slot_id))
    _mediapipe_pool_initialized = True


@contextmanager
def borrow_mediapipe() -> Iterator:
    """
    借用一個 MediaPipe FaceDetector instance（blocking queue），用完自動歸還。

    與 run_saliency 同構：pool 未預熱時（warmup 失敗 / 未呼叫）以雙重檢查鎖 lazy 建滿整池
    （_warm_up_mediapipe_pool，含不同 slot_id），確保 lazy 路徑同樣具備真平行、且避免永久阻塞。
    """
    global _mediapipe_pool_initialized
    # pool 未預熱（warmup 失敗或未呼叫）→ 雙重檢查鎖 lazy 建滿整池（不同 slot_id → 真平行）
    if not _mediapipe_pool_initialized:
        with _mediapipe_pool_init_lock:
            if not _mediapipe_pool_initialized:
                _warm_up_mediapipe_pool()
    # 借 instance 的阻塞（pool 全借出時）計入本 thread 的「等資源」累加，供 stage 拆分 compute/wait
    with ResourceWaitClock.measure():
        mgr = _mediapipe_pool.get()
    try:
        yield mgr
    finally:
        # finally 確保異常路徑也歸還 instance，避免 pool 被慢慢耗盡
        _mediapipe_pool.put(mgr)


def _warm_up_saliency_pool() -> None:
    """
    warmup 時建立 SALIENCY_POOL_SIZE 個「不同 slot_id」的 SaliencyModelManager instance 放進 pool。

    用不同 slot_id（(0,0)、(0,1)…）取得彼此獨立的 singleton，使每個 instance 各有自己的
    L3 _inference_lock → 借出後可真正多路 CPU 併發（不像共用單一 instance 會被 L3 序列化）。
    pool 預熱後 _saliency_pool_initialized 置 True，run_saliency 不再 lazy 初始化。
    """
    global _saliency_pool_initialized
    from model.saliency_model_manager import SaliencyModelManager
    for slot_id in range(SALIENCY_POOL_SIZE):
        _saliency_pool.put(SaliencyModelManager(slot_id=slot_id))
    _saliency_pool_initialized = True


def run_saliency(fn: Callable[[_M], _R]) -> _R:
    """
    供 saliency stage 使用：從 CPU pool 借一個 ``SaliencyModelManager`` 執行 ``fn``，用完自動歸還。

    Option 3 起 saliency 為純 CPU 模型（見 model.saliency_model_manager），不再走 GPU capacity
    pool / 跨卡 OOM failover —— CPU 不會 CUDA OOM、也無卡可換。pool 未預熱（warmup 失敗 / 未呼叫）
    時以雙重檢查鎖 lazy 建滿整池，避免永久阻塞。
    """
    global _saliency_pool_initialized
    if not _saliency_pool_initialized:
        with _saliency_pool_init_lock:
            if not _saliency_pool_initialized:
                _warm_up_saliency_pool()
    # 借 instance 的阻塞（pool 全借出時）計入本 thread 的「等資源」累加，供 stage 拆分 compute/wait
    with ResourceWaitClock.measure():
        saliency = _saliency_pool.get()
    try:
        return fn(saliency)
    finally:
        # finally 確保異常路徑也歸還 instance，避免 pool 被慢慢耗盡
        _saliency_pool.put(saliency)


def _warm_up_vad_pool() -> None:
    """
    warmup 時建立 VAD_POOL_SIZE 個「不同 slot_id」的 VadModelManager instance 放進 pool。

    與 _warm_up_saliency_pool 同構:用不同 slot_id 取得彼此獨立的 Silero singleton,各有自己的
    L3 _inference_lock → 借出後多支影片的 VAD 可真正多路併發。另對每個 instance 呼叫 ``warmup()``
    單執行緒預載 torchcodec(read_audio 首呼叫的 dlopen),避免執行期多 thread 首呼叫撞動態連結器鎖死結。
    pool 預熱後 _vad_pool_initialized 置 True,run_vad 不再 lazy 初始化。
    """
    global _vad_pool_initialized
    from model.vad_model_manager import VadModelManager
    for slot_id in range(VAD_POOL_SIZE):
        mgr = VadModelManager(slot_id=slot_id)
        # warmup 為 best-effort（內部吞例外）：預載 torchcodec，杜絕執行期並發 dlopen 死結
        mgr.warmup()
        _vad_pool.put(mgr)
    _vad_pool_initialized = True


def run_vad(fn: Callable[[_M], _R]) -> _R:
    """
    供 VAD stage 使用:從 CPU pool 借一個 ``VadModelManager`` 執行 ``fn``,用完自動歸還。

    VAD 為純 CPU 單張模型,不走 GPU gate / 跨卡 failover。pool 未預熱(warmup 失敗 / 未呼叫)時以
    雙重檢查鎖 lazy 建滿整池,避免永久阻塞。借出阻塞計入 ResourceWaitClock(供 stage 拆分 compute/wait)。
    """
    global _vad_pool_initialized
    if not _vad_pool_initialized:
        with _vad_pool_init_lock:
            if not _vad_pool_initialized:
                _warm_up_vad_pool()
    # 借 instance 的阻塞（pool 全借出時）計入本 thread 的「等資源」累加
    with ResourceWaitClock.measure():
        vad = _vad_pool.get()
    try:
        return fn(vad)
    finally:
        # finally 確保異常路徑也歸還 instance，避免 pool 被慢慢耗盡
        _vad_pool.put(vad)
