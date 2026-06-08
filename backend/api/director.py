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

    # 是否重新挑配樂：初始生成 / 「重新生成」為 True；純對話微調為 False（避免每次微調默默換掉 BGM）
    regenerate_music: bool = True
    # 不重抓配樂時，沿用前端傳回的上一版 bgm_track（保留手動的音量 / 起播與曲目）
    previous_bgm_track: Optional[Dict] = None


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
            regenerate_music=req.regenerate_music,
            previous_bgm_track=req.previous_bgm_track,
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


@router.get("/projects/{folder_name}/blueprint")
async def get_blueprint(folder_name: str, user_id: str = Depends(verify_token)):
    """
    讀回專案先前生成並落地的最終藍圖，供重新進入編輯器時自動載入。
    找不到素材資料夾或尚未生成過藍圖時回 404（前端視為「無已存結果」，不報錯）。
    """
    try:
        result = await asyncio.to_thread(director_service.load_blueprint, folder_name, user_id)
    except ValueError as e:
        # 找不到素材資料夾
        raise HTTPException(status_code=404, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="此專案尚未生成過影片藍圖")
    return result


class ChangeMusicRequest(BaseModel):
    """music-only 換曲請求：只重挑配樂、不重剪時間軸。"""
    asset_folder_name: str
    music_strategy: str = "search_copyright"  # search_copyright | search_free | none
    user_music_file: Optional[str] = None     # 已上傳的自訂音訊檔名（優先於策略）
    user_prompt: Optional[str] = None         # 搜尋關鍵字 / 音樂風格描述（選填）
    previous_bgm_track: Optional[Dict] = None # 沿用上一版的音量 / 起播


@router.post("/change_music")
async def change_music(req: ChangeMusicRequest, user_id: str = Depends(verify_token)):
    """
    只更換配樂、保留現有時間軸（music-only）：只跑配樂引擎取得新曲，組出 bgm_track 回傳，
    不經導演重剪。回傳 { bgm_track }，由前端就地套用到當前 blueprint（可 Undo）。
    """
    try:
        return await asyncio.to_thread(
            director_service.change_music,
            req.asset_folder_name, req.music_strategy, req.user_music_file,
            req.user_prompt, req.previous_bgm_track, user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print("\n❌ [換曲錯誤]")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class SnapshotCreateRequest(BaseModel):
    """建立快照的請求體：前端送來要存檔的標籤與當前 blueprint。"""
    label: str
    blueprint: Dict


@router.get("/projects/{folder_name}/snapshots")
async def list_snapshots(folder_name: str, user_id: str = Depends(verify_token)):
    """列出專案的所有編輯器快照 meta（不含 blueprint），供左欄版本清單。"""
    try:
        return await asyncio.to_thread(director_service.list_snapshots, folder_name, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/projects/{folder_name}/snapshots")
async def create_snapshot(folder_name: str, req: SnapshotCreateRequest, user_id: str = Depends(verify_token)):
    """把前端傳入的當前 blueprint 存成一筆具名快照，回傳新快照 meta。"""
    try:
        return await asyncio.to_thread(
            director_service.save_snapshot, folder_name, req.label, req.blueprint, user_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/projects/{folder_name}/snapshots/{snapshot_id}")
async def get_snapshot(folder_name: str, snapshot_id: str, user_id: str = Depends(verify_token)):
    """以 id 取回快照供還原，回傳 { blueprint, assets_root_url }；不存在回 404。"""
    try:
        result = await asyncio.to_thread(
            director_service.get_snapshot, folder_name, snapshot_id, user_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="找不到指定的快照")
    return result


@router.delete("/projects/{folder_name}/snapshots/{snapshot_id}")
async def delete_snapshot(folder_name: str, snapshot_id: str, user_id: str = Depends(verify_token)):
    """刪除指定快照；找不到回 404。"""
    try:
        deleted = await asyncio.to_thread(
            director_service.delete_snapshot, folder_name, snapshot_id, user_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="找不到指定的快照")
    return {"deleted": True}


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
