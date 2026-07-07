import asyncio
import os
import traceback
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, Dict
from backend.services.director_service import director_service, AssetsNotAnalyzedError
from backend.services.generation_request import GenerationRequest
from backend.services.render_service import RenderService
from backend.services.stores.agent_session_store import agent_session_store
from backend.services.jobs.async_job_runner import async_job_runner
from backend.services.jobs.generation_lock import generation_lock
from backend.services.jobs.generation_progress_meta import (
    clear_active_generation_job,
    publish_active_generation_job,
    read_active_generation_job,
)
from backend.services.jobs.job_manager import job_manager
from backend.auth.logto_jwt_verifier import verify_token
from config.app_config import ASSETS_DIR, RAW_SUBDIR
from config.media_formats import AUDIO_EXTENSIONS
import logging

logger = logging.getLogger(__name__)

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
    # 註：自動運鏡 / 卡點為純 render-time 視覺旗標，已由 DirectorFacade 在 global_settings 給開啟預設，
    #     生成後完全交由前端「專案 / 輸出」面板的即時開關控制，故不再經此生成參數（不需重新生成即可切換）。
    previous_timeline: Optional[Dict] = None

    # 配樂策略：由前端明確選擇，不依賴 AI 推測
    music_strategy: str = "search_copyright"  # search_copyright | search_free | none
    # 用戶已上傳至 assets 資料夾的音訊檔名（有值時優先於 music_strategy）
    user_music_file: Optional[str] = None

    # 是否重新挑配樂：初始生成 / 「重新生成」為 True；純對話微調為 False（避免每次微調默默換掉 BGM）
    regenerate_music: bool = True
    # 不重抓配樂時，沿用前端傳回的上一版 bgm_track（保留手動的音量 / 起播與曲目）
    previous_bgm_track: Optional[Dict] = None

    def to_generation_request(self) -> GenerationRequest:
        """把 API 契約模型轉成 service 層的 :class:`GenerationRequest`（欄位名對齊 service 慣例）。"""
        return GenerationRequest(
            prompt=self.user_prompt,
            folder_name=self.asset_folder_name,
            template=self.template_source,
            subtitles=self.enable_subtitles,
            filters=self.enable_filters,
            old_timeline=self.previous_timeline,
            music_strategy=self.music_strategy,
            user_music_file=self.user_music_file,
            regenerate_music=self.regenerate_music,
            previous_bgm_track=self.previous_bgm_track,
        )


@router.post("/generate")
async def generate_timeline(req: GenerateRequest, user_id: str = Depends(verify_token)):
    """
    啟動 blueprint 生成背景 job,立即回 ``{job_id}``(不等跑完)。

    前端據此開 ``WS /ws/progress/{job_id}`` 看 template ∥ music 兩分支即時進度,完成後走
    ``GET /projects/{folder}/blueprint`` 取落地藍圖(或 WS ``JOB_FINISHED`` 事件)。素材尚未分析
    時(非微調)**同步**回 409(沿用前端跳轉素材頁的既有契約,不必等 job 跑起);中途離開重進再按,
    偵測生成鎖已持有 → 回既有 job_id 讓前端附掛,而非 double-run(見 docs §10)。
    """
    is_refinement = req.previous_timeline is not None
    project_dir = os.path.join(_ASSETS_BASE_PATH, user_id, req.asset_folder_name)

    # 1. 素材就緒預檢(同步):非微調且素材未分析即回 409,讓前端跳素材頁(與舊同步版契約一致)
    try:
        await asyncio.to_thread(
            director_service.precheck_generation, req.asset_folder_name, user_id, is_refinement
        )
    except AssetsNotAnalyzedError as e:
        raise HTTPException(
            status_code=409,
            detail={"code": ASSETS_NOT_ANALYZED_CODE, "message": str(e)},
        )
    except ValueError as e:
        # _require_target_dir 找不到素材資料夾
        raise HTTPException(status_code=404, detail=str(e))

    # 2. 取生成鎖:搶不到代表已在生成中 → 回既有有效 job_id 讓前端附掛(避免 double-run 併寫藍圖 + 雙倍 GPU)
    if not generation_lock.acquire(user_id, req.asset_folder_name):
        active = await asyncio.to_thread(read_active_generation_job, project_dir)
        if active is not None and job_manager.get(active) is not None:
            return {"job_id": active, "already_running": True}
        # 鎖被持有但查無有效 job(極少數競態 / 孤兒):回 409 提示稍候,不強行另起
        raise HTTPException(status_code=409, detail="生成進行中，請稍候")

    # 3. 啟動背景 job;work 內落地進行中 job_id(供重進接回),收尾務必清 meta 並釋放鎖
    job_id_box: dict[str, str] = {}
    generation_request = req.to_generation_request()

    def work(tracker) -> dict:
        """背景執行緒內跑完整生成工作流(Phase 2–4),tracker 帶 job_id 把兩分支進度串到 WS。"""
        try:
            # 落地進行中 job_id:編輯頁重整後查 generation-progress 即可重新訂閱 WS 接回即時進度
            publish_active_generation_job(project_dir, job_id_box["id"])
            return director_service.run_workflow(
                generation_request, user_id=user_id, tracker=tracker,
            )
        finally:
            # 先清 active job_id 再釋放鎖;即使清除的原子寫失敗也務必釋放鎖,避免該專案永久卡 409
            try:
                clear_active_generation_job(project_dir)
            finally:
                generation_lock.release(user_id, req.asset_folder_name)

    try:
        job_id = async_job_runner.launch(user_id, work)
        job_id_box["id"] = job_id  # launch 與此行間無 await,work 啟動前必已填妥
    except BaseException:
        # launch 失敗(極少)時釋放已取得的鎖,避免洩漏使該專案永久卡 409
        generation_lock.release(user_id, req.asset_folder_name)
        raise
    return {"job_id": job_id}


