"""
ModelPool：多 GPU Object Pool，搭配 BaseModelManager 實現多執行緒安全推論。

設計模式：Object Pool Pattern + Context Manager

典型用法（多執行緒 + 多 GPU）：
    pool = ModelPool(QwenModelManager, gpu_ids=[0, 1])

    def worker(media_path):
        with pool.borrow() as model:
            return model.analyze_media(media_path)

    with ThreadPoolExecutor(max_workers=4) as exe:
        results = list(exe.map(worker, media_list))
"""
import queue
from contextlib import contextmanager
from typing import Generic, TypeVar

from model.base_model_manager import BaseModelManager

T = TypeVar("T", bound=BaseModelManager)


class ModelPool(Generic[T]):
    """
    管理跨多張 GPU 的模型實例池，每張 GPU 一個實例，
    透過 Queue 實現執行緒安全的借還機制。
    """

    def __init__(self, model_class: type[T], gpu_ids: list[int]):
        """
        初始化並在各 GPU 上建立模型實例。

        Args:
            model_class: 繼承 BaseModelManager 的模型類別
            gpu_ids:     要使用的 GPU device id 列表，例如 [0, 1, 2]
        """
        if not gpu_ids:
            raise ValueError("gpu_ids 不可為空，至少需指定一個 device id。")

        # 為每張 GPU 建立（或取得已快取的）模型實例
        self._instances: dict[int, T] = {
            gpu_id: model_class(device_id=gpu_id) for gpu_id in gpu_ids
        }

        # Queue 存放「可借出的 gpu_id」，實現執行緒安全的輪替
        self._available: queue.Queue[int] = queue.Queue()
        for gpu_id in gpu_ids:
            self._available.put(gpu_id)

    @contextmanager
    def borrow(self, timeout: float | None = None):
        """
        借出一個可用的模型實例（Context Manager）。
        若所有 GPU 都在使用中，則阻塞等待直到有實例歸還。

        Args:
            timeout: 最長等待秒數，None 表示無限等待

        Yields:
            BaseModelManager 子類別實例

        Raises:
            queue.Empty: 等待超過 timeout 仍無可用實例
        """
        gpu_id = self._available.get(timeout=timeout)
        try:
            yield self._instances[gpu_id]
        finally:
            self._available.put(gpu_id)

    @property
    def size(self) -> int:
        """Pool 管理的 GPU 數量。"""
        return len(self._instances)

    @property
    def available_count(self) -> int:
        """當前可立即借出的實例數量（非精確值，僅供監控用）。"""
        return self._available.qsize()
