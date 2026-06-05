"""
media_processor.pipeline 套件公開 API。

匯出兩組元件:
- Observer Pattern 進度介面(``progress`` 模組)。
- Pipeline 框架核心 ── Context / Stage / Pipeline / Builder / Scheduler /
  Executor & ModelPool Registry / Runner(Facade)。

對外建議只用 ``PipelineRunner`` 一個入口;其餘類別供組裝細粒度 Stage 時使用。
"""
# ── 進度觀測 ───────────────────────────────────────────────────────────────
from media_processor.pipeline.progress import (
    PrintProgressObserver,
    ProgressEvent,
    ProgressEventType,
    ProgressObserver,
    ProgressTracker,
)

# ── 框架核心 ───────────────────────────────────────────────────────────────
from media_processor.pipeline.builder import PipelineBuilder
from media_processor.pipeline.context import (
    AssetContext,
    MediaKind,
    derive_media_kind,
)
from media_processor.pipeline.executor import (
    ExecutorRegistry,
    ModelPoolRegistry,
    detect_gpu_ids,
)
from media_processor.pipeline.node import StageNode
from media_processor.pipeline.pipeline import Pipeline
from media_processor.pipeline.runner import PipelineRunner
from media_processor.pipeline.scheduler import HybridScheduler
from media_processor.pipeline.stage import (
    ResourceType,
    Stage,
    StageError,
    StageMeta,
)

__all__ = [
    # progress
    "PrintProgressObserver",
    "ProgressEvent",
    "ProgressEventType",
    "ProgressObserver",
    "ProgressTracker",
    # framework
    "PipelineRunner",
    "PipelineBuilder",
    "Pipeline",
    "HybridScheduler",
    "ExecutorRegistry",
    "ModelPoolRegistry",
    "detect_gpu_ids",
    "AssetContext",
    "MediaKind",
    "derive_media_kind",
    "Stage",
    "StageMeta",
    "StageError",
    "ResourceType",
    "StageNode",
]
