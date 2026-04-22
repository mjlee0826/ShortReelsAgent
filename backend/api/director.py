from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict
from backend.services.DirectorService import DirectorService

router = APIRouter()
# 使用 Singleton 模式確保 DirectorService 只有一個實例
director_service = DirectorService()

class GenerateRequest(BaseModel):
    # 1. 使用者輸入的資料夾名稱 (例如 "snowman")
    asset_folder_name: str 
    
    # 2. User Prompt
    user_prompt: str
    
    # 3. Template 網址或路徑 (選填)
    template_source: Optional[str] = None
    
    # 4. 功能勾選 (預設為 True)
    enable_subtitles: bool = False
    enable_filters: bool = True
    
    # 5. 用於微調的舊劇本
    previous_timeline: Optional[Dict] = None

@router.post("/generate")
async def generate_timeline(req: GenerateRequest):
    """
    處理劇本生成與微調的入口
    """
    try:
        # 呼叫封裝好的 AI 工作流
        result = director_service.run_workflow(
            prompt=req.user_prompt,
            template=req.template_source,
            old_timeline=req.previous_timeline
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))