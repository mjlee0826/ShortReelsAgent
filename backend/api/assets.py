"""
素材管理 API 端點 (Facade Pattern)。

Asset Management UI 的後端:列出專案素材與其狀態 / 策略 / 縮圖、更新逐檔策略(標記 dirty)、
以及以 async job model 觸發 Phase 1 重分析 / 開始生成(對 dirty+未處理素材重跑、進度經 WebSocket
串流)。全部以 JWT 的 user_id 命名空間,確保使用者只能存取自己的專案。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

# 重用 director.py 的 director_service 單例(避免再建一份 PipelineRunner / 模型池)
from backend.api.director import director_service
from backend.auth.logto_jwt_verifier import verify_token
from backend.services.async_job_runner import async_job_runner
from backend.services.asset_repository import AssetDetailView, AssetRepository, AssetView
from backend.services.thumbnail_service import ThumbnailService

router = APIRouter()

# 模組層級單例:縮圖服務與素材儲存庫(跨請求共享)
_thumbnail_service = ThumbnailService()
asset_repository = AssetRepository(thumbnail_service=_thumbnail_service)


class StrategyRequest(BaseModel):
    """更新單一素材策略的請求體。"""

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


@router.get("/projects/{project_name}/assets/{filename}", response_model=AssetDetailView)
async def get_asset_detail(
    project_name: str,
    filename: str,
    user_id: str = Depends(verify_token),
):
    """
    取得單一素材的完整詳情(AssetView + 原始媒體 URL + Phase 1 完整感知 metadata)。

    供前端詳情彈窗呈現未裁切全圖 / 完整影片與分區資訊;路徑穿越由 list_assets 的素材白名單
    天然擋掉(查無此 filename → 404)。讀檔不卡 event loop,丟 thread 執行。
    """
    try:
        return await asyncio.to_thread(
            asset_repository.get_asset_detail, user_id, project_name, filename
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/projects/{project_name}/assets/{filename}/strategy", response_model=AssetView)
async def set_asset_strategy(
    project_name: str,
    filename: str,
    req: StrategyRequest,
    user_id: str = Depends(verify_token),
):
    """更新單一素材的 Simple/Complex 策略並標記 dirty,回傳更新後的素材檢視。"""
    try:
        return await asyncio.to_thread(
            asset_repository.set_strategy, user_id, project_name, filename, req.strategy
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

    def work(tracker) -> dict:
        """背景執行緒內跑 Phase 1 重分析(沿用逐檔 Simple/Complex 策略),完成後清除這些素材的 dirty 標記。"""
        strategies = asset_repository.get_asset_strategies(user_id, project_name)
        success = director_service.run_phase1(
            project_name, user_id=user_id, tracker=tracker,
            asset_filenames=asset_ids, asset_strategies=strategies, require_success=False,
        )
        asset_repository.clear_dirty(user_id, project_name, asset_ids)
        return {"success_count": len(success)}

    job_id = async_job_runner.launch(user_id, work)
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
    # 先把本次選擇的逐檔策略落地(同時標記 dirty),讓 select_pending 撈得到
    if req.asset_strategies:
        for filename, strategy in req.asset_strategies.items():
            try:
                await asyncio.to_thread(
                    asset_repository.set_strategy, user_id, project_name, filename, strategy
                )
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc))

    def work(tracker) -> dict:
        """背景執行緒內:挑出待處理素材 → 帶逐檔策略跑 Phase 1 → 清除其 dirty。"""
        pending = asset_repository.select_pending(user_id, project_name)
        strategies = asset_repository.get_asset_strategies(user_id, project_name)
        success = director_service.run_phase1(
            project_name, user_id=user_id, tracker=tracker,
            asset_filenames=pending, asset_strategies=strategies, require_success=False,
        )
        asset_repository.clear_dirty(user_id, project_name, pending)
        return {"processed_count": len(pending), "success_count": len(success)}

    job_id = async_job_runner.launch(user_id, work)
    return {"job_id": job_id}
