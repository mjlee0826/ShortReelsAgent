"""
ResourceWaitClock：執行緒區域的「等資源時間」累加器 (Thread-Local + Context Manager)。

動機
----
一個 stage 的總耗時 = 等資源（borrow 佇列 / GpuGate 預算 / 即時 VRAM 重檢）＋ 真正 compute。
共用 GPU 被 Qwen 序列化時，小模型的耗時幾乎全是「等」而非「算」（log 裡 aes 實算 ~50ms 卻報 91s）。
本元件把每條 worker thread 在資源關卡上阻塞的時間累加起來，讓 Pipeline 能把「等」從總耗時拆出來，
一眼分辨瓶頸是「排隊等資源」還是「真的在運算」。

為什麼用 thread-local
--------------------
每個 stage 都在「自己的」pool worker thread 上跑，且它等待的資源關卡（``GpuGate.acquire``、
``ModelPool.borrow``、pool 的 ``Queue.get`` …）都阻塞在同一條 thread 上，故以 ``threading.local``
累加最自然：資源關卡只要在阻塞處包一層 ``with ResourceWaitClock.measure():``，完全不需知道
是哪個 stage 在用、也不需傳遞任何 context。模型層元件（gpu_gate / model_pool）可直接 import 本模組，
維持「pipeline → model」單向依賴不被打破。
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator


class ResourceWaitClock:
    """執行緒區域的等待時間累加器（單位：秒，對外以毫秒讀出）。"""

    # 每條 thread 一份獨立累加值，互不干擾（pool worker 之間不會串味）
    _local = threading.local()

    @classmethod
    def reset(cls) -> None:
        """歸零當前 thread 的累加值（Pipeline 在每個 stage 開跑前呼叫一次）。"""
        cls._local.waited_sec = 0.0

    @classmethod
    def add(cls, seconds: float) -> None:
        """累加一段等待秒數到當前 thread（內部用；負值夾 0 以防量測誤差倒扣）。"""
        cls._local.waited_sec = getattr(cls._local, "waited_sec", 0.0) + max(0.0, seconds)

    @classmethod
    def waited_ms(cls) -> float:
        """讀取當前 thread 自上次 ``reset`` 起累積的等待毫秒數。"""
        return getattr(cls._local, "waited_sec", 0.0) * 1000.0

    @classmethod
    @contextmanager
    def measure(cls) -> Iterator[None]:
        """
        包住一段「等資源」的阻塞程式碼，離開時把耗時計入當前 thread 的等待累加值。

        立即取得（無阻塞）時計入趨近 0，不影響 compute 估算；故可安心包在所有資源關卡外層。
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            cls.add(time.perf_counter() - start)
