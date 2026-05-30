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
  搭配 Week 3b ``BudgetGate`` 達成同卡併發紅利（需 VRAM 充裕）。
- Week 1 結構就緒但效果尚未顯現：``BinaryGate`` 下同卡兩 instance 仍被 L2 序列化。

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
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generic, Iterator, TypeVar

from model.base_model_manager import BaseModelManager

T = TypeVar("T", bound=BaseModelManager)

# 預設槽位 id：當 gpu_ids 介面被使用時，所有 GPU 隱式分配此槽位
_DEFAULT_SLOT_ID = 0


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
    ):
        """
        初始化並在指定槽位上建立（或取得已快取的）Manager 實例。

        Args:
            model_class: 繼承 ``BaseModelManager`` 的 Manager 類別
            slots:       明示槽位列表，可表達同卡多槽位
            gpu_ids:     向後相容介面，自動轉成 ``[GpuSlot(g, 0) for g in gpu_ids]``

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
    def borrow(self, timeout: float | None = None) -> Iterator[T]:
        """
        借出一個可用的 Manager 實例（Context Manager）。

        若所有槽位皆借出中則阻塞等待，直到有實例歸還或超過 timeout。

        Args:
            timeout: 最長等待秒數，``None`` 表示無限等待

        Yields:
            ``BaseModelManager`` 子類別實例

        Raises:
            queue.Empty: 等待超過 timeout 仍無可用實例
        """
        idx = self._available.get(timeout=timeout)
        try:
            yield self._instances[idx]
        finally:
            # finally 確保異常路徑下實例仍會歸還，避免池子被慢慢耗盡
            self._available.put(idx)

    @property
    def size(self) -> int:
        """Pool 管理的槽位數量。"""
        return len(self._instances)

    @property
    def available_count(self) -> int:
        """當前可立即借出的實例數量（非精確值，僅供監控用）。"""
        return self._available.qsize()
