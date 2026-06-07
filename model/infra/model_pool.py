"""
ModelPool：多 GPU / 多槽位的 Object Pool，搭配 BaseModelManager 實現執行緒安全推論。

設計模式
--------
- **Object Pool Pattern**：以固定數量的 Manager instance 服務 N 條 driver thread。
- **Value Object (dataclass)**：``GpuSlot`` 描述「在哪張 GPU 的哪個槽位」。
- **Context Manager**：``borrow()`` 自動歸還，免手動 release，異常時也不漏。

slot 概念
----------
- 預設 ``gpu_ids=[0, 1]`` 等價於 ``slots=[GpuSlot(0), GpuSlot(1)]``，每張 GPU 一份 instance。
- 顯式指定 ``slots=[GpuSlot(0, 0), GpuSlot(0, 1)]`` 可在**同卡載入兩份 weight**，
  搭配 ``BudgetGate`` 達成同卡併發紅利（需 VRAM 充裕）。
- ``GpuCapacityManager`` 會依該卡 free VRAM **自動決定 Qwen 同卡份數**
  （config ``QWEN_MAX_SLOTS_PER_GPU``：``0`` 自動 / ``>0`` 上限），呼叫端通常不必手填 slots。
- 注意：``BinaryGate`` 下同卡多 instance 仍被 L2 序列化，需 ``BudgetGate``（預設）才有同卡併發效果。

典型用法
--------
::

    pool = ModelPool(QwenModelManager, gpu_ids=[0, 1])  # 雙卡，向後相容寫法

    def worker(media_path):
        with pool.borrow() as model:
            return model.analyze_media(media_path)

    with ThreadPoolExecutor(max_workers=4) as exe:
        results = list(exe.map(worker, media_list))
"""
import queue
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Generic, Iterator, Optional, Protocol, TypeVar

from config.media_processor_config import (
    BORROW_VRAM_POLL_INTERVAL_SEC,
    BORROW_VRAM_MAX_WAIT_SEC,
    GPU_SAFETY_BUFFER_GB,
)
from model.infra.base_model_manager import BaseModelManager, is_cuda_oom
from model.infra.resource_wait_clock import ResourceWaitClock

T = TypeVar("T", bound=BaseModelManager)

# 預設槽位 id：當 gpu_ids 介面被使用時，所有 GPU 隱式分配此槽位
_DEFAULT_SLOT_ID = 0
# bytes → GB 換算（mem_get_info 回 bytes）
_BYTES_PER_GB = 1024 ** 3


class PoolBorrowObserver(Protocol):
    """
    borrow() 即時 VRAM 重檢的觀察者 (Protocol；定義在 model 層，不依賴 pipeline)。

    pipeline 側提供 adapter 實作，把 wait / ready 轉成 ProgressEvent 推給前端。
    以原生型別傳參（非 pipeline 物件），維持 model → pipeline 的零依賴。
    """

    def on_vram_wait(self, device_id: int, slot_id: int, free_gb: float, need_gb: float) -> None:
        """因即時 free VRAM 不足而開始等待時呼叫一次。"""
        ...

    def on_vram_ready(self, device_id: int, slot_id: int, free_gb: float) -> None:
        """等待後 VRAM 騰出（或逾時放行）、即將借出時呼叫一次。"""
        ...


@dataclass(frozen=True)
class GpuSlot:
    """
    指定某張 GPU 的某個槽位（Value Object）。

    ``device_id`` 為 CUDA device id；
    ``slot_id`` 區分同卡上的多份獨立 instance，預設 0 對應傳統「一卡一 instance」。
    frozen 確保可作為 dict key 與 set 元素。
    """
    device_id: int
    slot_id: int = _DEFAULT_SLOT_ID


