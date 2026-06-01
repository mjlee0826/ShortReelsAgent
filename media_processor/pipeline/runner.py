"""
PipelineRunner:Phase 1 素材感知的對外單一入口 (Facade Pattern)。

把 Builder / Scheduler / ExecutorRegistry / ModelPoolRegistry / ProgressTracker 全部藏在後面,
呼叫端(``DirectorService``)只需呼叫 :meth:`run`,傳入檔案清單與影片策略,拿回與舊版序列迴圈
**逐欄一致**的 metadata dict 列表,完全無感於底層的並行框架。

設計來源:integrated_acceleration_plan.md Layer 2/3;roadmap §4 Week 2a。
"""
from __future__ import annotations

import os
import uuid

from config.pipeline_config import EAGER_MODELS, MAX_ASSETS_PARALLEL
from media_processor.pipeline.builder import PipelineBuilder
from media_processor.pipeline.context import AssetContext, derive_media_kind
from media_processor.pipeline.executor.executor_registry import ExecutorRegistry
from media_processor.pipeline.executor.model_pool_registry import ModelPoolRegistry
from media_processor.pipeline.progress import (
    PrintProgressObserver,
    ProgressObserver,
    ProgressTracker,
)
from media_processor.pipeline.scheduler.hybrid_scheduler import HybridScheduler
from media_processor.video_strategy import VideoStrategy


class PipelineRunner:
    """
    Phase 1 Pipeline 的 Facade。一次建構、跨多個 generate 請求重複使用
    (內部 ExecutorRegistry / ModelPoolRegistry 長存,避免每次請求重建資源池)。
    """

    def __init__(
        self,
        max_assets_parallel: int = MAX_ASSETS_PARALLEL,
        observers: list[ProgressObserver] | None = None,
        eager_models: bool = EAGER_MODELS,
    ):
        """
        建好排程器與兩個 Registry,並印出資源佈局供啟動觀察。

        Args:
            max_assets_parallel: asset 並行度(env ``MAX_ASSETS_PARALLEL`` 可覆寫)。
            observers: 進度觀察者;``None`` 時預設掛 ``PrintProgressObserver``,
                       讓開發期可肉眼看到多 asset 事件交錯(驗收條件#2)。
            eager_models: 是否啟動期預載模型;Week 2a 僅保留旗標,實際 warm up 留 Week 3b。
        """
        # Layer 2 資源管理:跨請求長存的資源池與模型池
        self._registry = ExecutorRegistry()
        # Week 2a 建好但不接 LegacyStage,僅偵測 + log(驗收條件#3 基礎建設層)
        self._model_pool_registry = ModelPoolRegistry()
        # Layer 3 排程:Builder + HybridScheduler
        self._builder = PipelineBuilder()
        self._scheduler = HybridScheduler(self._registry, self._builder, max_assets_parallel)
        self._observers = observers if observers is not None else [PrintProgressObserver()]

        print(f"[PipelineRunner] {self._registry.describe()}")
        if eager_models:
            # 決策 A:Week 2a 維持 lazy,warm up 留 Week 3b GPU Capacity Manager
            print("[PipelineRunner] EAGER_MODELS=true,但 Week 2a 未實作 warm up,維持 lazy 載入")

    def run(
        self,
        asset_files: list[str],
        base_dir: str,
        video_strategy: VideoStrategy,
    ) -> list[dict]:
        """
        並行跑完所有素材的 Phase 1 感知分析。

        Args:
            asset_files: 已過濾、依輸入順序排列的媒體檔案絕對路徑清單。
            base_dir:    素材資料夾(目前僅供日誌 / 未來擴充,實際路徑已在 asset_files)。
            video_strategy: 影片策略(SIMPLE / COMPLEX);圖片不受影響(工廠依副檔名路由)。

        Returns:
            僅含 ``status == "success"`` 的 metadata dict 列表,**依輸入順序排列**,
            與舊版序列迴圈輸出逐欄一致。
        """
        contexts = self._build_contexts(asset_files, video_strategy)
        if not contexts:
            return []

        # 每次 run 一個 job_id + 一個 Tracker,訂閱設定的 observers
        tracker = ProgressTracker(job_id=uuid.uuid4().hex)
        for observer in self._observers:
            tracker.subscribe(observer)

        results = self._scheduler.run(contexts, tracker)
        # 只收成功的 asset,順序已由 scheduler 依 index 排好
        return [ctx.result for ctx in results if ctx.is_success and ctx.result is not None]

    def _build_contexts(
        self,
        asset_files: list[str],
        video_strategy: VideoStrategy,
    ) -> list[AssetContext]:
        """把檔案路徑清單轉成帶輸入索引的 AssetContext 列表。"""
        contexts: list[AssetContext] = []
        for index, file_path in enumerate(asset_files):
            try:
                media_kind = derive_media_kind(file_path)
            except ValueError:
                # 理論上呼叫端已過濾;防呆跳過不支援的副檔名
                print(f"[PipelineRunner] 跳過不支援的檔案: {os.path.basename(file_path)}")
                continue
            contexts.append(
                AssetContext(
                    asset_id=os.path.basename(file_path),
                    file_path=file_path,
                    media_kind=media_kind,
                    index=index,
                    # 影片套用前端策略;圖片此值會被工廠忽略(沿用舊版傳法)
                    video_strategy=video_strategy,
                )
            )
        return contexts

    def shutdown(self) -> None:
        """關閉底層資源池(伺服器正常運作下不需呼叫,程式結束自動回收)。"""
        self._registry.shutdown()
