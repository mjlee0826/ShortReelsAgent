from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict
from backend.services.DirectorService import DirectorService
import traceback  # 【新增】用來印出詳細錯誤追蹤

router = APIRouter()
director_service = DirectorService()

class GenerateRequest(BaseModel):
    asset_folder_name: str 
    user_prompt: str
    template_source: Optional[str] = None
    enable_subtitles: bool = True
    enable_filters: bool = True
    previous_timeline: Optional[Dict] = None 

@router.post("/generate")
async def generate_timeline(req: GenerateRequest):
    try:
        result = director_service.run_workflow(
            prompt=req.user_prompt,
            folder_name=req.asset_folder_name,
            template=req.template_source,
            subtitles=req.enable_subtitles,
            filters=req.enable_filters,
            old_timeline=req.previous_timeline
        )
        return result
    except Exception as e:
        # 【修改】把詳細錯誤印在終端機上，方便我們抓蟲
        print("\n❌ [後端發生錯誤] 詳細報錯資訊如下：")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))