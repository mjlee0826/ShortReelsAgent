import asyncio
import os
import traceback
import uuid
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, Dict
from backend.services.director_service import director_service
from backend.services.render_service import RenderService
from backend.services.jobs.job_manager import job_manager
from backend.services.jobs.phase1_lock import Phase1BusyError
from backend.services.jobs.progress_hub import progress_hub, ws_progress_observer
from backend.auth.logto_jwt_verifier import verify_token
from media_processor.pipeline.progress import ProgressTracker
from config.app_config import ASSETS_DIR, RAW_SUBDIR
from config.media_formats import AUDIO_EXTENSIONS

router = APIRouter()
# director_service 為跨模組共享的單例(定義於 backend.services.director_service),此處直接 import 使用;
# render_service 僅本檔 render_mp4 端點使用,無跨模組共享需求,故就地建立。
render_service = RenderService()

# 保存背景 job 的 asyncio.Task 參考,避免 task 在執行中被 GC 提前回收
_background_tasks: set = set()

_ASSETS_BASE_PATH = ASSETS_DIR


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
    except Phase1BusyError as e:
        # 前景 Phase 1 仍在跑且等待逾時:回 409 讓前端提示稍候再試(非伺服器錯誤)
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        print("\n❌ [後端發生錯誤] 詳細報錯資訊如下：")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def _run_job(job_id: str, tracker: ProgressTracker, req: GenerateRequest, user_id: str):
    """
    背景執行一次完整生成工作流:把 Phase 1 進度經 tracker 推給 WebSocket,
    結束時把結果 / 錯誤寫回 JobManager、發 JOB_FINISHED / JOB_ERROR 終端事件,並收尾 WS 連線。
    """
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
            tracker=tracker,
        )
        job_manager.mark_done(job_id, result)
        tracker.emit_job_finished(payload={"result": result})
    except Exception as e:
        print("\n❌ [背景生成發生錯誤] 詳細報錯資訊如下：")
        traceback.print_exc()
        job_manager.mark_error(job_id, str(e))
        tracker.emit_job_error(error=str(e))
    finally:
        # 推哨兵讓 WS 迴圈優雅收尾,並排程清除該 job 的 replay buffer
        progress_hub.finish(job_id)


@router.post("/jobs/generate")
async def start_generate_job(req: GenerateRequest, user_id: str = Depends(verify_token)):
    """
    建立背景生成 job 並立即回 job_id(不等工作流跑完)。

    前端據此開 ``WS /ws/progress/{job_id}`` 看即時進度、用 ``GET /api/jobs/{job_id}`` 取最終結果。
    """
    job_id = uuid.uuid4().hex
    job_manager.create(job_id, user_id)
    # 進度 tracker 帶此 job_id,訂閱 WebSocket Observer;事件依 job_id 分流到對應連線
    tracker = ProgressTracker(job_id=job_id)
    tracker.subscribe(ws_progress_observer)
    # 先在此 event loop 執行緒捕捉 loop,讓 worker thread 的事件能排回本 loop
    progress_hub.ensure_loop()
    task = asyncio.create_task(_run_job(job_id, tracker, req, user_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, user_id: str = Depends(verify_token)):
    """查詢背景生成 job 的狀態與最終結果;不存在回 404、非擁有者回 403。"""
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"找不到 job: {job_id}")
    if job.user_id != user_id:
        raise HTTPException(status_code=403, detail="無權存取此 job")
    return job


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
