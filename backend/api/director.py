import asyncio
import os
import traceback
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, Dict
from backend.services.director_service import director_service, AssetsNotAnalyzedError
from backend.services.render_service import RenderService
from backend.auth.logto_jwt_verifier import verify_token
from config.app_config import ASSETS_DIR, RAW_SUBDIR
from config.media_formats import AUDIO_EXTENSIONS

router = APIRouter()
# director_service 為跨模組共享的單例(定義於 backend.services.director_service),此處直接 import 使用;
# render_service 僅本檔 render_mp4 端點使用,無跨模組共享需求,故就地建立。
render_service = RenderService()

_ASSETS_BASE_PATH = ASSETS_DIR

# 素材未分析時回給前端的機器可讀錯誤碼:前端只在此 code 出現時跳轉素材頁(與一般 500 區分)
ASSETS_NOT_ANALYZED_CODE = "ASSETS_NOT_ANALYZED"


class GenerateRequest(BaseModel):
    asset_folder_name: str
    user_prompt: str
    template_source: Optional[str] = None
    enable_subtitles: bool = True
    enable_filters: bool = True
    previous_timeline: Optional[Dict] = None

    # 配樂策略：由前端明確選擇，不依賴 AI 推測
    music_strategy: str = "search_copyright"  # search_copyright | search_free | none
    # 用戶已上傳至 assets 資料夾的音訊檔名（有值時優先於 music_strategy）
    user_music_file: Optional[str] = None


@router.post("/generate")
async def generate_timeline(req: GenerateRequest, user_id: str = Depends(verify_token)):
    try:
        result = await asyncio.to_thread(
            director_service.run_workflow,
            prompt=req.user_prompt,
            folder_name=req.asset_folder_name,
            user_id=user_id,
            template=req.template_source,
            subtitles=req.enable_subtitles,
            filters=req.enable_filters,
            old_timeline=req.previous_timeline,
            music_strategy=req.music_strategy,
            user_music_file=req.user_music_file,
        )
        return result
    except AssetsNotAnalyzedError as e:
        # 素材尚未分析:回 409 + 機器可讀 code,讓前端只在此情境跳轉素材頁(與一般 500 區分)
        raise HTTPException(
            status_code=409,
            detail={"code": ASSETS_NOT_ANALYZED_CODE, "message": str(e)},
        )
    except Exception as e:
        print("\n❌ [後端發生錯誤] 詳細報錯資訊如下：")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload_music/{folder_name}")
async def upload_music(folder_name: str, file: UploadFile = File(...), user_id: str = Depends(verify_token)):
    """
    接收用戶上傳的音訊檔，儲存至對應的素材資料夾。
    成功回傳檔名，供後續 generate 請求的 user_music_file 欄位使用。
    """
    # 驗證副檔名
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支援的音訊格式 '{ext}'，請上傳: {', '.join(AUDIO_EXTENSIONS)}"
        )

    # 確認素材資料夾存在（路徑含 user_id）
    folder_path = os.path.join(_ASSETS_BASE_PATH, user_id, folder_name)
    if not os.path.isdir(folder_path):
        raise HTTPException(status_code=404, detail=f"找不到素材資料夾: {folder_name}")

    # 音訊與其他原始素材同存 raw/（不經 standardize）；回傳 basename,generate 時於 raw/ 下解析
    raw_dir = os.path.join(folder_path, RAW_SUBDIR)
    os.makedirs(raw_dir, exist_ok=True)
    save_path = os.path.join(raw_dir, file.filename)
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    print(f"[Upload] 音訊已儲存: {save_path}")
    return {"filename": file.filename}


class RenderRequest(BaseModel):
    blueprint: Dict
    assets_root_url: str


@router.post("/render_mp4")
async def render_mp4(req: RenderRequest, background_tasks: BackgroundTasks, user_id: str = Depends(verify_token)):
    """
    SSR 算圖端點：接收 JSON 藍圖，回傳 MP4，並在背景執行清理。
    """
    workspace = render_service.create_workspace()
    try:
        output_mp4 = await asyncio.to_thread(
            render_service.execute_render, workspace, req.blueprint, req.assets_root_url
        )
        # 檔案傳輸完畢後，背景任務立刻清理暫存資料夾
        background_tasks.add_task(workspace.cleanup)
        return FileResponse(
            path=output_mp4,
            media_type="video/mp4",
            filename="AI_Director_Output.mp4"
        )
    except Exception as e:
        workspace.cleanup()
        print("\n❌ [SSR 算圖錯誤]")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
