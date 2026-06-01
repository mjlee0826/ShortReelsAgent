"""
ExecutorRegistry:依 ResourceType 路由到對應 Worker Pool (Registry + Facade Pattern)。

把四個 ResourceExecutor 集中管理,Stage 只要宣告自己的 ``resource_type``,
Pipeline 就能把它丟到正確的 Pool,呼叫端無需知道 Pool 實體。
GPU Pool 大小依實際 GPU 數動態決定(plan §10),不寫死。
"""
from __future__ import annotations

from concurrent.futures import Future

from config.pipeline_config import (
    API_POOL_MAX_WORKERS,
    CPU_POOL_MAX_WORKERS,
    GPU_POOL_MIN_WORKERS,
    GPU_POOL_MULTIPLIER,
    IO_POOL_MAX_WORKERS,
)
from media_processor.pipeline.executor.gpu_detect import detect_gpu_count
from media_processor.pipeline.executor.resource_executor import (
    APIExecutor,
    CPUExecutor,
    GPUExecutor,
    IOExecutor,
    ResourceExecutor,
)
from media_processor.pipeline.stage import ResourceType


class ExecutorRegistry:
    """
    ResourceType → ResourceExecutor 的路由中樞。

    生命週期與一次 ``PipelineRunner`` 綁定;結束時呼叫 :meth:`shutdown` 釋放所有執行緒池。
    """

    def __init__(self, gpu_count: int | None = None):
        """
        建立四個資源池;GPU 池大小依 GPU 數 × multiplier 計算(下有最低值保底)。

        Args:
            gpu_count: 明示 GPU 數(主要供測試);``None`` 時自動偵測。
        """
        resolved_gpu_count = detect_gpu_count() if gpu_count is None else gpu_count
        gpu_pool_size = max(GPU_POOL_MIN_WORKERS, resolved_gpu_count * GPU_POOL_MULTIPLIER)

        # 一次建好四個池,之後依 ResourceType 查表路由
        self._executors: dict[ResourceType, ResourceExecutor] = {
            ResourceType.IO: IOExecutor(IO_POOL_MAX_WORKERS),
            ResourceType.CPU: CPUExecutor(CPU_POOL_MAX_WORKERS),
            ResourceType.GPU: GPUExecutor(gpu_pool_size),
            ResourceType.API: APIExecutor(API_POOL_MAX_WORKERS),
        }
        self._gpu_count = resolved_gpu_count

    def get(self, resource_type: ResourceType) -> ResourceExecutor:
        """取得指定資源型別的 Executor。"""
        return self._executors[resource_type]

    def submit(self, resource_type: ResourceType, fn, *args, **kwargs) -> Future:
        """把工作提交到對應資源池,回傳 Future(便利方法)。"""
        return self._executors[resource_type].submit(fn, *args, **kwargs)

    def describe(self) -> str:
        """回傳各池 worker 數的可讀字串(供啟動日誌)。"""
        parts = [f"{rt.value}={ex.max_workers}" for rt, ex in self._executors.items()]
        return f"ExecutorRegistry(gpu_count={self._gpu_count}, " + ", ".join(parts) + ")"

    def shutdown(self, wait: bool = True) -> None:
        """關閉所有資源池。"""
        for executor in self._executors.values():
            executor.shutdown(wait=wait)
