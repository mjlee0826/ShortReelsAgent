import sys
import os

# --- 將專案根目錄加入系統路徑 ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from backend.api.director import router as director_router 

app = FastAPI(title="Short Reels Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# [1] 影片素材區：掛載使用者的專案資料夾
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
if not os.path.exists(ASSETS_DIR):
    os.makedirs(ASSETS_DIR)
app.mount("/static", StaticFiles(directory=ASSETS_DIR), name="static")

# [2] 【新增】全域系統快取區：掛載 temp_templates
CACHE_DIR = os.path.join(PROJECT_ROOT, "temp_templates")
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)
app.mount("/cache", StaticFiles(directory=CACHE_DIR), name="cache")

app.include_router(director_router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    # 確保這裡的 port 是你正在使用的 5174
    uvicorn.run(app, host="0.0.0.0", port=5174)