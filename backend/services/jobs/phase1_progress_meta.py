"""
進行中 Phase 1 job_id 的 meta 落地 / 清除 (DRY helper)。

把「進行中的 Phase 1 job_id 寫進 / 移出 project_meta」這段讀-改-寫集中於此,讓三條觸發 Phase 1
的路徑共用同一份語意:
- 雲端同步背景預跑(``ingestion_provider``)
- 素材頁「重新分析」/「開始生成」(``api.assets``)

落地後,前端查 ``GET /api/projects/{name}/phase1-progress`` 即可拿到 ``active_job_id`` 並(重整後)
重新訂閱 ``/ws/progress/{job_id}`` 接回即時進度;job 收尾務必清除,避免殘留孤兒 id。
``phase1_status`` 屬雲端同步狀態機(``cloud_ingestion_service``)專管,本 helper 刻意不碰,避免
手動觸發干擾 poller 的「已收斂」判斷。
"""
from __future__ import annotations

from backend.services.stores.project_meta_store import project_meta_store
from ingestion_engine.models import META_KEY_ACTIVE_PHASE1_JOB_ID


def publish_active_job(project_dir: str, job_id: str) -> None:
    """把進行中的 Phase 1 ``job_id`` 落地 meta(其餘欄位不動);前端據此訂閱 WS 即時進度。"""
    def _set(meta: dict) -> None:
        """就地寫入進行中 job_id。"""
        meta[META_KEY_ACTIVE_PHASE1_JOB_ID] = job_id

    project_meta_store.update(project_dir, _set)


def clear_active_job(project_dir: str) -> None:
    """移除 meta 內進行中的 Phase 1 ``job_id``(缺鍵亦安全);job 收尾無論成功 / 失敗都應呼叫。"""
    def _clear(meta: dict) -> None:
        """就地移除進行中 job_id。"""
        meta.pop(META_KEY_ACTIVE_PHASE1_JOB_ID, None)

    project_meta_store.update(project_dir, _clear)
