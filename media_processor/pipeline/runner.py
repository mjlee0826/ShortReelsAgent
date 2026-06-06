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
from media_processor.pipeline.context import AssetContext, MediaKind, derive_media_kind
from media_processor.pipeline.executor.executor_registry import ExecutorRegistry
from media_processor.pipeline.executor.model_pool_registry import ModelPoolRegistry
from media_processor.pipeline.progress import (
    PrintProgressObserver,
    ProgressObserver,
    ProgressTracker,
)
from media_processor.pipeline.progress.watchdog import StallWatchdog
from media_processor.image_strategy import ImageStrategy
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
        tracker: ProgressTracker | None = None,
        asset_strategies: dict[str, str] | None = None,
        status_sink: list[dict] | None = None,
    ) -> list[dict]:
        """
        並行跑完所有素材的 Phase 1 感知分析。

        Args:
            asset_files: 已過濾、依輸入順序排列的媒體檔案絕對路徑清單。
            base_dir:    素材資料夾(目前僅供日誌,實際路徑已在 asset_files)。
            video_strategy: 全域影片策略(SIMPLE / COMPLEX);未被 asset_strategies 逐檔覆寫時沿用。
            tracker: 由呼叫端注入的進度 Tracker(帶外部 job_id 與已訂閱的 WebSocket observer);
                     傳 ``None`` 時自建一個帶隨機 job_id 的 Tracker(CLI / 無前端場景)。
            asset_strategies: 逐檔策略覆寫表 ``{檔名: "simple"|"complex"}``;
                              依 media_kind 套到對應的 image / video 策略,未列出者用全域預設。
            status_sink: 非 None 時,run 結束後把**每個** asset(含 rejected / error)的精簡狀態
                         依輸入順序 append 進此清單,供 UI 層落地全狀態(回傳值仍只收 success)。

        Returns:
            僅含 ``status == "success"`` 的 metadata dict 列表,**依輸入順序排列**,
            與舊版序列迴圈輸出逐欄一致。
        """
        contexts = self._build_contexts(asset_files, base_dir, video_strategy, asset_strategies)
        if not contexts:
            return []

        # 注入則沿用其 job_id 與既有訂閱;未注入則自建一個帶隨機 job_id 的 Tracker。
        # 無論來源為何,都把本 Runner 的標準 observers(PrintObserver)訂上,確保 server log 不漏。
        if tracker is None:
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
        # 需要全狀態(UI 用)時,把每個 asset 的精簡狀態(含 rejected / error)收進 sink
        if status_sink is not None:
            status_sink.extend(self._build_status_entry(ctx) for ctx in results)

        # 只收成功的 asset,順序已由 scheduler 依 index 排好
        return [ctx.result for ctx in results if ctx.is_success and ctx.result is not None]

    @staticmethod
    def _build_status_entry(context: AssetContext) -> dict:
        """
        把一個 asset 的處理結果壓成 UI 需要的精簡狀態(success / rejected / error 三態通用)。

        success 取技術分、rejected 取 reason、error 取錯誤訊息;不含完整 metadata
        (完整 metadata 仍只在 success 的 phase1_assets_metadata.json,供 Phase 4 使用)。
        """
        entry: dict = {
            "asset_id": context.asset_id,
            "type": context.media_kind.value,
            "status": context.status,
        }
        result = context.result or {}
        metadata = result.get("metadata") or {}
        if "technical_score" in metadata:
            entry["technical_score"] = metadata["technical_score"]
        if result.get("reason"):
            entry["reason"] = result["reason"]
        if context.error:
            entry["error"] = context.error
        return entry

    def _build_contexts(
        self,
        asset_files: list[str],
        base_dir: str,
        default_video_strategy: VideoStrategy,
        asset_strategies: dict[str, str] | None = None,
    ) -> list[AssetContext]:
        """
        把檔案絕對路徑清單轉成帶輸入索引的 AssetContext 列表,並套用逐檔策略覆寫。

        ``asset_id`` 取「相對 ``base_dir`` 的 relpath」(如 ``raw/photo.jpg``)作為素材身分:此身分
        一路貫穿 status / metadata / 策略 meta 的鍵與 blueprint 的 ``clip_id``。``file_path`` 仍為絕對
        路徑(供各 Stage 實際讀檔)。逐檔策略以同一 relpath 為鍵:image 覆寫 ``image_strategy``、
        video 覆寫 ``video_strategy``;未列出的檔案沿用全域預設(image 一律 SIMPLE、video 用
        default_video_strategy)。
        """
        overrides = asset_strategies or {}
        contexts: list[AssetContext] = []
        for index, file_path in enumerate(asset_files):
            try:
                media_kind = derive_media_kind(file_path)
            except ValueError:
                # 理論上呼叫端已過濾;防呆跳過不支援的副檔名
                print(f"[PipelineRunner] 跳過不支援的檔案: {os.path.basename(file_path)}")
                continue
            # 素材身分 = 相對 project root 的 relpath(正斜線);與 collect_asset_files / 策略 meta 鍵一致
            asset_id = os.path.relpath(file_path, base_dir).replace(os.sep, "/")
            # 逐檔覆寫是否選 COMPLEX(以列舉值字串比對,避免散落的 magic string)
            wants_complex = overrides.get(asset_id) == ImageStrategy.COMPLEX.value
            if media_kind == MediaKind.IMAGE:
                image_strategy = ImageStrategy.COMPLEX if wants_complex else ImageStrategy.SIMPLE
                video_strategy = default_video_strategy  # 圖片不會用到,僅佔位
            else:
                image_strategy = ImageStrategy.SIMPLE  # 影片不會用到,僅佔位
                video_strategy = VideoStrategy.COMPLEX if wants_complex else default_video_strategy
            contexts.append(
                AssetContext(
                    asset_id=asset_id,
                    file_path=file_path,
                    media_kind=media_kind,
                    index=index,
                    video_strategy=video_strategy,
                    image_strategy=image_strategy,
                )
            )
        return contexts

    def shutdown(self) -> None:
        """關閉底層資源池與所有 BatchCollector(伺服器正常運作下不需呼叫,程式結束自動回收)。"""
        self._registry.shutdown()
        # BatchCollector 的 worker 為 daemon thread,此處主動收工以利乾淨關閉
        BatchCollectorRegistry.shutdown_all()
