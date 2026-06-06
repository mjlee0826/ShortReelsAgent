import sys
import os
from contextlib import asynccontextmanager
# 【新增】引入 dotenv 套件來讀取 .env 檔案
from dotenv import load_dotenv

# --- 將專案根目錄加入系統路徑 ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

# 【關鍵修正】在讀取任何環境變數之前，必須先載入 .env 檔案
load_dotenv()

from config.app_config import ASSETS_DIR, TEMP_TEMPLATES_DIR
from config.ingestion_config import ENABLE_INGESTION_POLLER
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from backend.api.director import router as director_router
from backend.api.projects import router as projects_router
from backend.api.assets import router as assets_router
from backend.api.progress import router as progress_router
from backend.api.settings import router as settings_router
from backend.services.ingestion_provider import ingestion_poller


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用生命週期：啟動時拉起雲端攝取背景 poller，關閉時優雅停止（可由 env 關閉）。"""
    if ENABLE_INGESTION_POLLER:
        await ingestion_poller.start()
    try:
        yield
    finally:
        if ENABLE_INGESTION_POLLER:
            await ingestion_poller.stop()


app = FastAPI(title="Short Reels Agent API", lifespan=lifespan)

# 讀取允許連線的前端網址 (若未設定則預設為 localhost:5173)
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# [1] 影片素材區：掛載使用者的專案資料夾（指向本地 /data1，避免 NFS hang）
if not os.path.exists(ASSETS_DIR):
    os.makedirs(ASSETS_DIR)
app.mount("/static", StaticFiles(directory=ASSETS_DIR), name="static")

# [2] 全域系統快取區：掛載 temp_templates（指向本地 /data1，避免 NFS hang）
if not os.path.exists(TEMP_TEMPLATES_DIR):
    os.makedirs(TEMP_TEMPLATES_DIR)
app.mount("/cache", StaticFiles(directory=TEMP_TEMPLATES_DIR), name="cache")

app.include_router(director_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(assets_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
# 進度推播為 WebSocket 端點,路徑固定為 /ws/progress/{job_id},不掛 /api 前綴
app.include_router(progress_router)

if __name__ == "__main__":
    import uvicorn
    
    # 【修改】從環境變數讀取 Host 與 Port，讓啟動配置完全動態化
    # 若 .env 中沒有設定，則退回預設的 0.0.0.0 與 5174
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 5174))
    
    print(f"🚀 [系統啟動] FastAPI 伺服器運行於 http://{host}:{port}")
    print(f"🔒 [CORS 設定] 允許的前端連線來源: {frontend_url}")
    
    uvicorn.run(app, host=host, port=port)