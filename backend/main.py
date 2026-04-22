import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from api.director import router as director_router

app = FastAPI(title="Short Reels Agent API")

# 1. 配置 CORS (跨域資源共享)
# 允許前端 Vite (通常是 5173 埠) 存取後端 API 與素材
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. 靜態檔案映射 (核心功能)
# 將本地 assets 資料夾掛載到 /static 路徑
# 這樣前端就能透過 http://localhost:8000/static/video.mp4 讀取素材
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
if not os.path.exists(ASSETS_DIR):
    os.makedirs(ASSETS_DIR)

app.mount("/static", StaticFiles(directory=ASSETS_DIR), name="static")

# 3. 註冊路由
app.include_router(director_router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)