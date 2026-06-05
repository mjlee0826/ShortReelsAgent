"""
PipelineRunner:Phase 1 素材感知的對外單一入口 (Facade Pattern)。

把 Builder / Scheduler / ExecutorRegistry / ModelPoolRegistry / ProgressTracker 全部藏在後面,
呼叫端(``DirectorService``)只需呼叫 :meth:`run`,傳入檔案清單與影片策略,拿回與舊版序列迴圈
**逐欄一致**的 metadata dict 列表,完全無感於底層的並行框架。
"""
from __future__ import annotations

import os
import time
import uuid

from config.pipeline_config import (
    EAGER_MODELS,
    MAX_ASSETS_PARALLEL,
    WATCHDOG_ENABLED,
    WATCHDOG_FREEZE_DUMP_SEC,
    WATCHDOG_HEARTBEAT_SEC,
    WATCHDOG_STALL_WARN_SEC,
)
from media_processor.pipeline.batch_collector import BatchCollectorRegistry
from media_processor.pipeline.builder import PipelineBuilder
from media_processor.pipeline.context import AssetContext, derive_media_kind
from media_processor.pipeline.executor.executor_registry import ExecutorRegistry
from media_processor.pipeline.executor.model_pool_registry import ModelPoolRegistry
from media_processor.pipeline.progress import (
    PrintProgressObserver,
    ProgressObserver,
    ProgressTracker,
)
from media_processor.pipeline.progress.watchdog import StallWatchdog
from media_processor.pipeline.scheduler.hybrid_scheduler import HybridScheduler
from media_processor.pipeline.startup_report import StartupReporter
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
                       讓開發期可肉眼看到多 asset 事件交錯。
            eager_models: 是否在啟動期預載(warm up)模型,讓第一個 asset 不必等待載入。
        """
        # observers 需先就緒,供 ModelPoolRegistry 的 warm up / borrow 等待事件廣播
        self._observers = observers if observers is not None else [PrintProgressObserver()]
        # Layer 2 資源管理:跨請求長存的資源池與模型池
        self._registry = ExecutorRegistry()
        # ModelPoolRegistry 接 GpuCapacityManager,規劃多卡放置 + 每卡 BudgetGate 預算,
        # 並把自己註冊為 process 級共享實例(stage / batch_fn 經 instance() 借出模型)
        self._model_pool_registry = ModelPoolRegistry(observers=self._observers)
        # 套用 per-device BudgetGate(依各卡 free VRAM 預算;無 CUDA 時 no-op,維持 BinaryGate)
        self._model_pool_registry.apply_capacity_policy()
        # Layer 3 排程:Builder + HybridScheduler
        self._builder = PipelineBuilder()
        self._scheduler = HybridScheduler(self._registry, self._builder, max_assets_parallel)
        # Phase 1 最近一次 run 的總耗時(秒);run() 結束時寫入,供外部查詢 / 測試
        self.last_run_elapsed_sec: float | None = None

        print(f"[PipelineRunner] {self._registry.describe()}")
        if eager_models:
            # 依 capacity 規劃的優先序預載熱門模型(Qwen 多卡常駐、VRAM 不足自動降 lazy),
            # 讓第一個 asset 不再卡載入;無 CUDA 時 warm_up 自動 no-op
            print("[PipelineRunner] EAGER_MODELS=true,啟動期依 capacity 規劃預載熱門模型...")
            self._model_pool_registry.warm_up()

        # warm up 後印啟動佈局表(GPU VRAM 放置 + 各 pool 並行度),讓使用者一眼確認資源分佈
        print(StartupReporter(
            capacity_manager=self._model_pool_registry.capacity,
            executor_registry=self._registry,
            max_assets_parallel=max_assets_parallel,
            aux_rows=self._model_pool_registry.aux_pool_rows(),
        ).render())

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
            base_dir:    素材資料夾(目前僅供日誌,實際路徑已在 asset_files)。
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

        # 卡住偵測 watchdog(背景 daemon,定期印進行中 stage;本次 run 結束即收工)
        watchdog = (
            StallWatchdog(
                WATCHDOG_HEARTBEAT_SEC, WATCHDOG_STALL_WARN_SEC, WATCHDOG_FREEZE_DUMP_SEC
            )
            if WATCHDOG_ENABLED else None
        )
        if watchdog is not None:
            tracker.subscribe(watchdog)
            watchdog.start()
        # Phase 1 計時:記錄「處理所有素材」的總 wall time(從排程開始到全部結束)
        start_ts = time.perf_counter()
        try:
            results = self._scheduler.run(contexts, tracker)
        finally:
            # 無論成功 / 例外都停掉背景執行緒,避免殘留 daemon
            if watchdog is not None:
                watchdog.stop()
            # 計時與摘要寫在 finally,例外中斷也能看到已花多久
            self.last_run_elapsed_sec = time.perf_counter() - start_ts
            print(
                f"[PipelineRunner] Phase 1 處理 {len(contexts)} 個素材完成,"
                f"總耗時 {self.last_run_elapsed_sec:.1f}s"
                f"(平均 {self.last_run_elapsed_sec / len(contexts):.1f}s/素材)"
            )
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
        """關閉底層資源池與所有 BatchCollector(伺服器正常運作下不需呼叫,程式結束自動回收)。"""
        self._registry.shutdown()
        # BatchCollector 的 worker 為 daemon thread,此處主動收工以利乾淨關閉
        BatchCollectorRegistry.shutdown_all()
