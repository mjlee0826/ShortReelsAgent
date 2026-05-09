import asyncio
import traceback
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, Dict
from backend.services.DirectorService import DirectorService
from backend.services.RenderService import RenderService

router = APIRouter()
director_service = DirectorService()
render_service = RenderService()

class GenerateRequest(BaseModel):
    asset_folder_name: str 
    user_prompt: str
    template_source: Optional[str] = None
    enable_subtitles: bool = True
    enable_filters: bool = True
    previous_timeline: Optional[Dict] = None 
    
    # 【新增】影片處理策略 (預設為 2: 全部一般影片)
    video_strategy: str = "2" 

@router.post("/generate")
async def generate_timeline(req: GenerateRequest):
    try:
        result = await asyncio.to_thread(
            director_service.run_workflow,
            prompt=req.user_prompt,
            folder_name=req.asset_folder_name,
            template=req.template_source,
            subtitles=req.enable_subtitles,
            filters=req.enable_filters,
            old_timeline=req.previous_timeline,
            video_strategy=req.video_strategy
        )
        return result
    except Exception as e:
        # 【修改】把詳細錯誤印在終端機上，方便我們抓蟲
        print("\n❌ [後端發生錯誤] 詳細報錯資訊如下：")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
class RenderRequest(BaseModel):
    blueprint: Dict
    assets_root_url: str

@router.post("/render_mp4")
async def render_mp4(req: RenderRequest, background_tasks: BackgroundTasks):
    """
    SSR 算圖端點：接收 JSON，回傳 MP4，並在背景執行清理。
    """
    workspace = render_service.create_workspace()
    try:
        output_mp4 = await asyncio.to_thread(
            render_service.execute_render, workspace, req.blueprint, req.assets_root_url
        )
        
        # 註冊背景任務：當 FileResponse 將檔案傳送完畢後，立刻呼叫 cleanup 焚毀資料夾
        background_tasks.add_task(workspace.cleanup)
        
        return FileResponse(
            path=output_mp4, 
            media_type="video/mp4", 
            filename="AI_Director_Output.mp4"
        )
    except Exception as e:
        workspace.cleanup() # 發生錯誤也要立刻清理
        print("\n❌ [SSR 算圖錯誤]")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))