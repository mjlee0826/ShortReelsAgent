"""
Facade Pattern：使用者全域設定 API 端點。

對外暴露登入使用者的全域偏好（建立專案後是否自動分析、素材預設策略）的讀取與部分更新，
以 JWT 驗證確保使用者只能存取自己的設定。實際讀寫委派給 ``user_settings_store``（原子寫入）。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth.logto_jwt_verifier import verify_token
from backend.services.asset_repository import AssetStrategy
from backend.services.stores.user_settings_store import UserSettings, user_settings_store

router = APIRouter()

# 允許的素材預設策略值（與逐檔策略契約共用同一組列舉，避免散落的 magic string）
_VALID_STRATEGIES = {AssetStrategy.SIMPLE.value, AssetStrategy.COMPLEX.value}


class UserSettingsUpdate(BaseModel):
    """部分更新請求體；欄位皆 Optional，只套用實際送出的欄位（搭配 exclude_unset）。"""

    auto_analyze_on_create: Optional[bool] = None
    default_asset_strategy: Optional[str] = None
    preference_capture_enabled: Optional[bool] = None


@router.get("/settings", response_model=UserSettings)
async def get_settings(user_id: str = Depends(verify_token)):
    """取得目前登入使用者的全域設定；缺檔時回安全預設。"""
    return await asyncio.to_thread(user_settings_store.get, user_id)


@router.patch("/settings", response_model=UserSettings)
async def update_settings(req: UserSettingsUpdate, user_id: str = Depends(verify_token)):
    """部分更新全域設定並回傳更新後的完整設定；非法策略值回 400。"""
    # 只取本次實際送出的欄位（未送的欄位維持原值）
    patch = req.model_dump(exclude_unset=True)
    # 邊界驗證：策略值必須是支援的列舉，否則拒絕（避免寫入無法被 pipeline 識別的值）
    strategy = patch.get("default_asset_strategy")
    if strategy is not None and strategy not in _VALID_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"不支援的預設策略: {strategy}")

    def _mutate(settings: dict) -> None:
        """就地套用本次送出的欄位（未送者不動）。"""
        settings.update(patch)

    return await asyncio.to_thread(user_settings_store.update, user_id, _mutate)
