import sys
import os
# 【新增】引入 dotenv 套件來讀取 .env 檔案
from dotenv import load_dotenv 

# --- 將專案根目錄加入系統路徑 ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

# 【關鍵修正】在讀取任何環境變數之前，必須先載入 .env 檔案
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from backend.api.director import router as director_router 

app = FastAPI(title="Short Reels Agent API")

# 讀取允許連線的前端網址 (若未設定則預設為 localhost:5173)
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# [1] 影片素材區：掛載使用者的專案資料夾
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
if not os.path.exists(ASSETS_DIR):
    os.makedirs(ASSETS_DIR)
app.mount("/static", StaticFiles(directory=ASSETS_DIR), name="static")

# [2] 全域系統快取區：掛載 temp_templates
CACHE_DIR = os.path.join(PROJECT_ROOT, "temp_templates")
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)
app.mount("/cache", StaticFiles(directory=CACHE_DIR), name="cache")

app.include_router(director_router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    
    # 【修改】從環境變數讀取 Host 與 Port，讓啟動配置完全動態化
    # 若 .env 中沒有設定，則退回預設的 0.0.0.0 與 5174
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 5174))
    
    print(f"🚀 [系統啟動] FastAPI 伺服器運行於 http://{host}:{port}")
    print(f"🔒 [CORS 設定] 允許的前端連線來源: {frontend_url}")
    
    uvicorn.run(app, host=host, port=port)