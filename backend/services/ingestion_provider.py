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

from backend.services.director_service import director_service
from backend.services.jobs.async_job_runner import async_job_runner
from backend.services.jobs.phase1_lock import phase1_lock
from backend.services.stores.project_meta_store import project_meta_store
from config.app_config import ASSETS_DIR
from ingestion_engine import (
    CloudIngestionService,
    IngestionPoller,
    PublicDriveApiAdapter,
)
from ingestion_engine.exceptions import Phase1DeferredError
from ingestion_engine.models import META_KEY_ACTIVE_PHASE1_JOB_ID


def _phase1_runner(user_id: str, project_name: str) -> None:
    """
    攝取背景預跑的 Phase 1 觸發 callback：把**增量** Phase 1 包成 tracked job,讓素材頁即時看進度。

    用 run_phase1_incremental 只重跑「新增 / 策略變更」的素材,避免素材簽章一變就整包重跑
    昂貴的感知分析(Qwen / Gemini);首次同步時 status 為空 → 等同全量(正確)。

    本 callback 在 cloud_ingestion_service 的 worker thread 內被同步呼叫,於此把分析包成 tracked job
    (建 job_id + 帶 job_id 的 ProgressTracker,訂閱 WS Observer):job_id 一產生即寫進 project_meta 的
    active_phase1_job_id,讓素材頁掛載時能訂閱 /ws/progress/{job_id} 看每張卡片的 stage 進度;收尾無論
    成功 / 失敗都清掉該欄位。job/tracker 的建立刻意放在 backend 側(此處)而非 ingestion_engine,維持
    ingestion_engine 不 import backend 的單向依賴。失敗時 raise,交回 cloud_ingestion_service 標 failed
    (錯誤隔離語意不變)。

    與編輯頁 / 素材頁的 Phase 1 互斥:先以非阻塞 try 取得該專案執行鎖,搶不到(前景正在分析)即拋
    Phase1DeferredError 略過本輪(不建 job、不阻塞 poller、不雙重佔用 GPU);由 _reconcile 捕捉後
    保留待分析狀態,下輪重試。鎖於收尾 finally 釋放。
    """
    # 前景已有 Phase 1 在跑同一專案 → 本輪略過(非阻塞,不排隊堆積)
    if not phase1_lock.acquire(user_id, project_name, blocking=False):
        raise Phase1DeferredError(f"前景 Phase 1 進行中,略過本輪同步分析: {project_name}")

    project_dir = os.path.join(ASSETS_DIR, user_id, project_name)

    def _publish_job_id(job_id: str) -> None:
        """job 建立後立即把 job_id 落地 meta,前端查 phase1-progress 即可拿到並訂閱 WS。"""
        def _set(meta: dict) -> None:
            """就地寫入進行中 job_id(其餘欄位不動)。"""
            meta[META_KEY_ACTIVE_PHASE1_JOB_ID] = job_id
        project_meta_store.update(project_dir, _set)

    def _work(tracker) -> dict:
        """worker thread 內跑增量 Phase 1,透傳 tracker 讓 per-asset 進度經 WS 串流。"""
        success = director_service.run_phase1_incremental(
            project_name, user_id=user_id, tracker=tracker,
        )
        return {"success_count": len(success)}

    try:
        async_job_runner.run_tracked_sync(user_id, _work, on_job_created=_publish_job_id)
    finally:
        # 無論成功 / 失敗都清掉 active job_id;phase1_status(done/failed)由 cloud_ingestion_service 落地。
        # release 放最內層 finally:即使清 job_id 的原子寫失敗(OSError)也務必釋放鎖,
        # 否則該專案會永久卡住無法再分析(鎖洩漏)。
        def _clear(meta: dict) -> None:
            """就地移除進行中 job_id(缺鍵亦安全)。"""
            meta.pop(META_KEY_ACTIVE_PHASE1_JOB_ID, None)
        try:
            project_meta_store.update(project_dir, _clear)
        finally:
            # 釋放執行鎖,讓編輯頁 / 素材頁 / 下輪同步得以接手
            phase1_lock.release(user_id, project_name)


def _artifact_pruner(user_id: str, project_name: str) -> None:
    """
    攝取背景同步的衍生產物清理 callback：雲端刪檔 / 同名替換後,把對不上磁碟的衍生產物清掉。

    重用 director_service 既有的 asset_repository 單例(不另建,避免重複載入縮圖服務等),
    把 standardized 孤兒檔、phase1 metadata/status、逐檔策略收斂到與磁碟一致。
    """
    director_service.asset_repository.prune_orphaned_artifacts(user_id, project_name)


# 模組層級單例：跨 API 請求與背景輪詢共享同一份狀態與設定
drive_adapter = PublicDriveApiAdapter()
cloud_ingestion_service = CloudIngestionService(drive_adapter, _phase1_runner, _artifact_pruner)
ingestion_poller = IngestionPoller(cloud_ingestion_service)
