"""SemanticImageStage:依 strategy 以 Qwen(本地)或 Gemini(雲端)做語意分析(G3 平行群)。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from config.pipeline_config import GPU_POOL_ENABLED
from media_processor.image_strategy import ImageStrategy
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.image_work import get_image_work
from prompt_manager.task_mode import TaskMode

if TYPE_CHECKING:
    from model.gemini_model_manager import GeminiModelManager
    from model.qwen_model_manager import QwenModelManager

_STAGE_NAME = "semantic_image"
# analyze_media 的媒體型別參數(對齊原 ImageProcessor / ComplexImageProcessor 呼叫)
_MEDIA_TYPE_IMAGE = "image"


class SemanticImageStage(Stage):
    """
    視覺語意分析(Strategy 分派 Hook):SIMPLE 走本地 Qwen、COMPLEX 走 Gemini API。

    對應原 ``ImageProcessor`` / ``ComplexImageProcessor.analyze_visual_semantics``;
    語意只需 ``pil_image``(原版收的 exif 參數未被使用),故與其他 G3 stage 無依賴、可同群並行。
    resource_type 依策略決定:SIMPLE→GPU(Qwen)、COMPLEX→API(Gemini),供 ExecutorRegistry 路由。

    現狀 ``PipelineRunner`` 不傳 image_strategy(恆 SIMPLE)→ 走 Qwen,與 Legacy 逐欄一致;
    COMPLEX 分支先接好,待 Week 4 前端傳 per-asset 策略時即生效。
    """

    def __init__(self, image_strategy: ImageStrategy = ImageStrategy.SIMPLE):
        """依策略決定資源型別(Qwen=GPU / Gemini=API)並預備兩個 lazy 引擎。"""
        self._image_strategy = image_strategy
        resource = (
            ResourceType.API if image_strategy == ImageStrategy.COMPLEX else ResourceType.GPU
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
        """依策略呼叫對應引擎,語意結果 dict 寫入 ImageWork.vlm_result。"""
        work = get_image_work(context)
        if self._image_strategy == ImageStrategy.COMPLEX:
            work.vlm_result = self._gemini_engine().analyze_media(
                work.frame.pil_image, media_type=_MEDIA_TYPE_IMAGE, mode=TaskMode.COMPLEX_IMAGE_ANALYSIS
            )
        else:
            work.vlm_result = self._analyze_with_qwen(work.frame.pil_image, context)

    def _analyze_with_qwen(self, pil_image, context: AssetContext) -> dict:
        """
        SIMPLE 本地 Qwen 全局分析:``GPU_POOL_ENABLED`` 時從 capacity 規劃的多卡 pool 借出
        (享多卡分散 + borrow 即時 VRAM 重檢事件),否則回退 device-0 singleton(Week 3a 行為)。
        """
        if not GPU_POOL_ENABLED:
            return self._qwen_engine().analyze_media(
                pil_image, media_type=_MEDIA_TYPE_IMAGE, mode=TaskMode.GLOBAL_ANALYSIS
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
                pil_image, media_type=_MEDIA_TYPE_IMAGE, mode=TaskMode.GLOBAL_ANALYSIS
            ),
            observer=observer,
        )
