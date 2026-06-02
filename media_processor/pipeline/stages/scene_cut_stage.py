"""SceneCutStage:以 PySceneDetect 擷取場景切換時間點(CPU)。"""
from __future__ import annotations

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.video_work import get_video_work
from template_engine.scene_cut_extractor import SceneCutExtractor

_STAGE_NAME = "scene_cut"


class SceneCutStage(Stage):
    """
    以 SceneCutExtractor 擷取影片場景切換時間點列表,寫入 ``VideoWork.scene_cuts``。

    對齊原 ``_extract_scene_cuts``:失敗時靜默回空列表、不阻斷主流程(本 Stage 內部 try/except 保留此降級語意,
    而非讓例外往上把整個 asset 標 error)。純 CPU 運算,標記為 CPU 資源。
    """

    def __init__(self):
        """設定 Stage 靜態描述。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)

    def run(self, context: AssetContext) -> None:
        """擷取場景切點;失敗回空列表(對齊原版降級行為)。"""
        work = get_video_work(context)
        try:
            work.scene_cuts = SceneCutExtractor().get_cuts(context.file_path)
        except Exception as e:
            # 場景切點失敗不阻斷主流程,但印出以免靜默吞錯後難以定位(對齊原 _extract_scene_cuts)
            print(f"[SceneCutStage Warning] 場景切點擷取失敗 {context.file_path}: {e}")
            work.scene_cuts = []