class ModelPool(Generic[T]):
    """
    管理跨多 GPU / 多槽位的 Manager 實例池。

    每個 ``GpuSlot`` 對應一個 Manager singleton instance，
    透過 ``queue.Queue`` 達成執行緒安全的借還機制。
    """

    def __init__(
        self,
        model_class: type[T],
        slots: list[GpuSlot] | None = None,
        gpu_ids: list[int] | None = None,
        vram_need_gb: float = 0.0,
        safety_buffer_gb: float = GPU_SAFETY_BUFFER_GB,
        poll_interval_sec: float = BORROW_VRAM_POLL_INTERVAL_SEC,
        max_wait_sec: float = BORROW_VRAM_MAX_WAIT_SEC,
        free_scan: Optional[Callable[[int], float]] = None,
    ):
        """
        初始化並在指定槽位上建立（或取得已快取的）Manager 實例。

        Args:
            model_class: 繼承 ``BaseModelManager`` 的 Manager 類別
            slots:       明示槽位列表，可表達同卡多槽位
            gpu_ids:     向後相容介面，自動轉成 ``[GpuSlot(g, 0) for g in gpu_ids]``
            vram_need_gb: 借出前即時 VRAM 重檢所需的「單次 forward 暫態」VRAM（GB）；
                         ``0`` 表示停用重檢（CPU/內部管理模型或未知成本）。
            safety_buffer_gb: 重檢時額外要求空出的安全緩衝（與 BudgetGate 同義）。
            poll_interval_sec / max_wait_sec: 重檢輪詢間隔與等待上限（逾時盡力放行，OOM 由重試兜底）。
            free_scan: ``device_id → free_gb`` 掃描函式（可注入假值供測試）；``None`` 用真 mem_get_info。

        ``slots`` 與 ``gpu_ids`` 必須擇一提供，且不可同時提供以避免歧義。
        """
        normalized_slots = self._normalize_slots(slots, gpu_ids)

        # 為每個槽位建立 Manager singleton（同 key 已存在則回傳既有實例）
        self._instances: list[T] = [
            model_class(device_id=slot.device_id, slot_id=slot.slot_id)
            for slot in normalized_slots
        ]
        # Queue 內容為 instance index，借出時取走、歸還時放回
        self._available: queue.Queue[int] = queue.Queue()
        for idx in range(len(self._instances)):
            self._available.put(idx)

        # 即時 VRAM 重檢參數：need ≤ 0 等於停用
        self._vram_need_gb = vram_need_gb
        self._safety_buffer_gb = safety_buffer_gb
        self._poll_interval_sec = poll_interval_sec
        self._max_wait_sec = max_wait_sec
        self._free_scan = free_scan or self._default_free_scan

    @staticmethod
    def _normalize_slots(
        slots: list[GpuSlot] | None,
        gpu_ids: list[int] | None,
    ) -> list[GpuSlot]:
        """將 slots 與 gpu_ids 兩種介面正規化為單一 GpuSlot 列表。"""
        # 兩者皆未提供 → 無從建立 instance
        if slots is None and gpu_ids is None:
            raise ValueError("必須提供 slots 或 gpu_ids 其中之一")
        # 兩者同時提供 → 來源衝突
        if slots is not None and gpu_ids is not None:
            raise ValueError("slots 與 gpu_ids 不可同時提供")
        # 走 backward-compat 路徑：每張 GPU 用預設槽位 0
        if slots is None:
            slots = [GpuSlot(device_id=g, slot_id=_DEFAULT_SLOT_ID) for g in gpu_ids]
        if not slots:
            raise ValueError("slots 不可為空，至少需指定一個槽位")
        return slots

    @contextmanager
    def borrow(
        self,
        timeout: float | None = None,
        observer: Optional[PoolBorrowObserver] = None,
    ) -> Iterator[T]:
        """
        借出一個可用的 Manager 實例（Context Manager）。

        兩道關卡：
        1. **L1 借出佇列**：所有槽位皆借出中則阻塞，直到有實例歸還或超過 ``timeout``。
        2. **即時 VRAM 重檢**（``vram_need_gb > 0`` 時）：取得槽位後再以 mem_get_info 確認
           該卡真實 free VRAM（含鄰居 process）足夠本次 forward，不足則阻塞輪詢；逾 ``max_wait_sec``
           仍不足則「盡力放行」（交給 forward 嘗試，OOM 由 ``oom_resilient`` 兜底），避免永久卡死。

        Args:
            timeout:  L1 借出佇列最長等待秒數，``None`` 表示無限等待
            observer: 即時 VRAM 重檢的觀察者（wait / ready 事件），``None`` 表示不推事件

        Yields:
            ``BaseModelManager`` 子類別實例

        Raises:
            queue.Empty: 等待超過 timeout 仍無可用實例
        """
        # L1 借出佇列阻塞 + 即時 VRAM 重檢都是「等資源」，計入本 thread 的等待累加（供拆分 compute/wait）
        with ResourceWaitClock.measure():
            idx = self._available.get(timeout=timeout)
        try:
            # 借出前即時重檢該槽位所在卡的 free VRAM（不足則阻塞等待 / 逾時盡力放行）
            with ResourceWaitClock.measure():
                self._await_vram(self._instances[idx], observer)
            yield self._instances[idx]
        finally:
            # finally 確保異常路徑下實例仍會歸還，避免池子被慢慢耗盡
            self._available.put(idx)

    def _await_vram(
        self,
        instance: T,
        observer: Optional[PoolBorrowObserver],
    ) -> None:
        """
        借出前阻塞直到該卡 free VRAM ≥ ``vram_need + buffer``，或等待逾時盡力放行。

        僅對「設了 vram_need 且實例在 CUDA 卡上」生效；CPU / 內部管理模型（device 非 cuda）直接放行。
        """
        # 未設需求 → 停用重檢（CPU/內部模型或未知成本）
        if self._vram_need_gb <= 0:
            return
        device_id = getattr(instance, "_device_id", None)
        device_str = str(getattr(instance, "device", "") or "")
        # 非 CUDA 裝置不檢查（與 inference_guard 跳過 L2 的判準一致）
        if device_id is None or not device_str.lower().startswith("cuda"):
            return

        slot_id = getattr(instance, "_slot_id", _DEFAULT_SLOT_ID)
        required_gb = self._vram_need_gb + self._safety_buffer_gb
        deadline = time.monotonic() + self._max_wait_sec
        waited = False
        while True:
            free_gb = self._free_scan(device_id)
            if free_gb >= required_gb:
                break
            # 逾時：盡力放行（讓 forward 去試，OOM 由 oom_resilient 兜底），避免無限卡死
            if time.monotonic() >= deadline:
                print(
                    f"[ModelPool] cuda:{device_id} free {free_gb:.2f}GB < 需求 {required_gb:.2f}GB "
                    f"等待逾 {self._max_wait_sec}s，盡力放行（OOM 由重試兜底）"
                )
                break
            # 首次不足時推一次 wait 事件，避免每輪洗版
            if not waited and observer is not None:
                observer.on_vram_wait(device_id, slot_id, free_gb, required_gb)
            waited = True
            time.sleep(self._poll_interval_sec)

        # 曾等待過才推 ready 事件（與 wait 成對，前端可收斂「等待中」狀態）
        if waited and observer is not None:
            observer.on_vram_ready(device_id, slot_id, self._free_scan(device_id))

    def run_with_failover(
        self,
        fn: Callable[[T], object],
        observer: Optional[PoolBorrowObserver] = None,
        timeout: float | None = None,
    ) -> object:
        """
        借出一個 instance 執行 ``fn``；若 ``fn`` 拋 CUDA OOM 就**改換不同 device 的 instance 重試**，
        直到成功或試完所有不同的卡。專治「某張卡被鄰居 process 佔走 VRAM 而持續 OOM」——
        在同一張卡上重試再多次也沒用，必須換卡。

        與 manager 層 ``@oom_resilient`` 分工：
        - ``@oom_resilient``：同卡**瞬時** OOM（empty_cache + backoff 重試同一張卡）。
        - 本方法：同卡**持續** OOM → 換到別張卡。

        單 instance（或單卡）pool 等於只跑一次（沒有別的卡可換），行為與 ``borrow`` 一致、無回歸。

        Args:
            fn:       對借到的 manager instance 執行的工作；其回傳值即本方法回傳值。
            observer: borrow 即時 VRAM 重檢的觀察者（wait / ready 事件）。
            timeout:  L1 借出佇列等待上限。

        Raises:
            最後一次 CUDA OOM（所有不同卡都 OOM 時）；或 ``fn`` 拋出的非 OOM 例外（原樣上拋）。
        """
        # 不同 device 數 = 最多換卡次數（每張卡至多試一輪）
        distinct_devices = {getattr(inst, "_device_id", None) for inst in self._instances}
        tried_devices: set = set()
        last_oom: Optional[Exception] = None
        for _ in range(len(distinct_devices)):
            # 借槽位（L1 佇列阻塞）計入「等資源」累加
            with ResourceWaitClock.measure():
                idx = self._acquire_preferring(tried_devices, timeout)
            instance = self._instances[idx]
            try:
                # 借出前同樣做即時 VRAM 重檢（換到的新卡也要確認 free 夠）；此等待亦計入累加
                with ResourceWaitClock.measure():
                    self._await_vram(instance, observer)
                return fn(instance)
            except Exception as exc:
                if not is_cuda_oom(exc):
                    raise  # 非 OOM 不在 failover 職責內，原樣上拋（保持既有錯誤語意）
                last_oom = exc
                device_id = getattr(instance, "_device_id", None)
                tried_devices.add(device_id)
                print(
                    f"[ModelPool failover] {type(instance).__name__} cuda:{device_id} 持續 OOM，"
                    f"改換其他卡重試（已試 {sorted(d for d in tried_devices if d is not None)}）"
                )
            finally:
                # 不論成功 / OOM / 例外都歸還槽位，避免池子被耗盡
                self._available.put(idx)
        # 所有不同卡都 OOM → 拋最後一次（交由 Pipeline 隔離成 asset error）
        if last_oom is not None:
            raise last_oom
        # distinct_devices 至少 1、迴圈必跑；理論上不會到這
        raise RuntimeError("run_with_failover：pool 無可用 instance")

    def _acquire_preferring(self, avoid_devices: set, timeout: float | None) -> int:
        """
        從可用佇列借一個 instance，盡量避開 ``avoid_devices`` 的卡（給 failover 換卡用）。

        先阻塞取一個（保證至少一個）；若它在 avoid set，再非阻塞地多撈、找出不在 avoid 的，
        把沒選中的放回。全部都在 avoid（無其他卡可換）時退回最先取得的那個。
        """
        first = self._available.get(timeout=timeout)
        if getattr(self._instances[first], "_device_id", None) not in avoid_devices:
            return first
        # first 在 avoid set：非阻塞撈其餘的找「不在 avoid」的
        held: list[int] = []
        chosen: Optional[int] = None
        while True:
            try:
                idx = self._available.get_nowait()
            except queue.Empty:
                break
            if getattr(self._instances[idx], "_device_id", None) not in avoid_devices:
                chosen = idx
                break
            held.append(idx)
        # 沒被選中的 avoid instances 全部放回
        for idx in held:
            self._available.put(idx)
        if chosen is not None:
            self._available.put(first)  # 改用 chosen，把 first 放回佇列
            return chosen
        return first  # 沒有「不在 avoid」的可借，只能用 first（保持借出）

    def warmup_all(self) -> None:
        """
        對池內每個 instance 依序呼叫 ``warmup()``，在啟動單執行緒階段觸發其首呼叫 lazy import / 原生 dlopen。

        刻意**不經借出佇列、不參與併發**：在「併發開始前」序列跑完，確保所有原生擴充都已 import，
        執行期 worker thread 首呼叫便不再 dlopen，避免與其他執行緒撞動態連結器鎖造成死結
        （見 :meth:`BaseModelManager.warmup`）。未 override ``warmup`` 的子類為 no-op，呼叫無副作用。
        """
        for instance in self._instances:
            instance.warmup()

    @staticmethod
    def _default_free_scan(device_id: int) -> float:
        """真實掃描指定卡的 free VRAM（GB）。"""
        import torch
        free_b, _total_b = torch.cuda.mem_get_info(device_id)
        return free_b / _BYTES_PER_GB

    @property
    def size(self) -> int:
        """Pool 管理的槽位數量。"""
        return len(self._instances)

    @property
    def available_count(self) -> int:
        """當前可立即借出的實例數量（非精確值，僅供監控用）。"""
        return self._available.qsize()
