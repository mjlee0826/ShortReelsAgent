"""
media_processor.pipeline.executor 套件:資源管理層 (Layer 2)。

對外公開:
- ``ExecutorRegistry`` — 依 ResourceType 路由的四種 Worker Pool
- ``ModelPoolRegistry`` — 各模型的 ModelPool 集中管理(GPU 偵測 + 分散)
- 四種 ``ResourceExecutor`` 子類別與 ``detect_gpu_ids`` 工具
"""
from media_processor.pipeline.executor.executor_registry import ExecutorRegistry
from media_processor.pipeline.executor.gpu_detect import detect_gpu_count, detect_gpu_ids
from media_processor.pipeline.executor.model_pool_registry import ModelPoolRegistry
from media_processor.pipeline.executor.resource_executor import (
    APIExecutor,
    CPUExecutor,
    GPUExecutor,
    IOExecutor,
    ResourceExecutor,
)

__all__ = [
    "ExecutorRegistry",
    "ModelPoolRegistry",
    "ResourceExecutor",
    "IOExecutor",
    "CPUExecutor",
    "GPUExecutor",
    "APIExecutor",
    "detect_gpu_ids",
    "detect_gpu_count",
]
