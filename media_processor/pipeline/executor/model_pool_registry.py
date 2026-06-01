"""
ModelPoolRegistry:集中管理各模型的 ModelPool (Registry Pattern)。

職責
----
- 啟動時偵測可用 GPU,並能為任一模型建立「每張 GPU 一份實例」的 :class:`ModelPool`
  (多 GPU 環境自動分散到不同卡 → 對應 roadmap §4 驗收條件#3 的基礎建設層)。
- ``get_pool(model_class)`` 延遲建立並快取,多個 asset 共享同一份模型,不會每 asset 載一份。

Week 2a 範疇
------------
本 Registry **建好並可被驗證**(啟動 log 印出偵測到的裝置),但 **2a 的 LegacyStage 不呼叫它**
(沿用既有 device-0 singleton,確保輸出與 Week 1 逐欄一致、零 OOM 風險)。真正用 Pool 借出模型、
跨卡分散工作負載,留待 Week 2b/2c 拆 Stage(per-forward borrow)與 Week 3b 雙 GPU Qwen Pool。
"""
from __future__ import annotations

import threading

from media_processor.pipeline.executor.gpu_detect import detect_gpu_ids
from model.base_model_manager import BaseModelManager
from model.model_pool import ModelPool

# 無 GPU 時 ModelPool 仍需至少一個 slot;device 0 經 get_device_str 會對應到 'cpu'
_CPU_FALLBACK_DEVICE_ID = 0


class ModelPoolRegistry:
    """
    每個模型類別一個 ModelPool 的集中管理器(執行緒安全、延遲建立)。
    """

    def __init__(self, gpu_ids: list[int] | None = None):
        """
        決定 Pool 要鋪在哪些裝置上,並印出偵測結果供驗收觀察。

        Args:
            gpu_ids: 明示裝置列表(主要供測試);``None`` 時自動偵測,無 GPU 則退回 ``[0]``(cpu)。
        """
        detected = detect_gpu_ids()
        self._gpu_ids = list(gpu_ids) if gpu_ids is not None else (detected or [_CPU_FALLBACK_DEVICE_ID])
        self._pools: dict[type, ModelPool] = {}
        # 延遲建立 Pool 時的互斥鎖,避免多 driver 同時建同一個 Pool
        self._lock = threading.Lock()

        # 啟動 log:讓使用者在多卡機器上確認「ModelPool 會分散到哪幾張卡」(驗收條件#3)
        print(f"[ModelPoolRegistry] 偵測到模型可用裝置: {self._device_strs()}")

    def get_pool(self, model_class: type[BaseModelManager]) -> ModelPool:
        """
        取得(或延遲建立並快取)指定模型類別的 ModelPool。

        Pool 以 ``gpu_ids`` 配置,每張卡一份實例;多 GPU 時 ``borrow()`` 會把不同 driver
        分散到不同卡。Week 2a 尚未有呼叫端,留給後續週次。
        """
        # Fast path:已建則直接回傳
        pool = self._pools.get(model_class)
        if pool is not None:
            return pool

        # Slow path:加鎖後再次確認,確保單一建立
        with self._lock:
            pool = self._pools.get(model_class)
            if pool is None:
                pool = ModelPool(model_class, gpu_ids=self._gpu_ids)
                self._pools[model_class] = pool
                print(
                    f"[ModelPoolRegistry] 建立 {model_class.__name__} pool → "
                    f"slots={self._device_strs()}"
                )
            return pool

    @property
    def gpu_ids(self) -> list[int]:
        """Pool 鋪設的裝置 id 列表。"""
        return list(self._gpu_ids)

    def _device_strs(self) -> list[str]:
        """把 device id 轉成可讀裝置字串(例如 ['cuda:0', 'cuda:1'] 或 ['cpu'])。"""
        return [BaseModelManager.get_device_str(i) for i in self._gpu_ids]
