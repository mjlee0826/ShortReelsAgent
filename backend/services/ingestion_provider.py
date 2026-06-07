"""
攝取層元件接線 (Composition Root / Dependency Injection)。

集中組裝 Layer 0 的單例：PublicDriveApiAdapter（Drive API 公開資料夾存取）、
CloudIngestionService（同步協調）、IngestionPoller（背景輪詢）。Phase 1 的觸發以 callback 注入，
callback 包一層既有的 director_service 單例（重用，不重複載入 facade），讓 ingestion_engine
與 backend 維持單向依賴、避免循環 import。

API 端點（backend/api/projects.py）與背景任務啟動（backend/main.py）皆從此處取用同一組單例。
"""
from __future__ import annotations

import os
from contextlib import contextmanager

from backend.services.director_service import director_service
from backend.services.jobs.async_job_runner import async_job_runner
from backend.services.jobs.phase1_lock import (
    PHASE1_ACTIVITY_ANALYZING,
    PHASE1_ACTIVITY_INGESTING,
    phase1_lock,
)
from backend.services.jobs.phase1_progress_meta import clear_active_job, publish_active_job
from config.app_config import ASSETS_DIR
from ingestion_engine import (
    CloudIngestionService,
    IngestionPoller,
    PublicDriveApiAdapter,
)
from ingestion_engine.exceptions import Phase1DeferredError


@contextmanager
def _ingest_guard(user_id: str, project_name: str):
    """
    ingest 執行護衛(注入 CloudIngestionService):進入時以非阻塞 try 取得該專案的 Phase 1 執行鎖並
    標 ingesting,讓「下載 + 標準化(+ 自動分析)」整段與素材頁/編輯頁的手動 Phase 1 互斥——使用者無法
    在素材尚未下載/標準化完成時就自己跑 Phase 1。搶不到(前景正在分析)即拋 Phase1DeferredError,由
    _reconcile 略過本輪(不下載、不阻塞 poller、不雙重佔用 GPU),保留狀態下輪重試。離開時(含例外)釋放鎖。

    鎖的取得放在 backend 側(此處)而非 ingestion_engine,維持 ingestion_engine 不 import backend 的
    單向依賴(同 _phase1_runner / _artifact_pruner 的注入手法)。
    """
    if not phase1_lock.acquire(
        user_id, project_name, blocking=False, activity=PHASE1_ACTIVITY_INGESTING
    ):
        raise Phase1DeferredError(f"前景 Phase 1 進行中,略過本輪同步: {project_name}")
    try:
        yield
    finally:
        # 釋放執行鎖,讓編輯頁 / 素材頁 / 下輪同步得以接手
        phase1_lock.release(user_id, project_name)


def _standardize_runner(user_id: str, project_name: str) -> None:
    """
    標準化 callback(注入 CloudIngestionService):只對該專案做 raw→standardized,不跑感知分析。

    供「關閉自動分析」時也先把 .mov/.heic 等轉成 _std 身分穩定下來(前端可預覽、日後生成不漏跑)。
    由 _reconcile 在 ingest 護衛持鎖期間呼叫(故不另取鎖)。重用既有 director_service 單例。
    """
    director_service.standardize_project(project_name, user_id=user_id)


def _phase1_runner(user_id: str, project_name: str) -> None:
    """
    攝取背景預跑的 Phase 1 觸發 callback：把**增量** Phase 1 包成 tracked job,讓素材頁即時看進度。

    用 run_phase1_incremental 只重跑「新增 / 策略變更」的素材,避免素材簽章一變就整包重跑
    昂貴的感知分析(Qwen / Gemini);首次同步時 status 為空 → 等同全量(正確)。

    本 callback 由 cloud_ingestion_service 在「已持有該專案 Phase 1 執行鎖(ingest 護衛)」下於 worker
    thread 內同步呼叫,故此處**不再自行取鎖**(避免對同一把 threading.Lock 重入而死鎖);互斥與「前景忙碌
    即略過」已上移到 _reconcile 的 ingest 護衛。於此把分析包成 tracked job(建 job_id + 帶 job_id 的
    ProgressTracker,訂閱 WS Observer):job_id 一產生即寫進 active_phase1_job_id,讓素材頁掛載時能訂閱
    /ws/progress/{job_id} 看每張卡片的 stage 進度;收尾無論成功 / 失敗都清掉該欄位。job/tracker 的建立
    刻意放在 backend 側(此處)維持 ingestion_engine 不 import backend 的單向依賴。失敗時 raise,交回
    cloud_ingestion_service 標 failed(錯誤隔離語意不變)。
    """
    # 鎖已由 ingest 護衛以 ingesting 取得;真正進入感知分析,翻成 analyzing 讓搶不到鎖者看到「分析中」
    phase1_lock.set_activity(user_id, project_name, PHASE1_ACTIVITY_ANALYZING)
    project_dir = os.path.join(ASSETS_DIR, user_id, project_name)

    def _work(tracker) -> dict:
        """worker thread 內跑增量 Phase 1,透傳 tracker 讓 per-asset 進度經 WS 串流。"""
        success = director_service.run_phase1_incremental(
            project_name, user_id=user_id, tracker=tracker,
        )
        return {"success_count": len(success)}

    try:
        # job 建立後立即把 job_id 落地 meta,前端查 phase1-progress 即可拿到並訂閱 WS
        async_job_runner.run_tracked_sync(
            user_id, _work,
            on_job_created=lambda job_id: publish_active_job(project_dir, job_id),
        )
    finally:
        # 無論成功 / 失敗都清掉 active job_id;phase1_status(done/failed)由 cloud_ingestion_service 落地。
        # 執行鎖由 ingest 護衛(外層 with)釋放,此處不碰。
        clear_active_job(project_dir)


def _artifact_pruner(user_id: str, project_name: str) -> None:
    """
    攝取背景同步的衍生產物清理 callback：雲端刪檔 / 同名替換後,把對不上磁碟的衍生產物清掉。

    重用 director_service 既有的 asset_repository 單例(不另建,避免重複載入縮圖服務等),
    把 standardized 孤兒檔、phase1 metadata/status、逐檔策略收斂到與磁碟一致。
    """
    director_service.asset_repository.prune_orphaned_artifacts(user_id, project_name)


# 模組層級單例：跨 API 請求與背景輪詢共享同一份狀態與設定
drive_adapter = PublicDriveApiAdapter()
cloud_ingestion_service = CloudIngestionService(
    drive_adapter, _phase1_runner, _artifact_pruner, _ingest_guard, _standardize_runner,
)
ingestion_poller = IngestionPoller(cloud_ingestion_service)
