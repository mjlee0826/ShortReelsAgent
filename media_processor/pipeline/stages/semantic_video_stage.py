"""SemanticVideoStage:依 strategy 以 Qwen(本地全局)或 Gemini(雲端時間碼索引)做影片語意分析。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from config.pipeline_config import GPU_POOL_ENABLED
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.work.video_work import get_video_work
from media_processor.video_strategy import VideoStrategy
from prompt_manager.task_mode import TaskMode

if TYPE_CHECKING:
    from model.gemini_model_manager import GeminiModelManager
    from model.qwen_model_manager import QwenModelManager

_STAGE_NAME = "semantic_video"
# analyze_media 的媒體型別參數(對齊原 VideoProcessor / ComplexVideoProcessor 呼叫)
_MEDIA_TYPE_VIDEO = "video"


class SemanticVideoStage(Stage):
    """
    視覺語意分析(Strategy 分派 Hook):SIMPLE 走本地 Qwen 全局分析、COMPLEX 走 Gemini 時間碼事件索引。

    - SIMPLE:對**原始**影片做 ``GLOBAL_ANALYSIS``(GPU 資源)。
    - COMPLEX:對 TimecodeStage 燒好時間碼的影片做 ``TIMECODED_ACTION_INDEX``(API 資源);
      故 DAG 中本 Stage 只依賴 timecode,不需等音訊 / 視覺特徵 —— 修正了 StageGroup 時代的過度約束。
    結果 dict 寫入 ``VideoWork.vlm_result``,由 Assembly / EventBbox 後續取用。
    """

    def __init__(self, video_strategy: VideoStrategy = VideoStrategy.SIMPLE):
        """依策略決定資源型別(Qwen=GPU / Gemini=API)並預備兩個 lazy 引擎。"""
        self._video_strategy = video_strategy
        resource = (
            ResourceType.API if video_strategy == VideoStrategy.COMPLEX else ResourceType.GPU
        )
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=resource)
        self._qwen: Optional["QwenModelManager"] = None
        self._gemini: Optional["GeminiModelManager"] = None

    def _qwen_engine(self) -> "QwenModelManager":
        """延遲取得本地 Qwen singleton。"""
        if self._qwen is None:
            from model.qwen_model_manager import QwenModelManager
            self._qwen = QwenModelManager()
        return self._qwen

    def _gemini_engine(self) -> "GeminiModelManager":
        """延遲取得 Gemini API client。"""
        if self._gemini is None:
            from model.gemini_model_manager import GeminiModelManager
            self._gemini = GeminiModelManager()
        return self._gemini

    def run(self, context: AssetContext) -> None:
        """依策略呼叫對應引擎(Complex 用時間碼影片),語意結果寫入 VideoWork.vlm_result。"""
        work = get_video_work(context)
        if self._video_strategy == VideoStrategy.COMPLEX:
            work.vlm_result = self._gemini_engine().analyze_media(
                media_input=work.tc_file_path,
                media_type=_MEDIA_TYPE_VIDEO,
                mode=TaskMode.TIMECODED_ACTION_INDEX,
            )
        else:
            work.vlm_result = self._analyze_with_qwen(context.file_path, context)

    def _analyze_with_qwen(self, media_input, context: AssetContext) -> dict:
        """
        SIMPLE 本地 Qwen 全局分析:``GPU_POOL_ENABLED`` 時從 capacity 規劃的多卡 pool 借出
        (享多卡分散 + borrow 即時 VRAM 重檢事件),否則回退 device-0 singleton。
        """
        if not GPU_POOL_ENABLED:
            return self._qwen_engine().analyze_media(
                media_input=media_input, media_type=_MEDIA_TYPE_VIDEO, mode=TaskMode.GLOBAL_ANALYSIS
            )
        # lazy import 避免模組載入期耦合(與既有 _qwen_engine 的 lazy 風格一致)
        from model.qwen_model_manager import QwenModelManager
        from media_processor.pipeline.executor.model_pool_registry import ModelPoolRegistry

        observer = ModelPoolRegistry.make_borrow_observer(
            context.tracker, context.asset_id, self.meta.name
        )
        # run_with_failover:單卡持續 OOM(鄰居佔 VRAM)時自動換到別張卡重試,而非死守同卡
        return ModelPoolRegistry.instance().get_pool(QwenModelManager).run_with_failover(
            lambda qwen: qwen.analyze_media(
                media_input=media_input, media_type=_MEDIA_TYPE_VIDEO, mode=TaskMode.GLOBAL_ANALYSIS
            ),
            observer=observer,
        )
