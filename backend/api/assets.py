"""
素材管理 API 端點 (Facade Pattern)。

Asset Management UI 的後端:列出專案素材與其狀態 / 策略 / 縮圖、更新逐檔策略(標記 dirty)、
以及以 async job model 觸發 Phase 1 重分析 / 開始生成(對 dirty+未處理素材重跑、進度經 WebSocket
串流)。全部以 JWT 的 user_id 命名空間,確保使用者只能存取自己的專案。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

# 重用共享的 director_service 單例(避免再建一份 PipelineRunner / 模型池)
from backend.services.director_service import director_service
from backend.auth.logto_jwt_verifier import verify_token
from backend.services.asset_repository import AssetDetailView, AssetRepository, AssetView
from backend.services.jobs.async_job_runner import async_job_runner
from backend.services.jobs.phase1_lock import PHASE1_BUSY_MESSAGE, phase1_lock
from backend.services.thumbnail_service import ThumbnailService

router = APIRouter()

# 模組層級單例:縮圖服務與素材儲存庫(跨請求共享)
_thumbnail_service = ThumbnailService()
asset_repository = AssetRepository(thumbnail_service=_thumbnail_service)


class StrategyRequest(BaseModel):
    """更新單一素材策略的請求體;path 為素材身分 relpath(含 /,故走 body 而非 URL path param)。"""

    path: str      # 素材身分 relpath(如 raw/photo.jpg)
    strategy: str  # "simple" | "complex"


class ReanalyzeRequest(BaseModel):
    """重新分析請求體;asset_ids 為 None 代表整個專案全部重跑。"""

    asset_ids: Optional[list[str]] = None


class AssetGenerateRequest(BaseModel):
    """開始生成請求體;asset_strategies 為本次一併套用並落地的逐檔策略。"""

    asset_strategies: Optional[dict[str, str]] = None


@router.get("/projects/{project_name}/assets", response_model=list[AssetView])
async def list_assets(project_name: str, user_id: str = Depends(verify_token)):
    """列出某專案所有素材的檢視(狀態 / 策略 / dirty / 縮圖);順手 lazy 補產缺的縮圖。"""
    try:
        # 縮圖產生可能稍重(cv2 / PIL),丟 thread 不卡 event loop
        return await asyncio.to_thread(asset_repository.list_assets, user_id, project_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/projects/{project_name}/asset-detail", response_model=AssetDetailView)
async def get_asset_detail(
    project_name: str,
    path: str = Query(..., description="素材身分 relpath(如 raw/photo.jpg)"),
    user_id: str = Depends(verify_token),
):
    """
    取得單一素材的完整詳情(AssetView + 原始媒體 URL + Phase 1 完整感知 metadata)。

    素材身分(relpath)含 ``/``,故以 query 參數 ``path`` 傳遞(避免 URL path param 的 ``%2F`` 坑)。
    路徑穿越由 list_assets 的素材白名單天然擋掉(查無此 path → 404)。讀檔不卡 event loop,丟 thread 執行。
    """
    try:
        return await asyncio.to_thread(
            asset_repository.get_asset_detail, user_id, project_name, path
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/projects/{project_name}/asset-strategy", response_model=AssetView)
async def set_asset_strategy(
    project_name: str,
    req: StrategyRequest,
    user_id: str = Depends(verify_token),
):
    """更新單一素材(以 req.path 識別)的 Simple/Complex 策略並標記 dirty,回傳更新後的素材檢視。"""
    try:
        return await asyncio.to_thread(
            asset_repository.set_strategy, user_id, project_name, req.path, req.strategy
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/projects/{project_name}/reanalyze")
async def reanalyze_assets(
    project_name: str,
    req: ReanalyzeRequest,
    user_id: str = Depends(verify_token),
):
    """
    強制重跑 Phase 1(不看 dirty):asset_ids 為 None 跑全部、否則只跑指定素材。

    立即回 job_id;前端開 ``WS /ws/progress/{job_id}`` 看每個 asset 的 stage 進度。
    """
    asset_ids = req.asset_ids

    # 與其他 Phase 1 路徑(雲端同步 / 編輯頁 / 另一次觸發)互斥:前景分析中即回 409,
    # 前端提示稍候(非阻塞,不排隊堆積)。鎖於 work 收尾 finally 釋放。
    if not phase1_lock.acquire(user_id, project_name, blocking=False):
        raise HTTPException(status_code=409, detail=PHASE1_BUSY_MESSAGE)

    def work(tracker) -> dict:
        """背景執行緒內跑 Phase 1 重分析(沿用逐檔 Simple/Complex 策略),完成後清除這些素材的 dirty 標記。"""
        try:
            strategies = asset_repository.get_asset_strategies(user_id, project_name)
            success = director_service.run_phase1(
                project_name, user_id=user_id, tracker=tracker,
                asset_filenames=asset_ids, asset_strategies=strategies, require_success=False,
            )
            asset_repository.clear_dirty(user_id, project_name, asset_ids)
            return {"success_count": len(success)}
        finally:
            phase1_lock.release(user_id, project_name)

    try:
        job_id = async_job_runner.launch(user_id, work)
    except BaseException:
        # launch 失敗(極少)時釋放已取得的鎖,避免洩漏使該專案永久卡 409
        phase1_lock.release(user_id, project_name)
        raise
    return {"job_id": job_id}


@router.post("/projects/{project_name}/generate")
async def generate_assets(
    project_name: str,
    req: AssetGenerateRequest,
    user_id: str = Depends(verify_token),
):
    """
    「開始生成」:套用本次逐檔策略後,只對 dirty+未處理素材重跑 Phase 1(節省已是最新者)。

    立即回 job_id;前端據此訂閱 WebSocket 進度。需要 prompt 的完整生成(Phase 2–4)仍由編輯器負責。
    """
    # 先把本次選擇的逐檔策略落地(同時標記 dirty),讓 select_pending 撈得到;鍵為素材 relpath 身分。
    # 刻意在取鎖前落地:即使隨後 409,使用者的策略選擇也已持久化、dirty 仍在,下次觸發會補跑。
    if req.asset_strategies:
        for path, strategy in req.asset_strategies.items():
            try:
                await asyncio.to_thread(
                    asset_repository.set_strategy, user_id, project_name, path, strategy
                )
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc))

    # 與其他 Phase 1 路徑互斥:前景分析中即回 409(dirty 已落地,下次觸發補跑)。鎖於 work 收尾釋放。
    if not phase1_lock.acquire(user_id, project_name, blocking=False):
        raise HTTPException(status_code=409, detail=PHASE1_BUSY_MESSAGE)

    def work(tracker) -> dict:
        """背景執行緒內:挑出待處理素材 → 帶逐檔策略跑 Phase 1 → 清除其 dirty。"""
        try:
            pending = asset_repository.select_pending(user_id, project_name)
            strategies = asset_repository.get_asset_strategies(user_id, project_name)
            success = director_service.run_phase1(
                project_name, user_id=user_id, tracker=tracker,
                asset_filenames=pending, asset_strategies=strategies, require_success=False,
            )
            asset_repository.clear_dirty(user_id, project_name, pending)
            return {"processed_count": len(pending), "success_count": len(success)}
        finally:
            phase1_lock.release(user_id, project_name)

    try:
        job_id = async_job_runner.launch(user_id, work)
    except BaseException:
        # launch 失敗(極少)時釋放已取得的鎖,避免洩漏使該專案永久卡 409
        phase1_lock.release(user_id, project_name)
        raise
    return {"job_id": job_id}
