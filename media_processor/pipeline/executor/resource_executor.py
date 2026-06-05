"""
ResourceExecutor:四種資源 Worker Pool 的薄封裝 (Adapter Pattern)。

每種資源(IO / CPU / GPU / API)各有一個獨立的 ``ThreadPoolExecutor``,
彼此不爭用,確保「做 IO 時 GPU 不會被閒置卡住」。本類別只是把 ThreadPoolExecutor
包成帶名稱與資源型別的物件,讓 ExecutorRegistry 能依 ResourceType 路由。

四個子類別(IO/CPU/GPU/APIExecutor)彼此只差 ``RESOURCE_TYPE``,行為一致 ──
差異化的併發度由 ExecutorRegistry 從 config 注入。
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

from media_processor.pipeline.stage import ResourceType


class ResourceExecutor:
    """
    單一資源型別的執行緒池封裝。

    執行緒以 ``pipe-<name>`` 命名前綴,方便在 py-spy / 日誌中辨識是哪個 Pool 在跑。
    """

    #: 子類別必須覆寫,標示自己服務哪種資源
    RESOURCE_TYPE: ResourceType

    def __init__(self, max_workers: int, name: str | None = None):
        """以指定 worker 數建立底層執行緒池。"""
        self._name = name or self.RESOURCE_TYPE.value
        self._max_workers = max_workers
        # thread_name_prefix 讓除錯時一眼看出 thread 屬於哪個資源 Pool
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=f"pipe-{self._name}",
        )

    def submit(self, fn: Callable, *args, **kwargs) -> Future:
        """提交一個工作到本資源池,回傳 Future。"""
        return self._pool.submit(fn, *args, **kwargs)

    def shutdown(self, wait: bool = True) -> None:
        """關閉底層執行緒池,釋放執行緒資源。"""
        self._pool.shutdown(wait=wait)

    @property
    def name(self) -> str:
        """資源池名稱(用於日誌)。"""
        return self._name

    @property
    def max_workers(self) -> int:
        """本池的最大併發 worker 數。"""
        return self._max_workers


class IOExecutor(ResourceExecutor):
    """IO 密集工作池:FFmpeg subprocess、檔案讀寫、雲端上傳。"""

    RESOURCE_TYPE = ResourceType.IO


class CPUExecutor(ResourceExecutor):
    """CPU 密集工作池:cv2、KMeans、MediaPipe、SceneDetect(numpy/cv2 釋放 GIL)。"""

    RESOURCE_TYPE = ResourceType.CPU


class GPUExecutor(ResourceExecutor):
    """GPU 推論工作池:與 ModelPool / GpuGate 整合,同卡 forward 仍由 GpuGate 互斥。"""

    RESOURCE_TYPE = ResourceType.GPU


class APIExecutor(ResourceExecutor):
    """雲端 API 工作池:Gemini 推論,worker 數即 RPS 上限(Semaphore 效果)。"""

    RESOURCE_TYPE = ResourceType.API
