"""
進行中 blueprint 生成 job_id 的 meta 落地 / 清除 / 讀取 (DRY helper)。

比照 ``phase1_progress_meta``:把「進行中的生成 job_id 寫進 / 移出 / 讀出 project_meta」集中於此,
讓編輯頁中途離開重進時可查 ``GET /api/projects/{name}/generation-progress`` 拿
``active_generation_job_id``,並(重整後)重新訂閱 ``/ws/progress/{job_id}`` 接回即時進度;
job 收尾務必清除,避免殘留孤兒 id(見 docs/blueprint_prep_design.md §10.9)。
"""
from __future__ import annotations

from typing import Optional

from backend.services.stores.project_meta_store import project_meta_store
from ingestion_engine.models import META_KEY_ACTIVE_GENERATION_JOB_ID


def publish_active_generation_job(project_dir: str, job_id: str) -> None:
    """把進行中的生成 ``job_id`` 落地 meta(其餘欄位不動);前端據此訂閱 WS 即時進度。"""
    def _set(meta: dict) -> None:
        """就地寫入進行中 job_id。"""
        meta[META_KEY_ACTIVE_GENERATION_JOB_ID] = job_id

    project_meta_store.update(project_dir, _set)


def clear_active_generation_job(project_dir: str) -> None:
    """移除 meta 內進行中的生成 ``job_id``(缺鍵亦安全);job 收尾無論成功 / 失敗都應呼叫。"""
    def _clear(meta: dict) -> None:
        """就地移除進行中 job_id。"""
        meta.pop(META_KEY_ACTIVE_GENERATION_JOB_ID, None)

    project_meta_store.update(project_dir, _clear)


def read_active_generation_job(project_dir: str) -> Optional[str]:
    """讀出 meta 內進行中的生成 ``job_id``;無則回 ``None``。供端點偵測「已在生成中」回既有 job 附掛。"""
    meta = project_meta_store.read(project_dir)
    if meta is None:
        return None
    return meta.get(META_KEY_ACTIVE_GENERATION_JOB_ID)