class ResumeGenerationRequest(BaseModel):
    """B2 續跑請求：導演中途提問（ask_user）後，使用者回答接回 agentic loop。"""
    asset_folder_name: str
    answer: str


@router.post("/generate/resume")
async def resume_generation(req: ResumeGenerationRequest, user_id: str = Depends(verify_token)):
    """
    導演 ask_user 暫停後的續跑：以使用者答案接回 agentic loop，啟動背景 job，立即回 ``{job_id}``。

    前端據此開 ``WS /ws/progress/{job_id}`` 看續跑進度（導演可能再次提問 → 又回 needs_input）。
    查無待回答 session（已完成 / 逾時）時同步回 409，與 ``/generate`` 的鎖 / job 生命週期一致。
    """
    project_dir = os.path.join(_ASSETS_BASE_PATH, user_id, req.asset_folder_name)

    # 1. 預檢：必須有待回答 session（避免白白起 job）
    has_session = await asyncio.to_thread(
        lambda: agent_session_store.load(project_dir) is not None
    )
    if not has_session:
        raise HTTPException(status_code=409, detail="查無待回答的生成 session（可能已完成或逾時）")

    # 2. 取生成鎖（resume 是一次生成續跑）；已在生成 → 回既有 job 讓前端附掛，避免 double-run
    if not generation_lock.acquire(user_id, req.asset_folder_name):
        active = await asyncio.to_thread(read_active_generation_job, project_dir)
        if active is not None and job_manager.get(active) is not None:
            return {"job_id": active, "already_running": True}
        raise HTTPException(status_code=409, detail="生成進行中，請稍候")

    # 3. 啟動背景 job 續跑；收尾務必清 meta 並釋放鎖
    job_id_box: dict[str, str] = {}

    def work(tracker) -> dict:
        """背景執行緒內續跑 agentic loop，tracker 把 thinking / 旁白 / 再次提問串到 WS。"""
        try:
            publish_active_generation_job(project_dir, job_id_box["id"])
            return director_service.resume_generation(
                folder_name=req.asset_folder_name, user_id=user_id,
                answer=req.answer, tracker=tracker,
            )
        finally:
            # 先清 active job_id 再釋放鎖；即使清除失敗也務必釋鎖，避免該專案永久卡 409
            try:
                clear_active_generation_job(project_dir)
            finally:
                generation_lock.release(user_id, req.asset_folder_name)

    try:
        job_id = async_job_runner.launch(user_id, work)
        job_id_box["id"] = job_id
    except BaseException:
        generation_lock.release(user_id, req.asset_folder_name)
        raise
    return {"job_id": job_id}


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


class SaveBlueprintRequest(BaseModel):
    """編輯器自動儲存的請求體：前端送來要落地的當前完整 blueprint。"""
    blueprint: Dict


@router.put("/projects/{folder_name}/blueprint")
async def save_blueprint(folder_name: str, req: SaveBlueprintRequest, user_id: str = Depends(verify_token)):
    """
    編輯器自動儲存：把前端當前完整 blueprint 落地 PHASE4，供重整後 get_blueprint 自動還原。

    換曲 / 就地編輯 / 還原快照等不重新生成的變更，過去只存記憶體、重整即遺失；經此持久化後
    重整可完整還原。找不到素材資料夾回 404（沿用 get_blueprint 的錯誤契約）。
    """
    try:
        return await asyncio.to_thread(
            director_service.save_blueprint, folder_name, req.blueprint, user_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


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
        logger.error("\n❌ [換曲錯誤]")
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

    logger.info(f"[Upload] 音訊已儲存: {save_path}")
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
        logger.error("\n❌ [SSR 算圖錯誤]")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
